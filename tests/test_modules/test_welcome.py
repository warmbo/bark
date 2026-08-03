"""Welcome module tests — message formatting, join/leave event flows."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from modules.welcome.module import WelcomeModule


class _Member:
    """Minimal stand-in for discord.Member exposing the fields the module uses."""

    def __init__(self, guild, mid: int, is_bot: bool = False, name: str = "Newbie") -> None:
        self.id = mid
        self.guild = guild
        self.bot = is_bot
        self.display_name = name
        self.mention = f"<@{mid}>"
        self.send = AsyncMock()

    def __str__(self) -> str:
        return self.display_name


def _member(guild, mid: int, is_bot: bool = False, name: str = "Newbie"):
    return _Member(guild, mid, is_bot=is_bot, name=name)


def _guild(gid: int, member_count: int = 42):
    return SimpleNamespace(
        id=gid,
        name="Welcome Guild",
        member_count=member_count,
        get_channel=MagicMock(return_value=None),
        get_member=MagicMock(return_value=SimpleNamespace(id=1)),
    )


def _module(config: dict | None = None):
    module = WelcomeModule(MagicMock())
    module.load_dashboard_config = AsyncMock(return_value=config)
    return module


# ── _format placeholder replacement (pure logic) ────────


def test_format_replaces_all_placeholders():
    module = WelcomeModule(MagicMock())
    guild = _guild(12345)
    member = _member(guild, 777)
    out = module._format(
        "{user} | {user.mention} | {user.id} | {server} | {member_count}",
        member,
    )
    assert out == "Newbie | <@777> | 777 | Welcome Guild | 42"


def test_format_empty_template_returns_empty():
    module = WelcomeModule(MagicMock())
    assert module._format("", _member(_guild(1), 1)) == ""


# ── _build_message text vs embed ────────────────────────


def test_build_message_plain_text():
    module = WelcomeModule(MagicMock())
    member = _member(_guild(1), 5)
    out = module._build_message("Hi {user}", member, as_embed=False, title="Welcome!")
    assert out == "Hi Newbie"
    assert not isinstance(out, discord.Embed)


def test_build_message_embed():
    module = WelcomeModule(MagicMock())
    member = _member(_guild(1), 5)
    out = module._build_message("Hi {user}", member, as_embed=True, title="Welcome!")
    assert isinstance(out, discord.Embed)
    assert out.title == "Welcome!"
    assert "Hi Newbie" in (out.description or "")


# ── _on_member_join event flow ─────────────────────────


@pytest.mark.asyncio
async def test_join_with_no_config_is_noop():
    module = _module(config=None)
    member = _member(_guild(9), 1)
    await module._on_member_join("discord_member_join", member=member)
    member.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_without_channel_sends_no_message():
    module = _module(config={"welcome_channel": ""})
    member = _member(_guild(9), 1)
    await module._on_member_join("discord_member_join", member=member)
    member.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_sends_to_configured_channel():
    guild = _guild(10)
    channel = SimpleNamespace(send=AsyncMock())
    guild.get_channel.return_value = channel

    module = _module(
        config={
            "welcome_channel": "555",
            "welcome_message": "Welcome {user.mention}!",
            "welcome_embed": False,
        }
    )
    member = _member(guild, 2)
    await module._on_member_join("discord_member_join", member=member)
    channel.send.assert_awaited_once()
    assert channel.send.await_args.args[0] == "Welcome <@2>!"


@pytest.mark.asyncio
async def test_join_sends_embed_when_configured():
    guild = _guild(11)
    channel = SimpleNamespace(send=AsyncMock())
    guild.get_channel.return_value = channel

    module = _module(
        config={
            "welcome_channel": "555",
            "welcome_message": "Welcome {user}!",
            "welcome_embed": True,
        }
    )
    member = _member(guild, 3)
    await module._on_member_join("discord_member_join", member=member)
    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs.get("embed")
    assert isinstance(sent_embed, discord.Embed)


@pytest.mark.asyncio
async def test_join_dm_sent_when_enabled():
    guild = _guild(12)
    module = _module(
        config={
            "welcome_channel": "",
            "dm_enabled": True,
            "dm_message": "Welcome to {server}!",
        }
    )
    member = _member(guild, 4)
    await module._on_member_join("discord_member_join", member=member)
    member.send.assert_awaited_once()
    assert member.send.await_args.args[0] == "Welcome to Welcome Guild!"


@pytest.mark.asyncio
async def test_join_ignores_bots():
    module = _module(config={"welcome_channel": "555"})
    member = _member(_guild(13), 5, is_bot=True)
    await module._on_member_join("discord_member_join", member=member)
    member.send.assert_not_awaited()


# ── _on_member_remove event flow ───────────────────────


@pytest.mark.asyncio
async def test_leave_without_goodbye_channel_is_noop():
    module = _module(config={"goodbye_channel": ""})
    member = _member(_guild(14), 6)
    await module._on_member_remove("discord_member_remove", member=member)
    member.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_leave_sends_to_configured_channel():
    guild = _guild(15)
    channel = SimpleNamespace(send=AsyncMock())
    guild.get_channel.return_value = channel

    module = _module(
        config={
            "goodbye_channel": "666",
            "goodbye_message": "Goodbye {user}",
            "goodbye_embed": False,
        }
    )
    member = _member(guild, 7)
    await module._on_member_remove("discord_member_remove", member=member)
    channel.send.assert_awaited_once()
    assert channel.send.await_args.args[0] == "Goodbye Newbie"


# ── slash command registration ─────────────────────────


def test_welcome_command_registers():
    module = WelcomeModule(MagicMock())
    command = module._make_welcome_command()
    assert command.name == "welcome"
    assert command.description == "Preview or test welcome message"
