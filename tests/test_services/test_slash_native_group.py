"""Tests for the native module subcommand-group structure.

Bark registers `/bark` as a native command Group so users can type
`/bark reputation leaderboard` directly (native Discord autocomplete) instead
of selecting the old `command`/`args` string fields. Single-command modules
(and the general help commands) hang directly off `/bark`; multi-command
modules become subcommand-groups.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord import app_commands

from services.slash_dispatcher import SlashDispatcher


def _make_manager() -> MagicMock:
    mgr = MagicMock()
    mgr._command_enabled_check.return_value = None
    mgr.is_enabled_for_guild.return_value = True
    mgr.is_plugin.return_value = False
    return mgr


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.paginator = None
    return bot


def _make_leaf(name, params=()):
    captured = {}

    async def _real_callback(interaction: discord.Interaction):
        captured["interaction"] = interaction

    cmd = app_commands.Command(name=name, description=f"the {name} command", callback=_real_callback)
    leaf = SimpleNamespace(
        name=name,
        command=cmd,
        callback=_real_callback,
        parameters=list(params),
        commands=None,
        default_permissions=None,
    )
    return leaf, captured


def _register(d, module_name, leaves):
    """Register several leaf commands under one module."""
    module = MagicMock()
    # leaves is a list of (leaf, callback) tuples from _make_leaf.
    regs = [SimpleNamespace(slash=True, name=leaf.name) for leaf, _ in leaves]
    module.get_commands.return_value = regs
    for leaf, _ in leaves:
        setattr(module, f"_make_{leaf.name}_command", lambda l=leaf: l.command)
    d.register_module(module_name, module)


def test_build_group_creates_native_group_with_module_subgroups():
    d = SlashDispatcher(_make_bot(), _make_manager())
    # Multi-command module -> subcommand-group.
    _register(d, "moderation", [_make_leaf("warn"), _make_leaf("ban"), _make_leaf("kick")])
    # Single-command module -> direct subcommand.
    _register(d, "welcome", [_make_leaf("welcome")])

    group = d.build_group("bark")
    assert isinstance(group, app_commands.Group)
    assert group.name == "bark"

    # Moderation is a subcommand-group.
    mod_group = next((c for c in group.commands if c.name == "moderation"), None)
    assert mod_group is not None
    assert isinstance(mod_group, app_commands.Group)
    mod_names = {c.name for c in mod_group.commands}
    assert {"warn", "ban", "kick"} <= mod_names

    # Welcome hangs directly off /bark (single-command module).
    direct_names = {c.name for c in group.commands if not getattr(c, "commands", None)}
    assert "welcome" in direct_names


def test_general_help_commands_are_direct_subcommands():
    d = SlashDispatcher(_make_bot(), _make_manager())
    _register(d, "help", [_make_leaf("help"), _make_leaf("info"), _make_leaf("stats")])

    group = d.build_group("bark")
    direct_names = {c.name for c in group.commands if not getattr(c, "commands", None)}
    assert {"help", "info", "stats"} <= direct_names


def test_subcommand_has_module_enablement_check():
    """Each native subcommand carries a check that gates on module enablement."""
    d = SlashDispatcher(_make_bot(), _make_manager())
    leaf, _ = _make_leaf("leaderboard")
    leaf2, _2 = _make_leaf("reputation")
    _register(d, "reputation", [(leaf, _), (leaf2, _2)])

    group = d.build_group("bark")
    rep_group = next((c for c in group.commands if c.name == "reputation"), None)
    lb = next(c for c in rep_group.commands if c.name == "leaderboard")
    assert lb.checks, "subcommand should carry an enablement check"

    # When the module is disabled for the guild, the check rejects.
    d.manager.is_enabled_for_guild.return_value = False
    interaction = MagicMock()
    interaction.guild_id = 1
    with pytest.raises(discord.app_commands.CheckFailure):
        asyncio.run(lb.checks[0](interaction))
