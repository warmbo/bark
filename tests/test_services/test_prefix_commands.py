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


def _make_two_string_command():
    """Two string options, like a command with a label plus free-form text."""

    @discord.app_commands.command(name="note", description="Leave a note")
    @discord.app_commands.describe(label="short label", text="free-form text")
    async def note_cmd(interaction: discord.Interaction, label: str, text: str) -> None:
        _captured["label"] = label
        _captured["text"] = text

    return note_cmd


def test_prefix_command_final_string_consumes_remaining_tokens():
    """The final string option is a free-form sink, exactly like the slash
    dispatcher — so `bark!birthday set September 16` passes 'September 16'."""
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "note", _make_two_string_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "bob", "hello", "world"))
    assert _captured["label"] == "bob"  # non-final string still takes one token
    assert _captured["text"] == "hello world"


def _make_set_date_command():
    """A single required string option, like the birthdays `set` command."""

    @discord.app_commands.command(name="set", description="Set your birthday")
    @discord.app_commands.describe(date="month/day, e.g. 09/16 or September 16")
    async def set_cmd(interaction: discord.Interaction, date: str) -> None:
        _captured["date"] = date

    return set_cmd


def test_prefix_command_single_string_keeps_words_joined():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "set", _make_set_date_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "September", "16"))
    assert _captured["date"] == "September 16"


def _make_channel_command():
    """A required channel option, like `birthday channel`."""

    @discord.app_commands.command(name="channel", description="Pick a channel")
    @discord.app_commands.describe(channel="announcement channel")
    async def channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        _captured["channel"] = channel

    return channel_cmd


def test_prefix_command_unresolved_required_channel_fails_before_callback():
    """A mistyped channel must not reach the handler with channel=None — that is
    how an implicit destructive default (e.g. announcing "off") happens."""
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "channel", _make_channel_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "genral-typo"))
    assert "channel" not in _captured  # handler never ran
    ctx.send.assert_awaited_once()
    msg = ctx.send.await_args.args[0]
    # Same wording as the slash dispatcher's not-found guard.
    assert "find that channel" in msg


def test_prefix_command_resolved_required_channel_invokes_callback(monkeypatch):
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "channel", _make_channel_command())
    ctx = _make_ctx()
    sentinel = object()

    async def _fake_channel(_ctx, _raw):
        return sentinel

    monkeypatch.setattr("services.prefix_commands._to_channel", _fake_channel)

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "celebrations"))
    assert _captured["channel"] is sentinel


def test_prefix_command_missing_required_arg_shows_usage_not_traceback():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "ban", _make_restricted_command())
    ctx = _make_ctx()
    ctx.author.guild_permissions = discord.Permissions(ban_members=True)

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx))  # no target member supplied
    assert "banned" not in _captured  # handler never ran on a default target
    ctx.send.assert_awaited_once()
    msg = ctx.send.await_args.args[0]
    assert "member" in msg  # names the missing option


def test_prefix_command_moderation_shape_target_and_trailing_reason(monkeypatch):
    """`bark!warn <member> <reason...>` keeps its target and free-text reason."""

    @discord.app_commands.command(name="warn", description="Warn a member")
    async def warn_cmd(
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason",
    ) -> None:
        _captured["member"] = member
        _captured["reason"] = reason

    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "warn", warn_cmd)
    ctx = _make_ctx()
    target = object()

    async def _fake_member(_ctx, _raw):
        return target

    monkeypatch.setattr("services.prefix_commands._to_member_or_user", _fake_member)

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "@target-user", "spamming", "in", "general"))
    assert _captured["member"] is target
    assert _captured["reason"] == "spamming in general"


def test_prefix_command_disabled_module_refuses_without_dispatch():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(
        module, "greet", _make_greet_command(), check=AsyncMock(return_value=False)
    )
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "bob", "3"))
    assert _captured == {}  # handler never ran while the module is off
    ctx.send.assert_awaited_once()
    assert "isn't enabled" in ctx.send.await_args.args[0]


def _make_public_flag_command():
    """An informational command with a trailing `public: bool = False` (private default)."""

    @discord.app_commands.command(name="leaderboard", description="Show the top ranked members")
    @discord.app_commands.describe(public="Post in the channel for everyone (default private)")
    async def lb_cmd(interaction: discord.Interaction, public: bool = False) -> None:
        _captured["public"] = public
        await interaction.response.send_message(f"ephemeral={not public}")

    return lb_cmd


def test_prefix_command_omitted_boolean_keeps_handler_default():
    """Bare `bark!reputation leaderboard` must honour the handler's `public=False`
    default (private), not be forced public by the adapter."""
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_public_flag_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx))
    assert _captured.get("public") is False


def test_prefix_command_explicit_public_makes_response_public():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_public_flag_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "public"))
    assert _captured.get("public") is True


def test_prefix_command_explicit_private_keeps_response_private():
    module = _ConcreteModule(MagicMock())
    prefix_cmd = build_prefix_command(module, "leaderboard", _make_public_flag_command())
    ctx = _make_ctx()

    _captured.clear()
    asyncio.run(prefix_cmd.callback(ctx, "private"))
    assert _captured.get("public") is False


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
