"""Tests for per-guild command prefix resolution and persistence.

DB access is stubbed via ``_read_setting`` / ``_write_setting`` so these run
without a database. The cache is cleared between tests to keep lookups honest.
"""

from __future__ import annotations

import pytest

from services import command_prefix as cp


@pytest.fixture(autouse=True)
def _clear_cache():
    cp.invalidate_all()
    yield
    cp.invalidate_all()


def _stub_read(value: str | None):
    async def read(guild_id: str, key: str):
        return value

    cp._read_setting = read  # type: ignore[assignment]


def _stub_write(result: bool = True):
    calls: list[tuple] = []

    async def write(guild_id: str, key: str, value: str):
        calls.append((guild_id, key, value))
        return result

    cp._write_setting = write  # type: ignore[assignment]
    return calls


@pytest.mark.asyncio
async def test_unset_guild_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(cp.config.bot, "command_prefix", "bark!")
    _stub_read(None)
    assert await cp.resolve_guild_prefix(123) == "bark!"


@pytest.mark.asyncio
async def test_resolve_custom_prefix():
    _stub_read("!")
    assert await cp.resolve_guild_prefix(123) == "!"


@pytest.mark.asyncio
async def test_resolve_is_cached():
    _stub_read("bark!")
    assert await cp.resolve_guild_prefix(123) == "bark!"
    # A later DB value change is ignored until the cache is invalidated.
    _stub_read("!!")
    assert await cp.resolve_guild_prefix(123) == "bark!"
    cp.invalidate_guild(123)
    assert await cp.resolve_guild_prefix(123) == "!!"


@pytest.mark.asyncio
async def test_set_prefix_persists_and_caches():
    calls = _stub_write()
    prefix = await cp.set_guild_prefix(123, "  !  ")
    assert prefix == "!"
    assert calls == [(123, cp.PREFIX_SETTING, "!")]
    assert cp._prefix_cache["123"] == "!"
    assert await cp.resolve_guild_prefix(123) == "!"


@pytest.mark.asyncio
async def test_set_prefix_rejects_empty():
    _stub_write()
    with pytest.raises(ValueError):
        await cp.set_guild_prefix(123, "   ")


@pytest.mark.asyncio
async def test_set_prefix_rejects_too_long():
    _stub_write()
    with pytest.raises(ValueError):
        await cp.set_guild_prefix(123, "x" * 11)


@pytest.mark.asyncio
async def test_mention_defaults_false():
    _stub_read(None)
    assert await cp.guild_uses_mention(123) is False


@pytest.mark.asyncio
async def test_mention_true_when_enabled():
    _stub_read("true")
    assert await cp.guild_uses_mention(123) is True


@pytest.mark.asyncio
async def test_set_mention_persists_and_caches():
    calls = _stub_write()
    assert await cp.set_guild_mention(123, True) is True
    assert (123, cp.MENTION_SETTING, "true") in calls
    assert cp._mention_cache["123"] is True


@pytest.mark.asyncio
async def test_resolve_prefixes_includes_mention():
    class Bot:
        class _User:
            id = 42

        user = _User()

    _stub_read("!")
    _stub_write()
    await cp.set_guild_mention(123, True)
    prefixes = await cp.resolve_guild_prefixes(Bot(), 123)
    assert prefixes == ["!", "<@42> ", "<@!42> "]


@pytest.mark.asyncio
async def test_resolve_prefixes_no_mention():
    class Bot:
        class _User:
            id = 42

        user = _User()

    _stub_read("!")
    assert await cp.resolve_guild_prefixes(Bot(), 123) == ["!"]


@pytest.mark.asyncio
async def test_get_settings_bundle():
    _stub_read("!")
    _stub_write()
    await cp.set_guild_mention(123, True)
    settings = await cp.get_guild_command_settings(123)
    assert settings == {"prefix": "!", "mention": True}
