"""Tests for the `/bark stats` server-activity aggregation service.

Verifies each aggregation query reads the right guild-scoped rows from the
analytics / reputation / voice tables and degrades gracefully to empty results
when there is no data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database.engine import session_scope
from services import server_stats


async def _seed_guild(session, guild_id="1"):
    from database.models.guild import Guild

    session.add(Guild(discord_id=guild_id, name="War Lab"))
    await session.flush()


async def _seed_analytics(guild_id="1"):
    from database.models.analytics import DailyChannelStat, VoiceGameStat

    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        await _seed_guild(session, guild_id)
        await _seed_guild(session, "2")
        session.add(
            DailyChannelStat(
                guild_id=str(guild_id), stat_date=now.date(), channel_id="c1",
                channel_name="general", message_count=50,
            )
        )
        session.add(
            DailyChannelStat(
                guild_id=str(guild_id), stat_date=now.date(), channel_id="c2",
                channel_name="memes", message_count=30,
            )
        )
        session.add(
            DailyChannelStat(
                guild_id="2", stat_date=now.date(), channel_id="x1",
                channel_name="other", message_count=9999,
            )
        )
        session.add(
            VoiceGameStat(
                guild_id=str(guild_id), game_name="Minecraft", recorded_at=now,
            )
        )
        session.add(
            VoiceGameStat(
                guild_id=str(guild_id), game_name="Minecraft", recorded_at=now,
            )
        )
        session.add(
            VoiceGameStat(
                guild_id=str(guild_id), game_name="Valorant", recorded_at=now,
            )
        )
        await session.commit()


async def _seed_reputation(guild_id="1"):
    from database.models.reputation import ReputationEvent, ReputationProfile

    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        await _seed_guild(session, guild_id)
        session.add(
            ReputationProfile(
                guild_id=str(guild_id), user_id="u1", total_score=100.0, level=5,
                week_start=now.date(), month_start=now.date(),
            )
        )
        session.add(
            ReputationProfile(
                guild_id=str(guild_id), user_id="u2", total_score=75.0, level=3,
                week_start=now.date(), month_start=now.date(),
            )
        )
        # Rep source: thanks dominates in the window.
        session.add(
            ReputationEvent(
                guild_id=str(guild_id), actor_id="a1", event_type="message", points=10,
                created_at=now,
            )
        )
        session.add(
            ReputationEvent(
                guild_id=str(guild_id), actor_id="a1", event_type="thanks", points=40,
                created_at=now,
            )
        )
        await session.commit()


async def _seed_voice(guild_id="1"):
    from database.models.voice import VoiceSession

    now = datetime.now(timezone.utc)
    day = now.date()
    async with session_scope() as session:
        await _seed_guild(session, guild_id)
        session.add(
            VoiceSession(
                guild_id=str(guild_id), user_id="u1", user_tag="Alice",
                channel_id="vc1", channel_name="hangout",
                joined_at=now - timedelta(days=1, hours=1),
                left_at=now - timedelta(days=1),
                duration_seconds=3600,
            )
        )
        session.add(
            VoiceSession(
                guild_id=str(guild_id), user_id="u2", user_tag="Bob",
                channel_id="vc1", channel_name="hangout",
                joined_at=now, left_at=now,
                duration_seconds=600,
            )
        )
        # Two sessions on one day (for avg/max-per-day).
        session.add(
            VoiceSession(
                guild_id=str(guild_id), user_id="u1", user_tag="Alice",
                channel_id="vc2", channel_name="afk",
                joined_at=now - timedelta(days=1, hours=2),
                left_at=now - timedelta(days=1, hours=1),
                duration_seconds=300,
            )
        )
        await session.commit()
        return day


@pytest.mark.asyncio
async def test_top_channel_30d_returns_top_channels_guild_scoped(db):
    await _seed_analytics()
    result = await server_stats.top_channel_30d(1)
    assert [c["name"] for c in result] == ["general", "memes"]
    assert result[0]["count"] == 50
    # Other-guild channel (9999 msgs) must not leak in.
    assert all(c["count"] < 9999 for c in result)


@pytest.mark.asyncio
async def test_top_game_month_counts_and_guild_scopes(db):
    await _seed_analytics()
    result = await server_stats.top_game_month(1)
    assert result[0] == {"name": "Minecraft", "count": 2}
    assert result[1] == {"name": "Valorant", "count": 1}


@pytest.mark.asyncio
async def test_top_reputation_sorted_by_score(db):
    await _seed_reputation()
    result = await server_stats.top_reputation(1)
    assert result[0]["user_id"] == "u1"
    assert result[0]["score"] == 100.0
    assert result[1]["user_id"] == "u2"


@pytest.mark.asyncio
async def test_top_voice_30d_by_duration(db):
    await _seed_voice()
    result = await server_stats.top_voice_30d(1)
    # Alice has 3600 + 300s = 65 min; Bob 600s = 10 min.
    assert result[0]["user_id"] == "u1"
    assert result[0]["minutes"] == 65.0
    assert result[1]["user_id"] == "u2"
    assert result[1]["minutes"] == 10.0


@pytest.mark.asyncio
async def test_voice_session_summary_avg_and_max(db):
    day = await _seed_voice()
    result = await server_stats.voice_session_summary(1)
    assert result["max_per_day"] == 2  # Alice had 2 sessions on day-1
    assert result["avg_per_day"] > 0
    assert result["days"] > 0


@pytest.mark.asyncio
async def test_top_rep_source_picks_dominant_source(db):
    await _seed_reputation()
    result = await server_stats.top_rep_source(1)
    assert result["source"] == "thanks"
    assert result["points"] == 40.0


@pytest.mark.asyncio
async def test_empty_guild_degrades_gracefully(db):
    """A guild with no data yields empty/zero results, never raises."""
    result = await server_stats.top_channel_30d(999)
    assert result == []
    result = await server_stats.top_game_month(999)
    assert result == []
    result = await server_stats.top_reputation(999)
    assert result == []
    result = await server_stats.top_voice_30d(999)
    assert result == []
    result = await server_stats.voice_session_summary(999)
    assert result == {"avg_per_day": 0, "max_per_day": 0, "days": 0}
    result = await server_stats.top_rep_source(999)
    assert result == {"source": "none", "points": 0}
