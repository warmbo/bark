"""Reputation persistence and cap regression tests."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.reputation import ReputationEvent, ReputationProfile
from modules.reputation.module import ReputationModule


@pytest.mark.asyncio
async def test_daily_and_weekly_caps_limit_accumulated_awards(db):
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    module = ReputationModule(MagicMock())
    config = {
        "caps": {"daily": 10, "weekly": 12},
        "level_constant": 50,
    }
    await module._add_points(1, 42, 8, "message", actor_id=42, config=config)
    await module._add_points(1, 42, 8, "message", actor_id=42, config=config)

    async with session_scope() as session:
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "42",
                )
            )
        ).scalar_one()
        events = (
            (
                await session.execute(
                    select(ReputationEvent).where(
                        ReputationEvent.guild_id == "1",
                        ReputationEvent.target_id == "42",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert profile.total_score == 10
    assert profile.weekly_score == 10
    assert [event.points for event in events] == [8, 2]


@pytest.mark.asyncio
async def test_voice_awards_update_profile_voice_minutes(db):
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    module = ReputationModule(MagicMock())
    await module._add_points(
        1,
        42,
        2.5,
        "voice_minute",
        actor_id=42,
        metadata={"minutes": 5},
        config={},
    )

    async with session_scope() as session:
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "42",
                )
            )
        ).scalar_one()
    assert profile.voice_minutes == 5
