"""
AutoMod module for Bark.

Provides automated moderation: spam detection, invite filtering,
and mention spam prevention.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord

from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)
from database.engine import session_scope
from database.models.automod import AutoModConfig

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.modules.automod")

INVITE_REGEX = re.compile(
    r"(?:discord\.(?:gg|io|me|com\/invite)\/|discord\.com\/invite\/)[a-zA-Z0-9_\-]+",
    re.IGNORECASE,
)

RULE_TYPES = ["spam", "invite", "mention"]


class AutoModModule(BarkModule):
    """Automated content moderation — spam, invites, and mention limits."""

    name = "automod"
    version = "1.0.0"
    description = "Automatic spam detection, invite filtering, and mention spam prevention"
    author = "ZENHAWX"

    def __init__(self, bot: BarkBot) -> None:
        super().__init__(bot)
        # Track message counts per user for spam detection: {guild_id: {user_id: deque of timestamps}}
        self._message_track: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=100))
        )
        self._mention_track: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=20))
        )
        self._config_cache: dict[int, dict[str, dict]] = {}

    # ── Registration ──────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="automod", description="Configure AutoMod rules"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration(event_name="on_message"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/settings",
                label="AutoMod Settings",
                icon="🛡",
                parent="settings",
            ),
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="automod.configure", label="Configure AutoMod", description="Set AutoMod rules and thresholds"),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure automated moderation rules per type. Each rule type can be "
                           "independently enabled with custom thresholds and actions.",
            "properties": {
                rule_type: {
                    "type": "object",
                    "title": rule_type.replace("_", " ").title(),
                    "description": {
                        "spam": "Detects users sending many messages in a short window. "
                                "Triggers when a user exceeds the threshold within 10 seconds.",
                        "invite": "Detects Discord invite links (discord.gg, discord.com/invite) "
                                  "in messages and takes action.",
                        "mention": "Detects excessive @mentions in a single message or rapid "
                                   "mention spam within 30 seconds.",
                    }.get(rule_type, f"AutoMod rule for {rule_type}"),
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "title": "Enabled",
                            "description": "Turn this AutoMod rule on or off.",
                        },
                        "threshold": {
                            "type": "integer",
                            "minimum": 1,
                            "title": "Threshold",
                            "placeholder": "5",
                            "description": {
                                "spam": "Max messages allowed in the 10-second window before triggering.",
                                "invite": "Not used for invite filtering.",
                                "mention": "Max @mentions per message before triggering.",
                            }.get(rule_type, "Trigger threshold value."),
                        },
                        "action": {
                            "type": "string",
                            "enum": ["warn", "timeout", "delete"],
                            "title": "Action",
                            "placeholder": "warn",
                            "description": {
                                "spam": "What to do when spam is detected. 'warn' sends a warning, "
                                        "'timeout' temporarily mutes, 'delete' just removes the message.",
                                "invite": "What to do when an invite link is posted.",
                                "mention": "What to do on mention spam.",
                            }.get(rule_type, "Action to take when rule triggers."),
                        },
                        "duration": {
                            "type": "integer",
                            "minimum": 1,
                            "title": "Duration (minutes)",
                            "placeholder": "10",
                            "description": "How long a timeout lasts, in minutes. "
                                           "Only applies when action is set to 'timeout'.",
                        },
                        "ignored_roles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "title": "Ignored Role IDs",
                            "placeholder": '["123456789", "987654321"]',
                            "description": "Discord role IDs that are exempt from this rule. "
                                           "Members with any of these roles won't be checked.",
                        },
                        "ignored_channels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "title": "Ignored Channel IDs",
                            "placeholder": '["123456789", "987654321"]',
                            "description": "Channel IDs where this rule is disabled. "
                                           "Messages in these channels won't be checked.",
                        },
                    },
                }
                for rule_type in RULE_TYPES
            },
        }

    # ── Lifecycle ─────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling AutoMod module")
        self._message_track.clear()
        self._mention_track.clear()

        # Add slash command
        if hasattr(self.bot, "tree"):
            self.bot.tree.add_command(self._make_automod_command())

    async def disable(self) -> None:
        self._logger.info("Disabling AutoMod module")
        self._message_track.clear()
        self._mention_track.clear()
        self._config_cache.clear()

        if hasattr(self.bot, "tree"):
            self.bot.tree.remove_command("automod")

    # ── Commands ──────────────────────────────────────

    def _make_automod_command(self):
        @discord.app_commands.command(name="automod", description="Configure AutoMod rules")
        @discord.app_commands.default_permissions(manage_guild=True)
        async def automod(
            interaction: discord.Interaction,
            rule: str = "spam",
            enabled: bool = None,
            threshold: int = None,
            action: str = None,
        ):
            await self._cmd_automod(interaction, rule, enabled, threshold, action)
        return automod

    async def _cmd_automod(
        self,
        interaction: discord.Interaction,
        rule: str,
        enabled: bool | None,
        threshold: int | None,
        action: str | None,
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)

        if rule not in RULE_TYPES:
            await interaction.followup.send(
                f"Invalid rule type. Valid: {', '.join(RULE_TYPES)}", ephemeral=True
            )
            return

        from sqlalchemy import select

        async with session_scope() as session:
            result = await session.execute(
                select(AutoModConfig).where(
                    AutoModConfig.guild_id == interaction.guild.id,
                    AutoModConfig.rule_type == rule,
                )
            )
            config = result.scalar_one_or_none()

            if config is None:
                config = AutoModConfig(
                    guild_id=interaction.guild.id,
                    rule_type=rule,
                )
                session.add(config)

            if enabled is not None:
                config.enabled = enabled
            if threshold is not None:
                config.threshold = threshold
            if action is not None and action in ("warn", "timeout", "delete"):
                config.action = action

            await session.commit()

        # Invalidate cache
        self._config_cache.pop(interaction.guild.id, None)

        status = "enabled" if enabled else "configured"
        await interaction.followup.send(
            f"✅ AutoMod rule `{rule}` {status}.", ephemeral=True
        )

    # ── Event Handler ─────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:
        """Check every message against AutoMod rules."""
        if message.author.bot:
            return
        if not message.guild:
            return

        guild_id = message.guild.id
        author_id = message.author.id

        # Load config for this guild if not cached
        configs = await self._get_guild_configs(guild_id)
        if not configs:
            return

        # Check ignored roles
        member = message.author
        if isinstance(member, discord.Member):
            for rule_config in configs.values():
                ignored_roles = rule_config.get("ignored_roles", [])
                if any(str(role.id) in ignored_roles for role in member.roles):
                    return  # User has ignored role

        # Check ignored channels
        channel_id = str(message.channel.id)
        for rule_config in configs.values():
            if channel_id in rule_config.get("ignored_channels", []):
                return  # Channel is ignored

        # Run rules
        now = datetime.now(timezone.utc)

        for rule_type, rule_config in configs.items():
            if not rule_config.get("enabled", False):
                continue

            try:
                if rule_type == "spam":
                    await self._check_spam(message, guild_id, author_id, rule_config, now)
                elif rule_type == "invite":
                    await self._check_invites(message, guild_id, rule_config)
                elif rule_type == "mention":
                    await self._check_mentions(message, guild_id, author_id, rule_config, now)
            except Exception:
                self._logger.exception("Error checking AutoMod rule '%s'", rule_type)

    # ── Rule Checks ───────────────────────────────────

    async def _check_spam(
        self,
        message: discord.Message,
        guild_id: int,
        author_id: int,
        config: dict,
        now: datetime,
    ) -> None:
        """Check for message spam (rapid messages in a short window)."""
        threshold = config.get("threshold", 5)
        window = config.get("window_seconds", 10)

        track = self._message_track[guild_id][author_id]

        # Clean old entries
        cutoff = now - timedelta(seconds=window)
        while track and track[0] < cutoff:
            track.popleft()

        track.append(now)

        if len(track) >= threshold:
            self._logger.info(
                "Spam detected: %s in %s (message %d/%d within %ds)",
                message.author, message.guild, len(track), threshold, window,
            )
            await self._take_action(message, config, f"Spam ({len(track)} messages in {window}s)")

    async def _check_invites(
        self,
        message: discord.Message,
        guild_id: int,
        config: dict,
    ) -> None:
        """Check for Discord invite links."""
        if INVITE_REGEX.search(message.content):
            self._logger.info(
                "Invite detected from %s in %s: %s",
                message.author, message.guild, message.content[:50],
            )
            await self._take_action(message, config, "Discord invite link")

    async def _check_mentions(
        self,
        message: discord.Message,
        guild_id: int,
        author_id: int,
        config: dict,
        now: datetime,
    ) -> None:
        """Check for mention spam."""
        threshold = config.get("threshold", 5)
        mention_count = len(message.mentions) + len(message.role_mentions) + len(message.mention_everyone)

        if mention_count >= threshold:
            self._logger.info(
                "Mention spam detected: %s mentioned %d users in %s",
                message.author, mention_count, message.guild,
            )
            await self._take_action(message, config, f"Mention spam ({mention_count} mentions)")
            return

        # Also check cumulative mention rate
        if mention_count > 0:
            track = self._mention_track[guild_id][author_id]
            cutoff = now - timedelta(seconds=30)

            while track and track[0] < cutoff:
                track.popleft()

            for _ in range(mention_count):
                track.append(now)

            if len(track) >= threshold * 3:
                await self._take_action(
                    message, config,
                    f"Mention spam ({len(track)} mentions in 30s)",
                )

    # ── Actions ───────────────────────────────────────

    async def _take_action(
        self,
        message: discord.Message,
        config: dict,
        reason: str,
    ) -> None:
        """Execute the configured action for a rule violation."""
        action = config.get("action", "warn")
        duration = config.get("duration", 10)

        if action == "delete":
            try:
                await message.delete()
                logger.info("Deleted message from %s: %s", message.author, reason)
            except discord.Forbidden:
                logger.warning("Cannot delete message: insufficient permissions")

        elif action == "warn":
            # Log warning to database
            from database.models.moderation import ModerationCase, Warning

            async with session_scope() as session:
                from sqlalchemy import select, func
                result = await session.execute(
                    select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
                    .where(ModerationCase.guild_id == message.guild.id)
                )
                case_number = result.scalar()

                case = ModerationCase(
                    guild_id=message.guild.id,
                    case_number=case_number,
                    action_type="warn",
                    target_id=str(message.author.id),
                    target_tag=str(message.author),
                    moderator_id=str(self.bot.user.id),
                    moderator_tag=str(self.bot.user),
                    reason=f"[AutoMod] {reason}",
                )
                session.add(case)

                warning = Warning(
                    guild_id=message.guild.id,
                    user_id=str(message.author.id),
                    moderator_id=str(self.bot.user.id),
                    reason=f"[AutoMod] {reason}",
                    active=True,
                )
                session.add(warning)
                await session.commit()

            try:
                await message.channel.send(
                    f"⚠️ {message.author.mention}, {reason}. Case #{case_number}",
                    delete_after=10,
                )
            except discord.Forbidden:
                pass

        elif action == "timeout":
            if not isinstance(message.author, discord.Member):
                return

            until = discord.utils.utcnow() + timedelta(minutes=duration)

            from database.models.moderation import ModerationCase

            async with session_scope() as session:
                from sqlalchemy import select, func
                result = await session.execute(
                    select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
                    .where(ModerationCase.guild_id == message.guild.id)
                )
                case_number = result.scalar()

                case = ModerationCase(
                    guild_id=message.guild.id,
                    case_number=case_number,
                    action_type="timeout",
                    target_id=str(message.author.id),
                    target_tag=str(message.author),
                    moderator_id=str(self.bot.user.id),
                    moderator_tag=str(self.bot.user),
                    reason=f"[AutoMod] {reason}",
                    duration=duration,
                )
                session.add(case)
                await session.commit()

            try:
                await message.author.timeout(until, reason=f"[AutoMod] {reason}")
                await message.channel.send(
                    f"⏱ {message.author.mention} timed out for {duration}m. {reason}",
                    delete_after=10,
                )
            except discord.Forbidden:
                logger.warning("Cannot timeout %s: insufficient permissions", message.author)

    # ── Config Loading ────────────────────────────────

    async def _get_guild_configs(self, guild_id: int) -> dict[str, dict]:
        """Load and cache AutoMod configs for a guild."""
        if guild_id in self._config_cache:
            return self._config_cache[guild_id]

        from sqlalchemy import select

        async with session_scope() as session:
            result = await session.execute(
                select(AutoModConfig).where(AutoModConfig.guild_id == guild_id)
            )
            configs = result.scalars().all()

            parsed = {}
            for config in configs:
                parsed[config.rule_type] = {
                    "enabled": config.enabled,
                    "threshold": config.threshold,
                    "action": config.action,
                    "duration": config.duration,
                    "ignored_roles": json.loads(config.ignored_roles),
                    "ignored_channels": json.loads(config.ignored_channels),
                    "window_seconds": 10,  # spam detection window
                }

            self._config_cache[guild_id] = parsed
            return parsed
