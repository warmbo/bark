"""
Dashboard application runner.

Wraps the FastAPI app with uvicorn for async execution.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from uvicorn import Server

from config import config

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.dashboard")


class _SignalNeutralServer(Server):
    """uvicorn Server that does NOT install its own SIGINT/SIGTERM handlers.

    Uvicorn's ``serve()`` wraps the loop in ``capture_signals()``, which replaces
    the process's SIGINT/SIGTERM handlers with uvicorn's own ``handle_exit``.
    That only tells *the web server* to stop — it never stops the Discord bot
    running in the same process, so SIGINT could leave the bot task alive and
    the process hanging (you'd have to ``kill -9`` by PID).

    Bark installs one coordinated signal handler (see app.main) that stops the
    bot, the dashboard, and closes the database together. By neutralising
    uvicorn's handler here we keep a single, deterministic shutdown path.
    """

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[override]
        """No-op: do not hijack process signals; app.main owns them."""
        yield


class DashboardApp:
    """Wraps a FastAPI app with uvicorn lifecycle management."""

    def __init__(self, app: FastAPI, bot: BarkBot) -> None:
        self.app = app
        self.bot = bot
        self._server: _SignalNeutralServer | None = None

    async def run(self) -> None:
        """Run the dashboard server. Blocks until shutdown."""
        host = config.dashboard.host
        port = config.dashboard.port
        logger.info(
            "Dashboard starting on %s (bind %s:%d)",
            config.dashboard.public_url,
            host,
            port,
        )

        config_obj = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            # Trust X-Forwarded-* from the configured proxies so the real client
            # IP (rate limiting) and scheme (force_https, secure cookies) are
            # correct behind a TLS-terminating reverse proxy / Cloudflare.
            proxy_headers=True,
            forwarded_allow_ips=config.dashboard.forwarded_allow_ips,
        )
        server = _SignalNeutralServer(config_obj)
        self._server = server
        try:
            await server.serve()
        except SystemExit:
            logger.exception("Dashboard exited with SystemExit")

    def stop(self) -> None:
        """Ask uvicorn to stop accepting/processing requests and shut down.

        Safe to call from a signal handler: it only flips a flag that uvicorn's
        main loop checks, letting the running ``await server.serve()`` return so
        ``app.main``'s coordinated shutdown can finish.
        """
        if self._server is not None:
            self._server.should_exit = True
