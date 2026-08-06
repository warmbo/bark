"""Security middleware for Bark dashboard — rate limiting, CSP, HTTPS enforcement, auth."""

import re
import time
from collections import OrderedDict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

# ── Public paths that don't require auth ─────────────

PUBLIC_PATHS = {
    "/",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/auth/me",
    "/api/v1/health",
    "/api/v1/ping",
}


def _is_public(path: str) -> bool:
    """Check if a path is always accessible without auth."""
    if path in PUBLIC_PATHS:
        return True
    if path.startswith("/static/"):
        return True
    if path.startswith("/media/"):
        return True
    if path.startswith("/s/"):
        return True
    if path.startswith("/auth/share/"):
        return True
    return False


_GUILD_PATH = re.compile(r"^/(?:api/v1/)?guilds?/(\d+)(?:/|$)")
_MODULE_ACTION_PATH = re.compile(r"^/api/v1/guilds/(\d+)/modules/([a-z0-9_-]+)/(.+)$")
_API_GUILD_MUTATION_PATH = re.compile(r"^/api/v1/guilds/\d+/(.+)$")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _guild_id_from_path(path: str) -> str | None:
    match = _GUILD_PATH.match(path)
    return match.group(1) if match else None


def _module_action_from_path(path: str) -> tuple[int, str, str] | None:
    """Extract module runtime actions, excluding lifecycle control routes."""
    match = _MODULE_ACTION_PATH.match(path)
    if not match or match.group(3) in {"toggle", "reload"}:
        return None
    return int(match.group(1)), match.group(2), match.group(3)


def mutation_capability(method: str, path: str) -> str | None:
    """Resolve every API mutation to one centrally enforced capability.

    Unknown/new mutation routes fail closed to ``guild.manage`` so adding a
    POST route cannot silently create a viewer-accessible bypass.
    """
    if method.upper() in _SAFE_METHODS or not path.startswith("/api/"):
        return None
    path_match = _API_GUILD_MUTATION_PATH.match(path)
    if not path_match:
        return "guild.manage"
    tail = path_match.group(1).strip("/")
    action_match = re.fullmatch(r"actions/([a-z0-9_-]+)", tail)
    if action_match:
        return f"moderation.{action_match.group(1)}"
    if tail == "moderation/cases":
        return "moderation.cases.create"
    if tail == "moderation/notes":
        return "moderation.notes.create"
    if tail == "notes" or re.fullmatch(r"notes/\d+", tail):
        return "moderation.notes.create"
    if re.fullmatch(r"moderation/cases/\d+", tail):
        return "moderation.cases.delete"
    if re.fullmatch(r"moderation/warnings/\d+", tail):
        return "moderation.warnings.delete"
    if tail == "settings/general":
        return "settings.general"
    if tail == "settings/logging":
        return "logging.configure"
    if tail == "settings/automod":
        return "settings.automod"
    module_match = re.fullmatch(r"modules/([a-z0-9_-]+)(?:/(toggle|reload))?", tail)
    if module_match:
        return "modules.manage" if module_match.group(2) else "modules.configure"
    module_action_match = re.match(r"modules/([a-z0-9_-]+)/", tail)
    if module_action_match:
        return f"{module_action_match.group(1)}.manage"
    return "guild.manage"


# ── Auth Required Middleware ─────────────────────────


def _json_error(
    status_code: int,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    **extra,
) -> Response:
    """Build a JSON error response with the API's standard envelope."""
    from fastapi.responses import JSONResponse

    content = {"success": False, "error": message}
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _auth_required_response(path: str) -> Response:
    """Return the 401/302 response for a missing session on the given path."""
    if path.startswith("/api/"):
        return _json_error(401, "Authentication required")
    return RedirectResponse(url="/auth/login", status_code=302)


async def _user_can_manage_guild(user_id: str, guild_id: str) -> bool:
    """Check persisted dashboard access for the user on the guild."""
    from database.engine import session_scope
    from services.dashboard_access import user_can_manage_guild

    async with session_scope() as session:
        return await user_can_manage_guild(session, user_id, guild_id)


async def _user_is_guild_member(user_id: str, guild_id: str) -> bool:
    """Check whether Discord reported the user as a member of the guild.

    Membership is broader than manage access: any member of a server where
    Bark is installed may view its dashboard (mutations stay role-gated).
    """
    from database.engine import session_scope
    from services.dashboard_access import user_is_guild_member

    async with session_scope() as session:
        return await user_is_guild_member(session, user_id, guild_id)


