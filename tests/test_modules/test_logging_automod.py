"""Tests for the logging module's AutoMod alert channel.

The logging module subscribes to automod_triggered bus events and posts an
embed to the guild's configured mod-log channel (event type "automod").
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.logging.module import LoggingModule
from services.event_bus import EventBus


def _ctx_with_config(config: dict, channel):
    ctx = SimpleNamespace(events=EventBus(), get_guild=lambda gid: None)

    async def get_module_config(name, guild_id):
        return config

    async def save_module_config(name, guild_id, cfg):
        pass

    ctx.get_module_config = get_module_config
    ctx.save_module_config = save_module_config

    if channel is not None:
        guild = SimpleNamespace(get_channel=lambda cid: channel if str(cid) == str(channel.id) else None)
        ctx.get_guild = lambda gid: guild
    return ctx


@pytest.mark.asyncio
async def test_automod_event_posts_embed_to_configured_channel():
    channel = SimpleNamespace(id=1521214382334414929, send=AsyncMock())
    config = {"automod": {"channel_id": str(channel.id), "enabled": True}}
    module = LoggingModule(_ctx_with_config(config, channel))  # type: ignore[arg-type]

    await module._on_automod_event(
        "automod_triggered",
        guild_id=221627370375872512,
        rule="Ruleset:Scam Protection/duplicate_message",
        action="kick",
        user_tag="2y1v",
        content="bro",
    )

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.title == "🚨 AutoMod Triggered"
    assert any(f.name == "Rule" and "duplicate_message" in f.value for f in embed.fields)


@pytest.mark.asyncio
async def test_automod_event_skips_when_disabled():
    channel = SimpleNamespace(id=5, send=AsyncMock())
    config = {"automod": {"channel_id": "5", "enabled": False}}
    module = LoggingModule(_ctx_with_config(config, channel))  # type: ignore[arg-type]

    await module._on_automod_event(
        "automod_triggered", guild_id=1, rule="x", action="warn", user_tag="u"
    )
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_automod_event_ignores_other_event_types():
    channel = SimpleNamespace(id=5, send=AsyncMock())
    config = {"automod": {"channel_id": "5", "enabled": True}}
    module = LoggingModule(_ctx_with_config(config, channel))  # type: ignore[arg-type]

    await module._on_automod_event("member_joined", guild_id=1)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_enable_subscribes_and_disable_unsubscribes():
    ctx = _ctx_with_config({}, None)
    module = LoggingModule(ctx)  # type: ignore[arg-type]
    assert ctx.events.subscriber_count("automod_triggered") == 0

    await module.enable()
    assert ctx.events.subscriber_count("automod_triggered") == 1

    await module.disable()
    assert ctx.events.subscriber_count("automod_triggered") == 0
