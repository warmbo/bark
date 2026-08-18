"""Regression tests for the DB-backed message/emoji stats recorder.

Every non-bot message/reaction must upsert into the daily stats tables so the
Statistics page reads entirely from the database (source of truth) and always
has data — even right after a bot restart.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.analytics import DailyChannelStat, DailyEmojiStat
from database.models.guild import Guild
from services.stats_recorder import record_message, record_reaction


@pytest.mark.asyncio
async def test_record_message_upserts_today_channel_count(db):
    async with session_scope() as s:
        s.add(Guild(discord_id="11", name="Guild"))
        await s.commit()

    ch = SimpleNamespace(id=100, name="general")
    await record_message(11, ch)
    await record_message(11, ch)
    await record_message(11, SimpleNamespace(id=200, name="memes"))

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
    from services.stats_recorder import _today_aware

    expected = datetime.now(timezone.utc).date()
    assert _today_aware() == expected
