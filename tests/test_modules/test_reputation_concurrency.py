"""Concurrency + caching tests for the reputation module's hot path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.reputation import ReputationProfile
from modules.reputation.module import ReputationModule
from services.event_bus import EventBus


class _FakeCtx:
    def __init__(self) -> None:
        self.events = EventBus()
        self.bot = SimpleNamespace(user=SimpleNamespace(id="1", name="bark"))
        self.config = {}

    async def get_module_config(self, name, guild_id):
        return self.config

    async def save_module_config(self, name, guild_id, cfg):
        self.config = cfg

    def get_guild(self, guild_id):
        return None

    def get_member(self, guild_id, user_id):
        return None


@pytest.mark.asyncio
async def test_concurrent_add_points_do_not_lose_updates(db):
    """Two concurrent awards for the same user must serialize (per-user lock),
    so total_score reflects BOTH awards — not one lost update."""
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test"))
        await session.commit()

    ctx = _FakeCtx()
    ctx.config = {"level_constant": 50.0, "decay_rate": 0.05}
    module = ReputationModule(ctx)  # type: ignore[arg-type]
    module._send_showoff = AsyncMock()  # no Discord channel needed
    module._check_rewards = AsyncMock(return_value=[])

    await asyncio.gather(
        module._add_points(1, 100, 10.0, "message"),
        module._add_points(1, 100, 10.0, "message"),
        module._add_points(1, 100, 10.0, "reaction"),
    )

    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    select(ReputationProfile).where(
                        ReputationProfile.guild_id == "1",
                        ReputationProfile.user_id == "100",
                    )
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.total_score == pytest.approx(30.0), "all three awards must be counted"


@pytest.mark.asyncio
async def test_reaction_author_cache_lru(db):
    ctx = _FakeCtx()
    module = ReputationModule(ctx)  # type: ignore[arg-type]

    assert module._cached_message_author(123) is None
    module._cache_message_author(123, 456)
    assert module._cached_message_author(123) == 456

    # Bounded: inserting past the cap evicts oldest entries.
    for i in range(module._reaction_author_cache_max + 10):
        module._cache_message_author(10_000 + i, i)
    assert module._cached_message_author(123) is None  # evicted
    assert module._cached_message_author(10_000 + module._reaction_author_cache_max) is not None
