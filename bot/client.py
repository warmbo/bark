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
    from services.data_collector import GuildDataCollector
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

        # Slash commands (the single /bark dispatcher) are the primary
        # interface. A static text prefix is kept purely as a fallback so
        # bark!help still works; it is no longer per-guild configurable.
        super().__init__(
            command_prefix=config.bot.command_prefix or "bark!",
            intents=intents,
            help_command=None,  # our help module provides `bark!help` / /bark help
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name=config.bot.activity_text,
            ),
        )

        self._module_manager: ModuleManager | None = None
        self._app = None  # FastAPI app, set by dashboard at creation
        self._data_collector: GuildDataCollector | None = None
        self._initialized_once = False
        self._install_tree_error_handler()

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

    # ── Command error handling ─────────────────────────

    def _install_tree_error_handler(self) -> None:
        """Give every slash-command failure structured context.

        Without this, discord.py logs command errors to the root logger with
        no guild/user/command context, and users see the raw exception text in
        Discord. Log with context; reply with a generic message (never the
        raw exception — it can contain internals)."""

        async def _on_tree_error(interaction, error):
            guild_id = getattr(interaction.guild, "id", None) or interaction.guild_id
            user_id = getattr(interaction.user, "id", None)
            command = getattr(interaction.command, "name", None) or "?"
            if isinstance(error, discord.app_commands.CommandInvokeError):
                logger.exception(
                    "Command '%s' failed for user %s in guild %s",
                    command,
                    user_id,
                    guild_id,
                )
                message = "Something went wrong running that command. The error has been logged."
            else:
                # Expected command errors (bad args, checks) — quieter, still contextual.
                logger.warning(
                    "Command '%s' rejected for user %s in guild %s: %s",
                    command,
                    user_id,
                    guild_id,
                    error,
                )
                message = f"Couldn't run that command: {error}"
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

        self.tree.error(_on_tree_error)

    # ── Lifecycle ─────────────────────────────────────

    async def on_ready(self) -> None:
        if self.user is None:
            logger.warning("on_ready fired without a logged-in user; skipping init")
            return
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
        from database.engine import session_scope
        from database.models.module import ModuleConfig

        async with session_scope() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id.in_([str(g.id) for g in self.guilds])
                )
            )
            module_configs = list(result.scalars())
        self.modules.load_guild_states(
            ((row.guild_id, row.module_name, row.enabled) for row in module_configs)
        )
        # Register EVERY module's commands (core + installed plugins) so they
        # are all present in the global /bark tree after this sync. Per-guild
        # enablement then only flips an execution gate (instant) instead of
        # requiring a command re-sync with Discord's ~1h global-command lag.
        for name in list(self.modules.get_all_modules().keys()):
            await self.modules.enable_module(name)

        if config.bot.sync_commands:
            try:
                if config.bot.sync_guild_id:
                    # Dev instances: clear stale global registrations, then
                    # sync instantly to the configured test guild. Guild
                    # commands bypass Discord's global-command cache entirely.
                    await self.tree.sync()
                    await self.tree.sync(
                        guild=discord.Object(id=config.bot.sync_guild_id)
                    )
                    logger.info(
                        "Slash commands synced to guild %s",
                        config.bot.sync_guild_id,
                    )
                else:
                    await self.tree.sync()
                    logger.info("Slash commands synced")
            except Exception:
                logger.exception("Failed to sync slash commands")

        logger.info("Bot initialization complete")

        # Only sessions left by a previous process are stale. Reconnects must
        # not close sessions opened by this process.
        if not self._initialized_once:
            try:
                import datetime

                from sqlalchemy import update

                from database.engine import session_scope
                from database.models.voice import VoiceSession

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

        # A guild joined after startup may need modules that were not enabled
        # when the tree last synced (e.g. the bot started with zero guilds).
        # Enable them now and re-sync so slash commands appear without a
        # restart. Fresh guilds default to enabled via is_enabled_for_guild.
        for name in list(self.modules.get_all_modules().keys()):
            module = self.modules.get_module(name)
            if (
                module is not None
                and not module.enabled
                and self.modules.should_run_globally(name)
            ):
                await self.modules.enable_module(name)
        if config.bot.sync_commands:
            try:
                if config.bot.sync_guild_id:
                    await self.tree.sync(
                        guild=discord.Object(id=config.bot.sync_guild_id)
                    )
                else:
                    await self.tree.sync()
            except Exception:
                logger.exception("Failed to sync slash commands after guild join")

    # ── Event → EventBus bridge ───────────────────────

    async def on_interaction(self, interaction) -> None:
        """Log every incoming application interaction.

        discord.py 2.7.1 already dispatches application commands to the
        command tree (ConnectionState.parse_interaction_create →
        tree._from_interaction) and routes components/modals through the
        view store, so this listener must NOT dispatch again. Calling
        ``self.tree.interaction(...)`` (a method that does not exist in
        2.7.1) raised AttributeError here, whose error handler then sent a
        bogus "Something went wrong" message — acknowledging the interaction
        before the real command ran and failing it with error 40060
        (Interaction has already been acknowledged).
        """
        data = interaction.data or {}
        logger.info(
            "Interaction: name=%s id=%s type=%s guild=%s user=%s",
            data.get("name"),
            data.get("id"),
            interaction.type,
            interaction.guild_id,
            getattr(interaction.user, "id", None),
        )

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
        # discord.py reuses the cached `after` VoiceState object and mutates it
        # when Auto Voice's move generates the next gateway event. Snapshot the
        # channels before any handler can await or trigger another transition.
        payload = {
            "member": member,
            "before": before,
            "after": after,
            "before_channel": before.channel,
            "after_channel": after.channel,
        }
        await bus.emit("discord_voice_state", **payload)
        await bus.emit("voice_state_change", **payload)

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        await self.modules.event_bus.emit("discord_presence_update", before=before, after=after)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        bus = self.modules.event_bus
        await bus.emit("raw_reaction_add", payload=payload)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        bus = self.modules.event_bus
        await bus.emit("raw_reaction_remove", payload=payload)
