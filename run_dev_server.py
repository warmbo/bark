"""Bark Development entry point.

Runs the real bot + dashboard when a dev ``BARK_BOT_TOKEN`` is configured;
otherwise boots the dashboard with a mock bot so the UI (including the plugin
manager) is fully usable without a Discord connection.

Usage:
    BARK_BOT_TOKEN=<dev-token> python run_dev_server.py   # real bot
    python run_dev_server.py                               # mock dashboard
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _boot_mock() -> None:
    """Dashboard-only mode: a mock bot with no Discord connection."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    logging.basicConfig(level=logging.WARNING)

    from dashboard import create_app
    from database import engine as db_engine
    from database.engine import Base
    from services.module_manager import ModuleManager

    async def init_db() -> None:
        engine = db_engine.get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    class MockGuild:
        """Fake guild with template-accessible attributes."""

        def __init__(self, id: int = 123456789, name: str = "Dev Test Guild"):
            self.id = id
            self.name = name
            self.member_count = 142
            self.icon = None
            self.premium_subscription_count = 5
            self.premium_tier = 2
            self.verification_level = MagicMock()
            self.verification_level.name = "Medium"
            self.created_at = datetime(2023, 6, 15, tzinfo=timezone.utc)
            self.owner = MagicMock()
            self.owner.name = "TestOwner"
            self.owner.id = 98765
            self.text_channels = []
            self.voice_channels = []
            self.channels = []
            self.roles = []
            self.members = []

        def get_member(self, member_id):
            return None

    class MockBarkBot:
        def __init__(self):
            self._module_manager = ModuleManager(self)
            self.user = MagicMock()
            self.user.name = "Bark Dev"
            self.user.id = 123456789
            # Prevent MagicMock auto-attributes from leaking into API responses
            # (e.g. /bot/appearance serializes user.discriminator).
            self.user.discriminator = "0000"
            self.user.display_avatar = MagicMock()
            self.user.display_avatar.url = (
                "https://cdn.discordapp.com/avatars/123/hash.png"
            )
            self.user.banner = None
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._guild = MockGuild()
            self._module_manager.discover()

        @property
        def modules(self):
            return self._module_manager

        @property
        def guilds(self):
            return [self._guild]

        def is_ready(self):
            return True

        async def wait_until_ready(self):
            return None

        def get_guild(self, guild_id):
            return self._guild if int(guild_id) == self._guild.id else None

    import bot.client

    bot.client.BarkBot = MockBarkBot  # type: ignore[assignment]

    bot = MockBarkBot()
    bot.loop.run_until_complete(init_db())
    app = create_app(bot).app  # type: ignore[arg-type]

    # Real mode registers module API routes in on_ready; the mock never
    # connects to Discord, so do it here explicitly (core + plugin modules).
    bot.modules.register_api_routes(app)

    import uvicorn

    from config import config

    uvicorn.run(
        app,
        host=config.dashboard.host,
        port=config.dashboard.port,
        log_level="warning",
        proxy_headers=True,
        forwarded_allow_ips=config.dashboard.forwarded_allow_ips,
    )


if __name__ == "__main__":
    if os.getenv("BARK_BOT_TOKEN"):
        from app import run

        run()
    else:
        _boot_mock()
