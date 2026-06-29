"""
Bark — main entry point.

Runs both the Discord bot and web dashboard in a single process.
"""

import asyncio
import logging
import sys

from config import config
from bot.client import BarkBot
from dashboard import create_app
from database.engine import init_db, close_db

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

    logger.info("Bark v0.2.0 starting up...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start bot and dashboard concurrently
    bot = BarkBot()

    dashboard_app = create_app(bot)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(bot.start(config.bot.token))
        tg.create_task(
            dashboard_app.run()
        )


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
