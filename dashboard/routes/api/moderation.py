"""
Moderation API routes.
"""


from fastapi import APIRouter, Request

from database.engine import session_scope
from database.models.moderation import ModerationCase, Warning, UserNote
from services.response import api_success, api_error, api_paginated
from services.bark_context import emit_moderation_case_created

router = APIRouter(tags=["api-moderation"])


# ── Cases ────────────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/cases")
async def list_cases(request: Request, guild_id: str, page: int = 0, limit: int = 50):
    """List moderation cases for a guild with pagination."""
    gid = int(guild_id)
    from sqlalchemy import select, desc, func
    from database.models.moderation import ModerationCase

    async with session_scope() as session:
        # Total count
        total = (
            await session.execute(
                select(func.count(ModerationCase.id)).where(ModerationCase.guild_id == str(gid), ModerationCase.resolved == False)
            )
        ).scalar() or 0

        result = await session.execute(
            select(ModerationCase)
            .where(ModerationCase.guild_id == str(gid), ModerationCase.resolved == False)
            .order_by(desc(ModerationCase.created_at))
            .offset(page * limit)
            .limit(limit)
        )
        cases = result.scalars().all()

        return api_paginated(
            items=[
                {
                    "case_number": c.case_number,
                    "action_type": c.action_type,
                    "target_id": c.target_id,
                    "target_tag": c.target_tag,
                    "moderator_tag": c.moderator_tag,
                    "reason": c.reason,
                    "duration": c.duration,
                    "created_at": c.created_at.isoformat(),
                    "resolved": c.resolved,
                }
                for c in cases
            ],
            total=total,
            page=page,
            limit=limit,
        )


