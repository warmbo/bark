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


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def resolve_setup_host(host: str, setup_token: str) -> str:
    """Return the host the setup server should bind.

    Without a setup token the wizard is a zero-auth bootstrap, so a non-loopback
    host is forced back to loopback — the unauthenticated wizard must never be
    reachable off-host.
    """
    if not setup_token and host not in _LOOPBACK_HOSTS:
        logger.warning(
            "Setup mode has no BARK_SETUP_TOKEN — forcing loopback bind "
            "(configured host %r would expose the unauthenticated wizard)",
            host,
        )
        return "127.0.0.1"
    return host


async def run_setup() -> None:
    """Run the setup server on the configured dashboard port.

    When no ``BARK_SETUP_TOKEN`` is configured, the setup wizard is a
    zero-auth bootstrap, so it is forced to bind loopback — it must never be
    exposed on a non-loopback interface where an unauthenticated client could
    claim the instance by writing ``.env``.
    """
    from uvicorn import Config, Server

    app = create_setup_app()
    host = resolve_setup_host(config.dashboard.host, config.dashboard.setup_token)
    logger.info("Setup mode: open http://%s:%s/setup to configure Bark", host, config.dashboard.port)
    server = Server(
        Config(
            app,
            host=host,
            port=config.dashboard.port,
            log_level="warning",
        )
    )
    await server.serve()
