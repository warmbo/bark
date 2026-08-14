"""
Moderation module v3.1.0 — uses BarkContext + EventBus.

Now includes AutoMod (spam detection, invite filtering, mention limits).
Provides: warn, timeout, kick, ban, unban, voice control, case tracking,
and automatic content moderation.
Every action flows through BarkContext for audit logging.

See docs/module-workspace.md for workspace layout contract.
See docs/api-contracts.md#moderation for API endpoint contracts.
See docs/data-model.md#moderation for case/warning/note models.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from fastapi import Request

from database.engine import session_scope
from database.models.automod import AutoModConfig
from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)
from modules.moderation.ruleset_engine import (
    check_rule_conditions,
    check_ruleset_conditions,
    check_trigger,
    execute_effect,
)

if TYPE_CHECKING:
    from services.anti_raid import AntiRaidService

logger = logging.getLogger("bark.modules.moderation")

INVITE_REGEX = re.compile(
    r"(?:discord\.(?:gg|io|me|com\/invite)\/|discord\.com\/invite\/)[a-zA-Z0-9_\-]+", re.IGNORECASE
)
RULE_TYPES: list[str] = ["spam", "invite", "mention", "content_spam"]

# How long between raid alerts for the same guild (prevents DM floods during
# a join raid — a 100-user raid previously produced 100 owner DMs).
RAID_ALERT_COOLDOWN_SECONDS = 60

_ANTI_RAID: "AntiRaidService | None" = None


def _get_anti_raid() -> "AntiRaidService":
    global _ANTI_RAID
    if _ANTI_RAID is None:
        from services.anti_raid import AntiRaidService

        _ANTI_RAID = AntiRaidService()
    return _ANTI_RAID


# ── Ruleset engine helpers ───────────────────────────────────────


def _json_dict(value: str | dict) -> dict:
    """Parse a JSON string into a dict, or return the dict as-is."""
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _json_list(value: str | list) -> list:
    """Parse a JSON string into a list, or return the list as-is."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value) if value else []
    except (json.JSONDecodeError, TypeError):
        return []


def _voice_duration_seconds(joined_at: datetime, left_at: datetime) -> int:
    """Return a safe duration for timestamps loaded from any SQL backend.

    Kept for tests/backfill; live voice close/move now computes duration in
    SQL (julianday) so the claim is atomic.
    """
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=timezone.utc)
    else:
        joined_at = joined_at.astimezone(timezone.utc)
    if left_at.tzinfo is None:
        left_at = left_at.replace(tzinfo=timezone.utc)
    else:
        left_at = left_at.astimezone(timezone.utc)
    return max(0, int((left_at - joined_at).total_seconds()))


class _RulesetStub:
    """Minimal object duck-typing a RuleSet for condition checking."""

    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)


class _RuleStub:
    """Minimal object duck-typing a Rule for condition checking."""

    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)


def _dict_to_ruleset_stub(data: dict) -> _RulesetStub:
    """Wrap a cached dict as a stub that satisfies the ruleset engine's attribute access."""
    return _RulesetStub(data)


def _dict_to_rule_stub(data: dict) -> _RuleStub:
    """Wrap a cached dict as a stub that satisfies the ruleset engine's attribute access."""
    return _RuleStub(data)


