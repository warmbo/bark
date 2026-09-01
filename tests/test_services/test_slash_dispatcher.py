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
    mgr.is_plugin.return_value = False  # default: everything is a core module
    return mgr


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.tree = MagicMock()
    bot.paginator = None  # fall back to a simple (non-paginated) response
    return bot


def _make_leaf(name="warn", params=()):
    """A fake app_commands leaf with a spying callback."""
    callback = AsyncMock()
    leaf = MagicMock()
    leaf.name = name
    leaf.callback = callback
    leaf.parameters = list(params)
    leaf.commands = None  # a leaf has no subcommands (only Groups do)
    leaf.default_permissions = None  # no permission gate by default
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
    # Both optional so a bare /bark shows guidance.
    assert names == [("command", False), ("args", False)]


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
    assert d._module_paths["moderation"] == ["warn", "ban"]


def test_dispatch_unknown_command_sends_guidance_embed():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    asyncio.run(d.dispatch(interaction, "nonexistent", ""))
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    assert "recognised" in kwargs["embed"].title
    assert kwargs["embed"].description


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
    interaction.user = SimpleNamespace(name="invoker", id=1)
    member = SimpleNamespace(name="someuser", display_name="someuser", id=123)
    guild = MagicMock()
    guild.members = [member]
    interaction.guild = guild
    interaction.response = MagicMock()

    await d.dispatch(interaction, "warn", "someuser reason here")
    assert callback.await_count == 1
    kwargs = callback.await_args.kwargs
    # The final string param is a free-form sink: the whole reason survives.
    assert kwargs["reason"] == "reason here"
    assert kwargs["member"] is member


@pytest.mark.asyncio
async def test_dispatch_unresolved_member_shows_not_found_not_self_target():
    """A mistyped mention must not self-moderate — show a not-found error."""
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
    interaction.user = SimpleNamespace(name="invoker", id=1)
    guild = MagicMock()
    guild.members = []  # nothing matches the typo'd target
    interaction.guild = guild
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "warn", "typo some reason")
    assert callback.await_count == 0  # never warned the invoker by default
    interaction.response.send_message.assert_awaited_once()
    args, _ = interaction.response.send_message.await_args
    assert "member" in args[0]


@pytest.mark.asyncio
async def test_dispatch_missing_required_arg_shows_usage_not_dispatch():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    leaf, callback = _make_leaf(
        "warn",
        params=[SimpleNamespace(name="member", type=discord.AppCommandOptionType.mentionable, required=True)],
    )
    _register_fake_module(d, "moderation", "warn", leaf)
    interaction = MagicMock()
    interaction.user = "u"
    interaction.guild = None
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "warn", "")
    assert callback.await_count == 0  # never acted on a default target
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    assert kwargs["embed"].title == "🐺 Warn"


@pytest.mark.asyncio
async def test_dispatch_module_name_shows_menu():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    _register_fake_module(d, "moderation", "warn", _make_leaf("warn")[0])
    _register_fake_module(d, "moderation", "ban", _make_leaf("ban")[0])
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "moderation", "")
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    embed = kwargs["embed"]
    assert embed.title == "🐺 Moderation"
    assert embed.fields == []
    assert "Choose a command below" in embed.description
    assert kwargs.get("view") is not None  # interactive command picker attached


@pytest.mark.asyncio
async def test_dispatch_bare_shows_overview():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    _register_fake_module(d, "moderation", "warn", _make_leaf("warn")[0])
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "", "")
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    embed = kwargs["embed"]
    assert embed.title == "🐺 Bark Commands"
    assert "Choose a module below" in embed.description
    assert kwargs.get("view") is not None  # interactive module picker attached


def test_single_page_menu_is_guidance_only_without_fake_pagination():
    d = SlashDispatcher(_make_bot(), _make_manager())
    _register_fake_module(d, "birthdays", "birthday set", _make_leaf("set")[0])

    leaf = next(iter(d._registry.values()))
    pages = d._build_menu_pages(
        [leaf],
        title="🎂 Birthdays",
        detail="Choose a command below.",
    )

    assert len(pages) == 1
    assert pages[0].footer.text in (None, "")
    assert pages[0].fields == []
    assert pages[0].description == "Choose a command below."


@pytest.mark.asyncio
async def test_overview_keeps_addons_in_the_single_module_picker_page():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    _register_fake_module(d, "moderation", "warn", _make_leaf("warn")[0])
    # Treat "birthday" as an installed add-on plugin.
    def _is_plugin(name):
        return name == "birthday"

    d.manager.is_plugin.side_effect = _is_plugin
    _register_fake_module(d, "birthday", "birthday", _make_leaf("birthday")[0])

    pages = d._build_overview_pages(1)
    assert len(pages) == 1
    assert pages[0].title == "🐺 Bark Commands"
    assert pages[0].fields == []


