"""
Discord data collection service.

Collects and persists Discord guild data that is not captured by
individual module event handlers. Runs as a background task.

Data collected:
- Guild audit logs (moderation actions, settings changes)
- Invite analytics (creates, uses, expiration)
- Channel/thread/forum metadata snapshot
- Emoji/sticker inventory
- Member role changes
- Scheduled events
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import discord

from database.engine import session_scope

if TYPE_CHECKING:
    from bot.client import BarkBot

logger = logging.getLogger("bark.services.data_collector")

# ── Guild Audit Log Collection ────────────────────────────

AUDIT_LOG_ACTIONS = {
    discord.AuditLogAction.ban: "ban",
    discord.AuditLogAction.unban: "unban",
    discord.AuditLogAction.kick: "kick",
    discord.AuditLogAction.member_update: "member_update",
    discord.AuditLogAction.member_role_update: "member_role_update",
    discord.AuditLogAction.member_move: "member_move",
    discord.AuditLogAction.member_disconnect: "member_disconnect",
    discord.AuditLogAction.channel_create: "channel_create",
    discord.AuditLogAction.channel_delete: "channel_delete",
    discord.AuditLogAction.channel_update: "channel_update",
    discord.AuditLogAction.role_create: "role_create",
    discord.AuditLogAction.role_delete: "role_delete",
    discord.AuditLogAction.role_update: "role_update",
    discord.AuditLogAction.emoji_create: "emoji_create",
    discord.AuditLogAction.emoji_delete: "emoji_delete",
    discord.AuditLogAction.emoji_update: "emoji_update",
    discord.AuditLogAction.message_delete: "message_delete",
    discord.AuditLogAction.message_bulk_delete: "message_bulk_delete",
    discord.AuditLogAction.webhook_create: "webhook_create",
    discord.AuditLogAction.webhook_delete: "webhook_delete",
    discord.AuditLogAction.automod_rule_create: "automod_rule_create",
    discord.AuditLogAction.automod_rule_delete: "automod_rule_delete",
    discord.AuditLogAction.automod_block_message: "automod_block_message",
    discord.AuditLogAction.automod_flag_message: "automod_flag_message",
    discord.AuditLogAction.automod_timeout_member: "automod_timeout_member",
    discord.AuditLogAction.thread_create: "thread_create",
    discord.AuditLogAction.thread_delete: "thread_delete",
    discord.AuditLogAction.thread_update: "thread_update",
    discord.AuditLogAction.scheduled_event_create: "scheduled_event_create",
    discord.AuditLogAction.scheduled_event_delete: "scheduled_event_delete",
}


async def collect_guild_audit_logs(guild: discord.Guild) -> list[dict]:
    """Fetch recent guild audit log entries."""
    if not guild.me.guild_permissions.view_audit_log:
        return []

    entries = []
    try:
        async for entry in guild.audit_logs(limit=50, oldest_first=False):
            action_name = AUDIT_LOG_ACTIONS.get(entry.action, str(entry.action))
            entries.append(
                {
                    "id": entry.id,
                    "action": action_name,
                    "user_id": str(entry.user.id) if entry.user else None,
                    "user_tag": str(entry.user) if entry.user else "Unknown",
                    "target_id": str(entry.target.id) if entry.target else None,
                    "reason": entry.reason or "",
                    "created_at": entry.created_at.isoformat(),
                    "category": _audit_category(action_name),
                }
            )
    except discord.Forbidden:
        pass
    except Exception:
        logger.exception("Error fetching audit logs for %s", guild.name)
    return entries


def _audit_category(action: str) -> str:
    """Categorize audit log actions."""
    mod_actions = {
        "ban",
        "unban",
        "kick",
        "member_update",
        "member_role_update",
        "member_move",
        "member_disconnect",
        "message_delete",
        "message_bulk_delete",
    }
    config_actions = {
        "channel_create",
        "channel_delete",
        "channel_update",
        "role_create",
        "role_delete",
        "role_update",
        "webhook_create",
        "webhook_delete",
        "automod_rule_create",
        "automod_rule_delete",
    }
    if action in mod_actions:
        return "moderation"
    if action in config_actions:
        return "configuration"
    if action.startswith("automod"):
        return "automod"
    if action.startswith("emoji"):
        return "emoji"
    if action.startswith("thread"):
        return "thread"
    if action.startswith("scheduled_event"):
        return "events"
    return "other"


# ── Invite Tracking ──────────────────────────────────────


async def collect_invites(guild: discord.Guild) -> list[dict]:
    """Fetch current guild invites with usage stats."""
    if not guild.me.guild_permissions.manage_guild:
        return []

    invites = []
    try:
        for invite in await guild.invites():
            invites.append(
                {
                    "code": invite.code,
                    "channel_id": str(invite.channel.id) if invite.channel else None,
                    "channel_name": (
                        getattr(invite.channel, "name", "Unknown") if invite.channel else "Unknown"
                    ),
                    "uses": invite.uses,
                    "max_uses": invite.max_uses,
                    "max_age": invite.max_age,
                    "created_at": invite.created_at.isoformat() if invite.created_at else None,
                    "inviter_id": str(invite.inviter.id) if invite.inviter else None,
                    "inviter_tag": str(invite.inviter) if invite.inviter else "Unknown",
                    "expires_at": (
                        invite.created_at + timedelta(seconds=invite.max_age)
                    ).isoformat()
                    if invite.created_at and invite.max_age is not None and invite.max_age > 0
                    else None,
                    "temporary": invite.temporary,
                }
            )
    except discord.Forbidden:
        pass
    except Exception:
        logger.exception("Error fetching invites for %s", guild.name)
    return invites


# ── Channel/Thread Snapshot ──────────────────────────────


async def collect_channel_snapshot(guild: discord.Guild) -> dict:
    """Collect a snapshot of all channels, threads, and forums."""
    snapshot: dict[str, Any] = {
        "total_channels": len(guild.channels),
        "text_channels": 0,
        "voice_channels": 0,
        "forum_channels": 0,
        "category_channels": 0,
        "stage_channels": 0,
        "threads": 0,
        "active_threads": 0,
        "channels": [],
    }

    for channel in guild.channels:
        ch_type = str(channel.type)
        if isinstance(channel, discord.TextChannel):
            snapshot["text_channels"] += 1
            # Collect active threads in this channel
            try:
                active_threads = [t for t in channel.threads if not t.archived]
                snapshot["threads"] += len(channel.threads)
                snapshot["active_threads"] += len(active_threads)
            except Exception:
                pass
        elif isinstance(channel, discord.VoiceChannel):
            snapshot["voice_channels"] += 1
        elif isinstance(channel, discord.ForumChannel):
            snapshot["forum_channels"] += 1
        elif isinstance(channel, discord.CategoryChannel):
            snapshot["category_channels"] += 1
        elif isinstance(channel, discord.StageChannel):
            snapshot["stage_channels"] += 1

        snapshot["channels"].append(
            {
                "id": str(channel.id),
                "name": channel.name,
                "type": ch_type,
                "position": channel.position,
                "category": channel.category.name if channel.category else None,
                "topic": getattr(channel, "topic", None),
            }
        )

    return snapshot


# ── Emoji/Sticker Inventory ──────────────────────────────


async def collect_emoji_inventory(guild: discord.Guild) -> dict:
    """Collect all emojis and stickers."""
    return {
        "emojis": [
            {
                "id": str(e.id),
                "name": e.name,
                "animated": e.animated,
                "url": str(e.url),
            }
            for e in guild.emojis
        ],
        "stickers": [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "format": str(s.format),
            }
            for s in guild.stickers
        ],
        "emoji_count": len(guild.emojis),
        "sticker_count": len(guild.stickers),
        "emoji_slots": guild.emoji_limit,
        "sticker_slots": guild.sticker_limit,
    }


# ── Voice State Snapshot ─────────────────────────────────


async def collect_voice_snapshot(guild: discord.Guild) -> dict:
    """Collect current voice channel occupancy."""
    voice_state = {}
    for channel in guild.voice_channels:
        members_in_channel = [m for m in channel.members if not m.bot]
        if members_in_channel:
            voice_state[channel.name] = {
                "channel_id": str(channel.id),
                "member_count": len(members_in_channel),
                "members": [str(m) for m in members_in_channel],
            }
    return {
        "active_voice_channels": len(voice_state),
        "total_in_voice": sum(v["member_count"] for v in voice_state.values()),
        "channels": voice_state,
    }


# ── Guild Snapshot (all data) ─────────────────────────────


async def collect_full_guild_snapshot(guild: discord.Guild) -> dict:
    """Collect all available Discord data for a guild."""
    audit_logs, invites, channels, emojis, voice = await asyncio.gather(
        collect_guild_audit_logs(guild),
        collect_invites(guild),
        collect_channel_snapshot(guild),
        collect_emoji_inventory(guild),
        collect_voice_snapshot(guild),
        return_exceptions=True,
    )

    # Handle individual failures gracefully
    if isinstance(audit_logs, Exception):
        logger.warning("Audit log collection failed: %s", audit_logs)
        audit_logs = []
    if isinstance(invites, Exception):
        logger.warning("Invite collection failed: %s", invites)
        invites = []
    if isinstance(channels, Exception):
        logger.warning("Channel snapshot failed: %s", channels)
        channels = {}
    if isinstance(emojis, Exception):
        logger.warning("Emoji collection failed: %s", emojis)
        emojis = {}
    if isinstance(voice, Exception):
        logger.warning("Voice snapshot failed: %s", voice)
        voice = {}

    return {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "member_count": guild.member_count,
        "online_members": sum(1 for m in guild.members if m.status != discord.Status.offline),
        "bot_count": sum(1 for m in guild.members if m.bot),
        "audit_logs": audit_logs,
        "invites": invites,
        "channels": channels,
        "emojis": emojis,
        "voice": voice,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Background Collector (for the analytics service) ──────


class GuildDataCollector:
    """Periodically collects Discord data and persists to analytics tables."""

    def __init__(self, bot: BarkBot, interval_minutes: int = 15):
        self.bot = bot
        self.interval = interval_minutes
        self._task: asyncio.Task | None = None
        self._last_snapshots: dict[int, dict] = {}

    async def start(self):
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Data collector started (interval=%d min)", self.interval)

    async def stop(self):
        task = self._task
        self._task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        logger.info("Data collector stopped")

    async def _run_loop(self):
        from database.models.analytics import ActivitySnapshot

        try:
            while True:
                for guild in self.bot.guilds:
                    try:
                        snapshot = await collect_full_guild_snapshot(guild)

                        # Persist activity snapshot
                        now = datetime.now(timezone.utc)
                        async with session_scope() as session:
                            from sqlalchemy import select

                            result = await session.execute(
                                select(ActivitySnapshot).where(
                                    ActivitySnapshot.guild_id == str(guild.id),
                                    ActivitySnapshot.snapshot_date == now.date(),
                                )
                            )
                            existing = result.scalar_one_or_none()
                            if existing:
                                previous_member_count = existing.total_members
                                existing.total_members = snapshot["member_count"]
                                existing.new_members += max(
                                    0,
                                    snapshot["member_count"] - previous_member_count,
                                )
                                existing.total_channels = snapshot.get("channels", {}).get(
                                    "total_channels", 0
                                )
                            else:
                                session.add(
                                    ActivitySnapshot(
                                        guild_id=str(guild.id),
                                        snapshot_date=now.date(),
                                        total_members=snapshot["member_count"],
                                        total_channels=snapshot.get("channels", {}).get(
                                            "total_channels", 0
                                        ),
                                    )
                                )
                            await session.commit()
                        self._last_snapshots[guild.id] = snapshot
                    except Exception:
                        logger.exception("Error collecting data for guild %s", guild.name)

                await asyncio.sleep(self.interval * 60)
        except asyncio.CancelledError:
            pass

    def get_last_snapshot(self, guild_id: int) -> dict | None:
        return self._last_snapshots.get(guild_id)
