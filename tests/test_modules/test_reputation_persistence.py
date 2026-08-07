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


@pytest.mark.asyncio
async def test_second_emoji_on_same_message_awards_points(db):
    """Two different emojis on one message by the same reactor are distinct
    events: both must award points instead of one silently losing to the
    unique (guild, event_type, actor, message) constraint."""
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    module = ReputationModule(MagicMock())
    config = {"caps": {}, "level_constant": 50}
    await module._add_points(
        1, 200, 2.0, "reaction", actor_id=100, target_id=200, message_id=999,
        emoji="👍", config=config,
    )
    await module._add_points(
        1, 200, 2.0, "reaction", actor_id=100, target_id=200, message_id=999,
        emoji="❤️", config=config,
    )

    async with session_scope() as session:
        events = (
            (
                await session.execute(
                    select(ReputationEvent).where(
                        ReputationEvent.guild_id == "1",
                        ReputationEvent.target_id == "200",
                        ReputationEvent.event_type == "reaction",
                    )
                )
            )
            .scalars()
            .all()
        )
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "200",
                )
            )
        ).scalar_one()

    assert len(events) == 2
    assert {event.emoji for event in events} == {"👍", "❤️"}
    assert profile.total_score == 4.0


@pytest.mark.asyncio
async def test_duplicate_reaction_event_is_ignored_not_crash(db):
    """A redelivered/duplicate reaction (same emoji, same message) must not
    raise IntegrityError or double-award — it is treated as already recorded."""
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    module = ReputationModule(MagicMock())
    config = {"caps": {}, "level_constant": 50}
    result1 = await module._add_points(
        1, 200, 2.0, "reaction", actor_id=100, target_id=200, message_id=999,
        emoji="👍", config=config,
    )
    result2 = await module._add_points(
        1, 200, 2.0, "reaction", actor_id=100, target_id=200, message_id=999,
        emoji="👍", config=config,
    )

    async with session_scope() as session:
        events = (
            (
                await session.execute(
                    select(ReputationEvent).where(
                        ReputationEvent.guild_id == "1",
                        ReputationEvent.event_type == "reaction",
                        ReputationEvent.actor_id == "100",
                    )
                )
            )
            .scalars()
            .all()
        )
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "200",
                )
            )
        ).scalar_one()

    assert result1 is not None
    assert result2 is None  # duplicate ignored
    assert len(events) == 1
    assert profile.total_score == 2.0  # awarded exactly once


@pytest.mark.asyncio
async def test_thanks_cooldown_claimed_before_award(db):
    """The /thanks cooldown must be written BEFORE the award awaits so a
    double-click cannot pass the check twice and double-award."""
    import modules.reputation.module as reputation_module

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.commit()

    ctx = MagicMock()
    ctx.guilds = []
    module = ReputationModule(ctx)
    module.load_dashboard_config = AsyncMock(return_value={"caps": {}, "level_constant": 50})
    module._send_showoff_text = AsyncMock()

    cooldown_claimed_at_call = []
    original_add_points = module._add_points

    async def recording_add_points(*args, **kwargs):
        # Record whether the cooldown was already claimed when the first
        # award starts. If the fix regresses (claim-after-award), this is
        # 0 and the second invocation would also pass the check.
        cooldown_claimed_at_call.append(
            (42, 99) in module._thanks_cooldowns
        )
        return await original_add_points(*args, **kwargs)

    module._add_points = recording_add_points

    cmd = module._make_thanks_command()
    # discord.app_commands.command returns a Command wrapper; the decorated
    # function lives on .callback.
    thanks_fn = getattr(cmd, "callback", cmd)
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        user=SimpleNamespace(id=42, mention="<@42>", display_name="Actor"),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            defer=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    member = SimpleNamespace(id=99, bot=False, mention="<@99>", display_name="Target")

    # Freeze time so the cooldown check passes and stays frozen for the
    # second (must-be-blocked) invocation too.
    frozen = [1_700_000_000.0]
    original_time = reputation_module.time.time
    reputation_module.time.time = lambda: frozen[0]

    try:
        await thanks_fn(interaction, member, "great work")
        # A second immediate invocation must be blocked by the cooldown.
        await thanks_fn(interaction, member, "again")
    finally:
        reputation_module.time.time = original_time

    # First award: cooldown must already be claimed.
    assert cooldown_claimed_at_call[0] is True
    # After completion the cooldown is set for both pair and self.
    assert module._thanks_cooldowns.get((42, 99)) == frozen[0]
    assert module._thanks_self_cooldowns.get(42) == frozen[0]

    # The second invocation was rejected at the cooldown check.
    assert interaction.response.send_message.await_count == 1
    send_args = interaction.response.send_message.await_args.args[0]
    assert "again in" in send_args
