"""Tests for the single /bark slash dispatcher.

The dispatcher exposes every module/plugin command through ONE registered
slash command (``/bark <command> [args...]``) so Bark never hits Discord's
per-group subcommand cap.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from services.slash_dispatcher import SlashDispatcher


def _make_manager() -> MagicMock:
    mgr = MagicMock()
    mgr._command_enabled_check.return_value = None
    mgr.is_enabled_for_guild.return_value = True
    return mgr


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.tree = MagicMock()
    return bot


def _make_leaf(name="warn", params=()):
    """A fake app_commands leaf with a spying callback."""
    callback = AsyncMock()
    leaf = MagicMock()
    leaf.name = name
    leaf.callback = callback
    leaf.parameters = list(params)
    leaf.commands = None  # a leaf has no subcommands (only Groups do)
    return leaf, callback


def _register_fake_module(d: SlashDispatcher, module_name: str, name: str, leaf) -> None:
    module = MagicMock()
    module.get_commands.return_value = [SimpleNamespace(slash=True, name=name)]
    setattr(module, f"_make_{name}_command", lambda leaf_param=leaf: leaf_param)
    d.register_module(module_name, module)


def test_build_command_derives_command_and_args_params():
    d = SlashDispatcher(_make_bot(), _make_manager())
    cmd = d.build_command("bark")
    assert cmd.name == "bark"
    names = [(p.name, p.required) for p in cmd.parameters]
    assert names == [("command", True), ("args", False)]


def test_register_module_collects_leaf_paths():
    d = SlashDispatcher(_make_bot(), _make_manager())
    leaf1, _ = _make_leaf("warn")
    leaf2, _ = _make_leaf("ban")
    module = MagicMock()
    module.get_commands.return_value = [
        SimpleNamespace(slash=True, name="warn"),
        SimpleNamespace(slash=True, name="ban"),
    ]
    module._make_warn_command = lambda: leaf1
    module._make_ban_command = lambda: leaf2
    d.register_module("moderation", module)
    assert set(d._registry.keys()) == {"warn", "ban"}


def test_dispatch_unknown_command_sends_ephemeral_error():
    d = SlashDispatcher(_make_bot(), _make_manager())
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    asyncio.run(d.dispatch(interaction, "nonexistent", ""))
    interaction.response.send_message.assert_awaited_once()
    assert "Unknown command" in interaction.response.send_message.await_args.args[0]


@pytest.mark.asyncio
async def test_dispatch_invokes_leaf_callback_with_kwargs():
    d = SlashDispatcher(_make_bot(), _make_manager())
    leaf, callback = _make_leaf(
        "warn",
        params=[
            SimpleNamespace(name="member", type=discord.AppCommandOptionType.mentionable, required=True),
            SimpleNamespace(name="reason", type=discord.AppCommandOptionType.string, required=False),
        ],
    )
    _register_fake_module(d, "moderation", "warn", leaf)

    interaction = MagicMock()
    interaction.user = "u"
    interaction.guild = None
    interaction.response = MagicMock()

    await d.dispatch(interaction, "warn", "someuser reason here")
    assert callback.await_count == 1
    kwargs = callback.await_args.kwargs
    assert kwargs["reason"] == "reason"
    assert kwargs["member"] is not None


@pytest.mark.asyncio
async def test_autocomplete_filters_by_current():
    d = SlashDispatcher(_make_bot(), _make_manager())
    _register_fake_module(d, "moderation", "warn", _make_leaf("warn")[0])
    _register_fake_module(d, "moderation", "warnings", _make_leaf("warnings")[0])
    _register_fake_module(d, "moderation", "ban", _make_leaf("ban")[0])

    interaction = MagicMock()
    interaction.guild_id = 1
    choices = await d._autocomplete(interaction, "wa")
    values = [c.value for c in choices]
    assert values == ["warn", "warnings"]
    assert "ban" not in values
