"""
Guilds API routes.
"""

import discord
from fastapi import APIRouter, Request

from services.response import api_error, api_not_found, api_success

router = APIRouter(tags=["api-guilds"])


@router.get("/guilds")
async def list_guilds(request: Request):
    """List every Discord guild visible to the signed-in user."""
    bot = request.state.bot
    from config import config

    user = request.session.get("user") if config.oauth2.enabled else None
    if user:
        from database.engine import session_scope
        from services.dashboard_access import build_guild_catalog, get_user_guild_access

        async with session_scope() as session:
            access = await get_user_guild_access(session, user["id"])
        return api_success(
            {
                "guilds": build_guild_catalog(
                    access,
                    bot.guilds,
                    client_id=config.oauth2.client_id,
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
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from datetime import date, datetime, timedelta, timezone

    from sqlalchemy import func, select

    from database.engine import session_scope
    from database.models.analytics import ActivitySnapshot
    from database.models.moderation import ModerationCase

    async with session_scope() as session:
        result = await session.execute(
            select(func.count(ModerationCase.id)).where(ModerationCase.guild_id == str(guild_id))
        )
        total_cases = result.scalar() or 0

        result = await session.execute(
            select(ModerationCase.action_type, func.count(ModerationCase.id))
            .where(ModerationCase.guild_id == str(guild_id))
            .group_by(ModerationCase.action_type)
        )
        cases_by_type = {row[0]: row[1] for row in result}

        seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
        result = await session.execute(
            select(func.count(ModerationCase.id)).where(
                ModerationCase.guild_id == str(guild_id),
                ModerationCase.created_at >= seven_days_ago,
            )
        )
        cases_7d = result.scalar() or 0

        result = await session.execute(
            select(func.sum(ActivitySnapshot.new_members)).where(
                ActivitySnapshot.guild_id == str(guild_id),
                ActivitySnapshot.snapshot_date >= date.today() - timedelta(days=30),
            )
        )
        growth_30d = result.scalar() or 0

    online = sum(1 for member in guild.members if member.status is not discord.Status.offline)
    in_voice = sum(len(channel.members) for channel in guild.voice_channels)
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
                {"id": str(r.id), "name": r.name, "color": str(r.color) if r.color else None}
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


@router.get("/guilds/{guild_id}/activity")
async def get_guild_activity(request: Request, guild_id: int):
    """Aggregated recent activity feed — cases, audit logs, voice sessions, warnings.

    Each item carries ``type``, ``category`` (moderation / messaging / voice /
    roles / reputation / notes / system), a human ``label``, and usernames
    resolved from the guild member cache when possible.
    """
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from sqlalchemy import desc, select

    from database.engine import session_scope
    from database.models.auto_voice import AutoVoiceChannel
    from database.models.moderation import AuditLog, ModerationCase, UserNote
    from database.models.moderation import Warning as WarningModel
    from database.models.reputation import ReputationEvent
    from database.models.role_manager import RoleAssignment
    from database.models.voice import VoiceSession

    def member_name(user_id: str | None, fallback: str | None = None) -> str:
        """Resolve a Discord user ID to a display name via the guild cache."""
        if user_id:
            try:
                member = guild.get_member(int(user_id))
            except (TypeError, ValueError):
                member = None  # non-numeric actor IDs like "dashboard"
            if member is not None:
                return str(getattr(member, "display_name", None) or member)
        return fallback or user_id or "Unknown"

    items = []

    async with session_scope() as session:
        # Moderation cases
        cases_result = await session.execute(
            select(ModerationCase)
            .where(ModerationCase.guild_id == str(guild_id))
            .order_by(desc(ModerationCase.created_at))
            .limit(10)
        )
        for c in cases_result.scalars():
            target = member_name(c.target_id, c.target_tag)
            moderator = member_name(c.moderator_id, c.moderator_tag)
            label = {
                "warn": "Warning issued",
                "timeout": "Timeout applied",
                "kick": "Member kicked",
                "ban": "Member banned",
                "unban": "Member unbanned",
            }.get(c.action_type, c.action_type.replace("_", " ").title())
            items.append(
                {
                    "type": "case",
                    "category": "moderation",
                    "action": c.action_type,
                    "label": label,
                    "description": f"{label}: {target}",
                    "target": target,
                    "target_id": c.target_id,
                    "moderator": moderator,
                    "reason": c.reason or "",
                    "case_number": c.case_number,
                    "timestamp": c.created_at.isoformat() if c.created_at else None,
                    "icon": {"warn": "⚠️", "kick": "👢", "ban": "🔨", "timeout": "⏱"}.get(
                        c.action_type, "📝"
                    ),
                }
            )

        # Audit logs
        audit_result = await session.execute(
            select(AuditLog)
            .where(AuditLog.guild_id == str(guild_id))
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )
        for a in audit_result.scalars():
            detail = a.details or "{}"
            import json

            try:
                detail_dict = json.loads(detail) if isinstance(detail, str) else detail
            except (json.JSONDecodeError, TypeError):
                detail_dict = {}
            actor = member_name(a.actor_id, detail_dict.get("actor_tag"))
            messaging = a.action in {"message_edit", "message_delete", "link_posted"}
            channel = detail_dict.get("channel") or ""
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
            label = audit_labels.get(a.action, a.action.replace("_", " ").title())
            if messaging:
                # For messaging events target_id is the *message* id, not a user —
                # describe the actor and channel instead.
                location = f" in {channel}" if channel else ""
                if a.action == "message_edit":
                    description = f"Message edited by {actor}{location}"
                elif a.action == "message_delete":
                    description = f"Message deleted by {actor}{location}"
                else:
                    description = f"Link posted by {actor}{location}"
                target = actor
            else:
                target = member_name(a.target_id, detail_dict.get("target_tag"))
                description = f"{label}: {target}"
            category = (
                "moderation"
                if a.action in {"warn", "timeout", "kick", "ban", "unban", "vc_kick"}
                else "messaging"
                if messaging
                else "system"
            )
            items.append(
                {
                    "type": "audit",
                    "category": category,
                    "action": a.action,
                    "label": label,
                    "description": description,
                    "target": target,
                    "target_id": a.target_id,
                    "moderator": actor,
                    "reason": "",
                    "timestamp": a.created_at.isoformat() if a.created_at else None,
                    "icon": {
                        "kick": "👢",
                        "ban": "🔨",
                        "unban": "🔓",
                        "member_update": "✏️",
                        "member_role_update": "🎭",
                        "message_edit": "✏️",
                        "message_delete": "🗑️",
                        "link_posted": "🔗",
                    }.get(a.action, "📋"),
                }
            )

        # Voice sessions — members joining voice channels
        voice_result = await session.execute(
            select(VoiceSession)
            .where(VoiceSession.guild_id == str(guild_id))
            .order_by(desc(VoiceSession.joined_at))
            .limit(15)
        )
        for v in voice_result.scalars():
            user = member_name(v.user_id, v.user_tag)
            items.append(
                {
                    "type": "voice",
                    "category": "voice",
                    "action": "voice_join",
                    "label": "Joined voice",
                    "description": f"{user} joined voice ({v.channel_name or 'unknown'})",
                    "target": user,
                    "target_id": v.user_id,
                    "moderator": None,
                    "reason": "",
                    "timestamp": v.joined_at.isoformat() if v.joined_at else None,
                    "icon": "🎧",
                    "duration": v.duration_seconds,
                }
            )

        # Warnings (recently created)
        warns_result = await session.execute(
            select(WarningModel)
            .where(WarningModel.guild_id == str(guild_id))
            .order_by(desc(WarningModel.created_at))
            .limit(10)
        )
        for w in warns_result.scalars():
            user = member_name(w.user_id)
            moderator = member_name(w.moderator_id)
            items.append(
                {
                    "type": "warning",
                    "category": "moderation",
                    "action": "warning",
                    "label": "Warning issued",
                    "description": f"Warning issued: {user}",
                    "target": user,
                    "target_id": w.user_id,
                    "moderator": moderator,
                    "reason": w.reason or "",
                    "timestamp": w.created_at.isoformat() if w.created_at else None,
                    "icon": "⚠️",
                }
            )

        # Reputation events — only notable/abnormal ones. Per-message scoring
        # (message, reaction, reaction_given/received, emoji, voice_minute) is
        # too noisy for the feed.
        noisy_rep_events = {
            "message", "reaction", "reaction_given", "reaction_received",
            "emoji", "voice_minute",
        }
        rep_result = await session.execute(
            select(ReputationEvent)
            .where(ReputationEvent.guild_id == str(guild_id))
            .order_by(desc(ReputationEvent.created_at))
            .limit(50)
        )
        for e in rep_result.scalars():
            if e.event_type in noisy_rep_events:
                continue
            target = member_name(e.target_id)
            actor = member_name(e.actor_id)
            rep_labels = {
                "thanks": "Thanked",
                "award": "Awarded",
                "tier_up": "Tiered up",
                "level_up": "Leveled up",
            }
            label = rep_labels.get(e.event_type, e.event_type.replace("_", " ").title())
            items.append(
                {
                    "type": "reputation",
                    "category": "reputation",
                    "action": e.event_type,
                    "label": label,
                    "description": f"{actor} {label.lower()} {target} (+{e.points:g})",
                    "target": target,
                    "target_id": e.target_id,
                    "moderator": actor,
                    "reason": "",
                    "timestamp": e.created_at.isoformat() if e.created_at else None,
                    "icon": {
                        "thanks": "🙏",
                        "award": "🏆",
                        "tier_up": "⬆️",
                        "level_up": "⭐",
                    }.get(e.event_type, "🏆"),
                }
            )

        # Role assignments (roles granted/removed by role_manager)
        role_result = await session.execute(
            select(RoleAssignment)
            .where(RoleAssignment.guild_id == str(guild_id))
            .order_by(desc(RoleAssignment.created_at))
            .limit(10)
        )
        # Resolve rule names for the trigger info in one batched query.
        rule_ids = {ra.rule_id for ra in role_result.scalars().all() if ra.rule_id}
        rule_names: dict[int, str] = {}
        if rule_ids:
            from database.models.role_manager import RoleRule

            rules_result = await session.execute(
                select(RoleRule).where(RoleRule.id.in_(rule_ids))
            )
            for rr in rules_result.scalars():
                rule_names[rr.id] = rr.name
        # Re-execute so the scalar cursor is fresh for iteration.
        role_result = await session.execute(
            select(RoleAssignment)
            .where(RoleAssignment.guild_id == str(guild_id))
            .order_by(desc(RoleAssignment.created_at))
            .limit(10)
        )
        for ra in role_result.scalars():
            user = member_name(ra.user_id)
            role = guild.get_role(int(ra.role_id)) if ra.role_id else None
            role_name = str(getattr(role, "name", None) or ra.role_id or "role")
            action = "assigned" if ra.action == "add" else "removed"
            trigger = f" ({rule_names.get(ra.rule_id, 'manual')})" if ra.rule_id else ""
            label = f"Role {action}"
            items.append(
                {
                    "type": "role",
                    "category": "roles",
                    "action": f"role_{ra.action}",
                    "label": label,
                    "description": f"{label} '{role_name}' for {user}{trigger}",
                    "target": user,
                    "target_id": ra.user_id,
                    "moderator": None,
                    "reason": "",
                    "timestamp": ra.created_at.isoformat() if ra.created_at else None,
                    "icon": "🎭",
                }
            )

        # User notes (added by moderators)
        notes_result = await session.execute(
            select(UserNote)
            .where(UserNote.guild_id == str(guild_id))
            .order_by(desc(UserNote.created_at))
            .limit(10)
        )
        for n in notes_result.scalars():
            user = member_name(n.user_id)
            author = member_name(n.author_id)
            items.append(
                {
                    "type": "note",
                    "category": "notes",
                    "action": "note_added",
                    "label": "Note added",
                    "description": f"Note added: {user}",
                    "target": user,
                    "target_id": n.user_id,
                    "moderator": author,
                    "reason": n.content[:120],
                    "timestamp": n.created_at.isoformat() if n.created_at else None,
                    "icon": "📝",
                }
            )

        # Temporary voice channels created by auto_voice
        avc_result = await session.execute(
            select(AutoVoiceChannel)
            .where(AutoVoiceChannel.guild_id == str(guild_id))
            .order_by(desc(AutoVoiceChannel.created_at))
            .limit(10)
        )
        for avc in avc_result.scalars():
            owner = member_name(avc.owner_id)
            items.append(
                {
                    "type": "auto_voice",
                    "category": "voice",
                    "action": "voice_channel_created",
                    "label": "Voice channel created",
                    "description": f"Temp voice channel created: {owner}",
                    "target": owner,
                    "target_id": avc.owner_id,
                    "moderator": None,
                    "reason": "",
                    "timestamp": avc.created_at.isoformat() if avc.created_at else None,
                    "icon": "🎙️",
                }
            )

    # Sort all by timestamp descending, take top 40
    items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return api_success({"activity": items[:40]})
