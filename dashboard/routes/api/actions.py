"""
Moderation actions API — delegates to ModerationService.

NO business logic lives here. This layer validates input and
delegates to the service layer.
"""

import logging
from datetime import timedelta

import discord
from fastapi import APIRouter, Query, Request

from services.bark_context import emit_moderation_case_created
from services.moderation_service import ModerationService
from services.response import (
    api_error,
    api_forbidden,
    api_not_found,
    api_success,
    check_api_permission,
    get_module_min_role,
)

logger = logging.getLogger("bark.api.actions")

router = APIRouter(tags=["api-actions"])

SERVICE = ModerationService()

# Discord permission requirements for each moderation action
_ACTION_PERMISSIONS = {
    "warn": "moderate_members",
    "timeout": "moderate_members",
    "kick": "kick_members",
    "ban": "ban_members",
    "vc_kick": "move_members",
    "vc_move": "move_members",
    "vc_mute": "mute_members",
    "vc_unmute": "mute_members",
    "unban": "ban_members",
}


# ── Member list / search ─────────────────────────────


@router.get("/guilds/{guild_id}/members")
async def list_members(
    request: Request,
    guild_id: str,
    search: str = Query("", max_length=100),
    page: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=250),
    role_id: str = "",
    sort: str = "name",
    order: str = "asc",
    min_age_days: int = Query(0, ge=0),
    max_age_days: int = Query(0, ge=0),
):
    """List/search guild members with filtering, sorting, and pagination."""
    from datetime import datetime, timezone

    gid = int(guild_id)
    bot = request.state.bot
    guild = bot.get_guild(gid)
    if guild is None:
        return api_not_found("Guild")

    now = datetime.now(timezone.utc)
    query = search.lower()
    members = []

    for member in guild.members:
        if search:
            if query not in member.display_name.lower() and query not in str(member).lower():
                continue
        if role_id:
            if role_id not in {str(r.id) for r in member.roles}:
                continue
        account_age_days = (now - member.created_at).days if member.created_at else 0
        if min_age_days > 0 and account_age_days < min_age_days:
            continue
        if max_age_days > 0 and account_age_days >= max_age_days:
            continue

        members.append(
            {
                "id": str(member.id),
                "name": member.display_name,
                "tag": str(member),
                "avatar_url": member.display_avatar.url if member.display_avatar else None,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                "created_at": member.created_at.isoformat() if member.created_at else None,
                "account_age_days": account_age_days,
                "roles": [{"id": str(r.id), "name": r.name} for r in member.roles[1:]],
                "top_role": member.top_role.name if member.top_role else "None",
                "is_bot": member.bot,
                "voice_channel": member.voice.channel.name
                if member.voice and member.voice.channel
                else None,
                "is_timed_out": member.is_timed_out(),
            }
        )

    rev = order.lower() == "desc"
    if sort == "name":
        members.sort(key=lambda m: m["name"].lower(), reverse=rev)
    elif sort == "joined_at":
        members.sort(key=lambda m: m["joined_at"] or "", reverse=rev)
    elif sort == "account_age":
        members.sort(key=lambda m: m["account_age_days"], reverse=rev)
    elif sort == "role":
        members.sort(key=lambda m: m["top_role"].lower(), reverse=rev)

    total = len(members)
    start = page * limit
    return api_success({"members": members[start : start + limit], "total": total, "page": page})


# ── Member detail ────────────────────────────────────


async def _get_user_notes(guild_id: int, user_id: str) -> list[dict]:
    """Fetch notes for a specific user from the database."""
    from sqlalchemy import desc, select

    from database.engine import session_scope
    from database.models.moderation import UserNote

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote)
            .where(
                UserNote.guild_id == str(guild_id),
                UserNote.user_id == user_id,
            )
            .order_by(desc(UserNote.created_at))
        )
        return [
            {
                "id": n.id,
                "author_id": n.author_id,
                "content": n.content,
                "created_at": n.created_at.isoformat(),
            }
            for n in result.scalars().all()
        ]


