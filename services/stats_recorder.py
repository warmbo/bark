"""Persist live message/emoji activity to the daily stats tables.

The Statistics page is DB-backed: every non-bot message and reaction upserts a
row into ``daily_channel_stats`` / ``daily_emoji_stats``. This keeps the
database the source of truth that builds knowledge about a server over time and
always has data — even immediately after a bot restart (no in-memory-only
counters to lose).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select

from database.engine import session_scope
from database.models.analytics import DailyChannelStat, DailyEmojiStat

logger = logging.getLogger("bark.services.stats_recorder")


def _today_aware() -> date:
    """Today in UTC — the DB stores UTC dates."""
    return datetime.now(timezone.utc).date()


async def record_message(guild_id: int, channel) -> None:
    """Upsert today's message count for a channel. Never raises — a stats write
    must not break message processing."""
    try:
        ch_id = str(getattr(channel, "id", "unknown"))
        name = str(getattr(channel, "name", None) or ch_id)
        today = _today_aware()
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(DailyChannelStat).where(
                        DailyChannelStat.guild_id == str(guild_id),
                        DailyChannelStat.stat_date == today,
                        DailyChannelStat.channel_id == ch_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyChannelStat(
                        guild_id=str(guild_id),
                        stat_date=today,
                        channel_id=ch_id,
                        channel_name=name,
                        message_count=1,
                    )
                )
            else:
                row.message_count += 1
                row.channel_name = name
    except Exception:
        logger.exception("Failed to persist message stat for guild %s", guild_id)


async def record_reaction(guild_id: int, emoji) -> None:
    """Upsert today's reaction count for an emoji. Never raises."""
    try:
        key = str(emoji)
        if getattr(emoji, "is_unicode_emoji", lambda: False)():
            key = emoji.name  # unicode: show the glyph name
        today = _today_aware()
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(DailyEmojiStat).where(
                        DailyEmojiStat.guild_id == str(guild_id),
                        DailyEmojiStat.stat_date == today,
                        DailyEmojiStat.emoji_name == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyEmojiStat(
                        guild_id=str(guild_id),
                        stat_date=today,
                        emoji_name=key,
                        count=1,
                    )
                )
            else:
                row.count += 1
    except Exception:
        logger.exception("Failed to persist emoji stat for guild %s", guild_id)

