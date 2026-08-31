"""Server activity stats aggregation for the `/bark stats` command.

Reads entirely from the analytics / reputation / voice tables that the bot
already maintains, so the command never mutates state and works immediately on
any guild that has been running the bot. Every query is guild-scoped and
degraded gracefully: an absent table or empty result yields ``None``/``[]``
rather than raising, so the embed can render a friendly "no data yet" instead
of erroring.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from database.engine import session_scope


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def top_channel_30d(guild_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Most active text channels over the last 30 days (by message count)."""
    from database.models.analytics import DailyChannelStat

    since = _utc_now().date() - timedelta(days=30)
    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        DailyChannelStat.channel_name,
                        func.sum(DailyChannelStat.message_count).label("total"),
                    )
                    .where(
                        DailyChannelStat.guild_id == str(guild_id),
                        DailyChannelStat.stat_date >= since,
                    )
                    .group_by(DailyChannelStat.channel_id, DailyChannelStat.channel_name)
                    .order_by(func.sum(DailyChannelStat.message_count).desc())
                    .limit(limit)
                )
            ).all()
        return [
            {"name": r.channel_name or "unknown", "count": int(r.total or 0)} for r in rows
        ]
    except Exception:
        return []


async def top_game_month(guild_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Most-played games this calendar month (by recorded voice-game rows)."""
    from database.models.analytics import VoiceGameStat

    month_start = _utc_now().date().replace(day=1)
    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(VoiceGameStat.game_name, func.count(VoiceGameStat.id).label("total"))
                    .where(
                        VoiceGameStat.guild_id == str(guild_id),
                        VoiceGameStat.recorded_at >= month_start,
                    )
                    .group_by(VoiceGameStat.game_name)
                    .order_by(func.count(VoiceGameStat.id).desc())
                    .limit(limit)
                )
            ).all()
        return [{"name": r.game_name, "count": int(r.total or 0)} for r in rows]
    except Exception:
        return []


async def top_reputation(guild_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Members with the highest reputation total score."""
    from database.models.reputation import ReputationProfile

    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        ReputationProfile.user_id,
                        ReputationProfile.total_score,
                        ReputationProfile.level,
                    )
                    .where(ReputationProfile.guild_id == str(guild_id))
                    .order_by(ReputationProfile.total_score.desc())
                    .limit(limit)
                )
            ).all()
        return [
            {
                "user_id": r.user_id,
                "score": round(float(r.total_score or 0), 1),
                "level": int(r.level or 0),
            }
            for r in rows
        ]
    except Exception:
        return []


async def top_voice_30d(guild_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Members with the most voice time over the last 30 days (minutes)."""
    from database.models.voice import VoiceSession

    since = _utc_now() - timedelta(days=30)
    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        VoiceSession.user_id,
                        VoiceSession.user_tag,
                        func.coalesce(func.sum(VoiceSession.duration_seconds), 0).label("seconds"),
                    )
                    .where(
                        VoiceSession.guild_id == str(guild_id),
                        VoiceSession.left_at >= since,
                        VoiceSession.duration_seconds.isnot(None),
                    )
                    .group_by(VoiceSession.user_id, VoiceSession.user_tag)
                    .order_by(func.coalesce(func.sum(VoiceSession.duration_seconds), 0).desc())
                    .limit(limit)
                )
            ).all()
        return [
            {
                "user_id": r.user_id,
                "user_tag": r.user_tag or r.user_id,
                "minutes": round(int(r.seconds or 0) / 60, 1),
            }
            for r in rows
        ]
    except Exception:
        return []


async def voice_session_summary(guild_id: int) -> dict[str, Any]:
    """Average and max voice sessions per day over the last 30 days."""
    from database.models.voice import VoiceSession

    since = _utc_now().date() - timedelta(days=30)
    try:
        async with session_scope() as session:
            # Sessions per day.
            per_day = (
                await session.execute(
                    select(
                        func.date(VoiceSession.joined_at).label("day"),
                        func.count(VoiceSession.id).label("n"),
                    )
                    .where(
                        VoiceSession.guild_id == str(guild_id),
                        func.date(VoiceSession.joined_at) >= since,
                    )
                    .group_by(func.date(VoiceSession.joined_at))
                )
            ).all()
        counts = [int(r.n or 0) for r in per_day]
        if not counts:
            return {"avg_per_day": 0, "max_per_day": 0, "days": 0}
        return {
            "avg_per_day": round(sum(counts) / len(counts), 1),
            "max_per_day": max(counts),
            "days": len(counts),
        }
    except Exception:
        return {"avg_per_day": 0, "max_per_day": 0, "days": 0}


async def top_rep_source(guild_id: int) -> dict[str, Any]:
    """The reputation source that contributed the most points (30d)."""
    from database.models.reputation import ReputationEvent

    since = _utc_now() - timedelta(days=30)
    source_labels = {
        "message": "messages",
        "reaction": "reactions",
        "emoji": "reactions",
        "thanks": "thanks",
        "voice_minute": "voice",
    }
    try:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        ReputationEvent.event_type,
                        func.sum(ReputationEvent.points).label("points"),
                    )
                    .where(
                        ReputationEvent.guild_id == str(guild_id),
                        ReputationEvent.created_at >= since,
                    )
                    .group_by(ReputationEvent.event_type)
                    .order_by(func.sum(ReputationEvent.points).desc())
                )
            ).all()
        if not rows:
            return {"source": "none", "points": 0}
        top = rows[0]
        label = source_labels.get(top.event_type, top.event_type)
        return {"source": label, "points": round(float(top.points or 0), 1)}
    except Exception:
        return {"source": "none", "points": 0}
