"""
Moderation actions API — bridges dashboard actions to Discord bot commands.
These endpoints call the same underlying logic as slash commands.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.engine import session_scope
from database.models.moderation import ModerationCase, Warning, AuditLog

router = APIRouter(tags=["api-actions"])


async def _create_case(
    guild_id: int,
    action_type: str,
    target_id: str,
    target_tag: str,
    moderator_id: str,
    moderator_tag: str,
    reason: str,
    duration: int | None = None,
) -> int:
    from sqlalchemy import select, func
    async with session_scope() as session:
        result = await session.execute(
            select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
            .where(ModerationCase.guild_id == guild_id)
        )
        case_number = result.scalar()
        case = ModerationCase(
            guild_id=guild_id,
            case_number=case_number,
            action_type=action_type,
            target_id=target_id,
            target_tag=target_tag,
            moderator_id=moderator_id,
            moderator_tag=moderator_tag,
            reason=reason,
            duration=duration,
        )
        session.add(case)
        await session.commit()
    return case_number


async def _log_audit(guild_id: int, action: str, actor_id: str, target_id: str | None, details: dict | None = None):
    async with session_scope() as session:
        session.add(AuditLog(
            guild_id=guild_id,
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            details=json.dumps(details or {}),
        ))
        await session.commit()


@router.get("/guilds/{guild_id}/members")
async def list_members(request: Request, guild_id: int, search: str = "", page: int = 0, limit: int = 50):
    """List and search guild members."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    members = []
    for member in guild.members:
        name = member.display_name.lower()
        tag = str(member).lower()
        query = search.lower()
        if search and query not in name and query not in tag:
            continue
        members.append({
            "id": str(member.id),
            "name": member.display_name,
            "tag": str(member),
            "avatar_url": member.display_avatar.url if member.display_avatar else None,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "roles": [{"id": str(r.id), "name": r.name} for r in member.roles[1:]],
            "top_role": member.top_role.name if member.top_role else "None",
            "is_bot": member.bot,
            "voice_channel": member.voice.channel.name if member.voice and member.voice.channel else None,
            "is_timed_out": member.is_timed_out(),
        })

    total = len(members)
    start = page * limit
    end = start + limit
    return {"members": members[start:end], "total": total, "page": page}


