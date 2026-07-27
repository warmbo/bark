"""
ModerationService — business logic for all moderation operations.

This is the ONLY place moderation business logic lives.
API routes and slash commands both delegate here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, desc

from database.engine import session_scope
from database.models.moderation import ModerationCase, Warning, AuditLog
from database.models.voice import VoiceSession

logger = logging.getLogger("bark.services.moderation")


class ModerationService:
    """All moderation business logic consolidated here."""

    @staticmethod
    async def create_case(
        guild_id: int,
        action_type: str,
        target_id: str,
        target_tag: str,
        moderator_id: str,
        moderator_tag: str,
        reason: str,
        duration: int | None = None,
    ) -> int:
        """Create a moderation case and return case number."""
        async with session_scope() as session:
            result = await session.execute(
                select(func.coalesce(func.max(ModerationCase.case_number), 0) + 1)
                .where(ModerationCase.guild_id == str(guild_id))
            )
            case_number = result.scalar()
            case = ModerationCase(
                guild_id=str(guild_id), case_number=case_number,
                action_type=action_type,
                target_id=target_id, target_tag=target_tag,
                moderator_id=moderator_id, moderator_tag=moderator_tag,
                reason=reason, duration=duration,
            )
            session.add(case)
            await session.commit()
        return case_number

    @staticmethod
    async def add_warning(guild_id: int, user_id: str, moderator_id: str, reason: str) -> int:
        """Add a warning record."""
        async with session_scope() as session:
            w = Warning(guild_id=str(guild_id), user_id=user_id,
                        moderator_id=moderator_id, reason=reason, active=True)
            session.add(w)
            await session.commit()
            return w.id

    @staticmethod
    async def log_audit(
        guild_id: int, action: str,
        actor_id: str, actor_tag: str = "",
        target_id: str | None = None, target_tag: str = "",
        details: dict | None = None,
    ) -> None:
        """Create a structured audit log entry."""
        async with session_scope() as session:
            session.add(AuditLog(
                guild_id=str(guild_id), action=action,
                actor_id=actor_id,
                target_id=target_id,
                details=json.dumps({
                    "actor_tag": actor_tag,
                    "target_tag": target_tag,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **(details or {}),
                }),
            ))
            await session.commit()

    @staticmethod
    async def get_cases(guild_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
        """Get recent moderation cases."""
        async with session_scope() as session:
            result = await session.execute(
                select(ModerationCase)
                .where(ModerationCase.guild_id == str(guild_id))
                .order_by(desc(ModerationCase.created_at))
                .offset(offset).limit(limit)
            )
            return [{
                "case_number": c.case_number, "action_type": c.action_type,
                "target_id": c.target_id, "target_tag": c.target_tag,
                "moderator_id": c.moderator_id, "moderator_tag": c.moderator_tag,
                "reason": c.reason, "duration": c.duration,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            } for c in result.scalars().all()]

    @staticmethod
    async def get_warnings(guild_id: int, user_id: str | None = None) -> list[dict]:
        """Get active warnings, optionally filtered by user."""
        async with session_scope() as session:
            q = select(Warning).where(Warning.guild_id == str(guild_id), Warning.active == True)
            if user_id:
                q = q.where(Warning.user_id == user_id)
            q = q.order_by(desc(Warning.created_at))
            result = await session.execute(q)
            return [{
                "id": w.id, "user_id": w.user_id,
                "moderator_id": w.moderator_id, "reason": w.reason,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            } for w in result.scalars().all()]

    @staticmethod
    async def clear_warning(guild_id: int, warning_id: int) -> bool:
        """Deactivate a warning."""
        async with session_scope() as session:
            result = await session.execute(
                select(Warning).where(Warning.id == warning_id, Warning.guild_id == str(guild_id))
            )
            w = result.scalar_one_or_none()
            if not w:
                return False
            w.active = False
            await session.commit()
            return True

    @staticmethod
    async def get_voice_sessions(guild_id: int, user_id: str, limit: int = 20) -> list[dict]:
        """Get voice sessions for a user."""
        async with session_scope() as session:
            result = await session.execute(
                select(VoiceSession)
                .where(VoiceSession.guild_id == str(guild_id), VoiceSession.user_id == user_id)
                .order_by(desc(VoiceSession.joined_at)).limit(limit)
            )
            return [{
                "channel_name": s.channel_name,
                "joined_at": s.joined_at.isoformat() if s.joined_at else None,
                "left_at": s.left_at.isoformat() if s.left_at else None,
                "duration_seconds": s.duration_seconds,
            } for s in result.scalars().all()]
