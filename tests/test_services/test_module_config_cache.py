"""Tests for the central module-config cache in BarkContext."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from database.engine import session_scope
from database.models.guild import Guild
from database.models.module import ModuleConfig
from services.bark_context import BarkContext
from services.event_bus import EventBus


@pytest.fixture
def ctx(db) -> BarkContext:
    return BarkContext(MagicMock(), EventBus())


@pytest.mark.asyncio
async def test_get_module_config_caches_within_ttl(ctx):
    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test"))
        session.add(
            ModuleConfig(
                guild_id="1", module_name="moderation", enabled=True, config='{"spam": {"enabled": true}}'
            )
        )
        await session.commit()

    first = await ctx.get_module_config("moderation", 1)
    assert first == {"spam": {"enabled": True}}

    # Update the row directly (bypassing save) — cache must still serve old value.
    async with session_scope() as session:
        row = (
            await session.execute(
                __import__("sqlalchemy").select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1", ModuleConfig.module_name == "moderation"
                )
            )
        ).scalar_one()
        row.config = '{"spam": {"enabled": false}}'
        await session.commit()

    second = await ctx.get_module_config("moderation", 1)
    assert second == {"spam": {"enabled": True}}, "cache should serve the TTL'd value"

    # Save invalidates the cache immediately.
    await ctx.save_module_config("moderation", 1, {"spam": {"enabled": False}})
    third = await ctx.get_module_config("moderation", 1)
    assert third == {"spam": {"enabled": False}}


@pytest.mark.asyncio
async def test_get_module_config_returns_copy_not_cache_handle(ctx):
    async with session_scope() as session:
        session.add(Guild(discord_id="2", name="Test2"))
        session.add(
            ModuleConfig(
                guild_id="2", module_name="reputation", enabled=True, config='{"level_constant": 50}'
            )
        )
        await session.commit()

    # Cache-miss path returns a defensive copy.
    value = await ctx.get_module_config("reputation", 2)
    value["level_constant"] = 999  # caller mutates the returned dict
    again = await ctx.get_module_config("reputation", 2)
    assert again["level_constant"] == 50, "caller mutation must not corrupt the cache"

    # Cache-hit path (within TTL) must also return a copy, not the cached handle.
    again["level_constant"] = 12345
    third = await ctx.get_module_config("reputation", 2)
    assert third["level_constant"] == 50, "cache-hit mutation must not corrupt the cache"
