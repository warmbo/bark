"""
Bark — main entry point.

Runs both the Discord bot and web dashboard in a single process.
"""

import asyncio
import logging
import os
import signal
import sys

import discord

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
    logger.info("Bark running as PID %s (kill with: kill -INT %s)", os.getpid(), os.getpid())

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
    asyncio.get_event_loop().create_task(bot_ready_watchdog(bot, timeout=BOT_CONNECT_TIMEOUT))

    loop = asyncio.get_running_loop()

    # Single, coordinated shutdown: SIGINT/SIGTERM must stop the bot AND the
    # dashboard AND close the database. Uvicorn normally installs its own
    # handlers (which only stop the web server and can leave the bot task
    # keeping the process alive — the reason a bare `kill -INT` sometimes
    # appeared to do nothing and required a hard kill by PID). We neutralised
    # uvicorn's handler in DashboardApp, so these handlers are the only ones.
    def _request_shutdown(signame: str) -> None:
        logger.info("Received %s — shutting down", signame)
        # Tell uvicorn to stop: its main loop sees should_exit and `serve()`
        # returns, so dashboard_app.run() finishes.
        dashboard_app.stop()
        # Close the Discord client; bot.start() returns when closed, so the
        # gather below completes and the finally block closes the database.
        loop.create_task(bot.close())

    for sig, signame in ((signal.SIGINT, "SIGINT"), (signal.SIGTERM, "SIGTERM")):
        try:
            loop.add_signal_handler(sig, lambda s=signame: _request_shutdown(s))
        except (NotImplementedError, RuntimeError):
            # Non-POSIX platform (loop.add_signal_handler unavailable) — fall
            # back to asyncio.run's default KeyboardInterrupt handling.
            logger.warning("Could not install %s handler", signame)

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
                if isinstance(result, discord.errors.PrivilegedIntentsRequired):
                    # Discord gateway error 4014 (Disallowed intents): the bot
                    # app is missing a privileged gateway intent Bark requests.
                    # Unrecoverable without a Developer Portal change — make the
                    # fix obvious instead of a cryptic restart loop.
                    logger.critical(
                        "Discord rejected the connection (gateway error 4014, Disallowed intents). "
                        "Bark needs these Privileged Gateway Intents enabled in the Discord "
                        "Developer Portal -> your app -> Bot -> Privileged Gateway Intents: "
                        "Presence Intent, Server Members Intent, and Message Content Intent. "
                        "Enable all three, then restart Bark."
                    )
                else:
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
    the watchdog, the process exits after ``timeout`` seconds and the
    supervisor/systemd restarts it — the retry connects in the normal few
    seconds.

    ``bot.wait_until_ready()`` raises ``RuntimeError`` when the client has not
    been initialised yet — it races ``bot.start()`` at boot, and it fires
    immediately when the login/connect step fails (bad token, no gateway
    connection). That is "not ready yet", not a hang, so keep waiting until the
    deadline rather than letting the exception escape as an unretrieved task
    error.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.critical(
                "Bot did not connect to Discord within %ss — exiting for restart",
                timeout,
            )
            os._exit(1)
            return  # unreachable in production; present so tests that mock os._exit end the loop
        try:
            await asyncio.wait_for(bot.wait_until_ready(), timeout=min(remaining, 5.0))
            return  # ready
        except asyncio.TimeoutError:
            continue  # still connecting; re-check the deadline
        except RuntimeError:
            # Client not initialised yet (races bot.start() at boot, or login
            # failed). Not a hang — keep waiting; either a later iteration sees
            # ready, or the deadline exits.
            logger.debug("Bot not initialised yet — continuing to wait")
            await asyncio.sleep(0.5)


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
