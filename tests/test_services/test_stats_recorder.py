"""Regression tests for the DB-backed message/emoji stats recorder.

Every non-bot message/reaction must land in the daily stats tables so the
Statistics page reads entirely from the database (source of truth). Writes are
COALESCED in memory and flushed in batch (``flush_stats`` / background task) —
tests flush explicitly to observe the persisted rows.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import services.stats_recorder as stats_recorder
from database.engine import session_scope
from database.models.analytics import DailyChannelStat, DailyEmojiStat
from database.models.guild import Guild
from services.stats_recorder import (
    _pending_emoji,
    _pending_messages,
    flush_stats,
    record_message,
    record_reaction,
)


@pytest.fixture(autouse=True)
async def _clean_pending_counters():
    """Isolate module-level pending counters + flush task between tests."""
    _pending_messages.clear()
    _pending_emoji.clear()
    yield
    _pending_messages.clear()
    _pending_emoji.clear()
    task = stats_recorder._flush_task
    stats_recorder._flush_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_record_message_upserts_today_channel_count(db):
    async with session_scope() as s:
        s.add(Guild(discord_id="11", name="Guild"))
        await s.commit()

    ch = SimpleNamespace(id=100, name="general")
    await record_message(11, ch)
    await record_message(11, ch)
    await record_message(11, SimpleNamespace(id=200, name="memes"))
    await flush_stats()

    async with session_scope() as s:
        rows = (
            await s.execute(
                select(DailyChannelStat).where(DailyChannelStat.guild_id == "11")
            )
        ).scalars().all()
    by_channel = {r.channel_id: r for r in rows}
    assert by_channel["100"].message_count == 2
    assert by_channel["100"].channel_name == "general"
    assert by_channel["200"].message_count == 1
    assert len(rows) == 2, "one row per (guild, day, channel)"


@pytest.mark.asyncio
async def test_record_reaction_upserts_today_emoji_count(db):
    async with session_scope() as s:
        s.add(Guild(discord_id="12", name="Guild"))
        await s.commit()

    await record_reaction(12, "laugh")
    await record_reaction(12, "laugh")
    await record_reaction(12, "wow")
    await flush_stats()

    async with session_scope() as s:
        rows = (
            await s.execute(
                select(DailyEmojiStat).where(DailyEmojiStat.guild_id == "12")
            )
        ).scalars().all()
    by_emoji = {r.emoji_name: r for r in rows}
    assert by_emoji["laugh"].count == 2
    assert by_emoji["wow"].count == 1
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_coalesced_counters_are_not_written_before_flush(db):
    """The hot path only bumps counters — no DB write happens per message."""
    async with session_scope() as s:
        s.add(Guild(discord_id="14", name="Guild"))
        await s.commit()

    await record_message(14, SimpleNamespace(id=300, name="general"))

    async with session_scope() as s:
        rows = (
            await s.execute(
                select(DailyChannelStat).where(DailyChannelStat.guild_id == "14")
            )
        ).scalars().all()
    assert rows == [], "no DB write should happen before flush_stats()"
    await flush_stats()

    async with session_scope() as s:
        rows = (
            await s.execute(
                select(DailyChannelStat).where(DailyChannelStat.guild_id == "14")
            )
        ).scalars().all()
    assert len(rows) == 1 and rows[0].message_count == 1


@pytest.mark.asyncio
async def test_flush_failure_requeues_counters(db, monkeypatch):
    """A failed batch flush must not drop activity — counters return to the
    pending pool and a later flush writes them."""
    from database.models.analytics import DailyChannelStat as ChannelStat

    async with session_scope() as s:
        s.add(Guild(discord_id="15", name="Guild"))
        await s.commit()

    await record_message(15, SimpleNamespace(id=400, name="general"))
    await record_message(15, SimpleNamespace(id=400, name="general"))

    class BoomError(Exception):
        pass

    def failing_commit(self):
        raise BoomError("db down")

    monkeypatch.setattr("sqlalchemy.ext.asyncio.AsyncSession.commit", failing_commit)
    await flush_stats()  # fails internally, requeues
    assert _pending_messages[("15", "400")][0] == 2, "counters requeued after failure"

    monkeypatch.undo()
    await flush_stats()
    async with session_scope() as s:
        row = (
            await s.execute(
                select(ChannelStat).where(
                    ChannelStat.guild_id == "15", ChannelStat.channel_id == "400"
                )
            )
        ).scalar_one()
    assert row.message_count == 2


@pytest.mark.asyncio
async def test_record_message_never_raises_on_unknown_channel(db):
    # A stats write must never break message processing, even if the channel
    # object lacks expected attributes.
    async with session_scope() as s:
        s.add(Guild(discord_id="13", name="Guild"))
        await s.commit()

    await record_message(13, None)  # should not raise


@pytest.mark.asyncio
async def test_recorder_uses_utc_today():
    """Rows are keyed on UTC today so the daily window matches the rest of the
    analytics pipeline regardless of the host timezone."""
    expected = datetime.now(timezone.utc).date()
    assert stats_recorder._today_aware() == expected
