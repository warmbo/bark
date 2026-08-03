"""Role manager module v1.0.0 — automatic and self-service role assignment.

Supports:
- Welcome roles: assign a role automatically when a member joins.
- Tenure roles: assign a role after the member has been in the server N days.
- Voice roles: assign a role while the member is in a voice channel, remove on leave.
- Stream roles: assign a role while the member is live on Twitch, remove when offline.
- Reaction roles: members react to a message in a configured channel to claim a role,
  un-react to release it.

Rule persistence lives in `RoleRule`; every mutation is recorded in `RoleAssignment`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import discord
from fastapi import Request

from database.engine import session_scope
from database.models.role_manager import RoleAssignment, RoleRule
from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)

logger = logging.getLogger("bark.modules.role_manager")

TENURE_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
TENURE_RULE_TYPES = ("tenure",)
VOICE_RULE_TYPES = ("voice",)
STREAM_RULE_TYPES = ("stream",)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _is_twitch_live(activities) -> bool:
    """True when an activity is a Twitch stream.

    Discord exposes live streams as ActivityType.streaming. A user can stream
    on other platforms too (e.g. YouTube), so only count activities that are
    explicitly on Twitch: platform == 'twitch' or the URL points at twitch.tv.
    Detection requires the member to link their Twitch account to Discord and
    the bot's presence intent (already enabled).
    """
    for activity in activities or []:
        if getattr(activity, "type", None) != discord.ActivityType.streaming:
            continue
        platform = getattr(activity, "platform", None) or ""
        url = getattr(activity, "url", None) or ""
        if "twitch" in str(platform).lower() or "twitch.tv" in str(url).lower():
            return True
    return False


def _parse_emoji_spec(spec: str) -> dict[str, str] | None:
    """Parse a reaction emoji spec into match keys.

    Accepts: unicode emoji ('🎮'), bare id ('123456789012345678'),
    or Discord custom emoji ('<:name:123456789012345678>' / animated '<a:...>').
    Returns {name, id} for custom emoji or {unicode} for unicode, else None.
    """
    spec = (spec or "").strip()
    if not spec:
        return None
    custom = re.match(r"^<a?:([\w]+):(\d+)>$", spec)
    if custom:
        return {"name": custom.group(1), "id": custom.group(2)}
    if spec.isdigit():
        return {"id": spec}
    return {"unicode": spec}


class RoleManagerModule(BarkModule):
    """Automatic and reaction-based Discord role management."""

    name = "role_manager"
    version = "1.0.0"
    description = "Auto-assign roles on join, tenure, voice, Twitch streams, and reaction claims"
    author = "ZENHAWX"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._tenure_task: asyncio.Task | None = None
        self._rules_cache: dict[int, list[RoleRule]] = {}
        self._cache_ttl: dict[int, float] = {}
        self._voice_members: set[tuple[int, int]] = set()
        self._stream_members: set[tuple[int, int]] = set()

    # ── Registration ─────────────────────────────────────

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_member_join", handler="_on_member_join"),
            EventRegistration("discord_voice_state", handler="_on_voice_state"),
            EventRegistration("discord_presence_update", handler="_on_presence_update"),
            EventRegistration("raw_reaction_add", handler="_on_reaction_add"),
            EventRegistration("raw_reaction_remove", handler="_on_reaction_remove"),
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration("roles", "List roles you can claim in this server"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/role_manager",
                label="Roles",
                icon="badge-check",
                category="community",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="role_manager.manage", label="Manage Role Rules"),
            PermissionDefinition(name="role_manager.view", label="View Role Assignments"),
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": (
                    "Automatically manages Discord roles: welcome roles on join, "
                    "tenure roles after membership milestones, voice roles while "
                    "connected, stream roles while live on Twitch, and self-service "
                    "reaction roles where members react to a message to claim a role."
                ),
            },
            {
                "title": "Rule Types",
                "description": (
                    "• Welcome — assign on join\n"
                    "• Tenure — assign after N days in the server\n"
                    "• Voice — assign while in voice chat\n"
                    "• Stream — assign while live on Twitch\n"
                    "• Reaction — claim by reacting to a message"
                ),
            },
            {
                "title": "How Twitch Streaming Is Detected",
                "description": (
                    "Bark watches Discord presence updates, not Twitch itself. "
                    "When a member links their Twitch account to Discord and goes live, "
                    "Discord sends the bot a presence with a Streaming activity whose "
                    "platform/URL points at twitch.tv. Bark matches on that Twitch-specific "
                    "activity, so YouTube or other streaming platforms do not trigger the "
                    "role. The member must keep their Twitch connection active in Discord."
                ),
            },
            {
                "title": "Reaction Roles",
                "description": (
                    "Point a rule at a channel and emoji — or a single message ID for "
                    "a pinned post. Members react to claim the role and un-react to "
                    "release it. Both unicode (🎮) and custom server emoji "
                    "(<:name:id>) are supported."
                ),
            },
            {
                "title": "Safety",
                "description": (
                    "Bark only manages roles the bot is allowed to manage. "
                    "Every assignment and removal is recorded in the audit log tab."
                ),
            },
        ]

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure role manager behavior.",
            "properties": {
                "tenure_check_interval": {
                    "type": "integer",
                    "title": "Tenure Check Interval (minutes)",
                    "description": "How often to scan for members crossing tenure milestones.",
                    "default": 5,
                    "minimum": 1,
                },
            },
        }

    # ── Lifecycle ───────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling role manager module v%s", self.version)
        self._rules_cache.clear()
        self._cache_ttl.clear()
        self._voice_members.clear()
        self._stream_members.clear()
        # Prime in-memory voice/stream sets so roles sync after restart.
        await self._prime_state()
        interval = TENURE_CHECK_INTERVAL_SECONDS
        self._tenure_task = asyncio.create_task(self._tenure_loop(interval))

    async def disable(self) -> None:
        self._logger.info("Disabling role manager module")
        if self._tenure_task is not None:
            self._tenure_task.cancel()
            self._tenure_task = None
        self._rules_cache.clear()
        self._cache_ttl.clear()
        self._voice_members.clear()
        self._stream_members.clear()

    # ── Rule loading ─────────────────────────────────────

    async def _get_rules(self, guild_id: int, ttl: int = 30) -> list[RoleRule]:
        """Return enabled rules for a guild, cached briefly to avoid DB spam."""
        now = time.monotonic()
        if guild_id in self._rules_cache and now < self._cache_ttl.get(guild_id, 0):
            return self._rules_cache[guild_id]
        async with session_scope() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(RoleRule).where(
                    RoleRule.guild_id == str(guild_id),
                    RoleRule.enabled == True,  # noqa: E712
                )
            )
            rules = list(result.scalars().all())
        self._rules_cache[guild_id] = rules
        self._cache_ttl[guild_id] = now + ttl
        return rules

    async def _invalidate_cache(self, guild_id: int) -> None:
        self._rules_cache.pop(guild_id, None)
        self._cache_ttl.pop(guild_id, None)

    # ── Shared assignment helper ─────────────────────────

    async def _apply_role(
        self,
        guild: discord.Guild,
        member: discord.Member,
        role_id: str,
        action: str,
        *,
        rule_id: int | None = None,
        reason: str = "",
    ) -> bool:
        """Add or remove a role, recording an audit entry. Returns True on change."""
        role = guild.get_role(int(role_id))
        if role is None:
            return False
        bot = getattr(guild, "me", None)
        if bot is None or role >= bot.top_role:
            self._logger.warning(
                "Cannot manage role %s (%s) — hierarchy/position", role_id, role.name
            )
            return False
        has_role = role in member.roles
        if action == "add" and has_role:
            return False
        if action == "remove" and not has_role:
            return False
        try:
            if action == "add":
                await member.add_roles(role, reason=reason or "Bark Role Manager")
            else:
                await member.remove_roles(role, reason=reason or "Bark Role Manager")
        except (discord.Forbidden, discord.HTTPException):
            self._logger.exception(
                "Failed to %s role %s for user %s", action, role_id, member.id
            )
            return False

        async with session_scope() as session:
            session.add(
                RoleAssignment(
                    guild_id=str(guild.id),
                    user_id=str(member.id),
                    role_id=str(role_id),
                    rule_id=rule_id,
                    action=action,
                    reason=reason or f"{action} via Bark Role Manager",
                )
            )
        return True

    # ── Welcome roles ────────────────────────────────────

    async def _on_member_join(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or member.bot or not member.guild:
            return
        guild_id = int(member.guild.id)
        rules = await self._get_rules(guild_id)
        for rule in rules:
            if rule.rule_type != "welcome":
                continue
            await self._apply_role(
                member.guild,
                member,
                rule.role_id,
                "add",
                rule_id=rule.id,
                reason="Welcome role",
            )

    # ── Tenure roles ─────────────────────────────────────

    async def _tenure_loop(self, interval: int) -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await self._check_tenure()
        except asyncio.CancelledError:
            pass

    async def _check_tenure(self) -> None:
        now = datetime.now(timezone.utc)
        for guild in self.ctx.guilds:
            guild_id = int(guild.id)
            rules = await self._get_rules(guild_id)
            tenure_rules = [r for r in rules if r.rule_type == "tenure"]
            if not tenure_rules:
                continue
            for member in guild.members:
                if member.bot:
                    continue
                joined_at = member.joined_at
                if joined_at is None:
                    continue
                if joined_at.tzinfo is None:
                    joined_at = joined_at.replace(tzinfo=timezone.utc)
                membership_days = max(0, (now - joined_at).days)
                for rule in tenure_rules:
                    cfg = _json_loads(rule.trigger_config)
                    days_required = int(cfg.get("days_required", 30))
                    if membership_days >= days_required:
                        await self._apply_role(
                            guild,
                            member,
                            rule.role_id,
                            "add",
                            rule_id=rule.id,
                            reason=f"Member for {membership_days}d (≥{days_required}d)",
                        )

    # ── Voice roles ──────────────────────────────────────

    async def _on_voice_state(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or member.bot or not member.guild:
            return
        guild_id = int(member.guild.id)
        after_channel = data.get("after_channel")
        in_voice = after_channel is not None
        key = (guild_id, int(member.id))
        was_in_voice = key in self._voice_members
        if in_voice:
            self._voice_members.add(key)
        else:
            self._voice_members.discard(key)
        if in_voice == was_in_voice:
            return

        rules = await self._get_rules(guild_id)
        voice_rules = [r for r in rules if r.rule_type == "voice"]
        if not voice_rules:
            return
        action = "add" if in_voice else "remove"
        for rule in voice_rules:
            await self._apply_role(
                member.guild,
                member,
                rule.role_id,
                action,
                rule_id=rule.id,
                reason="In voice chat" if in_voice else "Left voice chat",
            )

    # ── Stream (Twitch live) roles ───────────────────────

    async def _on_presence_update(self, event_type: str, **data) -> None:
        after = data.get("after")
        if not after or after.bot or not after.guild:
            return
        guild_id = int(after.guild.id)
        key = (guild_id, int(after.id))
        live = _is_twitch_live(getattr(after, "activities", None))
        was_live = key in self._stream_members
        if live:
            self._stream_members.add(key)
        else:
            self._stream_members.discard(key)
        if live == was_live:
            return

        rules = await self._get_rules(guild_id)
        stream_rules = [r for r in rules if r.rule_type == "stream"]
        if not stream_rules:
            return
        action = "add" if live else "remove"
        for rule in stream_rules:
            await self._apply_role(
                after.guild,
                after,
                rule.role_id,
                action,
                rule_id=rule.id,
                reason="Live on Twitch" if live else "Stream ended",
            )

    # ── Reaction roles ───────────────────────────────────

    async def _on_reaction_add(self, event_type: str, **data) -> None:
        await self._handle_reaction(data.get("payload"), adding=True)

    async def _on_reaction_remove(self, event_type: str, **data) -> None:
        await self._handle_reaction(data.get("payload"), adding=False)

    async def _handle_reaction(self, payload, *, adding: bool) -> None:
        if payload is None or not getattr(payload, "guild_id", None):
            return
        guild_id = int(payload.guild_id)
        guild = self.ctx.get_guild(guild_id)
        if guild is None:
            return

        emoji_name = str(payload.emoji)
        if payload.emoji.is_unicode_emoji():
            emoji_key = payload.emoji.name
        else:
            emoji_key = str(payload.emoji.id or payload.emoji.name)

        rules = await self._get_rules(guild_id)
        matched = []
        for rule in rules:
            if rule.rule_type != "reaction":
                continue
            cfg = _json_loads(rule.trigger_config)
            if str(cfg.get("channel_id", "")) != str(payload.channel_id):
                continue
            # Optional message scoping: when set, only react on that message.
            rule_message_id = cfg.get("message_id", "")
            if rule_message_id and str(rule_message_id) != str(payload.message_id):
                continue
            rule_emoji = str(cfg.get("emoji", ""))
            if not rule_emoji:
                continue
            spec = _parse_emoji_spec(rule_emoji)
            if spec is None:
                continue
            if "unicode" in spec:
                if spec["unicode"] in (emoji_name, emoji_key):
                    matched.append(rule)
            elif "id" in spec:
                # Match a custom emoji by id, name, or the <:name:id> full form.
                if (
                    spec["id"] == emoji_key
                    or spec["name"] == payload.emoji.name
                    or rule_emoji in (emoji_name,)
                ):
                    matched.append(rule)
            elif spec["name"] == payload.emoji.name:
                matched.append(rule)

        if not matched:
            return

        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        action = "add" if adding else "remove"
        for rule in matched:
            await self._apply_role(
                guild,
                member,
                rule.role_id,
                action,
                rule_id=rule.id,
                reason=(
                    "Claimed via reaction" if adding else "Released via reaction"
                ),
            )

    # ── State priming ────────────────────────────────────

    async def _prime_state(self) -> None:
        """Recompute voice/stream membership sets after a restart."""
        self._voice_members.clear()
        self._stream_members.clear()
        for guild in self.ctx.guilds:
            guild_id = int(guild.id)
            rules = await self._get_rules(guild_id, ttl=0)
            if any(r.rule_type in VOICE_RULE_TYPES for r in rules):
                for member in guild.members:
                    if member.bot:
                        continue
                    voice = getattr(member, "voice", None)
                    if voice is not None and getattr(voice, "channel", None) is not None:
                        self._voice_members.add((guild_id, int(member.id)))
            if any(r.rule_type in STREAM_RULE_TYPES for r in rules):
                for member in guild.members:
                    if member.bot:
                        continue
                    if _is_twitch_live(getattr(member, "activities", None)):
                        self._stream_members.add((guild_id, int(member.id)))

    # ── Slash command ────────────────────────────────────

    def _make_roles_command(self):
        @discord.app_commands.command(
            name="roles", description="List roles you can claim in this server"
        )
        async def roles_cmd(interaction: discord.Interaction):
            if not interaction.guild:
                return
            await interaction.response.defer(ephemeral=True)
            guild_id = int(interaction.guild.id)
            rules = await self._get_rules(guild_id)
            reaction_rules = [r for r in rules if r.rule_type == "reaction"]

            embed = discord.Embed(
                title="🎟️ Claimable Roles",
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )
            if not reaction_rules:
                embed.description = "No reaction roles are configured in this server."
            else:
                lines = []
                for rule in reaction_rules:
                    cfg = _json_loads(rule.trigger_config)
                    role = interaction.guild.get_role(int(rule.role_id))
                    role_name = role.name if role else f"<@&{rule.role_id}>"
                    channel = interaction.guild.get_channel(
                        int(cfg.get("channel_id", 0) or 0)
                    )
                    channel_label = channel.mention if channel else "configured channel"
                    lines.append(
                        f"{cfg.get('emoji', '⭐')} **{rule.name}** → {role_name} "
                        f"(`react in {channel_label}`)"
                    )
                embed.description = "\n".join(lines)
                embed.set_footer(text="React to the configured message to claim these roles.")

            await interaction.followup.send(embed=embed, ephemeral=True)

        return roles_cmd

    # ── API routes ───────────────────────────────────────

    def get_extra_tabs(self) -> list[dict]:
        return [
            {"id": "rules", "label": "Rules", "template": "module_tabs/role_manager_rules.html"},
            {"id": "assignments", "label": "Assignment Log", "template": "module_tabs/role_manager_assignments.html"},
        ]

    def get_api_routes(self):
        """Dashboard API for managing role rules and viewing assignments."""
        from fastapi import APIRouter

        from services.response import api_error, api_not_found, api_success

        router = APIRouter(tags=["module-role_manager"])

        @router.get("/guilds/{guild_id}/modules/role_manager/rules")
        async def list_rules(guild_id: str):
            gid = int(guild_id)
            async with session_scope() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(RoleRule)
                    .where(RoleRule.guild_id == str(gid))
                    .order_by(RoleRule.rule_type, RoleRule.id)
                )
                rows = result.scalars().all()
            rules = [
                {
                    "id": r.id,
                    "name": r.name,
                    "rule_type": r.rule_type,
                    "role_id": r.role_id,
                    "trigger_key": r.trigger_key,
                    "trigger_config": _json_loads(r.trigger_config),
                    "enabled": r.enabled,
                    "remove_when_inactive": r.remove_when_inactive,
                }
                for r in rows
            ]
            return api_success({"rules": rules})

        @router.post("/guilds/{guild_id}/modules/role_manager/rules")
        async def create_rule(request: Request, guild_id: str):
            data = await request.json()
            gid = int(guild_id)
            name = str(data.get("name", "")).strip()
            rule_type = str(data.get("rule_type", "")).strip()
            role_id = str(data.get("role_id", "")).strip()
            trigger_config = data.get("trigger_config") or {}
            if not name or not rule_type or not role_id:
                return api_error("name, rule_type, and role_id are required")
            if rule_type not in {"welcome", "tenure", "voice", "stream", "reaction"}:
                return api_error(f"Unknown rule_type: {rule_type}")
            cfg = dict(trigger_config)
            trigger_key = ""
            if rule_type == "tenure":
                trigger_key = f"tenure:{cfg.get('days_required', 30)}"
            elif rule_type == "reaction":
                trigger_key = f"reaction:{cfg.get('channel_id', '')}:{cfg.get('emoji', '')}"
            async with session_scope() as session:
                rule = RoleRule(
                    guild_id=str(gid),
                    name=name,
                    rule_type=rule_type,
                    role_id=role_id,
                    trigger_key=trigger_key,
                    trigger_config=json.dumps(cfg),
                    enabled=bool(data.get("enabled", True)),
                    remove_when_inactive=bool(data.get("remove_when_inactive", True)),
                )
                session.add(rule)
                await session.flush()
                rule_id = rule.id
            await self._invalidate_cache(gid)
            return api_success({"id": rule_id}, status_code=201)

        @router.patch("/guilds/{guild_id}/modules/role_manager/rules/{rule_id}")
        async def update_rule(request: Request, guild_id: str, rule_id: int):
            data = await request.json()
            gid = int(guild_id)
            async with session_scope() as session:
                from sqlalchemy import select
                rule = (
                    await session.execute(
                        select(RoleRule).where(
                            RoleRule.id == rule_id,
                            RoleRule.guild_id == str(gid),
                        )
                    )
                ).scalar_one_or_none()
                if rule is None:
                    return api_not_found("RoleRule")
                if "name" in data:
                    rule.name = str(data["name"]).strip()
                if "role_id" in data:
                    rule.role_id = str(data["role_id"]).strip()
                if "enabled" in data:
                    rule.enabled = bool(data["enabled"])
                if "remove_when_inactive" in data:
                    rule.remove_when_inactive = bool(data["remove_when_inactive"])
                if "trigger_config" in data:
                    cfg = dict(data["trigger_config"])
                    rule.trigger_config = json.dumps(cfg)
                    if rule.rule_type == "tenure":
                        rule.trigger_key = f"tenure:{cfg.get('days_required', 30)}"
                    elif rule.rule_type == "reaction":
                        rule.trigger_key = (
                            f"reaction:{cfg.get('channel_id', '')}:{cfg.get('emoji', '')}"
                        )
            await self._invalidate_cache(gid)
            return api_success({"message": "Rule updated"})

        @router.delete("/guilds/{guild_id}/modules/role_manager/rules/{rule_id}")
        async def delete_rule(guild_id: str, rule_id: int):
            gid = int(guild_id)
            async with session_scope() as session:
                from sqlalchemy import select
                rule = (
                    await session.execute(
                        select(RoleRule).where(
                            RoleRule.id == rule_id,
                            RoleRule.guild_id == str(gid),
                        )
                    )
                ).scalar_one_or_none()
                if rule is None:
                    return api_not_found("RoleRule")
                await session.delete(rule)
            await self._invalidate_cache(gid)
            return api_success({"message": "Rule deleted"})

        @router.get("/guilds/{guild_id}/modules/role_manager/assignments")
        async def list_assignments(guild_id: str, limit: int = 100):
            gid = int(guild_id)
            async with session_scope() as session:
                from sqlalchemy import desc, select
                result = await session.execute(
                    select(RoleAssignment)
                    .where(RoleAssignment.guild_id == str(gid))
                    .order_by(desc(RoleAssignment.created_at))
                    .limit(min(limit, 500))
                )
                rows = result.scalars().all()
            assignments = [
                {
                    "id": a.id,
                    "user_id": a.user_id,
                    "role_id": a.role_id,
                    "action": a.action,
                    "reason": a.reason,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in rows
            ]
            return api_success({"assignments": assignments})

        return router
