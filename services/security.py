"""Security middleware for Bark dashboard — rate limiting, CSP, HTTPS enforcement, auth."""

import re
import time
from collections import defaultdict
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
    if path.startswith("/s/"):
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


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirects unauthenticated users to /auth/login when OAuth2 is configured."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from config import config

        # Only enforce when OAuth2 is configured
        if not config.oauth2.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip public paths
        if _is_public(path):
            return await call_next(request)

        # Check session
        user = request.session.get("user")
        if user is None:
            # API requests get JSON 401
            if path.startswith("/api/"):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "Authentication required"},
                )
            # HTML page requests get redirected
            return RedirectResponse(url="/auth/login", status_code=302)

        guild_id = _guild_id_from_path(path)
        if guild_id:
            from database.engine import session_scope
            from services.dashboard_access import user_can_manage_guild

            async with session_scope() as session:
                allowed = await user_can_manage_guild(session, user["id"], guild_id)
            if not allowed:
                if path.startswith("/api/"):
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "error": "You cannot manage this Discord server",
                        },
                    )
                from fastapi.responses import HTMLResponse

                return HTMLResponse(
                    "You do not have permission to manage this Discord server.",
                    status_code=403,
                )

        action = mutation_capability(request.method, path)
        if action is not None:
            from services.response import check_api_permission

            if not check_api_permission(request, action):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error": "Insufficient permissions",
                        "required_capability": action,
                    },
                )

        return await call_next(request)


# ── In-Memory Token Bucket Rate Limiter ──────────────


class RateLimiter:
    """Simple in-memory token bucket rate limiter per IP."""

    def __init__(self, capacity: int = 60):
        self.capacity = capacity
        self.tokens: dict[str, list[float]] = defaultdict(list)

    def check(self, ip: str) -> bool:
        now = time.monotonic()
        window = now - 60.0
        # Prune old entries
        self.tokens[ip] = [t for t in self.tokens[ip] if t > window]
        if len(self.tokens[ip]) >= self.capacity:
            return False
        self.tokens[ip].append(now)
        return True


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

        # HTTPS redirect
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
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": "Cross-origin write rejected",
                },
            )

        module_action = _module_action_from_path(request.url.path)
        if module_action is not None:
            guild_id, module_name, _ = module_action
            bot = getattr(request.app.state, "bot", None)
            manager = getattr(bot, "modules", None)
            if manager is not None and not manager.is_enabled_for_guild(guild_id, module_name):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=409,
                    content={
                        "success": False,
                        "error": f"Module '{module_name}' is disabled for this server",
                    },
                )

        # Rate limiting on API routes — separate GET (read) and POST/PUT/DELETE (write)
        path = request.url.path
        if path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            read_lim, write_lim = _get_limiters()
            method = request.method.upper()
            limiter = read_lim if method == "GET" else write_lim
            if not limiter.check(ip):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Too many requests. Try again in 60 seconds.",
                    },
                    headers={"Retry-After": "60"},
                )

        response = await call_next(request)

        # CSP headers on all responses
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

        return response