@router.get("/guilds/{guild_id}/members/{user_id}")
async def get_member_detail(request: Request, guild_id: int, user_id: str):
    """Get detailed info about a member including case history."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    member = guild.get_member(int(user_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    from sqlalchemy import select, desc, func

    async with session_scope() as session:
        # Cases
        result = await session.execute(
            select(ModerationCase)
            .where(ModerationCase.guild_id == guild_id, ModerationCase.target_id == user_id)
            .order_by(desc(ModerationCase.created_at))
            .limit(20)
        )
        cases = [{
            "case_number": c.case_number,
            "action_type": c.action_type,
            "moderator_tag": c.moderator_tag,
            "reason": c.reason,
            "created_at": c.created_at.isoformat(),
            "resolved": c.resolved,
        } for c in result.scalars().all()]

        # Active warnings
        result = await session.execute(
            select(Warning)
            .where(Warning.guild_id == guild_id, Warning.user_id == user_id, Warning.active == True)
            .order_by(desc(Warning.created_at))
        )
        warnings = [{
            "id": w.id,
            "moderator_id": w.moderator_id,
            "reason": w.reason,
            "created_at": w.created_at.isoformat(),
        } for w in result.scalars().all()]

        # Notes
        from database.models.moderation import UserNote
        result = await session.execute(
            select(UserNote)
            .where(UserNote.guild_id == guild_id, UserNote.user_id == user_id)
            .order_by(desc(UserNote.created_at))
        )
        notes = [{
            "id": n.id,
            "author_id": n.author_id,
            "content": n.content,
            "created_at": n.created_at.isoformat(),
        } for n in result.scalars().all()]

        # Voice sessions
        from database.models.voice import VoiceSession
        result = await session.execute(
            select(VoiceSession)
            .where(VoiceSession.guild_id == guild_id, VoiceSession.user_id == user_id)
            .order_by(desc(VoiceSession.joined_at))
            .limit(10)
        )
        voice_sessions = []
        for vs in result.scalars().all():
            duration = vs.duration_seconds
            dur_str = ""
            if duration is not None:
                m, s = divmod(duration, 60)
                h, m = divmod(m, 60)
                dur_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
            voice_sessions.append({
                "channel_name": vs.channel_name,
                "joined_at": vs.joined_at.isoformat(),
                "left_at": vs.left_at.isoformat() if vs.left_at else None,
                "duration": dur_str,
            })

    return {
        "id": str(member.id),
        "name": member.display_name,
        "tag": str(member),
        "avatar_url": member.display_avatar.url if member.display_avatar else None,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "roles": [{"id": str(r.id), "name": r.name} for r in member.roles[1:]],
        "top_role": member.top_role.name if member.top_role else "None",
        "is_bot": member.bot,
        "voice_channel": member.voice.channel.name if member.voice and member.voice.channel else None,
        "is_timed_out": member.is_timed_out(),
        "cases": cases,
        "warnings": warnings,
        "warnings_count": len(warnings),
        "notes": notes,
        "voice_sessions": voice_sessions,
    }


@router.post("/guilds/{guild_id}/actions/warn")
async def action_warn(request: Request, guild_id: int):
    """Warn a member (dashboard action, same as /warn command)."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    data = await request.json()
    target_id = data.get("target_id")
    reason = data.get("reason", "No reason provided")
    moderator_id = data.get("moderator_id", str(bot.user.id))

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    moderator = guild.get_member(int(moderator_id)) if moderator_id else None
    moderator_tag = str(moderator) if moderator else str(bot.user)

    case_number = await _create_case(
        guild_id=guild_id, action_type="warn",
        target_id=target_id, target_tag=str(member),
        moderator_id=moderator_id, moderator_tag=moderator_tag,
        reason=reason,
    )

    async with session_scope() as session:
        session.add(Warning(
            guild_id=guild_id, user_id=target_id,
            moderator_id=moderator_id, reason=reason, active=True,
        ))
        await session.commit()

    await _log_audit(guild_id=guild_id, action="warn",
                     actor_id=moderator_id, target_id=target_id,
                     details={"reason": reason, "case": case_number})

    return {"success": True, "case_number": case_number, "action": "warn"}


@router.post("/guilds/{guild_id}/actions/timeout")
async def action_timeout(request: Request, guild_id: int):
    """Timeout a member (dashboard action)."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)
    if not guild.me.guild_permissions.moderate_members:
        return JSONResponse({"error": "Bot lacks moderate_members permission"}, status_code=403)

    data = await request.json()
    target_id = data.get("target_id")
    duration = data.get("duration", 10)
    unit = data.get("unit", "minutes")
    reason = data.get("reason", "No reason provided")
    moderator_id = data.get("moderator_id", str(bot.user.id))

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    from datetime import timedelta
    unit_map = {"seconds": 1, "minutes": 60, "hours": 3600}
    seconds = duration * unit_map.get(unit, 60)
    until = discord_utcnow() + timedelta(seconds=seconds)
    minutes = seconds // 60

    try:
        await member.timeout(until, reason=f"Dashboard timeout: {reason}")
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot timeout this member"}, status_code=403)

    moderator_tag = str(guild.get_member(int(moderator_id)) or bot.user)
    case_number = await _create_case(
        guild_id=guild_id, action_type="timeout",
        target_id=target_id, target_tag=str(member),
        moderator_id=moderator_id, moderator_tag=moderator_tag,
        reason=reason, duration=minutes,
    )

    await _log_audit(guild_id=guild_id, action="timeout",
                     actor_id=moderator_id, target_id=target_id,
                     details={"duration": minutes, "reason": reason, "case": case_number})

    return {"success": True, "case_number": case_number, "action": "timeout", "duration_minutes": minutes}


@router.post("/guilds/{guild_id}/actions/kick")
async def action_kick(request: Request, guild_id: int):
    """Kick a member (dashboard action)."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)
    if not guild.me.guild_permissions.kick_members:
        return JSONResponse({"error": "Bot lacks kick_members permission"}, status_code=403)

    data = await request.json()
    target_id = data.get("target_id")
    reason = data.get("reason", "No reason provided")

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    try:
        await member.kick(reason=f"Dashboard kick: {reason}")
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot kick this member"}, status_code=403)

    case_number = await _create_case(
        guild_id=guild_id, action_type="kick",
        target_id=target_id, target_tag=str(member),
        moderator_id=str(bot.user.id), moderator_tag=str(bot.user),
        reason=reason,
    )

    return {"success": True, "case_number": case_number, "action": "kick"}


