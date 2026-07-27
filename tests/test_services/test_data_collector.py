import asyncio

import pytest

from services.data_collector import GuildDataCollector


@pytest.mark.asyncio
async def test_data_collector_start_is_idempotent_and_stop_awaits_task():
    bot = type("Bot", (), {"guilds": []})()
    collector = GuildDataCollector(bot, interval_minutes=15)

    await collector.start()
    first_task = collector._task
    try:
        await collector.start()
        assert collector._task is first_task
    finally:
        await collector.stop()
        if first_task and not first_task.done():
            first_task.cancel()
            await asyncio.gather(first_task, return_exceptions=True)

    assert collector._task is None
    assert first_task is not None and first_task.cancelled()
