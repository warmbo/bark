"""
Dashboard application runner.

Wraps the FastAPI app with uvicorn for async execution.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from config import config

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.dashboard")


class DashboardApp:
    """Wraps a FastAPI app with uvicorn lifecycle management."""

    def __init__(self, app: FastAPI, bot: BarkBot) -> None:
        self.app = app
        self.bot = bot
        self._server = None

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
        )
        server = uvicorn.Server(config_obj)
        self._server = server
        try:
            await server.serve()
        except SystemExit:
            logger.exception("Dashboard exited with SystemExit")
