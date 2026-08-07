"""
Guilds API routes.
"""

from datetime import datetime, timezone

import discord
from fastapi import APIRouter, Request

from services.response import (
    api_error,
    api_forbidden,
    api_not_found,
    api_success,
    check_api_permission,
    get_module_min_role,
)

router = APIRouter(tags=["api-guilds"])


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize persisted UTC datetimes with an explicit timezone offset.

    SQLite returns ``DateTime`` values without tzinfo even when callers stored
    aware UTC values. Browsers interpret offset-free ISO strings as local time,
    which can make old events look new (or even appear to be in the future).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


@router.get("/guilds")
async def list_guilds(request: Request):
    """List every Discord guild visible to the signed-in user."""
    bot = request.state.bot
    from config import config

    user = request.session.get("user") if config.oauth2.enabled else None
    if user:
        from database.engine import session_scope
        from services.dashboard_access import (
            build_guild_catalog,
            get_dashboard_moderator_roles,
            get_user_guild_access,
        )

        async with session_scope() as session:
            access = await get_user_guild_access(session, user["id"])
            moderator_roles = await get_dashboard_moderator_roles(
                session, (row.guild_id for row in access)
            )
        return api_success(
            {
                "guilds": build_guild_catalog(
                    access,
                    bot.guilds,
                    client_id=config.oauth2.client_id,
                    moderator_roles_by_guild=moderator_roles,
                )
            }
        )

    guilds = []
    for guild in bot.guilds:
        guilds.append(
            {
                "id": guild.id,
                "name": guild.name,
                "member_count": guild.member_count,
                "owner_id": str(guild.owner_id),
                "icon_url": guild.icon.url if guild.icon else None,
            }
        )
    return api_success({"guilds": guilds})


@router.get("/guilds/{guild_id}")
async def get_guild(request: Request, guild_id: int):
    """Get detailed info about a guild."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    # Resolve owner safely — guild.owner can raise if uncached
    try:
        owner_name = str(guild.owner) if guild.owner else "Unknown"
    except Exception:
        owner_name = "Unknown"

    try:
        banner_url = guild.banner.url if guild.banner else None
    except Exception:
        banner_url = None

    try:
        created_at = guild.created_at.isoformat() if guild.created_at else None
    except Exception:
        created_at = None

    try:
        premium_subscriber_count = guild.premium_subscriber_count
    except Exception:
        premium_subscriber_count = 0

    return api_success(
        {
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": str(guild.owner_id),
            "owner_name": owner_name,
            "icon_url": guild.icon.url if guild.icon else None,
            "banner_url": banner_url,
            "description": guild.description,
            "premium_tier": guild.premium_tier,
            "premium_subscriber_count": premium_subscriber_count,
            "max_members": guild.max_members,
            "channels": len(guild.channels),
            "roles": len(guild.roles),
            "emojis": len(guild.emojis),
            "created_at": created_at,
        }
    )


@router.get("/guilds/{guild_id}/stats")
async def get_guild_stats(request: Request, guild_id: int):
    """Get live guild and recent moderation statistics."""
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.view", guild_id):
        return api_forbidden("Insufficient permissions")

    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from database.engine import session_scope

    async with session_scope() as session:
        total_cases, cases_by_type, cases_7d = await _guild_case_counts(session, guild_id)
        growth_30d = await _guild_growth_30d(session, guild_id)
    online, in_voice = _online_and_voice_counts(guild)

    return api_success(
        {
            "members": guild.member_count,
            "members_online": online,
            "channels": len(guild.channels),
            "roles": len(guild.roles),
            "boosts": guild.premium_subscription_count,
            "in_voice": in_voice,
            "growth_30d": growth_30d,
            "total_cases": total_cases,
            "cases_7d": cases_7d,
            "cases_by_type": cases_by_type,
        }
    )


async def _guild_case_counts(session, guild_id: int) -> tuple[int, dict[str, int], int]:
    """Return (total_cases, cases_by_type, cases_last_7_days) for the guild."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from database.models.moderation import ModerationCase

    guild_filter = ModerationCase.guild_id == str(guild_id)
    total = (
        await session.execute(select(func.count(ModerationCase.id)).where(guild_filter))
    ).scalar() or 0
    by_type = {
        row[0]: row[1]
        for row in await session.execute(
            select(ModerationCase.action_type, func.count(ModerationCase.id))
            .where(guild_filter)
            .group_by(ModerationCase.action_type)
        )
    }
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    last_7_days = (
        await session.execute(
            select(func.count(ModerationCase.id)).where(
                guild_filter,
                ModerationCase.created_at >= seven_days_ago,
            )
        )
    ).scalar() or 0
    return total, by_type, last_7_days