@router.get("/guilds/{guild_id}/moderation/cases/{case_number}")
async def get_case(request: Request, guild_id: str, case_number: int):
    """Get a specific case."""
    from sqlalchemy import select
    gid = str(guild_id)

    async with session_scope() as session:
        result = await session.execute(
            select(ModerationCase).where(
                ModerationCase.guild_id == str(gid),
                ModerationCase.case_number == case_number,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            return api_error("Case not found", status_code=404)

        return api_success({"case_number": case.case_number, "action_type": case.action_type,
            "target_id": case.target_id, "target_tag": case.target_tag,
            "moderator_id": case.moderator_id, "moderator_tag": case.moderator_tag,
            "reason": case.reason, "duration": case.duration,
            "created_at": case.created_at.isoformat(),
            "resolved": case.resolved,
            "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        })


@router.post("/guilds/{guild_id}/moderation/cases")
async def create_case(request: Request, guild_id: str):
    """Create a new moderation case."""
    gid = int(guild_id)
    if request.state.bot.get_guild(gid) is None:
        return api_error("Guild not found", status_code=404)
    data = await request.json()

    from sqlalchemy import select, func

    async with session_scope() as session:
        # Get next case number
        result = await session.execute(
            select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
            .where(ModerationCase.guild_id == str(gid))
        )
        next_number = result.scalar()

        case = ModerationCase(
            guild_id=str(gid),
            case_number=next_number,
            action_type=data.get("action_type", "warn"),
            target_id=data.get("target_id", ""),
            target_tag=data.get("target_tag", "Unknown#0000"),
            moderator_id=data.get("moderator_id", ""),
            moderator_tag=data.get("moderator_tag", "Unknown#0000"),
            reason=data.get("reason", ""),
            duration=data.get("duration"),
        )
        session.add(case)
        await session.commit()

        await emit_moderation_case_created(
            request.state.bot.modules.event_bus,
            guild_id=gid,
            case_id=case.case_number,
            action_type=case.action_type,
            target_tag=case.target_tag,
            moderator_tag=case.moderator_tag,
            reason=case.reason,
        )
        return api_success({
            "success": True,
            "case_number": case.case_number,
            "id": case.id,
        })


# ── Warnings ─────────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/warnings")
async def list_warnings(request: Request, guild_id: str):
    """List all active warnings for a guild."""
    from sqlalchemy import select, desc
    gid = str(guild_id)

    async with session_scope() as session:
        result = await session.execute(
            select(Warning)
            .where(Warning.guild_id == str(gid), Warning.active == True)
            .order_by(desc(Warning.created_at))
            .limit(100)
        )
        warnings = result.scalars().all()

        return api_success({
            "warnings": [
                {
                    "id": w.id,
                    "user_id": w.user_id,
                    "moderator_id": w.moderator_id,
                    "reason": w.reason,
                    "created_at": w.created_at.isoformat(),
                    "active": w.active,
                }
                for w in warnings
            ]
        })


@router.get("/guilds/{guild_id}/moderation/warnings/{user_id}")
async def get_user_warnings(request: Request, guild_id: str, user_id: str):
    """List warnings for a specific user."""
    from sqlalchemy import select, desc
    gid = str(guild_id)

    async with session_scope() as session:
        result = await session.execute(
            select(Warning)
            .where(
                Warning.guild_id == str(gid),
                Warning.user_id == user_id,
            )
            .order_by(desc(Warning.created_at))
        )
        warnings = result.scalars().all()

        return api_success({
            "user_id": user_id,
            "warning_count": len([w for w in warnings if w.active]),
            "total_warnings": len(warnings),
            "warnings": [
                {
                    "id": w.id,
                    "moderator_id": w.moderator_id,
                    "reason": w.reason,
                    "created_at": w.created_at.isoformat(),
                    "active": w.active,
                }
                for w in warnings
            ],
        })


# ── Delete ────────────────────────────────────────────


from datetime import datetime, timezone


@router.delete("/guilds/{guild_id}/moderation/cases/{case_number}")
async def delete_case(request: Request, guild_id: str, case_number: int):
    """Delete a moderation case by case number."""
    from services.response import (
        api_forbidden,
        check_api_permission,
        get_module_min_role,
    )
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.cases.delete", guild_id):
        return api_forbidden()
    from sqlalchemy import select
    gid = str(guild_id)

    async with session_scope() as session:
        result = await session.execute(
            select(ModerationCase).where(
                ModerationCase.guild_id == str(gid),
                ModerationCase.case_number == case_number,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            return api_error("Case not found", status_code=404)

        # Soft-delete by marking as resolved
        case.resolved = True
        case.resolved_at = datetime.now(timezone.utc)
        await session.commit()

        return api_success({"deleted": True, "case_number": case_number})


@router.delete("/guilds/{guild_id}/moderation/warnings/{warning_id}")
async def delete_warning(request: Request, guild_id: str, warning_id: int):
    """Deactivate a warning by ID."""
    from services.response import (
        api_forbidden,
        check_api_permission,
        get_module_min_role,
    )
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.warnings.delete", guild_id):
        return api_forbidden()
    from services.moderation_service import ModerationService
    success = await ModerationService.clear_warning(int(guild_id), warning_id)
    if not success:
        return api_error("Warning not found", status_code=404)
    return api_success({"deleted": True, "warning_id": warning_id})


# ── Voice History ──────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/voice-history")
async def guild_voice_history(request: Request, guild_id: str, limit: int = 50):
    """Get recent voice session history across all users in a guild."""
    from sqlalchemy import select, desc
    from database.models.voice import VoiceSession

    gid = int(guild_id)
    bot = request.state.bot
    guild = bot.get_guild(gid)

    async with session_scope() as session:
        result = await session.execute(
            select(VoiceSession)
            .where(VoiceSession.guild_id == str(gid))
            .order_by(desc(VoiceSession.joined_at))
            .limit(limit)
        )
        sessions = result.scalars().all()

        enriched = []
        for s in sessions:
            # Resolve username from guild cache
            username = s.user_id
            user_tag = s.user_tag or s.user_id
            if guild:
                member = guild.get_member(int(s.user_id))
                if member:
                    username = member.display_name
                    user_tag = str(member)

            # Resolve channel name (guild may have renamed it since the session)
            channel_name = s.channel_name
            if guild:
                ch = guild.get_channel(int(s.channel_id)) if s.channel_id else None
                if ch:
                    channel_name = ch.name

            enriched.append({
                "id": s.id,
                "user_id": s.user_id,
                "username": username,
                "user_tag": user_tag,
                "channel_id": s.channel_id,
                "channel_name": channel_name or s.channel_name or "Unknown",
                "channel_original_name": s.channel_name or "",
                "joined_at": s.joined_at.isoformat() if s.joined_at else None,
                "left_at": s.left_at.isoformat() if s.left_at else None,
                "duration_seconds": s.duration_seconds,
            })

        return api_success({
            "sessions": enriched,
        })


# ── Admin Purge ─────────────────────────────────────────


@router.delete("/guilds/{guild_id}/moderation/voice-history")
async def purge_voice_history(request: Request, guild_id: str):
    """Admin-only: permanently delete all voice sessions for a guild."""
    from services.response import api_forbidden, check_api_permission
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Admin only")
    from sqlalchemy import delete
    from database.models.voice import VoiceSession
    gid_str = str(guild_id)
    async with session_scope() as session:
        result = await session.execute(
            delete(VoiceSession).where(VoiceSession.guild_id == str(gid_str))
        )
        await session.commit()
        return api_success({"deleted": result.rowcount})


@router.delete("/guilds/{guild_id}/moderation/audit-logs")
async def purge_audit_logs(request: Request, guild_id: str):
    """Admin-only: permanently delete all audit logs for a guild."""
    from services.response import api_forbidden, check_api_permission
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Admin only")
    from sqlalchemy import delete
    from database.models.moderation import AuditLog
    gid_str = str(guild_id)
    async with session_scope() as session:
        result = await session.execute(
            delete(AuditLog).where(AuditLog.guild_id == str(gid_str))
        )
        await session.commit()
        return api_success({"deleted": result.rowcount})


@router.delete("/guilds/{guild_id}/moderation/attachments")
async def purge_attachments(request: Request, guild_id: str):
    """Admin-only: permanently delete all file attachment records for a guild."""
    from services.response import api_forbidden, check_api_permission
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Admin only")
    from sqlalchemy import delete
    from database.models.attachments import FileAttachment
    gid_str = str(guild_id)
    async with session_scope() as session:
        result = await session.execute(
            delete(FileAttachment).where(FileAttachment.guild_id == str(gid_str))
        )
        await session.commit()
        return api_success({"deleted": result.rowcount})
