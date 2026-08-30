"""Security middleware for Bark dashboard — rate limiting, CSP, HTTPS enforcement, auth."""

import re
import time
from collections import OrderedDict
from typing import Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

# ── Public paths that don't require auth ─────────────

PUBLIC_PATHS = {
    "/",
    "/invite",
    "/privacy",
    "/terms",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/auth/me",
    "/api/v1/health",
    "/api/v1/ping",
}

# Origins allowed for state-changing requests (CSRF). We compare the FULL
# origin (scheme + host + port), not just the hostname — SameSite=Lax treats
# any same-host/different-port origin as same-site, so a second service on the
# dashboard host (different port) could otherwise drive a cross-origin write
# with a victim's session cookie. The allowlist is derived from config at
# request time (public_url + bind host + BARK_TRUSTED_ORIGINS), so no host IP
# is hardcoded.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def _allowed_origins(config) -> set[str]:
    """Full origins (``scheme://host[:port]``, lowercase) trusted for writes."""
    origins: set[str] = set()
    public = urlsplit(config.dashboard.public_url)
    if public.netloc:
        origins.add(f"{public.scheme}://{public.netloc}".lower())
    host = config.dashboard.host
    port = config.dashboard.port
    if host and host not in {"0.0.0.0", "::", "[::]"}:
        for scheme in ("http", "https"):
            origins.add(f"{scheme}://{host}:{port}".lower())
    for loopback in _LOOPBACK_HOSTS:
        for scheme in ("http", "https"):
            origins.add(f"{scheme}://{loopback}:{port}".lower())
    for extra in config.dashboard.trusted_origins:
        if extra:
            origins.add(extra.strip().lower())
    return origins


