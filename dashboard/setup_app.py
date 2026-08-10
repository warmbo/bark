"""Minimal FastAPI app for first-time setup (no bot, no auth).

Serves only the setup wizard + static assets until ``.env`` is written;
the normal dashboard (``dashboard/__init__.py``) takes over after restart.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bark_version import __version__
from config import config

logger = logging.getLogger("bark.setup")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_setup_app() -> FastAPI:
    """Build the setup-only application."""
    app = FastAPI(title="Bark Setup", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates

    from dashboard.routes.setup import router as setup_router

    app.include_router(setup_router)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/setup", status_code=303)

    return app


async def run_setup() -> None:
    """Run the setup server on the configured dashboard port."""
    from uvicorn import Config, Server

    app = create_setup_app()
    logger.info("Setup mode: open http://%s:%s/setup to configure Bark", config.dashboard.host, config.dashboard.port)
    server = Server(
        Config(
            app,
            host=config.dashboard.host,
            port=config.dashboard.port,
            log_level="warning",
        )
    )
    await server.serve()