@router.get("/guilds/{guild_id}/members/{user_id}")
async def get_member_detail(request: Request, guild_id: str, user_id: str):
    """Get full member detail including cases, warnings, voice sessions."""
    gid = int(guild_id)
    bot = request.state.bot
    guild = bot.get_guild(gid)
    if guild is None:
        return api_not_found("Guild")
    member = guild.get_member(int(user_id))
    if member is None:
        return api_not_found("Member")

    cases = await SERVICE.get_cases(gid, limit=50)
    member_cases = [c for c in cases if c["target_id"] == user_id]

    warnings = await SERVICE.get_warnings(gid, user_id=str(member.id))
    notes = await _get_user_notes(gid, str(member.id))
    voice_sessions = await SERVICE.get_voice_sessions(gid, str(member.id))

    return api_success(
        {
            "id": str(member.id),
            "name": member.display_name,
            "tag": str(member),
            "avatar_url": member.display_avatar.url if member.display_avatar else None,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "created_at": member.created_at.isoformat() if member.created_at else None,
            "roles": [{"id": str(r.id), "name": r.name} for r in member.roles[1:]],
            "top_role": member.top_role.name if member.top_role else "None",
            "is_bot": member.bot,
            "is_timed_out": member.is_timed_out(),
            "voice_channel": member.voice.channel.name
            if member.voice and member.voice.channel
            else None,
            "cases": member_cases,
            "warnings": warnings,
            "notes": notes,
            "voice_sessions": voice_sessions,
        }
    )


# ── Moderation Actions ───────────────────────────────


@router.post("/guilds/{guild_id}/actions/warn")
async def action_warn(request: Request, guild_id: str):
    """Warn a member — sends DM, creates warning record and case."""
    return await _mod_action(request, guild_id, "warn", _exec_warn)


@router.post("/guilds/{guild_id}/actions/timeout")
async def action_timeout(request: Request, guild_id: str):
    """Timeout a member — restricts channel access for duration."""
    return await _mod_action(request, guild_id, "timeout", _exec_timeout)


@router.post("/guilds/{guild_id}/actions/kick")
async def action_kick(request: Request, guild_id: str):
    """Kick a member from the server."""
    return await _mod_action(request, guild_id, "kick", _exec_kick)


@router.post("/guilds/{guild_id}/actions/ban")
async def action_ban(request: Request, guild_id: str):
    """Ban a member — optionally delete recent messages."""
    return await _mod_action(request, guild_id, "ban", _exec_ban)


@router.post("/guilds/{guild_id}/actions/vc_kick")
async def action_vc_kick(request: Request, guild_id: str):
    """Disconnect a member from voice chat."""
    return await _mod_action(request, guild_id, "vc_kick", _exec_vc_kick)


@router.post("/guilds/{guild_id}/actions/vc_move")
async def action_vc_move(request: Request, guild_id: str):
    """Move a member to another voice channel."""
    return await _mod_action(request, guild_id, "vc_move", _exec_vc_move)


@router.post("/guilds/{guild_id}/actions/vc_mute")
async def action_vc_mute(request: Request, guild_id: str):
    """Server-mute a member in voice chat."""
    return await _mod_action(request, guild_id, "vc_mute", _exec_vc_mute)


@router.post("/guilds/{guild_id}/actions/vc_unmute")
async def action_vc_unmute(request: Request, guild_id: str):
    """Server-unmute a member in voice chat."""
    return await _mod_action(request, guild_id, "vc_unmute", _exec_vc_unmute)


@router.post("/guilds/{guild_id}/actions/unban")
async def action_unban(request: Request, guild_id: str):
    """Unban a user by user ID."""
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.unban", guild_id):
        return api_forbidden("Insufficient permissions")
    gid = int(guild_id)
    bot = request.state.bot
    guild = bot.get_guild(gid)
    if guild is None:
        return api_not_found("Guild")

    data = await request.json()
    user_id = data.get("target_id", "").strip()
    reason = data.get("reason", "Unbanned via dashboard").strip()

    if not user_id:
        return api_error("target_id is required")

    try:
        user = await bot.fetch_user(int(user_id))
        await guild.unban(user, reason=reason)
    except discord.NotFound:
        return api_error("User not found or not banned")
    except discord.Forbidden:
        return api_forbidden("Cannot unban members")
    except Exception:
        logger.exception(
            "Unexpected Discord error while unbanning user %s in guild %s", user_id, gid
        )
        return api_error("Unable to complete the unban action", status_code=502)

    case = await SERVICE.create_case(
        guild_id=gid,
        action_type="unban",
        target_id=user_id,
        target_tag=str(user),
        moderator_id="dashboard",
        moderator_tag="Dashboard",
        reason=reason,
    )
    await emit_moderation_case_created(
        request.state.bot.modules.event_bus,
        guild_id=gid,
        case_id=case,
        action_type="unban",
        target_tag=str(user),
        moderator_tag="Dashboard",
        reason=reason,
    )
    await SERVICE.log_audit(
        guild_id=gid,
        action="unban",
        actor_id="dashboard",
        actor_tag="Dashboard",
        target_id=user_id,
        target_tag=str(user),
        details={"reason": reason, "case": case},
    )

    return api_success({"case": case, "action": "unban", "target": str(user)})


