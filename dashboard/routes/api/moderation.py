"""
Moderation API routes.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.engine import session_scope, get_session
from database.models.moderation import ModerationCase, Warning, UserNote, AuditLog

router = APIRouter(tags=["api-moderation"])


# ── Cases ────────────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/cases")
async def list_cases(request: Request, guild_id: int):
    """List moderation cases for a guild."""
    from sqlalchemy import select, desc

    async with session_scope() as session:
        result = await session.execute(
            select(ModerationCase)
            .where(ModerationCase.guild_id == guild_id)
            .order_by(desc(ModerationCase.created_at))
            .limit(100)
        )
        cases = result.scalars().all()

        return {
            "cases": [
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
            ]
        }


@router.get("/guilds/{guild_id}/moderation/cases/{case_number}")
async def get_case(request: Request, guild_id: int, case_number: int):
    """Get a specific case."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(ModerationCase).where(
                ModerationCase.guild_id == guild_id,
                ModerationCase.case_number == case_number,
            )
        )
        case = result.scalar_one_or_none()
        if case is None:
            return JSONResponse({"error": "Case not found"}, status_code=404)

        return {
            "case_number": case.case_number,
            "action_type": case.action_type,
            "target_id": case.target_id,
            "target_tag": case.target_tag,
            "moderator_id": case.moderator_id,
            "moderator_tag": case.moderator_tag,
            "reason": case.reason,
            "duration": case.duration,
            "created_at": case.created_at.isoformat(),
            "resolved": case.resolved,
            "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        }


@router.post("/guilds/{guild_id}/moderation/cases")
async def create_case(request: Request, guild_id: int):
    """Create a new moderation case."""
    data = await request.json()

    from sqlalchemy import select, func

    async with session_scope() as session:
        # Get next case number
        result = await session.execute(
            select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
            .where(ModerationCase.guild_id == guild_id)
        )
        next_number = result.scalar()

        case = ModerationCase(
            guild_id=guild_id,
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

        return {
            "success": True,
            "case_number": case.case_number,
            "id": case.id,
        }


# ── Warnings ─────────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/warnings")
async def list_warnings(request: Request, guild_id: int):
    """List all active warnings for a guild."""
    from sqlalchemy import select, desc

    async with session_scope() as session:
        result = await session.execute(
            select(Warning)
            .where(Warning.guild_id == guild_id)
            .order_by(desc(Warning.created_at))
            .limit(100)
        )
        warnings = result.scalars().all()

        return {
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
        }


@router.get("/guilds/{guild_id}/moderation/warnings/{user_id}")
async def get_user_warnings(request: Request, guild_id: int, user_id: str):
    """List warnings for a specific user."""
    from sqlalchemy import select, desc

    async with session_scope() as session:
        result = await session.execute(
            select(Warning)
            .where(
                Warning.guild_id == guild_id,
                Warning.user_id == user_id,
            )
            .order_by(desc(Warning.created_at))
        )
        warnings = result.scalars().all()

        return {
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
        }


# ── Notes ────────────────────────────────────────────


@router.get("/guilds/{guild_id}/moderation/notes")
async def list_notes(request: Request, guild_id: int):
    """List user notes for a guild."""
    from sqlalchemy import select, desc

    async with session_scope() as session:
        result = await session.execute(
            select(UserNote)
            .where(UserNote.guild_id == guild_id)
            .order_by(desc(UserNote.created_at))
            .limit(100)
        )
        notes = result.scalars().all()

        return {
            "notes": [
                {
                    "id": n.id,
                    "user_id": n.user_id,
                    "author_id": n.author_id,
                    "content": n.content,
                    "created_at": n.created_at.isoformat(),
                }
                for n in notes
            ]
        }


@router.post("/guilds/{guild_id}/moderation/notes")
async def create_note(request: Request, guild_id: int):
    """Create a user note."""
    data = await request.json()

    async with session_scope() as session:
        note = UserNote(
            guild_id=guild_id,
            user_id=data.get("user_id", ""),
            author_id=data.get("author_id", ""),
            content=data.get("content", ""),
        )
        session.add(note)
        await session.commit()

        return {"success": True, "id": note.id}
