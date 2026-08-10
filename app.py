"""
Bark — main entry point.

Runs both the Discord bot and web dashboard in a single process.
"""

import asyncio
import logging
import os
import sys

from bark_version import __version__
from bot.client import BarkBot
from config import config
from dashboard import create_app
from database.engine import close_db, init_db

# Seconds the bot may take to reach Discord "ready" before the process exits
# for a systemd restart. A hung gateway handshake (no error, no timeout)
# previously left the dashboard alive with a dead bot and every server
# looking disconnected; the watchdog self-heals by restarting.
BOT_CONNECT_TIMEOUT = 90

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

    logger.info("Bark v%s starting up...", __version__)

    # First-time setup: no BARK_BOT_TOKEN yet — boot the setup wizard
    # (dashboard-only, no bot) so the user can write .env from the browser.
    if config.needs_setup:
        from dashboard.setup_app import run_setup

        logger.warning(
            "No BARK_BOT_TOKEN configured — starting in first-time setup mode "
            "(open the dashboard URL to complete setup)"
        )
        await run_setup()
        return

    config.validate_startup()

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Start bot and dashboard concurrently
    bot = BarkBot()

    dashboard_app = create_app(bot)

    # Hang-proof startup: the dashboard keeps serving while the bot connects,
    # but if Discord never becomes ready (hung gateway handshake, no error),
    # exit so systemd (Restart=always) brings us back up. A retry connects
    # where a hang would not — without this the instance would sit alive with
    # a dead bot and every server would look empty/disconnected.
    asyncio.get_event_loop().create_task(
        bot_ready_watchdog(bot, timeout=BOT_CONNECT_TIMEOUT)
    )

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


async def bot_ready_watchdog(bot, timeout: float = BOT_CONNECT_TIMEOUT) -> None:
    """Exit the process if the bot never reaches Discord ``ready``.

    A hung gateway handshake previously left the dashboard alive with a dead
    bot (0 connected servers, every guild page failing) and no log line. With
    the watchdog, the process exits after ``timeout`` seconds and systemd
    restarts it — the retry connects in the normal few seconds.
    """
    try:
        await asyncio.wait_for(bot.wait_until_ready(), timeout)
    except asyncio.TimeoutError:
        logger.critical(
            "Bot did not connect to Discord within %ss — exiting for systemd restart",
            timeout,
        )
        os._exit(1)


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
