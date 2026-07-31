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
