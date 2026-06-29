"""
Bark Discord Bot Client.

The bot connects to Discord and provides the execution layer
for all Bark modules.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import Intents
from discord.ext import commands

from config import config
from database.engine import session_scope
from database.models.guild import Guild

if TYPE_CHECKING:
    from services.module_manager import ModuleManager

logger = logging.getLogger("bark.bot")


class BarkBot(commands.Bot):
    """
    Extends commands.Bot with Bark-specific lifecycle:
    - Module discovery and management
    - Guild configuration loading
    - Dashboard integration
    """

    def __init__(self) -> None:
        intents = Intents.default()
        intents.message_content = True
        intents.members = True
        intents.moderation = True

        super().__init__(
            command_prefix=config.bot.command_prefix,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=config.bot.activity_text,
            ),
        )

        self._module_manager: ModuleManager | None = None

    # ── Properties ────────────────────────────────────

    @property
    def modules(self) -> ModuleManager:
        """Access the module manager."""
        if self._module_manager is None:
            from services.module_manager import ModuleManager
            self._module_manager = ModuleManager(self)
        return self._module_manager

    # ── Lifecycle ─────────────────────────────────────

    async def on_ready(self) -> None:
        logger.info(
            "Bot connected as %s (ID: %s) — %d guilds",
            self.user,
            self.user.id,
            len(self.guilds),
        )

        # Ensure guilds are registered in the database
        for guild in self.guilds:
            await self._register_guild(guild)

        # Discover and enable modules
        self.modules.discover()
        for module_name, module in self.modules.get_all_modules().items():
            await self.modules.enable_module(module_name)

        # Sync slash commands
        if config.bot.sync_commands:
            try:
                await self.tree.sync()
                logger.info("Slash commands synced")
            except Exception:
                logger.exception("Failed to sync slash commands")

        logger.info("Bot initialization complete")

    async def close(self) -> None:
        await self.modules.disable_all()
        await super().close()
        logger.info("Bot disconnected")

    # ── Guild Management ──────────────────────────────

    async def _register_guild(self, guild: discord.Guild) -> None:
        """Ensure the guild is registered in the database."""
        async with session_scope() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Guild).where(Guild.discord_id == str(guild.id))
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = guild.name
                existing.owner_id = str(guild.owner_id)
            else:
                session.add(
                    Guild(
                        discord_id=str(guild.id),
                        name=guild.name,
                        owner_id=str(guild.owner_id),
                    )
                )
            await session.commit()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._register_guild(guild)
        logger.info("Joined guild: %s (%s)", guild.name, guild.id)

    # ── Event Dispatch ────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        await self.process_commands(message)
