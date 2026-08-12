"""Tests for the prefix-command adapter (services/prefix_commands.py)."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from modules.base import BarkModule
from services.prefix_commands import (
    PrefixFollowup,
    PrefixInteraction,
    PrefixResponse,
    build_prefix_command,
)


class _ConcreteModule(BarkModule):
    name = "concrete"

    async def enable(self) -> None:  # pragma: no cover - stub
        return None

    async def disable(self) -> None:  # pragma: no cover - stub
        return None


_captured: dict[str, Any] = {}


def _make_greet_command():
    """A real app_commands Command with two options, like a module factory."""
    @discord.app_commands.command(name="greet", description="Greet someone")
    @discord.app_commands.describe(name="who to greet", times="how many")
    async def greet_cmd(
        interaction: discord.Interaction,
        name: str,
        times: int,
    ) -> None:
        _captured["name"] = name
        _captured["times"] = times
        await interaction.response.send_message(f"hi {name}")
    return greet_cmd


def _make_ctx():
    ctx = MagicMock()
    guild = MagicMock()
    guild.id = 1
    ctx.guild = guild
    ctx.author = MagicMock()
    ctx.channel = MagicMock()
    ctx.message = MagicMock()
    ctx.message.id = 999
    ctx.message.edit = AsyncMock()
    ctx.send = AsyncMock()
    return ctx


def test_build_prefix_command_creates_named_command():
    cmd = build_prefix_command(_ConcreteModule(MagicMock()), "greet", _make_greet_command())
    assert isinstance(cmd, commands.Command)
    assert cmd.name == "greet"


def test_prefix_command_dispatches_handler_with_converted_args():
    module = _ConcreteModule(MagicMock())
    slash = _make_greet_command()
    prefix_cmd = build_prefix_command(module, "greet", slash)
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "bob", "3"))
    # The handler received the shim interaction + converted kwargs.
    assert _captured["name"] == "bob"
    assert _captured["times"] == 3  # int converted


def test_prefix_response_send_message_calls_ctx_send():
    ctx = _make_ctx()
    resp = PrefixResponse(ctx)
    asyncio.run(resp.send_message(content="hi"))
    ctx.send.assert_called_once()
    assert resp.is_done()


def test_prefix_followup_send_calls_ctx_send():
    ctx = _make_ctx()
    followup = PrefixFollowup(ctx)
    asyncio.run(followup.send(content="bye"))
    ctx.send.assert_called_once()


def test_prefix_interaction_exposes_guild_and_user():
    ctx = _make_ctx()
    inter = PrefixInteraction(ctx)
    assert inter.guild is ctx.guild
    assert inter.user is ctx.author
    assert inter.guild_id == 1
    assert inter.response is not None
    assert inter.followup is not None
