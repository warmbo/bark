"""
Bark Discord Bot Client.

Minimal execution engine. Bridges Discord events to the EventBus.
No business logic lives here.

See docs/architecture-overview.md#startup-flow for lifecycle documentation.
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
    Minimal Discord bot runtime.

    Connects to Discord, bridges events to EventBus,
    delegates to ModuleManager for all business logic.
    """

    def __init__(self) -> None:
        intents = Intents.default()
        intents.message_content = True
        intents.members = True
        intents.moderation = True
        intents.presences = True

        super().__init__(
            command_prefix=config.bot.command_prefix,
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=config.bot.activity_text,
            ),
        )

        self._module_manager: ModuleManager | None = None
        self._app = None  # FastAPI app, set by dashboard at creation
        self._data_collector = None
        self._initialized_once = False

    # ── Properties ────────────────────────────────────

    @property
    def modules(self) -> ModuleManager:
        if self._module_manager is None:
            from services.module_manager import ModuleManager
            self._module_manager = ModuleManager(self)
        return self._module_manager

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, value):
        self._app = value

    # ── Lifecycle ─────────────────────────────────────

    async def on_ready(self) -> None:
        logger.info(
            "Bot connected as %s (ID: %s) — %d guilds",
            self.user,
            self.user.id,
            len(self.guilds),
        )

        for guild in self.guilds:
            await self._register_guild(guild)

        self.modules.discover()
        # Register each module's API routes with the dashboard app
        if self._app:
            self.modules.register_api_routes(self._app)
            logger.info("Module API routes registered")
        # Load module states from DB — only enable those the user has enabled
        from database.models.module import ModuleConfig
        from database.engine import session_scope
        async with session_scope() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id.in_([str(g.id) for g in self.guilds])
                )
            )
            module_configs = list(result.scalars())
        self.modules.load_guild_states(
            (
                (row.guild_id, row.module_name, row.enabled)
                for row in module_configs
            )
        )
        for name in list(self.modules.get_all_modules().keys()):
            if self.modules.should_run_globally(name):
                await self.modules.enable_module(name)

        if config.bot.sync_commands:
            try:
                await self.tree.sync()
                logger.info("Slash commands synced")
            except Exception:
                logger.exception("Failed to sync slash commands")

        logger.info("Bot initialization complete")

        # Only sessions left by a previous process are stale. Reconnects must
        # not close sessions opened by this process.
        if not self._initialized_once:
            try:
                from database.models.voice import VoiceSession
                from database.engine import session_scope
                from sqlalchemy import update
                import datetime
                now_ts = datetime.datetime.now(datetime.timezone.utc)
                async with session_scope() as session:
                    await session.execute(
                        update(VoiceSession)
                        .where(VoiceSession.left_at.is_(None))
                        .values(left_at=now_ts, duration_seconds=0)
                    )
                    await session.commit()
                logger.info("Stale voice sessions cleaned up")
            except Exception:
                logger.exception("Failed to clean up stale voice sessions")
            self._initialized_once = True

        # Restore persisted presence settings
        try:
            from services.presence_store import restore_presence
            await restore_presence(self)
        except Exception:
            logger.exception("Failed to restore presence")

        # Start data collector for analytics
        try:
            from services.data_collector import GuildDataCollector
            if self._data_collector is None:
                self._data_collector = GuildDataCollector(self, interval_minutes=15)
            await self._data_collector.start()
        except Exception:
            logger.exception("Failed to start data collector")

    async def close(self) -> None:
        if self._data_collector is not None:
            await self._data_collector.stop()
            self._data_collector = None
        await self.modules.disable_all()
        await super().close()
        logger.info("Bot disconnected")

    async def _register_guild(self, guild: discord.Guild) -> None:
        async with session_scope() as session:
            from sqlalchemy import select
            result = await session.execute(select(Guild).where(Guild.discord_id == str(guild.id)))
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

    # ── Event → EventBus bridge ───────────────────────

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        await self.process_commands(message)
        bus = self.modules.event_bus
        await bus.emit("discord_message", message=message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot:
            return
        bus = self.modules.event_bus
        await bus.emit("discord_message_edit", before=before, after=after)

    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        bus = self.modules.event_bus
        await bus.emit("discord_message_delete", message=message)

    async def on_member_join(self, member: discord.Member) -> None:
        bus = self.modules.event_bus
        await bus.emit("discord_member_join", member=member)

    async def on_member_remove(self, member: discord.Member) -> None:
        bus = self.modules.event_bus
        await bus.emit("discord_member_remove", member=member)

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        bus = self.modules.event_bus
        await bus.emit("discord_voice_state", member=member, before=before, after=after)
        await bus.emit("voice_state_change", member=member, before=before, after=after)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        bus = self.modules.event_bus
        await bus.emit("raw_reaction_add", payload=payload)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        bus = self.modules.event_bus
        await bus.emit("raw_reaction_remove", payload=payload)
