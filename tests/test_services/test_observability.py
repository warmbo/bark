"""Tests for Phase 4 observability: event-bus guild context + tree error handler."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.client import BarkBot
from services.event_bus import EventBus

# ── EventBus failure context ───────────────────────────


@pytest.mark.asyncio
async def test_event_bus_failure_logs_guild_context(caplog):
    bus = EventBus()

    async def boom(event_type, **data):
        raise RuntimeError("kaboom")

    bus.subscribe("discord_message", boom)
    with caplog.at_level(logging.ERROR, logger="bark.event_bus"):
        await bus.emit("discord_message", message=SimpleNamespace(guild=SimpleNamespace(id=777)))
    assert any(
        "guild=777" in r.getMessage() and "kaboom" in r.exc_text or "guild=777" in r.getMessage()
        for r in caplog.records
    )


# ── Slash-command error handler ────────────────────────


class _FakeInteraction:
    def __init__(self, response, command=None):
        self.guild = SimpleNamespace(id=555)
        self.guild_id = 555
        self.user = SimpleNamespace(id=999)
        self.command = command or SimpleNamespace(name="ping")
        self.response = response


def _make_bot_with_handler():
    class _FakeBot:
        def __init__(self):
            self.tree = MagicMock()
            self.handler = None
            self.tree.error.side_effect = lambda cb: setattr(self, "handler", cb)

    fake = _FakeBot()
    BarkBot._install_tree_error_handler(fake)  # type: ignore[arg-type]  # method only uses self.tree
    assert fake.handler is not None
    return fake.handler


@pytest.mark.asyncio
async def test_tree_error_handler_logs_context_and_replies_generic(caplog):
    handler = _make_bot_with_handler()
    response = MagicMock()
    response.is_done.return_value = False
    response.send_message = AsyncMock()
    interaction = _FakeInteraction(response)
    error = discord.app_commands.CommandInvokeError.__new__(  # type: ignore[call-arg]
        discord.app_commands.CommandInvokeError
    )

    with caplog.at_level(logging.ERROR, logger="bark.client"):
        await handler(interaction, error)

    assert any("'ping'" in r.getMessage() and "guild 555" in r.getMessage() for r in caplog.records)
    response.send_message.assert_awaited_once()
    message = response.send_message.await_args.args[0]
    assert "secret internals" not in message, "raw exception must not leak to the user"


@pytest.mark.asyncio
async def test_tree_error_handler_expected_errors_reply_with_message():
    handler = _make_bot_with_handler()
    response = MagicMock()
    response.is_done.return_value = False
    response.send_message = AsyncMock()
    interaction = _FakeInteraction(response)
    error = discord.DiscordException("that's not a channel")

    await handler(interaction, error)
    response.send_message.assert_awaited_once()
    reply = response.send_message.await_args.args[0]
    # Generic reply — never echo the raw exception (it can contain internals).
    assert "Couldn't run that command" in reply
    assert "that's not a channel" not in reply
