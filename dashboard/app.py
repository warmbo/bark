"""
Dashboard application runner.

Wraps the FastAPI app with uvicorn for async execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from uvicorn import Server

from config import config

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.dashboard")


class DashboardApp:
    """Wraps a FastAPI app with uvicorn lifecycle management."""

    def __init__(self, app: FastAPI, bot: BarkBot) -> None:
        self.app = app
        self.bot = bot
        self._server: Server | None = None

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
        server = uvicorn.Server(config_obj)
        self._server = server
        try:
            await server.serve()
        except SystemExit:
            logger.exception("Dashboard exited with SystemExit")