@pytest.mark.asyncio
async def test_dispatch_help_with_command_shows_detailed_help():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    leaf, _ = _make_leaf(
        "warn",
        params=[
            SimpleNamespace(name="member", type=discord.AppCommandOptionType.mentionable,
                            required=True, description="The member to warn"),
            SimpleNamespace(name="reason", type=discord.AppCommandOptionType.string,
                            required=False, description="Why they're being warned"),
        ],
    )
    _register_fake_module(d, "moderation", "warn", leaf)
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "help", "warn")
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    embed = kwargs["embed"]
    assert "warn" in (embed.title or "").lower()
    field_text = " ".join((f.name or "") + (f.value or "") for f in embed.fields)
    assert "The member to warn" in field_text  # param description surfaced
    assert "required" in field_text
    assert "optional" in field_text


@pytest.mark.asyncio
async def test_dispatch_help_with_unknown_shows_guidance():
    d = SlashDispatcher(_make_bot(), _make_manager())
    d.build_command("bark")
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "help", "nonexistent")
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.await_args
    assert "recognised" in kwargs["embed"].title


@pytest.mark.asyncio
async def test_typed_command_binds_to_plain_option():
    """`/bark help` typed by hand must bind 'help' to the command option and
    run help — NOT fall through to the generic overview. Discord only commits
    free-typed text into a plain (non-autocomplete) string option; the flat
    command must therefore NOT autocomplete its 'command' parameter
    (2026-09-01 report: "/bark help" showed '+2 options' and gave the
    generic response because autocomplete kept the typed text pending)."""
    d = SlashDispatcher(_make_bot(), _make_manager())
    cmd = d.build_command("bark")
    param = next(p for p in cmd.parameters if p.name == "command")
    assert not param.autocomplete  # plain string (no autocomplete) -> typed text binds

    # 'help' is a registered leaf -> dispatch runs it, not the overview.
    leaf, callback = _make_leaf("help")
    leaf.default_permissions = None
    _register_fake_module(d, "help", "help", leaf)

    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user = SimpleNamespace(guild_permissions=discord.Permissions.all())
    interaction.guild = MagicMock()
    interaction.response = MagicMock()

    await d.dispatch(interaction, "help", "")
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_dispatch_denies_invoker_without_required_permission():
    """A plain member must not run a command whose default_permissions they lack."""
    d = SlashDispatcher(_make_bot(), _make_manager())
    leaf, callback = _make_leaf("ban")
    leaf.default_permissions = discord.Permissions(ban_members=True)
    _register_fake_module(d, "moderation", "ban", leaf)

    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user = SimpleNamespace(guild_permissions=discord.Permissions.none())
    interaction.response.send_message = AsyncMock()

    await d.dispatch(interaction, "ban", "@someone")
    assert callback.await_count == 0  # never reached the handler
    interaction.response.send_message.assert_awaited_once()
    args, kwargs = interaction.response.send_message.await_args
    assert "permission" in args[0]
    assert kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_dispatch_allows_invoker_with_required_permission():
    """An invoker holding the declared permission is dispatched to the handler."""
    d = SlashDispatcher(_make_bot(), _make_manager())
    leaf, callback = _make_leaf("ban")
    leaf.default_permissions = discord.Permissions(ban_members=True)
    _register_fake_module(d, "moderation", "ban", leaf)

    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user = SimpleNamespace(guild_permissions=discord.Permissions(ban_members=True))
    interaction.response = MagicMock()

    await d.dispatch(interaction, "ban", "@someone")
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_dispatch_public_flag_is_passed_to_informational_leaf():
    """`/bark leaderboard public` must reach the handler with public=True,
    `/bark leaderboard private` with public=False, and a bare invocation leaves
    public unset so the private-by-default applies."""
    d = SlashDispatcher(_make_bot(), _make_manager())
    captured = {}

    async def callback(interaction, **kwargs):
        captured.update(kwargs)

    leaf = MagicMock()
    leaf.name = "leaderboard"
    leaf.callback = callback
    leaf.parameters = [
        SimpleNamespace(
            name="public",
            type=discord.AppCommandOptionType.boolean,
            required=False,
            description="Post in the channel for everyone (default private)",
        )
    ]
    leaf.commands = None
    leaf.default_permissions = None
    _register_fake_module(d, "reputation", "leaderboard", leaf)

    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user = SimpleNamespace(guild_permissions=discord.Permissions.none())
    interaction.guild = MagicMock()
    interaction.response = MagicMock()

    # Bare invocation -> public omitted -> default (private) applies.
    await d.dispatch(interaction, "leaderboard", "")
    assert "public" not in captured

    # Explicit "public" -> public.
    captured.clear()
    await d.dispatch(interaction, "leaderboard", "public")
    assert captured.get("public") is True

    # Explicit "private" -> private.
    captured.clear()
    await d.dispatch(interaction, "leaderboard", "private")
    assert captured.get("public") is False