def _origin_allowed(origin: str, config) -> bool:
    """True when an Origin/Referer header is a trusted dashboard origin."""
    parsed = urlsplit(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    return f"{parsed.scheme}://{parsed.netloc}".lower() in _allowed_origins(config)


def trusted_origin_hosts(config) -> set[str]:
    """Hostnames (no port) trusted by TrustedHostMiddleware, derived from the
    same config as the CSRF origin allowlist."""
    hosts: set[str] = set()
    public = urlsplit(config.dashboard.public_url)
    if public.hostname:
        hosts.add(public.hostname.lower())
    host = config.dashboard.host
    if host and host not in {"0.0.0.0", "::", "[::]"}:
        hosts.add(host.lower())
    hosts |= {h for h in _LOOPBACK_HOSTS if h not in {"[::1]"}}
    for extra in config.dashboard.trusted_origins:
        parsed = urlsplit(extra)
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    return hosts


def _is_public(path: str) -> bool:
    """Check if a path is always accessible without auth."""
    if path in PUBLIC_PATHS:
        return True
    if path.startswith("/static/"):
        return True
    if path.startswith("/media/"):
        return True
    if path.startswith("/auth/share/"):
        return True
    return False


_GUILD_PATH = re.compile(r"^/(?:api/v1/)?guilds?/(\d+)(?:/|$)")
# A path shaped like a guild route but with a non-numeric id (e.g.
# /api/v1/guilds/abc/...) bypasses the _GUILD_PATH gate above and would make
# handlers crash on int(guild_id) -> 500. Reject it at the boundary.
_GUILD_PATH_NONDIGIT = re.compile(r"^/(?:api/v1/)?guilds?/[^\d/][^/]*(?:/|$)")
_MANAGEMENT_PAGE_PATH = re.compile(
    r"^/(?:api/v1/)?guilds?/\d+/(members|modules|moderation|settings|notes|activity|uploads|events)(?:/|$)"
)
_MODULE_ACTION_PATH = re.compile(r"^/api/v1/guilds/(\d+)/modules/([a-z0-9_-]+)/(.+)$")
_API_GUILD_MUTATION_PATH = re.compile(r"^/api/v1/guilds/\d+/(.+)$")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Sliding session renewal interval: refresh the cookie Max-Age at most this
# often per active session, instead of re-signing on every request.
SESSION_RENEW_SECONDS = 300


def _guild_id_from_path(path: str) -> str | None:
    match = _GUILD_PATH.match(path)
    return match.group(1) if match else None


def _is_management_page(path: str) -> bool:
    """Return whether the path is a management surface (members, modules,
    moderation, settings) that view-only members must not reach."""
    return _MANAGEMENT_PAGE_PATH.match(path) is not None


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
    # Instance-management routes (updates, backups, plugins, instance settings)
    # are owner-gated by their own handlers via ``can_manage_instance``. They are
    # NOT guild mutations, so the fail-closed default below (guild.manage = admin)
    # would wrongly 403 an instance owner who isn't a Discord server admin. Let
    # the route's owner check be the single authority for these paths.
    if path.startswith("/api/v1/instance/"):
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
        # Module lifecycle routes must resolve to the MODULE's own capability
        # (e.g. ``moderation.manage``), not the global ``modules.configure``,
        # so per-guild ModuleRoleAccess overrides apply uniformly. The generic
        # ``modules.configure``/``modules.manage`` core actions are the
        # fallback when no per-guild override exists (both default to admin).
        module_name = module_match.group(1)
        return f"{module_name}.manage" if module_match.group(2) else f"{module_name}.configure"
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


async def read_upload_limited(file, max_bytes: int) -> bytes:
    """Read an uploaded file without buffering more than ``max_bytes``.

    ``UploadFile.read()`` with no argument buffers the entire stream into
    memory before any size check, so a malicious client could stream an
    unbounded body and exhaust the process. Reading in capped chunks aborts
    as soon as the limit is exceeded.
    """
    chunk_size = 64 * 1024
    remaining = max_bytes + 1
    payload = bytearray()
    while remaining > 0:
        chunk = await file.read(min(chunk_size, remaining))
        if not chunk:
            break
        payload.extend(chunk)
        remaining -= len(chunk)
        if len(payload) > max_bytes:
            break
    return bytes(payload)


def _auth_required_response(path: str) -> Response:
    """Return the 401/302 response for a missing session on the given path."""
    if path.startswith("/api/"):
        return _json_error(401, "Authentication required")
    return RedirectResponse(url="/auth/login", status_code=302)


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

        # Sliding session renewal: refresh the cookie Max-Age at most once per
        # SESSION_RENEW_SECONDS instead of on every request, so an active user
        # stays logged in indefinitely but responses don't all carry a fresh
        # Set-Cookie. Inactivity beyond session_ttl still expires the cookie
        # (signer max_age).
        if int(time.monotonic()) - request.session.get("_renewed", 0) >= SESSION_RENEW_SECONDS:
            request.session["_renewed"] = int(time.monotonic())

        # Bark instances admit any Discord user who is a member of a server
        # where Bark is installed — login is always required, but no dashboard
        # invite is needed for server members. Owner identity is config-backed;
        # an active hosted-instance grant remains a fallback admission path so
        # access revocation still takes effect on the next request.
        if (
            config.oauth2.owner_discord_ids
            and str(user.get("id")) not in {str(oid) for oid in config.oauth2.owner_discord_ids}
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
        if not guild_id and _GUILD_PATH_NONDIGIT.match(path):
            # Non-numeric guild ids can't exist — 404 instead of letting
            # handlers crash on int(guild_id) with a 500.
            return _json_error(404, "Guild not found")
        if guild_id:
            # Guild pages are open to: any member of a server where Bark is
            # installed (connected), and any manager of a server who may still
            # be setting it up (the "Add Bark" tier). A plain non-member of an
            # uninstalled server has nothing behind /guild/{id}.
            bot = getattr(request.app.state, "bot", None)
            bot_guild_ids = {str(g.id) for g in bot.guilds} if bot is not None else set()
            from database.engine import session_scope
            from services.dashboard_access import (
                can_manage_server,
                get_dashboard_admin_role,
                get_dashboard_moderator_roles,
                get_user_guild_access_row,
                role_from_access_with_staff_roles,
            )

            async with session_scope() as session:
                access = await get_user_guild_access_row(session, user["id"], guild_id)
                moderator_roles = await get_dashboard_moderator_roles(session, [guild_id])
                admin_role = await get_dashboard_admin_role(session, [guild_id])
            if access is None:
                return _access_denied_response(
                    path,
                    "You are not a member of this Discord server",
                    "You do not have access to this Discord server.",
                )
            guild_moderator_roles = moderator_roles.get(str(guild_id), set())
            guild_admin_role = admin_role.get(str(guild_id))
            can_manage = can_manage_server(access, guild_moderator_roles, guild_admin_role)
            if str(guild_id) not in bot_guild_ids:
                # Bark isn't installed here — only its managers reach the
                # "Add Bark" setup tier.
                if not can_manage:
                    return _access_denied_response(
                        path,
                        "Bark isn't installed in this server yet",
                        "You cannot manage a server where Bark isn't installed.",
                    )
            # Connected servers are open to every member. Whether they get the
            # full management surface depends on a real manage grant (server
            # owner, Discord manage permission, or configured staff role).
            # Running this Bark instance grants nothing: the owner is treated
            # like any other member unless they hold a real grant here.
            request.session["role"] = role_from_access_with_staff_roles(
                access,
                guild_moderator_roles,
                guild_admin_role,
            )
            # Non-granted members get a read-only view of the server: the
            # dashboard/statistics/info status page, with every management
            # page and module surface blocked.
            request.state.guild_viewer = not can_manage
            if request.state.guild_viewer:
                # Viewers are hard read-only. Block every state-changing guild
                # API call regardless of module role overrides (a "viewer"
                # override on a private module must not let a plain member
                # mutate), and block reads of private/management surfaces.
                if path.startswith("/api/v1/guilds/") and request.method not in _SAFE_METHODS:
                    return _json_error(
                        403,
                        "View-only access: this server is read-only for you",
                    )
                if _is_management_page(path):
                    if path.startswith("/api/"):
                        return _json_error(
                            403,
                            "View-only access: managing this server requires admin or moderator rights",
                        )
                    from fastapi.responses import RedirectResponse

                    return RedirectResponse(url=f"/guild/{guild_id}", status_code=303)

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
        referer = request.headers.get("referer")
        if (
            (request.url.path.startswith("/api/") or request.url.path == "/auth/logout")
            and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        ):
            # CSRF gate. An Origin header must be trusted when present. When it
            # is absent, fall back to Referer and reject if that is present but
            # untrusted. (Both-absent requests — curl/scripts — carry no victim
            # session in a browser and the session cookie is SameSite=Lax, so
            # they are not a browser CSRF vector.)
            if origin:
                if not _origin_allowed(origin, config):
                    return _json_error(403, "Cross-origin write rejected")
            elif referer and not _origin_allowed(referer, config):
                return _json_error(403, "Cross-origin write rejected")

        module_action = _module_action_from_path(request.url.path)
        if module_action is not None:
            guild_id, module_name, _ = module_action
            bot = getattr(request.app.state, "bot", None)
            manager = getattr(bot, "modules", None)
            if manager is not None and not manager.is_enabled_for_guild(guild_id, module_name):
                return _json_error(409, f"Module '{module_name}' is disabled for this server")

        path = request.url.path
        # Rate-limit /api/ AND the unauthenticated auth entry points (login
        # hammering, callback/share probing) — the only paths reachable without
        # a session.
        is_auth_entry = (
            path in {"/auth/login", "/auth/callback", "/auth/logout"}
            or path.startswith("/auth/share/")
        )
        if path.startswith("/api/") or is_auth_entry:
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
    """Harden every response with CSP and related security headers.

    Fonts are self-hosted and no page loads scripts/styles from external CDNs,
    so the CSP allows none of them (no unpkg/googleapis/fonts allowances) —
    that removes an entire class of supply-chain / XSS-via-CDN attack surface.
    ``cdn.discordapp.com`` stays for avatars/banners/emojis and ``ws:``/``wss:``
    for the realtime bridge. ``'unsafe-inline'`` is kept only because the
    dashboard uses inline template scripts + inline styles (self-hosted).
    """
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' https://cdn.discordapp.com data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if config.dashboard.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