async def _guild_growth_30d(session, guild_id: int) -> int:
    """Sum new members recorded by activity snapshots over the last 30 days."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.analytics import ActivitySnapshot

    return (
        await session.execute(
            select(func.sum(ActivitySnapshot.new_members)).where(
                ActivitySnapshot.guild_id == str(guild_id),
                ActivitySnapshot.snapshot_date >= date.today() - timedelta(days=30),
            )
        )
    ).scalar() or 0


def _online_and_voice_counts(guild) -> tuple[int, int]:
    """Count members currently online and members sitting in voice channels."""
    online = sum(1 for member in guild.members if member.status is not discord.Status.offline)
    in_voice = sum(len(channel.members) for channel in guild.voice_channels)
    return online, in_voice


@router.get("/guilds/{guild_id}/roles")
async def get_guild_roles(request: Request, guild_id: int):
    """List all roles in a guild for filtering."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    return api_success(
        {
            "roles": [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "color": str(r.color) if r.color else None,
                    # ADMINISTRATOR permission (0x8) — these roles grant
                    # dashboard admin access regardless of the configured
                    # moderator role. ``permissions`` is a discord.Permissions
                    # object (``.value`` bitfield); tests mock it as an int.
                    "administrator": bool(
                        getattr(r.permissions, "value", r.permissions) & 0x8
                    ),
                }
                for r in guild.roles[1:]
            ]
        }
    )


@router.get("/guilds/{guild_id}/channels")
async def get_guild_channels(request: Request, guild_id: int):
    """List text or voice channels in a guild for schema-backed selectors."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    channel_type = request.query_params.get("type", "text")
    if channel_type not in ("text", "voice"):
        return api_error("Channel type must be 'text' or 'voice'", status_code=400)

    if channel_type == "voice":
        channels: list[discord.abc.GuildChannel] = [
            c for c in guild.channels if isinstance(c, discord.VoiceChannel)
        ]
    else:
        channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    channels.sort(
        key=lambda x: (
            x.category.name if x.category is not None else "",
            x.position,
        )
    )
    return api_success(
        {
            "channels": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "parent_name": c.category.name if c.category is not None else None,
                    "type": str(c.type),
                }
                for c in channels
            ]
        }
    )


def _member_name(guild, user_id: str | None, fallback: str | None = None) -> str:
    """Resolve a Discord user ID to a display name via the guild cache."""
    if user_id:
        try:
            member = guild.get_member(int(user_id))
        except (TypeError, ValueError):
            member = None  # non-numeric actor IDs like "dashboard"
        if member is not None:
            return str(getattr(member, "display_name", None) or member)
    return fallback or user_id or "Unknown"


async def _load_case_items(session, guild_id: int, guild) -> list[dict]:
    """Recent moderation cases, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import ModerationCase

    labels = {
        "warn": "Warning issued",
        "timeout": "Timeout applied",
        "kick": "Member kicked",
        "ban": "Member banned",
        "unban": "Member unbanned",
    }
    icons = {"warn": "⚠️", "kick": "👢", "ban": "🔨", "timeout": "⏱"}
    result = await session.execute(
        select(ModerationCase)
        .where(ModerationCase.guild_id == str(guild_id))
        .order_by(desc(ModerationCase.created_at))
        .limit(10)
    )
    items = []
    for case in result.scalars():
        target = _member_name(guild, case.target_id, case.target_tag)
        moderator = _member_name(guild, case.moderator_id, case.moderator_tag)
        label = labels.get(case.action_type, case.action_type.replace("_", " ").title())
        items.append(
            {
                "type": "case",
                "category": "moderation",
                "action": case.action_type,
                "label": label,
                "description": f"{label}: {target}",
                "target": target,
                "target_id": case.target_id,
                "moderator": moderator,
                "reason": case.reason or "",
                "case_number": case.case_number,
                "timestamp": _utc_iso(case.created_at),
                "icon": icons.get(case.action_type, "📝"),
            }
        )
    return items


