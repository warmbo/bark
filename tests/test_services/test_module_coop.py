"""Tests for the cross-module cooperation registry and GuildSettings service."""

import pytest

from services.guild_settings import get_setting, get_settings, set_setting
from services.module_coop import ModuleCoop


@pytest.mark.asyncio
async def test_coop_registry_returns_data_and_degrades_gracefully():
    coop = ModuleCoop()

    async def leaderboard(guild_id, **kw):
        return {"guild_id": guild_id, "top": ["alice", "bob"]}

    coop.register("reputation.leaderboard", leaderboard)
    assert coop.provides("reputation.leaderboard") is True
    assert "reputation.leaderboard" in coop.names()

    result = await coop.call("reputation.leaderboard", 42)
    assert result == {"guild_id": 42, "top": ["alice", "bob"]}

    # Unregistered provider -> None (graceful, not an error).
    assert await coop.call("birthdays.upcoming", 42) is None

    # A provider that raises -> None, not a crash.
    async def broken(_gid, **kw):
        raise RuntimeError("boom")

    coop.register("broken", broken)
    assert await coop.call("broken", 42) is None


@pytest.mark.asyncio
async def test_coop_unregister():
    coop = ModuleCoop()

    async def p(_gid, **kw):
        return {"ok": True}

    coop.register("x.provider", p)
    assert coop.provides("x.provider")
    coop.unregister("x.provider")
    assert not coop.provides("x.provider")
    assert await coop.call("x.provider", 1) is None


@pytest.mark.asyncio
async def test_guild_settings_upsert_read_and_delete(db):
    # GuildSetting rows are FK-bound to a Guild — create one first.
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as s:
        if not (await s.execute(select(Guild).where(Guild.discord_id == "9001"))).scalars().first():
            s.add(Guild(discord_id="9001", name="Coop Guild"))
            await s.commit()

    # get_settings returns defaults for unset keys.
    assert await get_setting(9001, "motd") == ""
    assert await get_settings(9001, "motd", "banner_url") == {}

    await set_setting(9001, "motd", "Hello **world**")
    assert await get_setting(9001, "motd") == "Hello **world**"
    assert await get_settings(9001, "motd", "banner_url") == {"motd": "Hello **world**"}

    # Overwrite.
    await set_setting(9001, "motd", "New MOTD")
    assert await get_setting(9001, "motd") == "New MOTD"

    # Empty value deletes the key.
    await set_setting(9001, "motd", "")
    assert await get_setting(9001, "motd") == ""