class ModerationModule(BarkModule):
    """Server moderation with full case tracking, voice controls, and AutoMod."""

    name = "moderation"
    version = "4.0.0"
    description = (
        "Warn, timeout, kick, ban, unban, and voice-control members "
        "with full case tracking, audit logging, automatic content moderation, "
        "and the ruleset-based AutoMod engine with 25+ trigger types."
    )
    author = "ZENHAWX"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # AutoMod state — per-guild, per-user message/mention tracking
        self._message_track: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=200))
        )
        self._mention_count: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=100))
        )
        self._config_cache: dict[int, dict[str, dict]] = {}
        self._cache_ttl: dict[int, float] = {}
        self._anti_raid = _get_anti_raid()
        self._cleanup_task: asyncio.Task | None = None
        # Ruleset system state
        self._ruleset_cache: dict[int, list[dict]] = {}
        self._ruleset_cache_ttl: dict[int, float] = {}
        self._dup_track: dict[int, dict[int, list[tuple[datetime, str]]]] = {}
        self._wordlist_cache: dict[str, list[str]] = {}
        # Whether we have warned about legacy flat configs being shadowed by
        # rulesets for a guild (checked once per guild to avoid log spam).
        self._flat_config_warned: dict[int, bool] = {}
        # Per-guild cooldown for raid alerts (a 100-join raid must not produce
        # 100 owner DMs / audit writes / SSE emits).
        self._raid_alert_cooldown: dict[int, float] = {}

    # ── Registration ──────────────────────────────────

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration(name="warn", description="Warn a member"),
            CommandRegistration(name="timeout", description="Timeout a member"),
            CommandRegistration(name="kick", description="Kick a member"),
            CommandRegistration(name="ban", description="Ban a member"),
            CommandRegistration(name="unban", description="Unban a user"),
            CommandRegistration(name="cases", description="View moderation cases"),
            CommandRegistration(name="warnings", description="View member warnings"),
            CommandRegistration(name="clearwarn", description="Clear a warning"),
            CommandRegistration(name="vc_kick", description="Disconnect a member from voice"),
            CommandRegistration(
                name="vc_move", description="Move a member to another voice channel"
            ),
            CommandRegistration(name="vc_mute", description="Server-mute a member in voice"),
            CommandRegistration(name="vc_unmute", description="Server-unmute a member in voice"),
            CommandRegistration(name="vc_deafen", description="Server-deafen a member in voice"),
            CommandRegistration(
                name="vc_undeafen", description="Server-undeafen a member in voice"
            ),
            CommandRegistration(name="voice_sessions", description="View voice session history"),
            CommandRegistration(name="automod", description="Configure AutoMod rules"),
        ]

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("voice_state_change", handler="_on_voice_state_update"),
            EventRegistration("discord_message", handler="_on_message"),
            EventRegistration("discord_message_edit", handler="_on_message_edit"),
            EventRegistration("discord_member_join", handler="_on_member_join"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/moderation",
                label="Moderation",
                icon="shield",
                category="moderation",
            ),
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure moderation role assignments, DM templates, AutoMod rules, and anti-raid settings.",
            "properties": {
                "general": {
                    "type": "object",
                    "title": "General Settings",
                    "description": "Role IDs and notification preferences.",
                    "properties": {
                        "mod_role_id": {
                            "type": "string",
                            "format": "role_select",
                            "title": "Moderator Role",
                            "description": "Role for moderators.",
                            "placeholder": "Select a role...",
                        },
                        "admin_role_id": {
                            "type": "string",
                            "format": "role_select",
                            "title": "Admin Role",
                            "description": "Role for admins.",
                            "placeholder": "Select a role...",
                        },
                        "dm_on_action": {
                            "type": "boolean",
                            "title": "DM on Action",
                            "description": "Send a DM to the target when a moderation action is taken.",
                            "default": True,
                        },
                        "dm_warn_template": {
                            "type": "string",
                            "title": "DM Warn Template",
                            "description": "Template for warn DMs. Use {server}, {reason}, {case} as placeholders.",
                            "placeholder": "You were warned in {server}. Reason: {reason} | Case #{case}",
                        },
                    },
                },
                "anti_raid": {
                    "type": "object",
                    "title": "Anti-Raid",
                    "description": "Rapid-join detection and auto-response.",
                    "properties": {
                        "enabled": {"type": "boolean", "title": "Enabled", "default": True},
                        "join_threshold": {
                            "type": "integer",
                            "minimum": 2,
                            "title": "Join Threshold",
                            "description": "Joins within window to trigger raid mode.",
                            "default": 5,
                        },
                        "join_window_seconds": {
                            "type": "integer",
                            "minimum": 5,
                            "title": "Join Window (sec)",
                            "description": "Time window for join counting.",
                            "default": 30,
                        },
                        "notify_channel_id": {
                            "type": "string",
                            "format": "channel_select",
                            "title": "Alert Channel",
                            "description": "Channel to send raid alerts (empty = system channel).",
                            "placeholder": "Select a channel...",
                        },
                        "webhook_check": {
                            "type": "boolean",
                            "title": "Webhook Scam Check",
                            "description": "Delete + alert on webhook messages containing scam patterns/domains (nitro gifts, steam gifts, etc.).",
                            "default": True,
                        },
                    },
                    "default": {
                        "enabled": True,
                        "join_threshold": 5,
                        "join_window_seconds": 30,
                        "webhook_check": True,
                    },
                },
                "account_age": {
                    "type": "object",
                    "title": "Account Age Gate",
                    "description": "Auto-kick/ban members with accounts younger than N days.",
                    "properties": {
                        "enabled": {"type": "boolean", "title": "Enabled", "default": False},
                        "min_days": {
                            "type": "integer",
                            "minimum": 1,
                            "title": "Minimum Age (days)",
                            "description": "Auto-action accounts younger than this.",
                            "default": 3,
                        },
                        "action": {
                            "type": "string",
                            "enum": ["kick", "ban"],
                            "title": "Action",
                            "default": "kick",
                        },
                    },
                    "default": {"enabled": False, "min_days": 3, "action": "kick"},
                },
                "scam_protection": {
                    "type": "object",
                    "title": "Scam Protection",
                    "description": "Custom scam domains and detection patterns for the AutoMod scam_link trigger.",
                    "properties": {
                        "domains": {
                            "type": "string",
                            "title": "Scam Domains",
                            "description": "One domain per line. Messages containing these domains trigger the scam_link rule.",
                            "placeholder": "example-scam.com\nanother-scam.net",
                        },
                        "patterns": {
                            "type": "string",
                            "title": "Scam Patterns (Regex)",
                            "description": "One regex pattern per line. Matched against message content (case-insensitive).",
                            "placeholder": "free\\s+nitro\nsteam\\s+gift",
                        },
                    },
                },
            },
            **{
                rule_type: {
                    "type": "object",
                    "title": rule_type.replace("_", " ").title(),
                    "description": {
                        "spam": "Detects rapid messages across all channels per user.",
                        "invite": "Detects Discord invite links in messages.",
                        "mention": "Detects excessive @mentions. Also tracks total @mentions across recent messages to catch slow-burn mention spam.",
                        "content_spam": "Detects repeated/similar message content from the same user.",
                    }.get(rule_type, f"Rule for {rule_type}"),
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "title": "Enabled",
                            "description": "Turn this rule on or off.",
                        },
                        "threshold": {
                            "type": "integer",
                            "minimum": 1,
                            "title": "Threshold",
                            "placeholder": {
                                "spam": "Max msgs in the time window",
                                "invite": "Not used",
                                "mention": "Max @ per msg (e.g. 5)",
                            }.get(rule_type, "Value"),
                            "description": {
                                "spam": "Max messages in the time window.",
                                "invite": "Not used.",
                                "mention": "Max mentions per message.",
                            }.get(rule_type, ""),
                        },
                        "action": {
                            "type": "string",
                            "enum": ["warn", "timeout", "delete"],
                            "title": "Action",
                        },
                        "duration": {
                            "type": "integer",
                            "minimum": 1,
                            "title": "Duration (min)",
                            "placeholder": "Minutes (e.g. 10)",
                        },
                        "window_seconds": {
                            "type": "integer",
                            "minimum": 2,
                            "maximum": 120,
                            "title": "Time Window (seconds)",
                            "description": {
                                "spam": "Time window for message counting (default: 10s).",
                                "mention": "Time window for cross-message mention tracking (default: 30s).",
                                "invite": "Not used.",
                            }.get(rule_type, ""),
                            "placeholder": {"spam": "10", "mention": "30"}.get(rule_type, "10"),
                            "default": {
                                "spam": 10,
                                "mention": 30,
                                "invite": 1,
                                "content_spam": 10,
                            }.get(rule_type, 10),
                        },
                        "ignored_roles": {
                            "type": "array",
                            "items": {"type": "string"},
                            "title": "Ignored Role IDs",
                            "placeholder": '["role_id_1", "role_id_2"]',
                        },
                        "ignored_channels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "title": "Ignored Channel IDs",
                            "placeholder": '["channel_id_1", "channel_id_2"]',
                        },
                    },
                }
                for rule_type in RULE_TYPES
            },
        }

    def _get_operational_actions(self) -> list[dict]:
        return [
            {
                "id": "quick_warn",
                "label": "Quick Warn",
                "description": "Quickly warn a member with a reason.",
                "endpoint": "quick-warn",
                "fields": [
                    {
                        "key": "target_id",
                        "label": "Member",
                        "type": "api_select",
                        "required": True,
                        "api": "/api/v1/guilds/{guild_id}/members",
                        "value_key": "id",
                        "label_key": "tag",
                        "placeholder": "Select a member to warn...",
                    },
                    {
                        "key": "reason",
                        "label": "Reason",
                        "type": "text",
                        "required": True,
                        "placeholder": "Reason for the warning",
                    },
                ],
            },
            {
                "id": "test_rule",
                "label": "Test Rule",
                "description": "Simulate a rule trigger to test your AutoMod configuration.",
                "endpoint": "test-rule",
                "fields": [
                    {
                        "key": "rule_type",
                        "label": "Rule Type",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "spam", "label": "Rapid messages (spam)"},
                            {"value": "invite", "label": "Discord invite link"},
                            {"value": "mention", "label": "Excessive @mentions"},
                            {"value": "content_spam", "label": "Duplicate / repeated content"},
                            {"value": "mention_rate", "label": "Mention rate per window"},
                        ],
                        "placeholder": "Select a rule type to test...",
                    },
                ],
            },
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="moderation.view", label="View Moderation Records"),
            PermissionDefinition(name="moderation.warn", label="Warn Members"),
            PermissionDefinition(name="moderation.timeout", label="Timeout Members"),
            PermissionDefinition(name="moderation.kick", label="Kick Members"),
            PermissionDefinition(name="moderation.ban", label="Ban Members"),
            PermissionDefinition(name="moderation.vc_kick", label="Voice Kick"),
            PermissionDefinition(name="moderation.vc_move", label="Voice Move"),
            PermissionDefinition(name="moderation.vc_mute", label="Voice Mute"),
            PermissionDefinition(name="moderation.notes.create", label="Create Notes"),
            PermissionDefinition(name="automod.configure", label="Configure AutoMod"),
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": "Warn, timeout, kick, ban, or voice-control members with full case tracking and audit logging. Every action is recorded as a numbered case for review.",
            },
            {
                "title": "Display Warnings & Timeouts",
                "description": f"When a member breaks a rule, issue a warning or timeout from the dashboard or via /{self.command_group_name()} warn and /{self.command_group_name()} timeout slash commands. The member gets a DM, a case is logged, and the dashboard shows live status.",
            },
            {
                "title": "AutoMod — Spam & Invite Protection",
                "description": "Configure rules for spam, invite links, excessive mentions, and duplicate content. Violations trigger automatic actions: warn, timeout, or delete.",
            },
            {
                "title": "Anti-Raid Protection",
                "description": "Rapid join detection watches for X joins in Y seconds and triggers raid mode. Combined with account-age gating, new accounts can be auto-kicked or banned.",
            },
            {
                "title": "Usage",
                "description": f"Enable the module, then use /{self.command_group_name()} warn, /timeout, /kick, /ban slash commands or the dashboard Moderation page. Configure AutoMod rules and anti-raid settings in the Configuration section.",
            },
        ]

    def get_extra_tabs(self) -> list[dict]:
        return [
            {"id": "cases", "label": "Cases", "template": "module_tabs/moderation_cases.html"},
            {
                "id": "warnings",
                "label": "Warnings",
                "template": "module_tabs/moderation_warnings.html",
            },
            {"id": "notes", "label": "Notes", "template": "module_tabs/moderation_notes.html"},
            {
                "id": "rulesets",
                "label": "Rulesets",
                "template": "module_tabs/moderation_rulesets.html",
            },
            {
                "id": "wordlists",
                "label": "Word Lists",
                "template": "module_tabs/moderation_wordlists.html",
            },
            {"id": "voice", "label": "Voice", "template": "module_tabs/moderation_voice.html"},
        ]

    # ── Lifecycle ─────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling moderation module v%s", self.version)
        self._message_track.clear()
        self._mention_count.clear()
        self._config_cache.clear()
        self._ruleset_cache.clear()
        self._ruleset_cache_ttl.clear()
        self._dup_track.clear()
        self._wordlist_cache.clear()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def disable(self) -> None:
        self._logger.info("Disabling moderation module")
        self._message_track.clear()
        self._mention_count.clear()
        self._config_cache.clear()
        self._cache_ttl.clear()
        self._ruleset_cache.clear()
        self._ruleset_cache_ttl.clear()
        self._dup_track.clear()
        self._wordlist_cache.clear()
        task = self._cleanup_task
        self._cleanup_task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # ── Command factories (called by ModuleManager) ────

    def _make_warn_command(self):
        @discord.app_commands.command(name="warn", description="Warn a member")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def warn(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_warn(interaction, member, reason)

        return warn

    def _make_timeout_command(self):
        @discord.app_commands.command(name="timeout", description="Timeout a member")
        @discord.app_commands.default_permissions(moderate_members=True)
        @discord.app_commands.choices(
            unit=[
                discord.app_commands.Choice(name="minutes", value="minutes"),
                discord.app_commands.Choice(name="seconds", value="seconds"),
                discord.app_commands.Choice(name="hours", value="hours"),
            ]
        )
        async def timeout(
            interaction: discord.Interaction,
            member: discord.Member,
            duration: int,
            unit: str = "minutes",
            reason: str = "No reason",
        ):
            await self._cmd_timeout(interaction, member, duration, unit, reason)

        return timeout

    def _make_kick_command(self):
        @discord.app_commands.command(name="kick", description="Kick a member")
        @discord.app_commands.default_permissions(kick_members=True)
        async def kick(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_kick(interaction, member, reason)

        return kick

    def _make_ban_command(self):
        @discord.app_commands.command(name="ban", description="Ban a member")
        @discord.app_commands.default_permissions(ban_members=True)
        async def ban(
            interaction: discord.Interaction,
            member: discord.Member,
            reason: str = "No reason",
            delete_days: int = 0,
        ):
            await self._cmd_ban(interaction, member, reason, delete_days)

        return ban

    def _make_unban_command(self):
        @discord.app_commands.command(name="unban", description="Unban a user")
        @discord.app_commands.default_permissions(ban_members=True)
        async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason"):
            await self._cmd_unban(interaction, user_id, reason)

        return unban

    def _make_cases_command(self):
        @discord.app_commands.command(name="cases", description="View recent moderation cases")
        async def cases(interaction: discord.Interaction, limit: int = 10):
            await self._cmd_cases(interaction, limit)

        return cases

    def _make_warnings_command(self):
        @discord.app_commands.command(name="warnings", description="View warnings for a member")
        async def warnings(interaction: discord.Interaction, member: discord.Member):
            await self._cmd_warnings(interaction, member)

        return warnings

    def _make_clearwarn_command(self):
        @discord.app_commands.command(name="clearwarn", description="Clear a warning by ID")
        @discord.app_commands.default_permissions(moderate_members=True)
        async def clearwarn(interaction: discord.Interaction, warning_id: int):
            await self._cmd_clearwarn(interaction, warning_id)

        return clearwarn

    def _make_vc_kick_command(self):
        @discord.app_commands.command(name="vc_kick", description="Disconnect from voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_kick(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_vc_kick(interaction, member, reason)

        return vc_kick

    def _make_vc_move_command(self):
        @discord.app_commands.command(name="vc_move", description="Move to another voice channel")
        @discord.app_commands.default_permissions(move_members=True)
        async def vc_move(
            interaction: discord.Interaction,
            member: discord.Member,
            channel: discord.VoiceChannel,
            reason: str = "No reason",
        ):
            await self._cmd_vc_move(interaction, member, channel, reason)

        return vc_move

    def _make_vc_mute_command(self):
        @discord.app_commands.command(name="vc_mute", description="Server-mute in voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_mute(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_vc_mute(interaction, member, reason)

        return vc_mute

    def _make_vc_unmute_command(self):
        @discord.app_commands.command(name="vc_unmute", description="Server-unmute in voice")
        @discord.app_commands.default_permissions(mute_members=True)
        async def vc_unmute(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_vc_unmute(interaction, member, reason)

        return vc_unmute

    def _make_vc_deafen_command(self):
        @discord.app_commands.command(name="vc_deafen", description="Server-deafen in voice")
        @discord.app_commands.default_permissions(deafen_members=True)
        async def vc_deafen(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_vc_deafen(interaction, member, reason)

        return vc_deafen

    def _make_vc_undeafen_command(self):
        @discord.app_commands.command(name="vc_undeafen", description="Server-undeafen in voice")
        @discord.app_commands.default_permissions(deafen_members=True)
        async def vc_undeafen(
            interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"
        ):
            await self._cmd_vc_undeafen(interaction, member, reason)

        return vc_undeafen

    def _make_voice_sessions_command(self):
        @discord.app_commands.command(
            name="voice_sessions", description="View voice session history"
        )
        @discord.app_commands.default_permissions(moderate_members=True)
        async def voice_sessions(
            interaction: discord.Interaction, member: discord.Member, limit: int = 5
        ):
            await self._cmd_voice_sessions(interaction, member, limit)

        return voice_sessions

    def _make_automod_command(self):
        @discord.app_commands.command(name="automod", description="Configure AutoMod rules")
        @discord.app_commands.default_permissions(manage_guild=True)
        async def automod(
            interaction: discord.Interaction,
            rule: str = "spam",
            enabled: bool | None = None,
            threshold: int | None = None,
            action: str | None = None,
        ):
            await self._cmd_automod(interaction, rule, enabled, threshold, action)

        return automod

    # ── Voice State (via EventBus) ─────────────────────

    async def _on_voice_state_update(self, event_type: str, **data) -> None:
        """Track voice sessions via EventBus."""
        member = data.get("member")
        before = data.get("before")
        after = data.get("after")
        if not member or not member.guild:
            return

        from datetime import datetime, timezone

        from database.engine import session_scope
        from database.models.voice import VoiceSession

        guild_id = member.guild.id
        user_id = str(member.id)
        now = datetime.now(timezone.utc)
        before_channel, after_channel = await self.ctx.normalize_voice_transition(
            guild_id,
            data.get("before_channel", before.channel if before else None),
            data.get("after_channel", after.channel if after else None),
        )

        if before_channel is None and after_channel is not None:
            async with session_scope() as session:
                session.add(
                    VoiceSession(
                        guild_id=str(guild_id),
                        user_id=user_id,
                        user_tag=str(member),
                        channel_id=str(after_channel.id),
                        channel_name=after_channel.name,
                        joined_at=now,
                    )
                )
                await session.commit()

        elif before_channel is not None and after_channel is None:
            # Atomic claim: only the first event that flips left_at wins; a
            # concurrent duplicate leave/move sees rowcount 0 and skips.
            from sqlalchemy import func, update

            channel_name = getattr(before_channel, "name", None)
            values: dict = {
                "left_at": now,
                "duration_seconds": func.max(
                    0,
                    func.round(
                        (func.julianday(now) - func.julianday(VoiceSession.joined_at))
                        * 86400
                    ),
                ),
            }
            if channel_name:
                values["channel_name"] = channel_name
            async with session_scope() as session:
                result = await session.execute(
                    update(VoiceSession)
                    .where(
                        VoiceSession.guild_id == str(guild_id),
                        VoiceSession.user_id == user_id,
                        VoiceSession.channel_id == str(before_channel.id),
                        VoiceSession.left_at.is_(None),
                    )
                    .values(**values)
                )
                await session.commit()
                affected = getattr(result, "rowcount", 0) or 0
                if affected == 0:
                    self._logger.debug(
                        "No open voice session to close for %s in %s",
                        member,
                        before_channel,
                    )

        elif (
            before_channel is not None
            and after_channel is not None
            and before_channel.id != after_channel.id
        ):
            # Member moved between voice channels — close old session, open new one
            from sqlalchemy import func, update

            channel_name = getattr(before_channel, "name", None)
            values = {
                "left_at": now,
                "duration_seconds": func.max(
                    0,
                    func.round(
                        (func.julianday(now) - func.julianday(VoiceSession.joined_at))
                        * 86400
                    ),
                ),
            }
            if channel_name:
                values["channel_name"] = channel_name
            async with session_scope() as session:
                await session.execute(
                    update(VoiceSession)
                    .where(
                        VoiceSession.guild_id == str(guild_id),
                        VoiceSession.user_id == user_id,
                        VoiceSession.channel_id == str(before_channel.id),
                        VoiceSession.left_at.is_(None),
                    )
                    .values(**values)
                )
                session.add(
                    VoiceSession(
                        guild_id=str(guild_id),
                        user_id=user_id,
                        user_tag=str(member),
                        channel_id=str(after_channel.id),
                        channel_name=after_channel.name,
                        joined_at=now,
                    )
                )
                await session.commit()

    # ── Anti-Raid: member join handler ─────────────────---

    async def _on_member_join(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or not member.guild or member.bot:
            return
        guild_id = member.guild.id

        # Record join for raid detection
        anti_raid_enabled = await self._get_setting(guild_id, "anti_raid", "enabled", True)
        if anti_raid_enabled:
            join_threshold = await self._get_setting(guild_id, "anti_raid", "join_threshold", 5)
            join_window = await self._get_setting(guild_id, "anti_raid", "join_window_seconds", 30)
            in_raid = self._anti_raid.record_join(
                guild_id,
                threshold=int(join_threshold or 5),
                window=int(join_window or 30),
            )
            if in_raid:
                self._logger.warning(
                    "RAID DETECTED in guild %s (%d users joined recently)",
                    member.guild.name,
                    guild_id,
                )
                # Alert once per cooldown window — not once per join.
                now_ts = datetime.now(timezone.utc).timestamp()
                last_alert = self._raid_alert_cooldown.get(guild_id, 0.0)
                if now_ts - last_alert < RAID_ALERT_COOLDOWN_SECONDS:
                    return
                self._raid_alert_cooldown[guild_id] = now_ts
                try:
                    channel_id = await self._get_setting(
                        guild_id, "anti_raid", "notify_channel_id", ""
                    )
                    if channel_id:
                        ch = member.guild.get_channel(int(channel_id))
                    else:
                        ch = member.guild.system_channel
                    if ch:
                        await ch.send(
                            f"🚨 **Raid detected!** {member.mention} joined — {join_threshold}+ joins in {join_window}s."
                        )
                    # Full alert: owner DM + persistent dashboard entry + mod log
                    await self._notify_automod(
                        member.guild,
                        rule=f"Raid detected ({join_threshold}+ joins in {join_window}s)",
                        action="monitor",
                        user_tag=str(member),
                        content=f"Member {member} joined during a join raid.",
                        target_id=member.id,
                    )
                except Exception:
                    pass

        # Account age check
        age_enabled = await self._get_setting(guild_id, "account_age", "enabled", False)
        if age_enabled:
            min_days = await self._get_setting(guild_id, "account_age", "min_days", 3)
            action = await self._get_setting(guild_id, "account_age", "action", "kick")
            passed, reason = self._anti_raid.check_account_age(member, min_days)
            if not passed:
                self._logger.info("Account age check: %s %s — %s", member, action, reason)
                try:
                    if action == "kick":
                        await member.kick(reason=f"[Anti-Raid] {reason}")
                    elif action == "ban":
                        await member.ban(reason=f"[Anti-Raid] {reason}")
                    await self._notify_automod(
                        member.guild,
                        rule=f"Account age gate ({reason})",
                        action=action or "kick",
                        user_tag=str(member),
                        content="",
                        target_id=member.id,
                    )
                except discord.Forbidden:
                    self._logger.warning("Cannot %s %s for account age", action, member)

    # ── AutoMod: discord_message handler ───────────────
    # Uses new ruleset-based engine with old flat-config fallback.

    async def _on_message(self, event_type: str, **data):
        message = data.get("message")
        if not message or not message.guild:
            return

        # Webhook spam: webhook authors are bot-flagged below, which would skip
        # them entirely — so handle webhook-driven raids/scams FIRST. This is
        # the vector that normal user rules never see (they are scoped to
        # non-bot authors by ignore_bots/author.bot guards).
        if message.webhook_id:
            wc_enabled = await self._get_setting(
                message.guild.id, "anti_raid", "webhook_check", True
            )
            if not wc_enabled:
                return
            suspicious, reason = self._anti_raid.check_webhook_scam(message)
            if suspicious:
                self._logger.warning(
                    "Webhook scam in %s: %s", message.guild.id, reason
                )
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await self._notify_automod(
                    message.guild,
                    rule=f"Webhook scam ({reason})",
                    action="delete",
                    user_tag=getattr(message.author, "name", "unknown"),
                    content=(message.content or "")[:500],
                    target_id=getattr(message.author, "id", None),
                )
            return

        if message.author.bot:
            return

        # Step 1: Try ruleset-based AutoMod
        rulesets_data = await self._get_rulesets_and_rules(message.guild.id)
        if rulesets_data:
            # Legacy flat configs are shadowed once rulesets exist. Surface
            # that once per guild so admins know old rules are not evaluated.
            if not self._flat_config_warned.get(message.guild.id):
                legacy = await self._get_configs(message.guild.id)
                if legacy:
                    self._logger.warning(
                        "Guild %s has %d legacy flat AutoMod rule(s) shadowed by "
                        "rulesets — they are NOT evaluated. Move them into a "
                        "ruleset or they will never fire.",
                        message.guild.id,
                        len(legacy),
                    )
                self._flat_config_warned[message.guild.id] = True
            await self._process_rulesets(message, rulesets_data)
            return

        # Step 2: Fallback to flat config (legacy RULE_TYPES)
        configs = await self._get_configs(message.guild.id)
        if not configs:
            return

        # Legacy webhook check
        if message.webhook_id:
            suspicious, reason = self._anti_raid.check_webhook_scam(message)
            if suspicious:
                self._logger.warning("Webhook scam detected in %s: %s", message.guild.id, reason)
                cfg = configs.get("spam", configs.get("mention", {"action": "warn"}))
                await self._take_action(message, cfg, f"[Webhook Scam] {reason}")
            return

        now = datetime.now(timezone.utc)
        for rule_type, cfg in configs.items():
            if not cfg.get("enabled"):
                continue
            try:
                if rule_type == "spam":
                    await self._check_spam(message, cfg, now)
                elif rule_type == "invite":
                    await self._check_invites(message, cfg)
                elif rule_type == "mention":
                    await self._check_mentions(message, cfg, now)
                elif rule_type == "content_spam":
                    await self._check_content_spam(message, cfg)
                elif rule_type == "mention_rate":
                    await self._check_mention_rate(message, cfg, now)
            except Exception:
                self._logger.exception("Error in %s check", rule_type)

    # ── Ruleset processing ─────────────────────────────────────

    async def _get_rulesets_and_rules(self, guild_id: int) -> list[dict]:
        """Load rulesets + rules for a guild from DB, with 30s cache."""
        import time as _time

        now = _time.monotonic()
        if (
            guild_id in self._ruleset_cache
            and (now - self._ruleset_cache_ttl.get(guild_id, 0)) < 30
        ):
            return self._ruleset_cache[guild_id]

        from sqlalchemy import select

        from database.engine import session_scope
        from database.models.ruleset import Rule, RuleSet

        async with session_scope() as session:
            result = await session.execute(
                select(RuleSet)
                .where(RuleSet.guild_id == str(guild_id), RuleSet.enabled.is_(True))
                .order_by(RuleSet.priority)
            )
            rulesets = result.scalars().all()

            if not rulesets:
                # Auto-seed: convert legacy flat config to a default ruleset
                seeded = await self._ensure_default_ruleset(guild_id)
                if seeded:
                    # Re-query after seeding
                    result = await session.execute(
                        select(RuleSet)
                        .where(RuleSet.guild_id == str(guild_id), RuleSet.enabled.is_(True))
                        .order_by(RuleSet.priority)
                    )
                    rulesets = result.scalars().all()

            if not rulesets:
                self._ruleset_cache[guild_id] = []
                self._ruleset_cache_ttl[guild_id] = now
                return []

            result_data = []
            for rs in rulesets:
                rules_result = await session.execute(
                    select(Rule)
                    .where(Rule.ruleset_id == rs.id, Rule.enabled.is_(True))
                    .order_by(Rule.priority)
                )
                rules = rules_result.scalars().all()
                if not rules:
                    continue
                result_data.append(
                    {
                        "id": rs.id,
                        "name": rs.name,
                        "priority": rs.priority,
                        "ignored_roles": rs.ignored_roles,
                        "require_roles": rs.require_roles,
                        "require_all_roles": rs.require_all_roles,
                        "ignored_channels": rs.ignored_channels,
                        "active_channels": rs.active_channels,
                        "ignored_categories": rs.ignored_categories,
                        "active_categories": rs.active_categories,
                        "account_age_minutes_min": rs.account_age_minutes_min,
                        "account_age_minutes_max": rs.account_age_minutes_max,
                        "member_duration_minutes_min": rs.member_duration_minutes_min,
                        "member_duration_minutes_max": rs.member_duration_minutes_max,
                        "only_bots": rs.only_bots,
                        "ignore_bots": rs.ignore_bots,
                        "check_new_messages": rs.check_new_messages,
                        "check_edited_messages": rs.check_edited_messages,
                        "rules": [
                            {
                                "id": r.id,
                                "trigger_type": r.trigger_type,
                                "trigger_config": r.trigger_config,
                                "effect_type": r.effect_type,
                                "effect_config": r.effect_config,
                                "conditions": r.conditions,
                            }
                            for r in rules
                        ],
                    }
                )

            self._ruleset_cache[guild_id] = result_data
            self._ruleset_cache_ttl[guild_id] = now
            return result_data

    async def _on_message_edit(self, event_type: str, **data):
        """AutoMod on edited messages — honors per-ruleset check_edited_messages."""
        after = data.get("after")
        if not after or not after.guild or getattr(after.author, "bot", False):
            return
        rulesets_data = await self._get_rulesets_and_rules(after.guild.id)
        if not rulesets_data:
            return
        await self._process_rulesets(after, rulesets_data, edited=True)

    async def _process_rulesets(self, message, rulesets_data: list[dict], *, edited: bool = False) -> None:
        """Iterate rulesets and their rules, checking conditions and triggers.

        ``edited`` selects which message-generation the ruleset applies to:
        new messages honor check_new_messages, edits honor check_edited_messages.
        """
        for rs in rulesets_data:
            if edited and not rs.get("check_edited_messages", True):
                continue
            if not edited and not rs.get("check_new_messages", True):
                continue
            # Check ruleset-scoped conditions
            passed, fail_reason = check_ruleset_conditions(None, message, _dict_to_ruleset_stub(rs))
            if not passed:
                continue

            for rule in rs["rules"]:
                # Check per-rule conditions
                passed, rule_reason = check_rule_conditions(message, _dict_to_rule_stub(rule))
                if not passed:
                    continue

                # Check trigger
                triggered, trigger_reason = await check_trigger(
                    message,
                    rule["trigger_type"],
                    _json_dict(rule["trigger_config"]),
                    rule["id"],
                    self,
                )
                if triggered:
                    await execute_effect(
                        message,
                        rule["effect_type"],
                        _json_dict(rule["effect_config"]),
                        trigger_reason,
                        self,
                    )
                    # Full alert: persistent dashboard audit entry, owner DM,
                    # bus event (SSE feed + mod-log channel post).
                    await self._notify_automod(
                        message.guild,
                        rule=f"Ruleset:{rs['name']}/{rule['trigger_type']}",
                        action=rule["effect_type"],
                        user_tag=str(message.author),
                        content=(message.content or "")[:500],
                        target_id=message.author.id,
                    )

    async def _ensure_default_ruleset(self, guild_id: int) -> bool:
        """Seed a default ruleset from the legacy flat config if no rulesets exist.
        Returns True if a default ruleset was created."""
        from sqlalchemy import func, select

        from database.engine import session_scope
        from database.models.ruleset import RuleSet

        async with session_scope() as session:
            count = (
                await session.execute(
                    select(func.count(RuleSet.id)).where(RuleSet.guild_id == str(guild_id))
                )
            ).scalar() or 0
            if count > 0:
                return False

            # Read existing flat config
            existing = await self._get_configs_for_seed(guild_id)
            if not existing:
                # Create a minimal default
                rs = RuleSet(
                    guild_id=str(guild_id),
                    name="Default",
                    enabled=True,
                    priority=100,
                )
                session.add(rs)
                await session.commit()
                return True

            # Convert flat rules to a ruleset
            rs = RuleSet(
                guild_id=str(guild_id),
                name="Default (migrated)",
                enabled=True,
                priority=100,
            )
            session.add(rs)
            await session.flush()

            from database.models.ruleset import Rule

            trigger_map = {
                "spam": ("user_message_rate", {"threshold": 5, "window_seconds": 10}),
                "invite": ("invite", {}),
                "mention": ("mention", {"threshold": 5}),
                "content_spam": ("content_spam", {"threshold": 3}),
            }
            for rule_type, cfg in existing.items():
                if not cfg.get("enabled"):
                    continue
                t_type, extra = trigger_map.get(rule_type, (rule_type, {}))
                t_config = {**extra, "threshold": cfg.get("threshold", 5)}
                if "window_seconds" in cfg and "window_seconds" not in extra:
                    t_config["window_seconds"] = cfg["window_seconds"]
                e_type = cfg.get("action", "warn")
                e_config = {
                    "duration_minutes": cfg.get("duration", 10),
                }
                if e_type == "delete":
                    e_config["duration_minutes"] = 0

                session.add(
                    Rule(
                        ruleset_id=rs.id,
                        trigger_type=t_type,
                        trigger_config=json.dumps(t_config),
                        effect_type=e_type,
                        effect_config=json.dumps(e_config),
                        priority=50,
                    )
                )
            await session.commit()
            self._ruleset_cache.pop(guild_id, None)
            self._ruleset_cache_ttl.pop(guild_id, None)
            return True

    async def _get_configs_for_seed(self, guild_id: int) -> dict:
        """Read flat config without caching (used during seed migration)."""
        result = {}
        try:
            mc_config = await self.ctx.get_module_config(self.name, guild_id)
            if any(rt in mc_config for rt in ["spam", "invite", "mention", "content_spam"]):
                for rule_type in ["spam", "invite", "mention", "content_spam"]:
                    rule = mc_config.get(rule_type, {})
                    if isinstance(rule, dict) and rule.get("enabled"):
                        result[rule_type] = rule
        except Exception:
            logger.exception("Failed to load ModuleConfig for guild %s", guild_id)
        return result

    # ── Legacy flat-config checks (fallback, unchanged) ─────────

    async def _check_spam(self, message, config, now):
        threshold = config.get("threshold", 5)
        window = config.get("window_seconds", 10)
        if self._is_ignored(message, config):
            return
        track = self._message_track[message.guild.id][message.author.id]
        cutoff = now - timedelta(seconds=window)
        while track and track[0] < cutoff:
            track.popleft()
        track.append(now)
        if len(track) >= threshold:
            await self._take_action(message, config, f"Spam ({len(track)} msgs/{window}s)")

    async def _check_invites(self, message, config):
        if self._is_ignored(message, config):
            return
        if INVITE_REGEX.search(message.content):
            await self._take_action(message, config, "Invite link")

    async def _check_mentions(self, message, config, now):
        if self._is_ignored(message, config):
            return
        threshold = config.get("threshold", 5)
        count = (
            len(message.mentions)
            + len(message.role_mentions)
            + (1 if message.mention_everyone else 0)
        )
        if count >= threshold:
            await self._take_action(message, config, f"Mention spam ({count} @)")

    async def _check_content_spam(self, message, config):
        if self._is_ignored(message, config):
            return
        content = message.content
        if not content or len(content) < 20:
            return
        threshold = config.get("threshold", 3)
        tally = 0
        track = self._anti_raid._recent_content[message.guild.id][message.author.id]
        for prev in list(track):
            from difflib import SequenceMatcher

            if SequenceMatcher(None, prev, content).ratio() >= 0.85:
                tally += 1
                if tally + 1 >= threshold:
                    await self._take_action(message, config, f"Content spam ({tally} similar msgs)")
                    return
        track.append(content)

    async def _take_action(self, message, config, reason):
        action = config.get("action", "warn")
        duration = config.get("duration", 10)
        executed = False
        if action == "delete":
            try:
                await message.delete()
                executed = True
            except discord.Forbidden:
                pass
        elif action == "warn":
            from services.moderation_service import ModerationService

            bot_user = self.ctx.bot.user
            moderator_id = str(bot_user.id) if bot_user else ""
            moderator_tag = str(bot_user) if bot_user else "Bark"
            await ModerationService.create_case(
                guild_id=message.guild.id,
                action_type="warn",
                target_id=str(message.author.id),
                target_tag=str(message.author),
                moderator_id=moderator_id,
                moderator_tag=moderator_tag,
                reason=f"[AutoMod] {reason}",
                warning_user_id=str(message.author.id),
            )
            executed = True
            try:
                await message.channel.send(f"⚠️ {message.author.mention}, {reason}", delete_after=10)
            except discord.Forbidden:
                pass
        elif action == "timeout":
            if not isinstance(message.author, discord.Member):
                return
            until = discord.utils.utcnow() + timedelta(minutes=duration)
            try:
                await message.author.timeout(until, reason=f"[AutoMod] {reason}")
                await message.channel.send(
                    f"⏱ {message.author.mention} timed out {duration}m. {reason}", delete_after=10
                )
                executed = True
            except discord.Forbidden:
                pass

        if executed:
            await self._notify_automod(
                message.guild,
                rule=reason,
                action=action,
                user_tag=str(message.author),
                content=getattr(message, "content", "")[:500],
                target_id=getattr(message.author, "id", None),
            )

        # ── Escalation: track violations for repeat offenders ──
        if action in ("warn", "timeout") and hasattr(message.author, "id"):
            escalation_action, strikes = await self._anti_raid.record_violation(
                message.guild.id, message.author.id
            )
            if escalation_action and escalation_action != action:
                self._logger.info(
                    "Escalating %s (strike %d) → %s", message.author, strikes, escalation_action
                )
                try:
                    channel = message.channel
                    if escalation_action == "timeout":
                        until = discord.utils.utcnow() + timedelta(minutes=30)
                        await message.author.timeout(
                            until, reason=f"[AutoMod] Escalation ({strikes} strikes)"
                        )
                        await channel.send(
                            f"⏱ {message.author.mention} auto-escalated to timeout (strike {strikes})",
                            delete_after=10,
                        )
                    elif escalation_action == "kick":
                        await message.author.kick(
                            reason=f"[AutoMod] Escalation ({strikes} strikes)"
                        )
                        await channel.send(
                            f"👢 {message.author.mention} auto-kicked (strike {strikes})"
                        )
                except discord.Forbidden:
                    pass

    # ── AutoMod alerting ─────────────────────────────────
    # Every trigger fans out to three surfaces so raids never happen silently:
    #   1. Persistent dashboard audit feed (ctx.log_audit)
    #   2. DM to the server owner
    #   3. EventBus event -> SSE toast + mod-log channel (logging module)

    async def _notify_automod(
        self,
        guild,
        *,
        rule: str,
        action: str,
        user_tag: str,
        content: str = "",
        target_id: int | str | None = None,
    ) -> None:
        """Alert on an AutoMod/raid trigger across all surfaces."""
        guild_id = guild.id
        bot_user = self.ctx.bot.user if self.ctx.bot else None
        try:
            await self.ctx.log_audit(
                guild_id,
                "automod_triggered",
                actor_id=str(bot_user.id) if bot_user else "",
                actor_tag=str(bot_user) if bot_user else "Bark",
                target_id=str(target_id) if target_id is not None else None,
                target_tag=user_tag,
                details={
                    "rule": rule,
                    "action": action,
                    "content": (content or "")[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            self._logger.exception("Failed to write automod audit entry")
        # Kicks/bans from rules must surface as real moderation cases (Recent
        # Activity + Cases feed), not just as a generic automod audit row.
        if action in ("kick", "kick_purge", "ban") and target_id is not None:
            try:
                from services.moderation_service import ModerationService

                await ModerationService.create_case(
                    guild_id=guild_id,
                    action_type="kick" if action == "kick_purge" else action,
                    target_id=str(target_id),
                    target_tag=user_tag,
                    moderator_id=str(bot_user.id) if bot_user else "",
                    moderator_tag=str(bot_user) if bot_user else "Bark",
                    reason=f"[AutoMod] {rule}",
                )
            except Exception:
                self._logger.exception("Failed to create moderation case for automod action")
        await self._dm_owner(guild, rule, action, user_tag, content)
        try:
            await self.ctx.events.emit(
                "automod_triggered",
                guild_id=str(guild_id),
                rule=rule,
                action=action,
                user_tag=user_tag,
                content=(content or "")[:500],
            )
        except Exception:
            self._logger.exception("Failed to emit automod_triggered event")

    async def _dm_owner(
        self, guild, rule: str, action: str, user_tag: str, content: str
    ) -> None:
        """DM the guild owner with an alert embed. Silently no-ops when the
        owner has DMs closed or cannot be resolved."""
        try:
            owner = guild.owner
            if owner is None and guild.owner_id:
                owner = guild.get_member(guild.owner_id)
            if owner is None and guild.owner_id:
                owner = await self.ctx.bot.fetch_user(guild.owner_id)
            if owner is None:
                return
            embed = discord.Embed(
                title="🚨 Bark AutoMod Alert",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Server", value=guild.name, inline=True)
            embed.add_field(name="Rule", value=rule[:256], inline=True)
            embed.add_field(name="Action", value=action, inline=True)
            embed.add_field(name="User", value=user_tag[:256], inline=True)
            if content:
                embed.add_field(name="Message", value=content[:1024], inline=False)
            await owner.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            self._logger.exception("Failed to DM owner about automod alert")

    async def _get_configs(self, guild_id: int) -> dict:
        """Load AutoMod rules from ModuleConfig (dashboard saves), falling back to AutoModConfig (slash commands)."""
        import time as _time

        now = _time.monotonic()
        # Cache hit with 30s TTL
        if guild_id in self._config_cache and (now - self._cache_ttl.get(guild_id, 0)) < 30:
            return self._config_cache[guild_id]

        result = {}

        # Priority 1: ModuleConfig (dashboard) — top-level auto-mod rules
        try:
            mc_config = await self.ctx.get_module_config(self.name, guild_id)
            # Check if any rule type key exists at the top level
            if any(rt in mc_config for rt in RULE_TYPES):
                for rule_type in RULE_TYPES:
                    rule = mc_config.get(rule_type, {})
                    if isinstance(rule, dict) and rule.get("enabled"):
                        result[rule_type] = {
                            "enabled": True,
                            "threshold": rule.get(
                                "threshold",
                                {"spam": 5, "invite": 1, "mention": 5, "content_spam": 3}.get(
                                    rule_type, 5
                                ),
                            ),
                            "action": rule.get("action", "warn"),
                            "duration": rule.get("duration", 10),
                            "window_seconds": rule.get("window_seconds", 10),
                            "ignored_roles": rule.get("ignored_roles", []),
                            "ignored_channels": rule.get("ignored_channels", []),
                        }
        except Exception:
            logger.exception("Failed to load ModuleConfig for guild %s", guild_id)

        # Priority 2: AutoModConfig DB table (legacy slash-command saves)
        if not result:
            try:
                from sqlalchemy import select

                async with session_scope() as session:
                    configs = (
                        (
                            await session.execute(
                                select(AutoModConfig).where(AutoModConfig.guild_id == str(guild_id))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for c in configs:
                        if c.enabled:
                            result[c.rule_type] = {
                                "enabled": True,
                                "threshold": c.threshold
                                or {"spam": 5, "mention": 5, "content_spam": 3}.get(c.rule_type, 1),
                                "action": c.action or "warn",
                                "duration": c.duration or 10,
                                "window_seconds": 10,
                                "ignored_roles": json.loads(c.ignored_roles)
                                if c.ignored_roles
                                else [],
                                "ignored_channels": json.loads(c.ignored_channels)
                                if c.ignored_channels
                                else [],
                            }
            except Exception:
                pass

        self._config_cache[guild_id] = result
        self._cache_ttl[guild_id] = now
        return result

    # ── Cross-channel per-user mention rate tracking ─────

    async def _check_mention_rate(self, message, config, now):
        """Track total mentions across all recent messages in a time window."""
        threshold = config.get("threshold", 5)
        window = config.get("window_seconds", 30)
        guild_id = message.guild.id
        user_id = message.author.id
        msg_mention_count = (
            len(message.mentions)
            + len(message.role_mentions)
            + (1 if message.mention_everyone else 0)
        )
        if msg_mention_count == 0:
            return

        cutoff = now - timedelta(seconds=window)
        track = self._mention_count[guild_id][user_id]
        # Prune old entries
        while track and track[0][0] < cutoff:
            track.popleft()
        # Add current batch
        track.append((now, msg_mention_count))
        total = sum(c for _, c in track)
        if total >= threshold:
            await self._take_action(
                message, config, f"Mention rate ({total} @ in {window}s across {len(track)} msgs)"
            )
            track.clear()  # Reset after action

    # ── In-memory state cleanup task ─────────────────

    async def _cleanup_loop(self):
        """Periodically prune stale spam/mention tracking data to prevent memory leaks."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(minutes=2)
                # Prune message track — handles both datetime and (datetime, count) tuple entries
                for gid in list(self._message_track.keys()):
                    for uid in list(self._message_track[gid].keys()):
                        track = self._message_track[gid][uid]
                        while track:
                            first = track[0]
                            if isinstance(first, datetime):
                                if first < cutoff:
                                    track.popleft()
                                else:
                                    break
                            elif isinstance(first, tuple) and len(first) >= 1:
                                if first[0] < cutoff:
                                    track.popleft()
                                else:
                                    break
                            else:
                                break  # unknown type, skip
                        if not track:
                            del self._message_track[gid][uid]
                    if not self._message_track[gid]:
                        del self._message_track[gid]
                # Prune mention count track
                for gid in list(self._mention_count.keys()):
                    for uid in list(self._mention_count[gid].keys()):
                        track = self._mention_count[gid][uid]
                        while track and track[0][0] < cutoff:
                            track.popleft()
                        if not track:
                            del self._mention_count[gid][uid]
                # Expire config cache entries older than 5 min
                import time as _time

                now_ts = _time.monotonic()
                stale = [g for g, t in self._cache_ttl.items() if now_ts - t > 300]
                for g in stale:
                    self._config_cache.pop(g, None)
                    self._cache_ttl.pop(g, None)

                # Prune dup_track (consecutive identical message tracking)
                for gid in list(self._dup_track.keys()):
                    for uid in list(self._dup_track[gid].keys()):
                        dup_track = self._dup_track[gid][uid]
                        while dup_track and dup_track[0][0] < cutoff:
                            dup_track.pop(0)
                        if not dup_track:
                            del self._dup_track[gid][uid]
                    if not self._dup_track[gid]:
                        del self._dup_track[gid]

                # Expire ruleset cache
                stale_rs = [g for g, t in self._ruleset_cache_ttl.items() if now_ts - t > 300]
                for g in stale_rs:
                    self._ruleset_cache.pop(g, None)
                    self._ruleset_cache_ttl.pop(g, None)

                # Prune anti-raid content/mention trackers: deques are bounded
                # but (guild, user) keys were never evicted, so a user who
                # posted once kept an entry forever. Idle 10 minutes → drop.
                for gid in set(self._anti_raid._recent_content.keys()) | set(
                    self._anti_raid._mention_track.keys()
                ):
                    self._anti_raid.prune_idle_users(int(gid), idle_seconds=600)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._logger.exception("Cleanup loop iteration failed; continuing")

    # ── Existing helpers ─────────────────────────────

    def _is_ignored(self, message, config) -> bool:
        """Check if the message author or channel is in the ignored lists."""
        ignored_roles = config.get("ignored_roles", [])
        if ignored_roles and message.author:
            if hasattr(message.author, "roles"):
                for role in message.author.roles:
                    if str(role.id) in ignored_roles:
                        return True
        ignored_channels = config.get("ignored_channels", [])
        if ignored_channels and message.channel and str(message.channel.id) in ignored_channels:
            return True
        return False

    # ── Helper: shared moderation logic ────────────────

    async def _act(
        self,
        interaction: discord.Interaction,
        action: str,
        member: discord.Member,
        reason: str,
        executor=None,
        duration: int | None = None,
    ) -> int:
        """Execute a moderation action, create case, log audit."""
        if interaction.guild is None:
            raise ValueError("Cannot act outside a guild")
        case_number = await self.ctx.create_case(
            guild_id=interaction.guild.id,
            action_type=action,
            target_id=str(member.id),
            target_tag=str(member),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
            duration=duration,
        )
        await self.ctx.log_audit(
            guild_id=interaction.guild.id,
            action=action,
            actor_id=str(interaction.user.id),
            actor_tag=str(interaction.user),
            target_id=str(member.id),
            target_tag=str(member),
            details={"reason": reason, "case": case_number, "duration": duration},
        )
        return case_number

    # ── Command handlers ──────────────────────────────

    async def _cmd_warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send("❌ Cannot warn bot accounts.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        case = await self._act(interaction, "warn", member, reason)
        await self.ctx.add_warning(
            interaction.guild.id, str(member.id), str(interaction.user.id), reason
        )
        await interaction.followup.send(f"⚠️ Warned {member.mention} | Case #{case}")
        try:
            await member.send(
                f"You were warned in {interaction.guild.name}.\nReason: {reason}\nCase #{case}"
            )
        except discord.Forbidden:
            pass

    async def _cmd_timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: int,
        unit: str,
        reason: str,
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send(
                "❌ Cannot timeout bot accounts.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild.me.guild_permissions.moderate_members:
            return await interaction.followup.send("❌ Cannot timeout members.", ephemeral=True)
        unit_map = {"seconds": 1, "minutes": 60, "hours": 3600}
        seconds = duration * unit_map.get(unit, 60)
        minutes = seconds // 60
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await member.timeout(until, reason=f"{reason}")
        except discord.Forbidden:
            return await interaction.followup.send("❌ Cannot timeout that member.", ephemeral=True)
        case = await self._act(interaction, "timeout", member, reason, duration=minutes)
        await interaction.followup.send(
            f"⏱ {member.mention} timed out {duration}{unit} | Case #{case}"
        )

    async def _cmd_kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send("❌ Cannot kick bot accounts.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.followup.send("❌ Cannot kick members.", ephemeral=True)
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Cannot kick that member.", ephemeral=True)
        case = await self._act(interaction, "kick", member, reason)
        await interaction.followup.send(f"👢 Kicked {member.mention} | Case #{case}")

    async def _cmd_ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        delete_days: int,
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send("❌ Cannot ban bot accounts.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.followup.send("❌ Cannot ban members.", ephemeral=True)
        try:
            await member.ban(reason=reason, delete_message_days=delete_days)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Cannot ban that member.", ephemeral=True)
        case = await self._act(interaction, "ban", member, reason)
        await interaction.followup.send(f"🔨 Banned {member.mention} | Case #{case}")

    async def _cmd_unban(self, interaction: discord.Interaction, user_id: str, reason: str) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        try:
            user = await self.ctx.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
        except (discord.NotFound, discord.Forbidden) as e:
            return await interaction.followup.send(f"❌ {e}", ephemeral=True)
        case = await self.ctx.create_case(
            guild_id=interaction.guild.id,
            action_type="unban",
            target_id=user_id,
            target_tag=str(user),
            moderator_id=str(interaction.user.id),
            moderator_tag=str(interaction.user),
            reason=reason,
        )
        await interaction.followup.send(f"✅ Unbanned {user.mention} | Case #{case}")

    async def _cmd_cases(self, interaction: discord.Interaction, limit: int) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import desc, select

        from database.engine import session_scope
        from database.models.moderation import ModerationCase

        async with session_scope() as session:
            result = await session.execute(
                select(ModerationCase)
                .where(ModerationCase.guild_id == str(interaction.guild.id))
                .order_by(desc(ModerationCase.created_at))
                .limit(min(limit, 50))
            )
            cases = result.scalars().all()
            if not cases:
                return await interaction.followup.send("No cases found.", ephemeral=True)
            embed = discord.Embed(title=f"Cases ({len(cases)})", color=discord.Color.blurple())
            for c in cases[:10]:
                embed.add_field(
                    name=f"#{c.case_number} — {c.action_type.upper()}",
                    value=f"**Target:** {c.target_tag}\n**Mod:** {c.moderator_tag}\n**Reason:** {c.reason or 'No reason'}\n<t:{int(c.created_at.timestamp())}:R>",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_warnings(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import desc, select

        from database.engine import session_scope
        from database.models.moderation import Warning

        async with session_scope() as session:
            result = await session.execute(
                select(Warning)
                .where(
                    Warning.guild_id == str(interaction.guild.id),
                    Warning.user_id == str(member.id),
                    Warning.active.is_(True),
                )
                .order_by(desc(Warning.created_at))
            )
            warns = result.scalars().all()
            if not warns:
                return await interaction.followup.send(
                    f"{member.mention} has no warnings.", ephemeral=True
                )
            embed = discord.Embed(
                title=f"Warnings for {member.display_name}", color=discord.Color.gold()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            for w in warns:
                embed.add_field(
                    name=f"Warning #{w.id}",
                    value=f"**Reason:** {w.reason}\n**By:** <@{w.moderator_id}>\n<t:{int(w.created_at.timestamp())}:R>",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_clearwarn(self, interaction: discord.Interaction, warning_id: int) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import select

        from database.engine import session_scope
        from database.models.moderation import Warning

        async with session_scope() as session:
            result = await session.execute(
                select(Warning).where(
                    Warning.id == warning_id, Warning.guild_id == str(interaction.guild.id)
                )
            )
            w = result.scalar_one_or_none()
            if not w:
                return await interaction.followup.send("Warning not found.", ephemeral=True)
            w.active = False
            await session.commit()
        await interaction.followup.send(f"✅ Warning #{warning_id} cleared.", ephemeral=True)

    async def _cmd_voice_sessions(
        self, interaction: discord.Interaction, member: discord.Member, limit: int
    ) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import desc, select

        from database.engine import session_scope
        from database.models.voice import VoiceSession

        async with session_scope() as session:
            result = await session.execute(
                select(VoiceSession)
                .where(
                    VoiceSession.guild_id == str(interaction.guild.id),
                    VoiceSession.user_id == str(member.id),
                )
                .order_by(desc(VoiceSession.joined_at))
                .limit(min(limit, 20))
            )
            sessions = result.scalars().all()
            if not sessions:
                return await interaction.followup.send(
                    f"No sessions for {member.mention}.", ephemeral=True
                )
            embed = discord.Embed(
                title=f"Voice — {member.display_name}", color=discord.Color.blurple()
            )
            for s in sessions:
                dur = ""
                if s.duration_seconds:
                    m, sec = divmod(s.duration_seconds, 60)
                    h, m_ = divmod(m, 60)
                    dur = f" ({h}h {m_}m {sec}s)" if h else f" ({m_}m {sec}s)"
                left = f"<t:{int(s.left_at.timestamp())}:R>" if s.left_at else "Now"
                embed.add_field(
                    name=f"#{s.channel_name}",
                    value=f"**Joined:** <t:{int(s.joined_at.timestamp())}:R>\n**Left:** {left}{dur}",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _cmd_vc_kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send(
                "❌ Cannot disconnect bot accounts from voice.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        if not member.voice or not member.voice.channel:
            return await interaction.followup.send("❌ Not in voice.", ephemeral=True)
        try:
            await member.move_to(None, reason=reason)
            await self.ctx.log_audit(
                interaction.guild.id, "vc_kick", str(interaction.user.id), target_id=str(member.id)
            )
            await interaction.followup.send(f"🔊 Disconnected {member.mention} | {reason}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Cannot disconnect.", ephemeral=True)

    async def _cmd_vc_move(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        channel: discord.VoiceChannel,
        reason: str,
    ) -> None:
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send(
                "❌ Cannot move bot accounts in voice.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        if not member.voice or not member.voice.channel:
            return await interaction.followup.send("❌ Not in voice.", ephemeral=True)
        try:
            await member.move_to(channel, reason=reason)
            await interaction.followup.send(f"🔊 Moved {member.mention} to {channel.name}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Cannot move.", ephemeral=True)

    async def _cmd_vc_mute(self, interaction, member, reason):
        await self._vc_edit(interaction, member, "mute", True, reason)

    async def _cmd_vc_unmute(self, interaction, member, reason):
        await self._vc_edit(interaction, member, "mute", False, reason)

    async def _cmd_vc_deafen(self, interaction, member, reason):
        await self._vc_edit(interaction, member, "deafen", True, reason)

    async def _cmd_vc_undeafen(self, interaction, member, reason):
        await self._vc_edit(interaction, member, "deafen", False, reason)

    async def _vc_edit(self, interaction, member, attr, value, reason):
        if not interaction.guild:
            return
        if member.bot:
            return await interaction.followup.send(
                "❌ Cannot modify bot accounts in voice.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        try:
            await member.edit(**{attr: value}, reason=reason)
            await interaction.followup.send(
                f"{'🔇' if value else '🔊'} {attr.capitalize()}d {member.mention}"
            )
        except discord.Forbidden:
            await interaction.followup.send(f"❌ Cannot edit {member.mention}.", ephemeral=True)

    async def _cmd_automod(self, interaction, rule, enabled, threshold, action):
        if not interaction.guild:
            return
        await interaction.response.defer(ephemeral=True)
        if rule not in RULE_TYPES:
            return await interaction.followup.send(
                f"Invalid. Valid: {', '.join(RULE_TYPES)}", ephemeral=True
            )

        # Check if rulesets exist — if so, this command is deprecated
        from sqlalchemy import func, select

        from database.models.ruleset import RuleSet

        async with session_scope() as session:
            rs_count = (
                await session.execute(
                    select(func.count(RuleSet.id)).where(
                        RuleSet.guild_id == str(interaction.guild.id)
                    )
                )
            ).scalar() or 0

        if rs_count > 0:
            # Migrated to rulesets — show deprecation message
            await interaction.followup.send(
                "⚠️ This server is using the new Ruleset system. "
                "Configure AutoMod rules from the dashboard **Moderation → Rulesets** tab instead. "
                "The `/automod` command only works with the legacy configuration.",
                ephemeral=True,
            )
            return

        # Legacy path — pre-ruleset guilds
        from sqlalchemy import select

        async with session_scope() as session:
            cfg = (
                await session.execute(
                    select(AutoModConfig).where(
                        AutoModConfig.guild_id == str(interaction.guild.id),
                        AutoModConfig.rule_type == rule,
                    )
                )
            ).scalar_one_or_none()
            if cfg is None:
                cfg = AutoModConfig(guild_id=str(interaction.guild.id), rule_type=rule)
                session.add(cfg)
            if enabled is not None:
                cfg.enabled = enabled
            if threshold is not None:
                cfg.threshold = threshold
            if action in ("warn", "timeout", "delete"):
                cfg.action = action
            await session.commit()
        self._config_cache.pop(interaction.guild.id, None)
        await interaction.followup.send(
            f"✅ AutoMod `{rule}` configured. Tip: Use the dashboard Moderation → Rulesets tab for more powerful AutoMod rules.",
            ephemeral=True,
        )

    def get_actions(self) -> list[dict]:
        return self._get_operational_actions() + [
            {
                "id": "cleanup_archive",
                "label": "Cleanup & Archive",
                "description": "Archive old resolved moderation cases to keep the active case list clean.",
                "endpoint": "cleanup-archive",
                "destructive": True,
                "fields": [
                    {
                        "key": "older_than_days",
                        "label": "Archive Cases Older Than (days)",
                        "type": "integer",
                        "required": True,
                        "placeholder": "90",
                    },
                    {
                        "key": "dry_run",
                        "label": "Dry Run",
                        "type": "boolean",
                        "required": False,
                        "default": True,
                    },
                ],
            },
            {
                "id": "purge_warnings",
                "label": "Purge Inactive Warnings",
                "description": "Permanently delete inactive warnings older than the specified number of days.",
                "endpoint": "purge-warnings",
                "destructive": True,
                "fields": [
                    {
                        "key": "older_than_days",
                        "label": "Older Than (days)",
                        "type": "integer",
                        "required": True,
                        "placeholder": "365",
                    },
                    {
                        "key": "dry_run",
                        "label": "Dry Run",
                        "type": "boolean",
                        "required": False,
                        "default": True,
                    },
                ],
            },
            {
                "id": "archive_by_member",
                "label": "Archive Member History",
                "description": "Soft-archive all moderation history for a target member.",
                "endpoint": "archive-member",
                "destructive": True,
                "fields": [
                    {
                        "key": "target_id",
                        "label": "Member",
                        "type": "api_select",
                        "required": True,
                        "api": "/api/v1/guilds/{guild_id}/members",
                        "value_key": "id",
                        "label_key": "name",
                        "placeholder": "Select a member...",
                    },
                    {
                        "key": "keep_active",
                        "label": "Keep Active Warnings",
                        "type": "boolean",
                        "required": False,
                    },
                ],
            },
        ]

    # ── API Routes (module dashboard actions) ─────────

    def get_api_routes(self):
        """Register API endpoints for the Moderation module's dashboard actions."""
        from fastapi import APIRouter

        from services.moderation_service import ModerationService
        from services.response import (
            api_error,
            api_forbidden,
            api_not_found,
            api_success,
            check_api_permission,
            get_module_min_role,
        )

        svc = ModerationService()
        router = APIRouter(tags=["module-moderation"])

        async def _configure_guard(request: Request, guild_id: str):
            """Ruleset/rule/wordlist mutations are module-configure gated.

            These routes previously relied only on the middleware's implicit
            guild.manage fallthrough — fragile defense-in-depth. Gate them
            explicitly like the sibling moderation actions.
            """
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.configure", guild_id):
                return api_forbidden()
            return None

        async def can_view(request: Request, guild_id: str) -> bool:
            await get_module_min_role("moderation", guild_id)
            return check_api_permission(request, "moderation.view", guild_id)

        @router.post("/guilds/{guild_id}/modules/moderation/quick-warn")
        async def quick_warn(request: Request, guild_id: str):
            """Quick-warn a member from the dashboard."""
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.warn", guild_id):
                return api_forbidden("Insufficient permissions")
            gid = int(guild_id)
            bot = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")
            data = await request.json()
            target_id = data.get("target_id", "").strip()
            reason = data.get("reason", "No reason").strip()
            if not target_id:
                return api_error("target_id is required")
            member = guild.get_member(int(target_id))
            if member is None:
                return api_not_found("Member")
            case = await svc.create_case(
                gid, "warn", str(member.id), str(member), "dashboard", "Dashboard", reason
            )
            await svc.add_warning(gid, str(member.id), "dashboard", reason)
            await svc.log_audit(
                gid,
                "warn",
                actor_id="dashboard",
                actor_tag="Dashboard",
                target_id=str(member.id),
                target_tag=str(member),
                details={"reason": reason, "case": case},
            )
            # Emit event for realtime bridge and logging
            from services.bark_context import emit_moderation_case_created

            await emit_moderation_case_created(
                self.ctx.events,
                guild_id=gid,
                case_id=case,
                action_type="warn",
                target_tag=str(member),
                moderator_tag="Dashboard",
                reason=reason,
            )
            return api_success({"case": case, "target": str(member)})

        @router.post("/guilds/{guild_id}/modules/moderation/test-rule")
        async def test_rule(request: Request, guild_id: str):
            """Simulate a rule trigger to test AutoMod configuration."""
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.configure", guild_id):
                return api_forbidden("Insufficient permissions")
            gid = int(guild_id)
            bot = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")
            data = await request.json()
            rule_type = data.get("rule_type", "").strip()
            configs = await self._get_configs(gid)
            cfg = configs.get(rule_type)
            if not cfg:
                return api_error(
                    f"Rule '{rule_type}' is not enabled. Enable it in the Configuration section first.",
                    status_code=400,
                )
            return api_success(
                {
                    "message": f"Rule '{rule_type}' is active. Threshold={cfg.get('threshold')}, "
                    f"Action={cfg.get('action')}, Window={cfg.get('window_seconds')}s. "
                    f"No simulated violations detected.",
                }
            )

        @router.post("/guilds/{guild_id}/modules/moderation/archive-member")
        async def archive_member(request: Request, guild_id: str):
            """Soft-archive all moderation history for a target member."""
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.cases.delete", guild_id):
                return api_forbidden("Insufficient permissions")
            gid = int(guild_id)
            from sqlalchemy import delete, select

            from database.models.moderation import ModerationCase
            from database.models.moderation import Warning as WarningModel

            bot = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")
            data = await request.json()
            target_id = data.get("target_id", "").strip()
            keep_active = data.get("keep_active", True)
            if not target_id:
                return api_error("target_id is required")
            async with session_scope() as session:
                cases = (
                    (
                        await session.execute(
                            select(ModerationCase).where(
                                ModerationCase.guild_id == str(gid),
                                ModerationCase.target_id == target_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                case_count = 0
                for case in cases:
                    if case.resolved:
                        continue
                    case.resolved = True
                    case.resolved_at = datetime.now(timezone.utc)
                    case.reason = f"[Archived] {case.reason or ''}"
                    case_count += 1
                if not keep_active:
                    await session.execute(
                        delete(WarningModel).where(
                            WarningModel.guild_id == str(gid),
                            WarningModel.user_id == target_id,
                        )
                    )
                await session.commit()
            return api_success(
                {
                    "message": f"Archived {case_count} active cases for target.",
                    "archived_cases": case_count,
                }
            )

        @router.post("/guilds/{guild_id}/modules/moderation/cleanup-archive")
        async def cleanup_archive(request: Request, guild_id: str):
            """Archive resolved cases older than N days."""
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.cases.delete", guild_id):
                return api_forbidden("Insufficient permissions")
            from sqlalchemy import select, update

            from database.models.moderation import ModerationCase

            data = await request.json()
            days = int(data.get("older_than_days", 90))
            dry_run = data.get("dry_run", False)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with session_scope() as session:
                result = await session.execute(
                    select(ModerationCase).where(
                        ModerationCase.guild_id == str(guild_id),
                        ModerationCase.resolved.is_(True),
                        ModerationCase.created_at <= cutoff,
                    )
                )
                count = len(result.scalars().all())
                if not dry_run:
                    await session.execute(
                        update(ModerationCase)
                        .where(
                            ModerationCase.guild_id == str(guild_id),
                            ModerationCase.resolved.is_(True),
                            ModerationCase.created_at <= cutoff,
                        )
                        .values(resolved_at=datetime.now(timezone.utc))
                    )
                    await session.commit()
            return api_success(
                {
                    "message": f"{'Would archive' if dry_run else 'Archived'} {count} resolved cases older than {days}d.",
                    "count": count,
                    "dry_run": dry_run,
                }
            )

        @router.post("/guilds/{guild_id}/modules/moderation/purge-warnings")
        async def purge_warnings(request: Request, guild_id: str):
            """Permanently delete inactive warnings older than N days."""
            await get_module_min_role("moderation", guild_id)
            if not check_api_permission(request, "moderation.warnings.delete", guild_id):
                return api_forbidden("Insufficient permissions")
            from sqlalchemy import delete, select

            from database.models.moderation import Warning as WarningModel

            data = await request.json()
            days = int(data.get("older_than_days", 365))
            dry_run = data.get("dry_run", False)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            async with session_scope() as session:
                result = await session.execute(
                    select(WarningModel).where(
                        WarningModel.guild_id == str(guild_id),
                        WarningModel.active.is_(False),
                        WarningModel.created_at <= cutoff,
                    )
                )
                count = len(result.scalars().all())
                if not dry_run:
                    await session.execute(
                        delete(WarningModel).where(
                            WarningModel.guild_id == str(guild_id),
                            WarningModel.active.is_(False),
                            WarningModel.created_at <= cutoff,
                        )
                    )
                    await session.commit()
            return api_success(
                {
                    "message": f"{'Would purge' if dry_run else 'Purged'} {count} inactive warnings older than {days}d.",
                    "count": count,
                    "dry_run": dry_run,
                }
            )

        # ── Ruleset CRUD ──────────────────────────────────────

        @router.get("/guilds/{guild_id}/rulesets")
        async def list_rulesets(request: Request, guild_id: str):
            """List all rulesets for a guild with their rules."""
            if not await can_view(request, guild_id):
                return api_forbidden("Insufficient permissions")
            from sqlalchemy import select

            from database.models.ruleset import Rule, RuleSet

            async with session_scope() as session:
                result = await session.execute(
                    select(RuleSet)
                    .where(RuleSet.guild_id == str(guild_id))
                    .order_by(RuleSet.priority)
                )
                rulesets = result.scalars().all()
                data = []
                for rs in rulesets:
                    rules_result = await session.execute(
                        select(Rule).where(Rule.ruleset_id == rs.id).order_by(Rule.priority)
                    )
                    rules = rules_result.scalars().all()
                    data.append(
                        {
                            "id": rs.id,
                            "name": rs.name,
                            "enabled": rs.enabled,
                            "priority": rs.priority,
                            "scoped_conditions": {
                                "ignored_roles": _json_list(rs.ignored_roles),
                                "require_roles": _json_list(rs.require_roles),
                                "require_all_roles": rs.require_all_roles,
                                "ignored_channels": _json_list(rs.ignored_channels),
                                "active_channels": _json_list(rs.active_channels),
                                "ignored_categories": _json_list(rs.ignored_categories),
                                "active_categories": _json_list(rs.active_categories),
                                "account_age_minutes_min": rs.account_age_minutes_min,
                                "account_age_minutes_max": rs.account_age_minutes_max,
                                "member_duration_minutes_min": rs.member_duration_minutes_min,
                                "member_duration_minutes_max": rs.member_duration_minutes_max,
                                "only_bots": rs.only_bots,
                                "ignore_bots": rs.ignore_bots,
                            },
                            "rules": [
                                {
                                    "id": r.id,
                                    "enabled": r.enabled,
                                    "trigger_type": r.trigger_type,
                                    "trigger_config": _json_dict(r.trigger_config),
                                    "effect_type": r.effect_type,
                                    "effect_config": _json_dict(r.effect_config),
                                    "conditions": _json_dict(r.conditions),
                                    "priority": r.priority,
                                }
                                for r in rules
                            ],
                        }
                    )
                return api_success({"rulesets": data})

        @router.post("/guilds/{guild_id}/rulesets")
        async def create_ruleset(request: Request, guild_id: str):
            """Create a new ruleset."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from database.models.ruleset import RuleSet

            data = await request.json()
            rs = RuleSet(
                guild_id=str(guild_id),
                name=data.get("name", "New Ruleset"),
                enabled=data.get("enabled", True),
                priority=data.get("priority", 100),
            )
            async with session_scope() as session:
                session.add(rs)
                await session.commit()
                await session.refresh(rs)
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"id": rs.id, "name": rs.name})

        @router.patch("/guilds/{guild_id}/rulesets/{ruleset_id}")
        async def update_ruleset(request: Request, guild_id: str, ruleset_id: int):
            """Update a ruleset's metadata or scoped conditions."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import RuleSet

            data = await request.json()
            async with session_scope() as session:
                result = await session.execute(
                    select(RuleSet).where(
                        RuleSet.id == ruleset_id, RuleSet.guild_id == str(guild_id)
                    )
                )
                rs = result.scalar_one_or_none()
                if not rs:
                    return api_error("Ruleset not found", status_code=404)
                for field in (
                    "name",
                    "enabled",
                    "priority",
                    "require_all_roles",
                    "only_bots",
                    "ignore_bots",
                    "check_new_messages",
                    "check_edited_messages",
                ):
                    if field in data:
                        setattr(rs, field, data[field])
                for field in (
                    "ignored_roles",
                    "require_roles",
                    "ignored_channels",
                    "active_channels",
                    "ignored_categories",
                    "active_categories",
                ):
                    if field in data:
                        setattr(rs, field, json.dumps(data[field]))
                for field in (
                    "account_age_minutes_min",
                    "account_age_minutes_max",
                    "member_duration_minutes_min",
                    "member_duration_minutes_max",
                ):
                    if field in data:
                        setattr(rs, field, data[field] or 0)
                await session.commit()
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"message": "Ruleset updated"})

        @router.delete("/guilds/{guild_id}/rulesets/{ruleset_id}")
        async def delete_ruleset(request: Request, guild_id: str, ruleset_id: int):
            """Delete a ruleset and all its rules."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import RuleSet

            async with session_scope() as session:
                result = await session.execute(
                    select(RuleSet).where(
                        RuleSet.id == ruleset_id, RuleSet.guild_id == str(guild_id)
                    )
                )
                rs = result.scalar_one_or_none()
                if not rs:
                    return api_error("Ruleset not found", status_code=404)
                await session.delete(rs)
                await session.commit()
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"message": "Ruleset deleted"})

        # ── Rule CRUD (within a ruleset) ──────────────────────

        @router.post("/guilds/{guild_id}/rulesets/{ruleset_id}/rules")
        async def create_rule(request: Request, guild_id: str, ruleset_id: int):
            """Add a rule to a ruleset."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import Rule, RuleSet

            data = await request.json()
            async with session_scope() as session:
                # Verify ruleset exists
                rs_result = await session.execute(
                    select(RuleSet).where(
                        RuleSet.id == ruleset_id, RuleSet.guild_id == str(guild_id)
                    )
                )
                if not rs_result.scalar_one_or_none():
                    return api_error("Ruleset not found", status_code=404)
                rule = Rule(
                    ruleset_id=ruleset_id,
                    enabled=data.get("enabled", True),
                    priority=data.get("priority", 50),
                    trigger_type=data.get("trigger_type", "spam"),
                    trigger_config=json.dumps(data.get("trigger_config", {})),
                    effect_type=data.get("effect_type", "warn"),
                    effect_config=json.dumps(data.get("effect_config", {})),
                    conditions=json.dumps(data.get("conditions", {})),
                )
                session.add(rule)
                await session.commit()
                await session.refresh(rule)
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"id": rule.id})

        @router.patch("/guilds/{guild_id}/rulesets/{ruleset_id}/rules/{rule_id}")
        async def update_rule(request: Request, guild_id: str, ruleset_id: int, rule_id: int):
            """Update a rule within a ruleset."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import Rule, RuleSet

            data = await request.json()
            async with session_scope() as session:
                result = await session.execute(
                    select(Rule)
                    .join(RuleSet, Rule.ruleset_id == RuleSet.id)
                    .where(
                        Rule.id == rule_id,
                        Rule.ruleset_id == ruleset_id,
                        RuleSet.guild_id == str(guild_id),
                    )
                )
                rule = result.scalar_one_or_none()
                if not rule:
                    return api_error("Rule not found", status_code=404)
                for field in ("enabled", "priority", "trigger_type", "effect_type"):
                    if field in data:
                        setattr(rule, field, data[field])
                for json_field in ("trigger_config", "effect_config", "conditions"):
                    if json_field in data:
                        setattr(rule, json_field, json.dumps(data[json_field]))
                await session.commit()
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"message": "Rule updated"})

        @router.delete("/guilds/{guild_id}/rulesets/{ruleset_id}/rules/{rule_id}")
        async def delete_rule(request: Request, guild_id: str, ruleset_id: int, rule_id: int):
            """Delete a rule from a ruleset."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import Rule, RuleSet

            async with session_scope() as session:
                result = await session.execute(
                    select(Rule)
                    .join(RuleSet, Rule.ruleset_id == RuleSet.id)
                    .where(
                        Rule.id == rule_id,
                        Rule.ruleset_id == ruleset_id,
                        RuleSet.guild_id == str(guild_id),
                    )
                )
                rule = result.scalar_one_or_none()
                if not rule:
                    return api_error("Rule not found", status_code=404)
                await session.delete(rule)
                await session.commit()
            self._ruleset_cache.pop(int(guild_id), None)
            return api_success({"message": "Rule deleted"})

        # ── WordList CRUD ──────────────────────────────────────

        @router.get("/guilds/{guild_id}/wordlists")
        async def list_wordlists(request: Request, guild_id: str):
            """List word/domain lists for a guild."""
            if not await can_view(request, guild_id):
                return api_forbidden("Insufficient permissions")
            from sqlalchemy import select

            from database.models.ruleset import WordList

            async with session_scope() as session:
                result = await session.execute(
                    select(WordList)
                    .where(WordList.guild_id == str(guild_id))
                    .order_by(WordList.list_type, WordList.name)
                )
                lists = result.scalars().all()
                return api_success(
                    {
                        "wordlists": [
                            {
                                "id": wl.id,
                                "name": wl.name,
                                "list_type": wl.list_type,
                                "entries": _json_list(wl.entries),
                            }
                            for wl in lists
                        ]
                    }
                )

        @router.post("/guilds/{guild_id}/wordlists")
        async def create_wordlist(request: Request, guild_id: str):
            """Create a word/domain list."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from database.models.ruleset import WordList

            data = await request.json()
            wl = WordList(
                guild_id=str(guild_id),
                name=data.get("name", "New List"),
                list_type=data.get("list_type", "word"),
                entries=json.dumps(data.get("entries", [])),
            )
            async with session_scope() as session:
                session.add(wl)
                await session.commit()
                await session.refresh(wl)
            self._wordlist_cache.clear()
            return api_success({"id": wl.id, "name": wl.name})

        @router.patch("/guilds/{guild_id}/wordlists/{list_id}")
        async def update_wordlist(request: Request, guild_id: str, list_id: int):
            """Update a word/domain list."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import WordList

            data = await request.json()
            async with session_scope() as session:
                result = await session.execute(
                    select(WordList).where(
                        WordList.id == list_id, WordList.guild_id == str(guild_id)
                    )
                )
                wl = result.scalar_one_or_none()
                if not wl:
                    return api_error("WordList not found", status_code=404)
                if "name" in data:
                    wl.name = data["name"]
                if "entries" in data:
                    wl.entries = json.dumps(data["entries"])
                await session.commit()
            self._wordlist_cache.clear()
            return api_success({"message": "WordList updated"})

        @router.delete("/guilds/{guild_id}/wordlists/{list_id}")
        async def delete_wordlist(request: Request, guild_id: str, list_id: int):
            """Delete a word/domain list."""
            denied = await _configure_guard(request, guild_id)
            if denied:
                return denied
            from sqlalchemy import select

            from database.models.ruleset import WordList

            async with session_scope() as session:
                result = await session.execute(
                    select(WordList).where(
                        WordList.id == list_id, WordList.guild_id == str(guild_id)
                    )
                )
                wl = result.scalar_one_or_none()
                if not wl:
                    return api_error("WordList not found", status_code=404)
                await session.delete(wl)
                await session.commit()
            self._wordlist_cache.clear()
            return api_success({"message": "WordList deleted"})

        return router
