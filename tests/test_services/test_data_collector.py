"""Guild analytics collection regression tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.analytics import ActivitySnapshot
from database.models.guild import Guild
from services.data_collector import GuildDataCollector


@pytest.mark.asyncio
async def test_collector_counts_members_added_since_existing_daily_snapshot(db, monkeypatch):
    today = datetime.now(timezone.utc).date()
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Guild"))
        await session.flush()
        session.add(
            ActivitySnapshot(
                guild_id="1",
                snapshot_date=today,
                total_members=10,
                new_members=0,
            )
        )
        await session.commit()

    guild = SimpleNamespace(id=1, name="Guild")
    collector = GuildDataCollector(SimpleNamespace(guilds=[guild]), interval_minutes=5)
    snapshot = {
        "member_count": 12,
        "channels": {"total_channels": 3},
    }
    monkeypatch.setattr(
        "services.data_collector.collect_full_guild_snapshot",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        "services.data_collector.asyncio.sleep",
        AsyncMock(side_effect=__import__("asyncio").CancelledError),
    )

    await collector._run_loop()

    async with session_scope() as session:
        saved = (
            await session.execute(
                select(ActivitySnapshot).where(
                    ActivitySnapshot.guild_id == "1",
                    ActivitySnapshot.snapshot_date == today,
                )
            )
        ).scalar_one()
    assert saved.total_members == 12
    assert saved.new_members == 2


@pytest.mark.asyncio
async def test_collector_skips_fresh_baseline_while_cache_warming(db, monkeypatch):
    """A fresh-day baseline must not be written from a warming member cache —
    the next full-cache tick would count the warm-up difference as new members
    (growth inflation after every restart)."""
    async with session_scope() as session:
        session.add(Guild(discord_id="2", name="Guild"))
        await session.commit()

    guild = SimpleNamespace(id=2, name="Guild", chunked=False)
    collector = GuildDataCollector(SimpleNamespace(guilds=[guild]), interval_minutes=5)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "services.data_collector.collect_full_guild_snapshot",
        AsyncMock(return_value={"member_count": 500, "channels": {"total_channels": 5}}),
    )
    monkeypatch.setattr(
        "services.data_collector.asyncio.sleep",
        AsyncMock(side_effect=__import__("asyncio").CancelledError),
    )
    await collector._run_loop()

    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ActivitySnapshot).where(ActivitySnapshot.guild_id == "2")
            )
        ).scalars().all()
    assert rows == [], "no baseline while chunked=False"

    # Once the cache is complete, the baseline is written (new_members=0).
    guild.chunked = True
    await collector._run_loop()
    async with session_scope() as session:
        saved = (
            await session.execute(
                select(ActivitySnapshot).where(ActivitySnapshot.guild_id == "2")
            )
        ).scalar_one()
    assert saved.total_members == 500
    assert saved.new_members == 0


@pytest.mark.asyncio
async def test_collector_persists_channel_and_emoji_breakdown(db, monkeypatch):
    """The collector writes today's live channel/emoji message counts into the
    daily ActivitySnapshot so the Statistics page survives a bot restart."""
    today = datetime.now(timezone.utc).date()
    async with session_scope() as session:
        session.add(Guild(discord_id="3", name="Guild"))
        await session.commit()

    guild = SimpleNamespace(id=3, name="Guild", chunked=True)
    collector = GuildDataCollector(SimpleNamespace(guilds=[guild]), interval_minutes=5)
    monkeypatch.setattr(
        "services.data_collector.collect_full_guild_snapshot",
        AsyncMock(return_value={"member_count": 20, "channels": {"total_channels": 4}}),
    )
    monkeypatch.setattr(
        "services.data_collector.asyncio.sleep",
        AsyncMock(side_effect=__import__("asyncio").CancelledError),
    )
    collector.bot.message_stats = lambda _gid: {
        "messages": 9,
        "channels": {"100": {"name": "general", "count": 6}, "200": {"name": "memes", "count": 3}},
        "emojis": {"laugh": 5},
        "emoji_total": {"laugh": 5, "wow": 2},
    }

    await collector._run_loop()

    async with session_scope() as session:
        saved = (
            await session.execute(
                select(ActivitySnapshot).where(
                    ActivitySnapshot.guild_id == "3",
                    ActivitySnapshot.snapshot_date == today,
                )
            )
        ).scalar_one()
    import json

    assert saved.total_messages == 9
    assert saved.total_reactions == 5
    assert saved.channels_active == 2
    channels = json.loads(saved.channel_messages)
    assert channels["100"] == {"name": "general", "count": 6}
    assert channels["200"] == {"name": "memes", "count": 3}
    assert json.loads(saved.emoji_counts) == {"laugh": 5, "wow": 2}
