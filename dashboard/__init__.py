"""
Dashboard — FastAPI application for the Bark management web UI.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bark_version import __version__
from config import config
from dashboard.app import DashboardApp
from dashboard.middleware.compression import SafeGzipMiddleware
from services.security import AuthMiddleware, SecurityMiddleware, trusted_origin_hosts

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.dashboard")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(bot: BarkBot) -> DashboardApp:
    """Create and configure the Bark dashboard."""
    app = FastAPI(
        title="Bark Dashboard",
        version=__version__,
        description="ZENHAWX server management platform",
        docs_url=None,
        redoc_url=None,
    )

    # Starlette executes class middleware in reverse registration order.
    # Session must wrap Security (rate-limit user identity) and Auth; Security
    # must wrap Auth so rejected responses still receive security headers.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.dashboard.secret_key,
        max_age=config.dashboard.session_ttl,
        same_site="lax",
        https_only=config.dashboard.secure_cookies,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        # Hosts derived from config (public_url + bind host + loopback +
        # BARK_TRUSTED_ORIGINS); "test" covers the test client's hostname.
        allowed_hosts=sorted(trusted_origin_hosts(config) | {"test"}),
    )

    # Static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Uploaded images for Discord markdown fields (public so Discord can fetch them)
    from dashboard.routes.api.uploads import uploads_directory

    uploads_directory().mkdir(parents=True, exist_ok=True)
    app.mount(
        "/media/uploads",
        StaticFiles(directory=str(uploads_directory())),
        name="media-uploads",
    )

    # Templates. The primary search path is the shared dashboard templates
    # tree, but module-specific UI now lives in each module's own
    # ``templates/`` directory (e.g. ``moderation/templates/...``). Adding the
    # project root as a secondary loader lets ``{% include %}`` resolve those
    # colocated templates without re-coupling them into the shared tree.
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    repo_root = TEMPLATES_DIR.parent.parent
    templates.env.loader.searchpath.append(str(repo_root))
    templates.env.globals.setdefault("config", config)

    # Every API error goes through the standard envelope. FastAPI's default
    # HTTPException handler returns {"detail": ...}, the one non-{success,error}
    # shape in the app (e.g. the plugin-removal route guard). Override it so
    # dependency-raised HTTP errors match api_error() output.
    from fastapi import HTTPException
    from fastapi.exception_handlers import http_exception_handler
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    async def _envelope_or_branded_404(request: Request, exc):
        """Shared handling: API errors keep the JSON envelope; a 404 on a
        non-API path renders the branded Bark 404 page."""
        if request.url.path.startswith("/api/"):
            content = {"success": False, "error": str(exc.detail or "Request failed")}
            return JSONResponse(
                status_code=exc.status_code, content=content, headers=getattr(exc, "headers", None)
            )
        if exc.status_code == 404:
            from services.response import render_not_found_standalone

            return await render_not_found_standalone(
                request,
                templates,
                detail=str(exc.detail) if exc.detail else None,
            )
        return await http_exception_handler(request, exc)

    @app.exception_handler(HTTPException)
    async def _envelope_http_exception(request: Request, exc: HTTPException):
        return await _envelope_or_branded_404(request, exc)

    # Unmatched routes raise StarletteHTTPException (a subclass of HTTPException);
    # FastAPI's built-in handler for that subclass would otherwise win and return a
    # bare JSON body. Register the same branded handling for it so a broken URL on
    # ANY instance renders the on-brand 404 page.
    @app.exception_handler(StarletteHTTPException)
    async def _envelope_starlette_http_exception(request: Request, exc: StarletteHTTPException):
        return await _envelope_or_branded_404(request, exc)

    # Make templates available on app state
    app.state.templates = templates
    app.state.version = __version__

    # Make bot available on app state
    app.state.bot = bot

    from services.realtime_bridge import RealtimeBridge

    realtime_bridge = RealtimeBridge(bot.modules.event_bus)
    app.state.realtime_bridge = realtime_bridge
    app.router.add_event_handler("startup", realtime_bridge.start)
    app.router.add_event_handler("shutdown", realtime_bridge.stop)
    from services.response import load_module_role_access_cache

    app.router.add_event_handler("startup", load_module_role_access_cache)

    # Give bot a reference to the FastAPI app for module API route registration
    bot.app = app

    # ── Middleware ────────────────────────────────────

    @app.middleware("http")
    async def add_bot_to_request(request: Request, call_next):
        request.state.bot = bot
        response = await call_next(request)
        # Versioned static assets can be cached aggressively — ?v=N handles invalidation
        content_type = response.headers.get("content-type", "")
        if request.url.path.startswith(("/static/", "/media/")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        # Prevent browser caching on HTML pages
        elif "text/html" in content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Dev-build watermark: applied at the HTTP layer so EVERY page/module on
    # the subdomain carries it (module detail pages render via their own Jinja
    # envs without `config`, so the old template include was bypassed there).
    from services.dev_overlay import dev_overlay_middleware

    app.middleware("http")(dev_overlay_middleware)

    # Slug routing: rewrite /g/{slug}[/<page>] -> /guild/{guild_id}[/<page>]
    # internally so slug URLs work behind any reverse proxy with no per-host
    # rewrite rules and never expose the numeric guild id. Registered AFTER the
    # auth/security middleware so it runs BEFORE them (Starlette runs the last
    # registered middleware outermost) and they see the canonical /guild/{id}
    # path with the same gates as a direct id URL.
    from services.slug_router import slug_rewrite_middleware

    app.middleware("http")(slug_rewrite_middleware)

    # Outermost middleware: compresses the final response. Registered last so
    # Starlette runs it first (outermost) — inner middleware (e.g. the dev
    # overlay, which rewrites raw HTML bodies) must see the uncompressed body.
    app.add_middleware(SafeGzipMiddleware, minimum_size=500)

    # ── Web Routes ────────────────────────────────────

    from dashboard.routes.web.home import router as home_router
    from dashboard.routes.web.members import router as members_router
    from dashboard.routes.web.moderation import router as moderation_router
    from dashboard.routes.web.modules import router as modules_router
    from dashboard.routes.web.settings import router as settings_router
    from dashboard.routes.web.stats import router as stats_router

    app.include_router(home_router, prefix="")
    app.include_router(modules_router, prefix="/guild/{guild_id}")
    app.include_router(moderation_router, prefix="/guild/{guild_id}")
    app.include_router(settings_router, prefix="/guild/{guild_id}")
    app.include_router(members_router, prefix="/guild/{guild_id}")
    app.include_router(stats_router, prefix="/guild/{guild_id}")

    # ── API Routes ────────────────────────────────────

    from dashboard.routes.api.actions import router as actions_api
    from dashboard.routes.api.audit_log import router as audit_log_api
    from dashboard.routes.api.backups import router as backups_api
    from dashboard.routes.api.bot_appearance import router as bot_appearance_api
    from dashboard.routes.api.guilds import router as guilds_api
    from dashboard.routes.api.health import router as health_api
    from dashboard.routes.api.instance_invites import router as instance_invites_api
    from dashboard.routes.api.manifest import router as manifest_api
    from dashboard.routes.api.moderation import router as moderation_api
    from dashboard.routes.api.modules import router as modules_api
    from dashboard.routes.api.notes import router as notes_api
    from dashboard.routes.api.plugins import router as plugins_api
    from dashboard.routes.api.realtime import router as realtime_api
    from dashboard.routes.api.settings import router as settings_api
    from dashboard.routes.api.updates import router as updates_api
    from dashboard.routes.api.uploads import router as uploads_api
    from dashboard.routes.auth import router as auth_router

    app.include_router(manifest_api, prefix="/api/v1")
    app.include_router(guilds_api, prefix="/api/v1")
    app.include_router(modules_api, prefix="/api/v1")
    app.include_router(moderation_api, prefix="/api/v1")
    app.include_router(settings_api, prefix="/api/v1")
    app.include_router(updates_api, prefix="/api/v1")
    app.include_router(backups_api, prefix="/api/v1")
    app.include_router(actions_api, prefix="/api/v1")
    app.include_router(health_api, prefix="/api/v1")
    app.include_router(instance_invites_api, prefix="/api/v1")
    app.include_router(audit_log_api, prefix="/api/v1")
    app.include_router(realtime_api, prefix="/api/v1")
    app.include_router(notes_api, prefix="/api/v1")
    app.include_router(plugins_api, prefix="/api/v1")
    app.include_router(bot_appearance_api, prefix="/api/v1")
    app.include_router(uploads_api, prefix="/api/v1")
    app.include_router(auth_router)

    # ── Root Route ────────────────────────────────────

    @app.get("/invite", response_class=HTMLResponse)
    async def invite_redirect(request: Request):
        """Branded invite landing page — redirects humans to Discord OAuth.

        Returns 200 HTML with Bark OpenGraph tags instead of a bare 302 so that
        sharing the invite link in Discord shows a Bark-branded card. Discord's
        link unfurl reads the HTML (it never follows client-side redirects);
        humans get a meta-refresh + JS redirect to the real Discord OAuth URL,
        with a manual "Continue to Discord" button as fallback.

        The user-facing invite URL shown in the UI is always the branded
        ``{public_url}/invite`` (config.dashboard.invite_url); this route
        computes the actual Discord OAuth redirect target server-side so the
        page never loops back to itself.
        """
        from services.dashboard_access import build_bot_invite_url

        invite_url = build_bot_invite_url(config.oauth2.client_id, "")
        tmpl = request.app.state.templates
        return tmpl.TemplateResponse(
            request,
            "pages/invite.html",
            {
                "config": config,
                "invite_url": invite_url,
            },
        )

    @app.get("/")
    async def root(request: Request):
        """Serve the Bark landing/welcome page with OG tags."""
        avatar_url = ""
        if bot and bot.user and bot.user.display_avatar:
            avatar_url = bot.user.display_avatar.url

        from dashboard.routes.auth import AUTH_ERROR_MESSAGES

        auth_error_code = request.query_params.get("auth_error", "")
        auth_error = AUTH_ERROR_MESSAGES.get(auth_error_code, "")

        tmpl = request.app.state.templates
        return tmpl.TemplateResponse(
            request,
            "pages/landing.html",
            {
                "config": config,
                "avatar_url": avatar_url,
                "auth_error": auth_error,
            },
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_home(request: Request):
        # Uvicorn starts accepting requests before the Discord gateway is ready.
        # Give the initial dashboard request a chance to receive the real guild
        # cache instead of rendering a stale "0 connected" page.
        if not bot.is_ready():
            try:
                await asyncio.wait_for(bot.wait_until_ready(), timeout=10)
            except TimeoutError:
                logger.warning("Dashboard rendered before Discord became ready")

        if config.oauth2.enabled and request.session.get("user"):
            from database.engine import session_scope
            from services.dashboard_access import (
                build_guild_catalog,
                get_dashboard_admin_role,
                get_dashboard_moderator_roles,
                get_user_guild_access,
            )

            user_id = request.session["user"]["id"]
            async with session_scope() as session:
                access = await get_user_guild_access(session, user_id)
                moderator_roles = await get_dashboard_moderator_roles(
                    session, (row.guild_id for row in access)
                )
                admin_roles = await get_dashboard_admin_role(
                    session, (row.guild_id for row in access)
                )
            guilds = build_guild_catalog(
                access,
                bot.guilds,
                client_id=config.oauth2.client_id,
                moderator_roles_by_guild=moderator_roles,
                admin_roles_by_guild=admin_roles,
                is_instance_owner=bool(
                    config.oauth2.owner_discord_ids
                    and user_id in config.oauth2.owner_discord_ids
                ),
                public_url=config.dashboard.public_url,
            )
        else:
            guilds = [
                {
                    "id": str(guild.id),
                    "name": guild.name,
                    "icon_url": guild.icon.url if guild.icon else None,
                    "member_count": guild.member_count,
                    "connected": True,
                    "can_manage": True,
                    "ready_to_manage": True,
                    "access_tier": "connected",
                    "invite_url": "",
                }
                for guild in bot.guilds
            ]
        tmpl = request.app.state.templates
        return tmpl.TemplateResponse(
            request,
            "pages/dashboard.html",
            {
                "guilds": guilds,
                "config": config,
                "command_prefix": f"/{bot.modules.command_group_name()} ",
            },
        )

    return DashboardApp(app, bot)