async def _load_audit_items(session, guild_id: int, guild) -> list[dict]:
    """Recent audit-log entries, newest first."""
    import json

    from sqlalchemy import desc, select

    from database.models.moderation import AuditLog

    messaging_actions = {"message_edit", "message_delete", "link_posted"}
    audit_labels = {
        "warn": "Warning issued",
        "timeout": "Timeout applied",
        "kick": "Member kicked",
        "ban": "Member banned",
        "unban": "Member unbanned",
        "vc_kick": "Kicked from voice",
        "member_update": "Member updated",
        "member_role_update": "Role changed",
        "message_edit": "Message edited",
        "message_delete": "Message deleted",
        "link_posted": "Link posted",
    }
    icons = {
        "kick": "👢",
        "ban": "🔨",
        "unban": "🔓",
        "member_update": "✏️",
        "member_role_update": "🎭",
        "message_edit": "✏️",
        "message_delete": "🗑️",
        "link_posted": "🔗",
    }
    moderation_actions = {"warn", "timeout", "kick", "ban", "unban", "vc_kick"}
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.guild_id == str(guild_id))
        .order_by(desc(AuditLog.created_at))
        .limit(10)
    )
    items = []
    for entry in result.scalars():
        try:
            details = json.loads(entry.details) if isinstance(entry.details, str) else entry.details
        except (json.JSONDecodeError, TypeError):
            details = {}
        actor = _member_name(guild, entry.actor_id, details.get("actor_tag"))
        messaging = entry.action in messaging_actions
        channel = details.get("channel") or ""
        label = audit_labels.get(entry.action, entry.action.replace("_", " ").title())
        if messaging:
            # For messaging events target_id is the *message* id, not a user —
            # describe the actor and channel instead.
            location = f" in {channel}" if channel else ""
            if entry.action == "message_edit":
                description = f"Message edited by {actor}{location}"
            elif entry.action == "message_delete":
                description = f"Message deleted by {actor}{location}"
            else:
                description = f"Link posted by {actor}{location}"
            target = actor
        else:
            target = _member_name(guild, entry.target_id, details.get("target_tag"))
            description = f"{label}: {target}"
        category = (
            "moderation"
            if entry.action in moderation_actions
            else "messaging"
            if messaging
            else "system"
        )
        items.append(
            {
                "type": "audit",
                "category": category,
                "action": entry.action,
                "label": label,
                "description": description,
                "target": target,
                "target_id": entry.target_id,
                "moderator": actor,
                "reason": "",
                "timestamp": _utc_iso(entry.created_at),
                "icon": icons.get(entry.action, "📋"),
            }
        )
    return items


async def _load_voice_items(session, guild_id: int, guild) -> list[dict]:
    """Recent voice-session joins, newest first."""
    from sqlalchemy import desc, select

    from database.models.voice import VoiceSession

    result = await session.execute(
        select(VoiceSession)
        .where(VoiceSession.guild_id == str(guild_id))
        .order_by(desc(VoiceSession.joined_at))
        .limit(15)
    )
    items = []
    for session_row in result.scalars():
        user = _member_name(guild, session_row.user_id, session_row.user_tag)
        items.append(
            {
                "type": "voice",
                "category": "voice",
                "action": "voice_join",
                "label": "Joined voice",
                "description": f"{user} joined voice ({session_row.channel_name or 'unknown'})",
                "target": user,
                "target_id": session_row.user_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(session_row.joined_at),
                "icon": "🎧",
                "duration": session_row.duration_seconds,
            }
        )
    return items


