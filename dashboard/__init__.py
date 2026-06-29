"""
Dashboard — FastAPI application for the Bark management web UI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import config
from dashboard.app import DashboardApp

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.dashboard")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app(bot: BarkBot) -> DashboardApp:
    """Create and configure the Bark dashboard."""
    app = FastAPI(
        title="Bark Dashboard",
        version="0.2.0",
        description="ZENHAWX server management platform",
        docs_url=None,
        redoc_url=None,
    )

    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.dashboard.secret_key,
        max_age=config.dashboard.session_ttl,
        same_site="lax",
    )

    # Static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Make templates available on app state
    app.state.templates = templates

    # Make bot available on app state
    app.state.bot = bot

    # ── Middleware ────────────────────────────────────

    @app.middleware("http")
    async def add_bot_to_request(request: Request, call_next):
        request.state.bot = bot
        response = await call_next(request)
        # Prevent browser caching on HTML pages
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # ── Web Routes ────────────────────────────────────

    from dashboard.routes.web.home import router as home_router
    from dashboard.routes.web.modules import router as modules_router
    from dashboard.routes.web.moderation import router as moderation_router
    from dashboard.routes.web.settings import router as settings_router
    from dashboard.routes.web.members import router as members_router

    app.include_router(home_router, prefix="")
    app.include_router(modules_router, prefix="/guild/{guild_id}")
    app.include_router(moderation_router, prefix="/guild/{guild_id}")
    app.include_router(settings_router, prefix="/guild/{guild_id}")
    app.include_router(members_router, prefix="/guild/{guild_id}")

    # ── API Routes ────────────────────────────────────

    from dashboard.routes.api.guilds import router as guilds_api
    from dashboard.routes.api.modules import router as modules_api
    from dashboard.routes.api.moderation import router as moderation_api
    from dashboard.routes.api.settings import router as settings_api
    from dashboard.routes.api.actions import router as actions_api

    app.include_router(guilds_api, prefix="/api/v1")
    app.include_router(modules_api, prefix="/api/v1")
    app.include_router(moderation_api, prefix="/api/v1")
    app.include_router(settings_api, prefix="/api/v1")
    app.include_router(actions_api, prefix="/api/v1")

    # ── Root Route ────────────────────────────────────

    @app.get("/")
    async def root(request: Request):
        return RedirectResponse(url="/dashboard")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_home(request: Request):
        guilds = list(bot.guilds)
        tmpl = request.app.state.templates
        return tmpl.TemplateResponse(
            request,
            "pages/dashboard.html",
            {"guilds": guilds},
        )

    return DashboardApp(app, bot)
