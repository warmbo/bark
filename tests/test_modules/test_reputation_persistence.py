"""Reputation persistence and cap regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_voice_tick_does_not_restore_member_who_left_during_award():
    ctx = MagicMock()
    ctx.get_guild.return_value = MagicMock()
    module = ReputationModule(ctx)
    module._voice_activity[1][42] = 100.0
    module.load_dashboard_config = AsyncMock(
        return_value={
            "enabled_sources": {"voice": True},
            "weights": {"voice_minute": 1},
        }
    )

    async def leave_during_award(*_args, **_kwargs):
        module._voice_activity[1].pop(42)

    module._add_points = AsyncMock(side_effect=leave_during_award)

    await module._credit_voice_tick(now=1000.0)

    assert 42 not in module._voice_activity[1]


@pytest.mark.asyncio
async def test_voice_leave_during_tick_does_not_double_credit(monkeypatch):
    import modules.reputation.module as reputation_module

    ctx = MagicMock()
    ctx.get_guild.return_value = MagicMock()
    module = ReputationModule(ctx)
    module._voice_activity[1][42] = 100.0
    module.load_dashboard_config = AsyncMock(
        return_value={
            "enabled_sources": {"voice": True},
            "weights": {"voice_minute": 1},
        }
    )
    monkeypatch.setattr(reputation_module.time, "time", lambda: 1000.0)
    leave_award = AsyncMock()

    async def leave_during_award(*_args, **_kwargs):
        module._add_points = leave_award
        member = SimpleNamespace(id=42, bot=False, guild=SimpleNamespace(id=1))
        await module._on_voice_state("voice_state", member=member, after_channel=None)

    module._add_points = AsyncMock(side_effect=leave_during_award)

    await module._credit_voice_tick(now=1000.0)

    leave_award.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_tick_award_error_restores_timer_and_continues():
    """A transient award failure must not terminate the periodic voice worker."""
    module = ReputationModule(MagicMock())
    module._voice_activity[1][42] = 100.0
    module._voice_activity[1][43] = 100.0
    module.load_dashboard_config = AsyncMock(
        return_value={
            "enabled_sources": {"voice": True},
            "weights": {"voice_minute": 1},
        }
    )
    module._add_points = AsyncMock(side_effect=[RuntimeError("database unavailable"), None])

    await module._credit_voice_tick(now=1000.0)

    assert module._voice_activity[1][42] == 100.0
    assert module._voice_activity[1][43] == 1000.0
    assert module._add_points.await_count == 2
