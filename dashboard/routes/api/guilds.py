"""
Guilds API routes.
"""

from fastapi import APIRouter, Request
from services.response import api_success, api_error, api_not_found

import discord


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
        return api_success({
            "guilds": build_guild_catalog(
                access,
                bot.guilds,
                client_id=config.oauth2.client_id,
            )
        })

    guilds = []
    for guild in bot.guilds:
        guilds.append({
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": str(guild.owner_id),
            "icon_url": guild.icon.url if guild.icon else None,
        })
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

    return api_success({
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
    })


@router.get("/guilds/{guild_id}/stats")
async def get_guild_stats(request: Request, guild_id: int):
    """Get live guild and recent moderation statistics."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from datetime import date, datetime, timedelta, timezone
    from sqlalchemy import select, func
    from database.models.analytics import ActivitySnapshot
    from database.models.moderation import ModerationCase
    from database.engine import session_scope

    async with session_scope() as session:
        result = await session.execute(
            select(func.count(ModerationCase.id)).where(
                ModerationCase.guild_id == str(guild_id)
            )
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

    online = sum(
        1 for member in guild.members if member.status is not discord.Status.offline
    )
    in_voice = sum(len(channel.members) for channel in guild.voice_channels)
    return api_success({
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
    })


@router.get("/guilds/{guild_id}/roles")
async def get_guild_roles(request: Request, guild_id: int):
    """List all roles in a guild for filtering."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    return api_success({
        "roles": [
            {"id": str(r.id), "name": r.name, "color": str(r.color) if r.color else None}
            for r in guild.roles[1:]
        ]
    })


@router.get("/guilds/{guild_id}/channels")
async def get_guild_channels(request: Request, guild_id: int):
    """List all text channels in a guild for posting."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    return api_success({
        "channels": [
            {
                "id": str(c.id),
                "name": c.name,
                "parent_name": c.category.name if c.category else None,
                "type": str(c.type),
            }
            for c in sorted(guild.channels, key=lambda x: (x.category.name if x.category else "", x.position))
            if isinstance(c, discord.TextChannel)
        ]
    })


@router.get("/guilds/{guild_id}/activity")
async def get_guild_activity(request: Request, guild_id: int):
    """Aggregated recent activity feed — cases, audit logs, voice sessions, warnings."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from datetime import datetime, timezone
    from sqlalchemy import select, desc
    from database.models.moderation import ModerationCase, AuditLog
    from database.models.moderation import Warning as WarningModel
    from database.models.voice import VoiceSession
    from database.engine import session_scope

    items = []

    async with session_scope() as session:
        # Moderation cases
        result = await session.execute(
            select(ModerationCase)
            .where(ModerationCase.guild_id == str(guild_id))
            .order_by(desc(ModerationCase.created_at))
            .limit(10)
        )
        for c in result.scalars():
            items.append({
                "type": "case",
                "action": c.action_type,
                "description": f"{c.action_type} {c.target_tag or c.target_id or 'unknown'}",
                "target": c.target_tag or c.target_id,
                "moderator": c.moderator_tag or c.moderator_id,
                "reason": c.reason or "",
                "case_number": c.case_number,
                "timestamp": c.created_at.isoformat() if c.created_at else None,
                "icon": {"warn": "⚠️", "kick": "👢", "ban": "🔨", "timeout": "⏱"}.get(c.action_type, "📝"),
            })

        # Audit logs
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.guild_id == str(guild_id))
            .order_by(desc(AuditLog.created_at))
            .limit(10)
        )
        for a in result.scalars():
            detail = a.details or "{}"
            import json
            try:
                detail_dict = json.loads(detail) if isinstance(detail, str) else detail
            except (json.JSONDecodeError, TypeError):
                detail_dict = {}
            target_tag = detail_dict.get("target_tag", a.target_id or "unknown")
            actor_tag = detail_dict.get("actor_tag", a.actor_id)
            items.append({
                "type": "audit",
                "action": a.action,
                "description": f"{a.action} {target_tag}",
                "target": target_tag,
                "moderator": actor_tag,
                "reason": "",
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "icon": {"kick": "👢", "ban": "🔨", "unban": "🔓", "member_update": "✏️", "member_role_update": "🎭"}.get(a.action, "📋"),
            })

        # Voice sessions
        result = await session.execute(
            select(VoiceSession)
            .where(VoiceSession.guild_id == str(guild_id), VoiceSession.left_at.isnot(None))
            .order_by(desc(VoiceSession.joined_at))
            .limit(10)
        )
        for v in result.scalars():
            items.append({
                "type": "voice",
                "action": "voice_leave",
                "description": f"{v.user_tag or v.user_id or 'Someone'} left voice ({v.channel_name or 'unknown'})",
                "target": v.user_tag or v.user_id,
                "moderator": None,
                "reason": "",
                "timestamp": v.left_at.isoformat() if v.left_at else (v.joined_at.isoformat() if v.joined_at else None),
                "icon": "🎧",
                "duration": v.duration_seconds,
            })

        # Warnings (recently created)
        result = await session.execute(
            select(WarningModel)
            .where(WarningModel.guild_id == str(guild_id))
            .order_by(desc(WarningModel.created_at))
            .limit(10)
        )
        for w in result.scalars():
            items.append({
                "type": "warning",
                "action": "warning",
                "description": f"Warning for {w.user_id}",
                "target": w.user_id,
                "moderator": w.moderator_id,
                "reason": w.reason or "",
                "timestamp": w.created_at.isoformat() if w.created_at else None,
                "icon": "⚠️",
            })

    # Sort all by timestamp descending, take top 25
    items.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return api_success({"activity": items[:25]})