async def _mod_action(request: Request, guild_id: str, action: str, executor):
    """Generic moderation action handler — delegates to service layer."""
    # Permission check
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, f"moderation.{action}", guild_id):
        return api_forbidden("Insufficient permissions")

    gid = int(guild_id)
    bot = request.state.bot
    guild = bot.get_guild(gid)
    if guild is None:
        return api_not_found("Guild")

    # Verify bot has the required Discord guild permission
    required_perm = _ACTION_PERMISSIONS.get(action)
    if required_perm and not getattr(guild.me.guild_permissions, required_perm, False):
        return api_forbidden(f"Bot lacks '{required_perm}' Discord permission for {action}")

    data = await request.json()
    target_id = data.get("target_id", "").strip()
    reason = data.get("reason", "Dashboard action").strip()
    duration = data.get("duration")

    if not target_id:
        return api_error("target_id is required")

    try:
        target_id_int = int(target_id)
    except (ValueError, TypeError):
        return api_error("target_id must be a valid Discord user ID (numeric)")

    member = guild.get_member(target_id_int)
    if member is None:
        return api_not_found("Member")

    # Prevent moderating bot accounts
    if member.bot:
        return api_error("Cannot moderate bot accounts")

    # Verify the dashboard user has the required Discord permission
    try:
        session_user = request.session.get("user", {})
        actor_id = session_user.get("id", "")
        if actor_id:
            actor_member = guild.get_member(int(actor_id))
            if actor_member:
                if required_perm and not getattr(
                    actor_member.guild_permissions, required_perm, False
                ):
                    return api_forbidden(
                        f"You lack '{required_perm}' Discord permission for {action}"
                    )
                # Role hierarchy check: actor's top role must be above target's top role
                if action in ("kick", "ban", "timeout"):
                    actor_top = actor_member.top_role.position
                    target_top = member.top_role.position
                    if actor_top <= target_top and not actor_member.guild_permissions.administrator:
                        return api_forbidden(
                            "Cannot moderate that member — their highest role is equal to or above yours"
                        )
    except (ValueError, TypeError):
        pass  # If actor lookup fails, proceed with bot-only check

    try:
        await executor(guild, member, reason, duration)
    except discord.Forbidden:
        return api_forbidden(f"Cannot {action} that member")
    except Exception:
        logger.exception(
            "Unexpected Discord error while running %s for member %s in guild %s",
            action,
            member.id,
            gid,
        )
        return api_error(f"Unable to complete the {action} action", status_code=502)

    case = await SERVICE.create_case(
        guild_id=gid,
        action_type=action,
        target_id=str(member.id),
        target_tag=str(member),
        moderator_id="dashboard",
        moderator_tag="Dashboard",
        reason=reason,
        duration=duration,
    )
    await emit_moderation_case_created(
        request.state.bot.modules.event_bus,
        guild_id=gid,
        case_id=case,
        action_type=action,
        target_tag=str(member),
        moderator_tag="Dashboard",
        reason=reason,
    )
    await SERVICE.log_audit(
        guild_id=gid,
        action=action,
        actor_id="dashboard",
        actor_tag="Dashboard",
        target_id=str(member.id),
        target_tag=str(member),
        details={"reason": reason, "case": case, "duration": duration},
    )

    return api_success({"case": case, "action": action, "target": str(member)})


# ── Execution helpers (delegated to Discord API) ─────


async def _exec_warn(guild, member, reason, duration=None):
    try:
        await member.send(f"You were warned in {guild.name}.\nReason: {reason}")
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("Could not DM warning to %s in guild %s", member, guild.id)
    await SERVICE.add_warning(guild.id, str(member.id), "dashboard", reason)


async def _exec_timeout(guild, member, reason, duration):
    minutes = duration or 10
    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)


async def _exec_kick(guild, member, reason, duration):
    await member.kick(reason=reason)


async def _exec_ban(guild, member, reason, duration):
    await member.ban(reason=reason, delete_message_days=0)


async def _exec_vc_kick(guild, member, reason, duration):
    await member.move_to(None, reason=reason)


async def _exec_vc_move(guild, member, reason, duration):
    ch_id = duration  # Reuse duration param as channel_id for vc_move
    if ch_id:
        channel = guild.get_channel(int(ch_id))
        if channel:
            await member.move_to(channel, reason=reason)


async def _exec_vc_mute(guild, member, reason, duration):
    await member.edit(mute=True, reason=reason)


async def _exec_vc_unmute(guild, member, reason, duration):
    await member.edit(mute=False, reason=reason)
