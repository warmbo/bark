"""Persist live message/emoji activity to the daily stats tables.

The Statistics page is DB-backed: every non-bot message and reaction upserts a
row into ``daily_channel_stats`` / ``daily_emoji_stats``. This keeps the
database the source of truth that builds knowledge about a server over time and
always has data — even immediately after a bot restart (no in-memory-only
counters to lose).

Message/reaction writes are COALESCED: ``record_message``/``record_reaction``
only bump in-memory counters, and a single background task flushes them to the
DB in batch every ``FLUSH_SECONDS``. A per-message await on the hot ``on_message``
path would add a DB round-trip to Discord message processing and serialize
under burst load; batching keeps the same durability guarantee (at most
``FLUSH_SECONDS`` of counters are lost on a crash) at a fraction of the cost.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select

from database.engine import session_scope
from database.models.analytics import DailyChannelStat, DailyEmojiStat, VoiceGameStat

logger = logging.getLogger("bark.services.stats_recorder")

FLUSH_SECONDS = 30.0

# (guild_id, channel_id) -> [count, name]
_pending_messages: dict[tuple[str, str], list] = defaultdict(lambda: [0, ""])
# (guild_id, emoji_key) -> count
_pending_emoji: dict[tuple[str, str], int] = defaultdict(int)
_flush_task: asyncio.Task | None = None


def _today_aware() -> date:
    """Today in UTC — the DB stores UTC dates."""
    return datetime.now(timezone.utc).date()


async def _flush_pending() -> None:
    """Write pending counters to the DB. Never raises to callers."""
    if not _pending_messages and not _pending_emoji:
        return
    # Swap contents in place (never rebind the dicts — other modules import
    # these objects directly).
    messages = dict(_pending_messages)
    _pending_messages.clear()
    emoji = dict(_pending_emoji)
    _pending_emoji.clear()
    today = _today_aware()
    try:
        async with session_scope() as session:
            for (guild_id, ch_id), (count, name) in messages.items():
                guild = str(guild_id)
                row = (
                    await session.execute(
                        select(DailyChannelStat).where(
                            DailyChannelStat.guild_id == str(guild),
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
                            message_count=count,
                        )
                    )
                else:
                    row.message_count += count
                    row.channel_name = name
            for (guild_id, key), count in emoji.items():
                guild = str(guild_id)
                row = (
                    await session.execute(
                        select(DailyEmojiStat).where(
                            DailyEmojiStat.guild_id == str(guild),
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
                            count=count,
                        )
                    )
                else:
                    row.count += count
    except Exception:
        # Put the counters back so the next flush retries them rather than
        # silently dropping up to FLUSH_SECONDS of activity.
        for key, value in messages.items():
            _pending_messages[key][0] += value[0]
            _pending_messages[key][1] = value[1]
        for key, count in emoji.items():
            _pending_emoji[key] += count
        logger.exception("Failed to flush pending stats (will retry next cycle)")


def _ensure_flush_task() -> None:
    """Start the periodic flusher once, from inside the running loop."""
    global _flush_task
    if _flush_task is not None and not _flush_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop (e.g. import-time) — flush on next call instead

    async def _loop() -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            try:
                await _flush_pending()
            except Exception:
                logger.exception("Stats flush cycle failed")

    _flush_task = loop.create_task(_loop())


async def record_message(guild_id: int, channel) -> None:
    """Count a message for today's channel stats (flushed in batch). Never
    raises — a stats write must not break message processing."""
    try:
        ch_id = str(getattr(channel, "id", "unknown"))
        name = str(getattr(channel, "name", None) or ch_id)
        _pending_messages[(str(guild_id), ch_id)][0] += 1
        _pending_messages[(str(guild_id), ch_id)][1] = name
        _ensure_flush_task()
        # Opportunistic early flush keeps "just happened" activity visible
        # without waiting the full cycle on quiet servers.
        if sum(v[0] for v in _pending_messages.values()) >= 50 or len(_pending_messages) >= 50:
            await _flush_pending()
    except Exception:
        logger.exception("Failed to record message stat for guild %s", guild_id)


async def record_reaction(guild_id: int, emoji) -> None:
    """Count a reaction for today's emoji stats (flushed in batch). Never raises."""
    try:
        key = str(emoji)
        if getattr(emoji, "is_unicode_emoji", lambda: False)():
            key = emoji.name  # unicode: show the glyph name
        _pending_emoji[(str(guild_id), key)] += 1
        _ensure_flush_task()
    except Exception:
        logger.exception("Failed to record emoji stat for guild %s", guild_id)


async def flush_stats() -> None:
    """Public flush hook — used by tests and graceful shutdown."""
    await _flush_pending()


async def record_game(guild_id: int, game_name: str) -> None:
    """Record a detected game on a managed voice channel. Never raises.

    Called when a temporary voice channel is created (or renamed) with a
    detected activity so the Statistics page can show the most popular games.
    """
    try:
        name = str(game_name or "").strip()
        if not name:
            return
        async with session_scope() as session:
            session.add(
                VoiceGameStat(
                    guild_id=str(guild_id),
                    game_name=name[:120],
                    recorded_at=datetime.now(timezone.utc),
                )
            )
    except Exception:
        logger.exception("Failed to persist game stat for guild %s", guild_id)