def _access_denied_response(path: str, api_message: str, html_message: str) -> Response:
    """Return the 403 response (JSON envelope for API paths, HTML otherwise)."""
    if path.startswith("/api/"):
        return _json_error(403, api_message)
    from fastapi.responses import HTMLResponse

    return HTMLResponse(html_message, status_code=403)


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirects unauthenticated users to /auth/login when OAuth2 is configured."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from config import config

        if not config.oauth2.enabled:
            return await call_next(request)

        path = request.url.path

        if _is_public(path):
            return await call_next(request)

        user = request.session.get("user")
        if user is None:
            return _auth_required_response(path)

        # Sliding session renewal: write a rotating value on every
        # authenticated request so Starlette re-signs the cookie with a fresh
        # Max-Age. An active user stays logged in indefinitely; inactivity
        # beyond session_ttl still expires the cookie (signer max_age).
        request.session["_renewed"] = int(time.monotonic())

        # Bark instances admit any Discord user who is a member of a server
        # where Bark is installed — login is always required, but no dashboard
        # invite is needed for server members. Owner identity is config-backed;
        # an active hosted-instance grant remains a fallback admission path so
        # access revocation still takes effect on the next request.
        if (
            config.oauth2.owner_discord_ids
            and user.get("id") not in config.oauth2.owner_discord_ids
        ):
            from database.engine import session_scope
            from services.dashboard_access import user_shares_guild_with_bot
            from services.instance_invites import is_instance_user_authorized

            bot = getattr(request.app.state, "bot", None)
            bot_guild_ids = {str(g.id) for g in bot.guilds} if bot is not None else set()
            async with session_scope() as session:
                shared = await user_shares_guild_with_bot(session, user["id"], bot_guild_ids)
                if not shared:
                    shared = await is_instance_user_authorized(session, user["id"])
            if not shared:
                request.session.clear()
                return _access_denied_response(
                    path,
                    "You must be a member of a server where Bark is installed",
                    "You must be a member of a server where Bark is installed to use this dashboard.",
                )

        guild_id = _guild_id_from_path(path)
        if guild_id:
            # Guild pages are open to: any member of a server where Bark is
            # installed (connected), and any manager of a server who may still
            # be setting it up (the "Add Bark" tier). A plain non-member of an
            # uninstalled server has nothing behind /guild/{id}.
            bot = getattr(request.app.state, "bot", None)
            bot_guild_ids = {str(g.id) for g in bot.guilds} if bot is not None else set()
            is_member = await _user_is_guild_member(user["id"], guild_id)
            can_manage = await _user_can_manage_guild(user["id"], guild_id)
            if not is_member or (str(guild_id) not in bot_guild_ids and not can_manage):
                return _access_denied_response(
                    path,
                    "You are not a member of this Discord server",
                    "You do not have access to this Discord server.",
                )

        action = mutation_capability(request.method, path)
        if action is not None:
            from services.response import check_api_permission

            if not check_api_permission(request, action):
                return _json_error(403, "Insufficient permissions", required_capability=action)

        return await call_next(request)


# ── In-Memory Token Bucket Rate Limiter ──────────────


class RateLimiter:
    """Bounded in-memory request-window limiter per identity."""

    def __init__(self, capacity: int = 60, max_keys: int = 10_000):
        self.capacity = capacity
        self.max_keys = max_keys
        self.tokens: OrderedDict[str, list[float]] = OrderedDict()
        self._last_sweep = 0.0

    def check(self, identity: str) -> bool:
        now = time.monotonic()
        window = now - 60.0
        if now - self._last_sweep >= 60.0:
            for key in list(self.tokens):
                recent = [timestamp for timestamp in self.tokens[key] if timestamp > window]
                if recent:
                    self.tokens[key] = recent
                else:
                    del self.tokens[key]
            self._last_sweep = now

        bucket = [timestamp for timestamp in self.tokens.get(identity, []) if timestamp > window]
        if len(bucket) >= self.capacity:
            self.tokens[identity] = bucket
            self.tokens.move_to_end(identity)
            return False
        bucket.append(now)
        self.tokens[identity] = bucket
        self.tokens.move_to_end(identity)
        while len(self.tokens) > self.max_keys:
            self.tokens.popitem(last=False)
        return True


def rate_limit_identity(request: Request) -> str:
    """Use a signed-in user ID before the shared reverse-proxy address."""
    session = request.scope.get("session") or {}
    user = session.get("user") or {}
    if user.get("id"):
        return f"user:{user['id']}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


# Separate limiters: GET requests are read-only and much more frequent
# POST/PUT/DELETE are write operations and should be stricter
_read_limiter: RateLimiter | None = None
_write_limiter: RateLimiter | None = None


def _get_limiters() -> tuple[RateLimiter, RateLimiter]:
    """Lazy-init rate limiters from config."""
    global _read_limiter, _write_limiter
    if _read_limiter is None:
        from config import config as cfg

        base = cfg.dashboard.rate_limit_per_minute
        _read_limiter = RateLimiter(max(base * 3, 120))
        _write_limiter = RateLimiter(max(base // 2, 20))
    if _read_limiter is None or _write_limiter is None:
        raise RuntimeError("Rate limiter initialization failed")
    return _read_limiter, _write_limiter


# ── Middleware ────────────────────────────────────────


class SecurityMiddleware(BaseHTTPMiddleware):
    """Adds CSP headers, rate limiting, and HTTPS enforcement."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from config import config

        if config.dashboard.force_https and request.url.scheme == "http":
            url = str(request.url).replace("http://", "https://", 1)
            return RedirectResponse(url=url, status_code=301)

        origin = request.headers.get("origin")
        if (
            (request.url.path.startswith("/api/") or request.url.path == "/auth/logout")
            and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin.rstrip("/") != config.dashboard.public_url
        ):
            return _json_error(403, "Cross-origin write rejected")

        module_action = _module_action_from_path(request.url.path)
        if module_action is not None:
            guild_id, module_name, _ = module_action
            bot = getattr(request.app.state, "bot", None)
            manager = getattr(bot, "modules", None)
            if manager is not None and not manager.is_enabled_for_guild(guild_id, module_name):
                return _json_error(409, f"Module '{module_name}' is disabled for this server")

        path = request.url.path
        if path.startswith("/api/"):
            identity = rate_limit_identity(request)
            read_lim, write_lim = _get_limiters()
            method = request.method.upper()
            limiter = read_lim if method == "GET" else write_lim
            if not limiter.check(identity):
                return _json_error(
                    429,
                    "Too many requests. Try again in 60 seconds.",
                    headers={"Retry-After": "60"},
                )

        response = await call_next(request)
        _apply_security_headers(response, config)
        return response


def _apply_security_headers(response: Response, config) -> None:
    """Harden every response with CSP and related security headers."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://*.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' https://cdn.discordapp.com data:; "
        "connect-src 'self' ws: wss: https://unpkg.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if config.dashboard.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
