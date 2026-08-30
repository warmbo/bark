"""Tests for the prefix-command adapter (services/prefix_commands.py)."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from modules.base import BarkModule
from services.module_manager import ModuleManager
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


def _make_hidable_command():
    """An informational command with a trailing `hide: bool = True` (private default)."""
    @discord.app_commands.command(name="leaderboard", description="Show the top ranked members")
    @discord.app_commands.describe(hide="Only show this to you (default true)")
    async def lb_cmd(interaction: discord.Interaction, hide: bool = True) -> None:
        _captured["hide"] = hide
        await interaction.response.send_message(f"ephemeral={hide}")
    return lb_cmd


def test_prefix_command_omitted_boolean_keeps_handler_default():
    """Bare `bark!reputation leaderboard` must honour the handler's `hide=True`
    default (private), not be forced public by the adapter."""
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_hidable_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx))
    assert _captured.get("hide") is True


def test_prefix_command_explicit_false_makes_response_public():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_hidable_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "false"))
    assert _captured.get("hide") is False


def test_prefix_command_explicit_true_keeps_response_private():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_hidable_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "true"))
    assert _captured.get("hide") is True


def _make_restricted_command():
    """A real app_commands Command with a ban_members default_permissions."""
    @discord.app_commands.command(name="ban", description="Ban a member")
    @discord.app_commands.default_permissions(ban_members=True)
    async def ban_cmd(interaction: discord.Interaction, member: discord.Member) -> None:
        _captured["banned"] = True
    return ban_cmd


def test_prefix_command_denies_invoker_without_required_permission():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "ban", _make_restricted_command())
    ctx = _make_ctx()
    ctx.author.guild_permissions = discord.Permissions.none()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "@someone"))
    assert "banned" not in _captured  # handler never ran
    ctx.send.assert_awaited_once()
    assert "permission" in ctx.send.await_args.args[0]


def test_prefix_command_allows_invoker_with_required_permission():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "ban", _make_restricted_command())
    ctx = _make_ctx()
    ctx.author.guild_permissions = discord.Permissions(ban_members=True)

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "@someone"))
    assert _captured.get("banned") is True  # handler ran


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


def _make_trivia_group():
    """A group-like slash command with subcommands (mirrors the trivia module)."""
    from types import SimpleNamespace

    @discord.app_commands.command(name="start", description="Start trivia")
    async def start_cmd(interaction: discord.Interaction) -> None:
        _captured["sub"] = "start"
        await interaction.response.send_message("trivia started")

    @discord.app_commands.command(name="stop", description="Stop trivia")
    async def stop_cmd(interaction: discord.Interaction) -> None:
        _captured["sub"] = "stop"
        await interaction.response.send_message("trivia stopped")

    return SimpleNamespace(
        name="trivia",
        description="Trivia commands",
        commands=[start_cmd, stop_cmd],
    )


def test_build_prefix_command_from_group_makes_text_group():
    group = build_prefix_command(_ConcreteModule(MagicMock()), "trivia", _make_trivia_group())
    assert isinstance(group, commands.Group)
    names = {c.name for c in group.commands}
    assert names == {"start", "stop"}


# ── ModuleManager integration: enable_module registers prefix commands ─────


def test_enable_module_registers_prefix_commands(db, tmp_path):
    import discord.app_commands as ac

    registered: dict[str, object] = {}

    class FakeBot:
        def __init__(self):
            self.http = MagicMock()
            self._connection = MagicMock()
            self._connection._command_tree = None
            self.tree = ac.CommandTree(self)
            self._event_bus = MagicMock()
            self.guilds = []
            self.user = MagicMock()
            self.user.name = "bark"

        def add_command(self, cmd):
            registered[cmd.name] = cmd

        def get_command(self, name):
            return registered.get(name)

        def remove_command(self, name):
            registered.pop(name, None)

        async def is_ready(self):
            return True

    bot = FakeBot()

    class SampleModule(_ConcreteModule):
        name = "sample"

        def get_commands(self):
            from modules.base import CommandRegistration

            return [CommandRegistration(name="greet", description="greet")]

        def _make_greet_command(self):
            return _make_greet_command()  # real app_commands Command

    bot.modules = ModuleManager(bot)
    bot.modules.discover = MagicMock()
    bot.modules._register_module(SampleModule(bot.modules._context))

    import asyncio

    asyncio.run(bot.modules.enable_module("sample"))
    assert "greet" in registered
    # Disable removes it.
    asyncio.run(bot.modules.disable_module("sample"))
    assert "greet" not in registered