async def _load_warning_items(session, guild_id: int, guild) -> list[dict]:
    """Recently created warnings, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import Warning as WarningModel

    result = await session.execute(
        select(WarningModel)
        .where(WarningModel.guild_id == str(guild_id))
        .order_by(desc(WarningModel.created_at))
        .limit(10)
    )
    items = []
    for warning in result.scalars():
        user = _member_name(guild, warning.user_id)
        moderator = _member_name(guild, warning.moderator_id)
        items.append(
            {
                "type": "warning",
                "category": "moderation",
                "action": "warning",
                "label": "Warning issued",
                "description": f"Warning issued: {user}",
                "target": user,
                "target_id": warning.user_id,
                "moderator": moderator,
                "reason": warning.reason or "",
                "timestamp": _utc_iso(warning.created_at),
                "icon": "⚠️",
            }
        )
    return items


async def _load_reputation_items(session, guild_id: int, guild) -> list[dict]:
    """Notable reputation events, newest first.

    Per-message scoring (message, reaction, emoji, voice minutes) is too noisy
    for the feed and is filtered out.
    """
    from sqlalchemy import desc, select

    from database.models.reputation import ReputationEvent

    noisy_events = {
        "message",
        "reaction",
        "reaction_given",
        "reaction_received",
        "emoji",
        "voice_minute",
    }
    labels = {
        "thanks": "Thanked",
        "award": "Awarded",
        "tier_up": "Tiered up",
        "level_up": "Leveled up",
    }
    icons = {"thanks": "🙏", "award": "🏆", "tier_up": "⬆️", "level_up": "⭐"}
    result = await session.execute(
        select(ReputationEvent)
        .where(
            ReputationEvent.guild_id == str(guild_id),
            # Filter noisy per-message scoring in SQL, not Python — fetching 50
            # recent rows and discarding most of them could return an empty
            # feed on a busy server even when notable events exist.
            ReputationEvent.event_type.notin_(list(noisy_events)),
        )
        .order_by(desc(ReputationEvent.created_at))
        .limit(50)
    )
    items = []
    for event in result.scalars():
        target = _member_name(guild, event.target_id)
        actor = _member_name(guild, event.actor_id)
        label = labels.get(event.event_type, event.event_type.replace("_", " ").title())
        items.append(
            {
                "type": "reputation",
                "category": "reputation",
                "action": event.event_type,
                "label": label,
                "description": f"{actor} {label.lower()} {target} (+{event.points:g})",
                "target": target,
                "target_id": event.target_id,
                "moderator": actor,
                "reason": "",
                "timestamp": _utc_iso(event.created_at),
                "icon": icons.get(event.event_type, "🏆"),
            }
        )
    return items


async def _load_role_items(session, guild_id: int, guild) -> list[dict]:
    """Recent role assignments, newest first, with rule trigger names."""
    from sqlalchemy import desc, select

    from database.models.role_manager import RoleAssignment, RoleRule

    async def fetch_assignments() -> list:
        result = await session.execute(
            select(RoleAssignment)
            .where(RoleAssignment.guild_id == str(guild_id))
            .order_by(desc(RoleAssignment.created_at))
            .limit(10)
        )
        return list(result.scalars())

    assignments = await fetch_assignments()
    rule_ids = {row.rule_id for row in assignments if row.rule_id}
    rule_names: dict[int, str] = {}
    if rule_ids:
        rules_result = await session.execute(select(RoleRule).where(RoleRule.id.in_(rule_ids)))
        for rule in rules_result.scalars():
            rule_names[rule.id] = rule.name

    items = []
    for row in assignments:
        user = _member_name(guild, row.user_id)
        role = guild.get_role(int(row.role_id)) if row.role_id else None
        role_name = str(getattr(role, "name", None) or row.role_id or "role")
        action = "assigned" if row.action == "add" else "removed"
        trigger = f" ({rule_names.get(row.rule_id, 'manual')})" if row.rule_id else ""
        label = f"Role {action}"
        items.append(
            {
                "type": "role",
                "category": "roles",
                "action": f"role_{row.action}",
                "label": label,
                "description": f"{label} '{role_name}' for {user}{trigger}",
                "target": user,
                "target_id": row.user_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(row.created_at),
                "icon": "🎭",
            }
        )
    return items


async def _load_note_items(session, guild_id: int, guild) -> list[dict]:
    """Recent user notes, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import UserNote

    result = await session.execute(
        select(UserNote)
        .where(UserNote.guild_id == str(guild_id))
        .order_by(desc(UserNote.created_at))
        .limit(10)
    )
    items = []
    for note in result.scalars():
        user = _member_name(guild, note.user_id)
        author = _member_name(guild, note.author_id)
        items.append(
            {
                "type": "note",
                "category": "notes",
                "action": "note_added",
                "label": "Note added",
                "description": f"Note added: {user}",
                "target": user,
                "target_id": note.user_id,
                "moderator": author,
                "reason": note.content[:120],
                "timestamp": _utc_iso(note.created_at),
                "icon": "📝",
            }
        )
    return items


async def _load_auto_voice_items(session, guild_id: int, guild) -> list[dict]:
    """Recent temporary voice channels created by auto_voice, newest first."""
    from sqlalchemy import desc, select

    from database.models.auto_voice import AutoVoiceChannel

    result = await session.execute(
        select(AutoVoiceChannel)
        .where(AutoVoiceChannel.guild_id == str(guild_id))
        .order_by(desc(AutoVoiceChannel.created_at))
        .limit(10)
    )
    items = []
    for channel in result.scalars():
        owner = _member_name(guild, channel.owner_id)
        items.append(
            {
                "type": "auto_voice",
                "category": "voice",
                "action": "voice_channel_created",
                "label": "Voice channel created",
                "description": f"Temp voice channel created: {owner}",
                "target": owner,
                "target_id": channel.owner_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(channel.created_at),
                "icon": "🎙️",
            }
        )
    return items


ACTIVITY_SOURCE_LOADERS = (
    _load_case_items,
    _load_audit_items,
    _load_voice_items,
    _load_warning_items,
    _load_reputation_items,
    _load_role_items,
    _load_note_items,
    _load_auto_voice_items,
)


@router.get("/guilds/{guild_id}/activity")
async def get_guild_activity(request: Request, guild_id: int):
    """Aggregated recent activity feed — cases, audit logs, voice sessions, warnings.

    Each item carries ``type``, ``category`` (moderation / messaging / voice /
    roles / reputation / notes / system), a human ``label``, and usernames
    resolved from the guild member cache when possible.
    """
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.view", guild_id):
        return api_forbidden("Insufficient permissions")

    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from database.engine import session_scope

    items: list[dict] = []
    async with session_scope() as session:
        for loader in ACTIVITY_SOURCE_LOADERS:
            items.extend(await loader(session, guild_id, guild))

    # Sort all by timestamp descending, take top 40
    items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return api_success({"activity": items[:40]})