@router.post("/guilds/{guild_id}/actions/ban")
async def action_ban(request: Request, guild_id: int):
    """Ban a member (dashboard action)."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)
    if not guild.me.guild_permissions.ban_members:
        return JSONResponse({"error": "Bot lacks ban_members permission"}, status_code=403)

    data = await request.json()
    target_id = data.get("target_id")
    reason = data.get("reason", "No reason provided")
    delete_days = data.get("delete_days", 0)

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    try:
        await member.ban(reason=f"Dashboard ban: {reason}", delete_message_days=delete_days)
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot ban this member"}, status_code=403)

    case_number = await _create_case(
        guild_id=guild_id, action_type="ban",
        target_id=target_id, target_tag=str(member),
        moderator_id=str(bot.user.id), moderator_tag=str(bot.user),
        reason=reason,
    )

    return {"success": True, "case_number": case_number, "action": "ban"}


@router.post("/guilds/{guild_id}/actions/vc_kick")
async def action_vc_kick(request: Request, guild_id: int):
    """Voice-disconnect a member."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    data = await request.json()
    target_id = data.get("target_id")
    reason = data.get("reason", "No reason provided")

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)
    if member.voice is None or member.voice.channel is None:
        return JSONResponse({"error": "Member not in voice"}, status_code=400)

    try:
        await member.move_to(None, reason=f"Dashboard VC kick: {reason}")
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot disconnect this member"}, status_code=403)

    case_number = await _create_case(
        guild_id=guild_id, action_type="vc_kick",
        target_id=target_id, target_tag=str(member),
        moderator_id=str(bot.user.id), moderator_tag=str(bot.user),
        reason=reason,
    )

    return {"success": True, "case_number": case_number, "action": "vc_kick"}


@router.post("/guilds/{guild_id}/actions/vc_move")
async def action_vc_move(request: Request, guild_id: int):
    """Move a member to another voice channel."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    data = await request.json()
    target_id = data.get("target_id")
    channel_id = data.get("channel_id")
    reason = data.get("reason", "No reason provided")

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return JSONResponse({"error": "Channel not found"}, status_code=404)

    try:
        await member.move_to(channel, reason=f"Dashboard VC move: {reason}")
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot move this member"}, status_code=403)

    return {"success": True, "action": "vc_move"}


@router.post("/guilds/{guild_id}/actions/vc_mute")
async def action_vc_mute(request: Request, guild_id: int):
    """Server-mute a member in voice."""
    return await _vc_toggle_mute(request, guild_id, mute=True)


@router.post("/guilds/{guild_id}/actions/vc_unmute")
async def action_vc_unmute(request: Request, guild_id: int):
    """Server-unmute a member in voice."""
    return await _vc_toggle_mute(request, guild_id, mute=False)


async def _vc_toggle_mute(request: Request, guild_id: int, mute: bool):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return JSONResponse({"error": "Guild not found"}, status_code=404)

    data = await request.json()
    target_id = data.get("target_id")
    reason = data.get("reason", "No reason provided")

    member = guild.get_member(int(target_id))
    if member is None:
        return JSONResponse({"error": "Member not found"}, status_code=404)

    try:
        await member.edit(mute=mute, reason=f"Dashboard VC {'mute' if mute else 'unmute'}: {reason}")
    except discord.Forbidden:
        return JSONResponse({"error": "Cannot edit this member"}, status_code=403)

    return {"success": True, "action": "vc_mute" if mute else "vc_unmute"}


def discord_utcnow():
    from datetime import timezone
    from datetime import datetime
    return datetime.now(timezone.utc)


import discord
