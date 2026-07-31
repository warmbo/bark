"""
Bark — main entry point.

Runs both the Discord bot and web dashboard in a single process.
"""

import asyncio
import logging
import sys

from bark_version import __version__
from bot.client import BarkBot
from config import config
from dashboard import create_app
from database.engine import close_db, init_db

logger = logging.getLogger("bark")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.logging.level, logging.INFO),
        format=config.logging.format,
        stream=sys.stdout,
    )
    # Quiet noisy libs
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    config.validate_startup()

    logger.info("Bark v%s starting up...", __version__)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start bot and dashboard concurrently
    bot = BarkBot()

    dashboard_app = create_app(bot)

    try:
        # Keep the dashboard available for diagnostics if Discord authentication
        # fails, but report each service failure explicitly.
        results = await asyncio.gather(
            bot.start(config.bot.token),
            dashboard_app.run(),
            return_exceptions=True,
        )
        for label, result in zip(("bot", "dashboard"), results, strict=True):
            if isinstance(result, Exception):
                logger.error("%s failed: %s", label, result)
    finally:
        try:
            await bot.close()
        finally:
            await close_db()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    run()
