"""Tests for the `/bark help` module: DM command reference + fallbacks."""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from modules.help.module import HelpModule
from services.bark_context import BarkContext


class FakeCommand:
    def __init__(self, name: str, description: str = "", commands=None):
        self.name = name
        self.description = description
        self.commands = commands


class FakeTree:
    def __init__(self, group):
        self._group = group

    def get_commands(self):
        return [self._group]


def _build_tree():
    """/bark with a direct child (roll) and a subgroup (trivia start)."""
    roll = FakeCommand("roll", "Roll dice")
    start = FakeCommand("start", "Start a trivia game")
    trivia = FakeCommand("trivia", "Trivia commands", commands=[start])
    return FakeTree(FakeCommand("bark", "Bark commands", commands=[roll, trivia]))


class _CaptureSend:
    def __init__(self, exc=None):
        self.sent = []
        self.exc = exc

    async def send(self, content=None, **kwargs):
        if self.exc:
            raise self.exc
        self.sent.append({"content": content, "embed": kwargs.get("embed")})


class _Response:
    def __init__(self):
        self.messages = []
        self._done = False

    def is_done(self):
        return self._done

    async def send_message(self, content=None, ephemeral=False, **kwargs):
        self.messages.append(content)
        self._done = True

    async def followup(self, content=None, embed=None, ephemeral=False, **kwargs):
        self.messages.append(content)
        return None


class _Interaction:
    def __init__(self, user_send):
        self.user = SimpleNamespace(send=user_send)
        self.response = _Response()
        self.followup = SimpleNamespace(send=lambda *a, **k: None)
        self.guild = SimpleNamespace(id=1)


def _make_module(bot):
    return HelpModule(BarkContext(bot, SimpleNamespace()))


@pytest.mark.asyncio
async def test_help_dms_every_command_and_dashboard_info():
    captured = _CaptureSend()
    bot = SimpleNamespace(tree=_build_tree())
    module = _make_module(bot)
    interaction = _Interaction(captured.send)

    await module._make_help_command().callback(interaction)

    # Two DMs: a "How to use Bark" guide, then the command reference.
    assert len(captured.sent) == 2
    guide = captured.sent[0]["embed"]
    reference = captured.sent[1]["embed"]

    # Guide message carries the how-to instructions
    assert guide.title == "🐺 How to use Bark"
    guide_text = guide.title + " " + " ".join(
        f"{f.name} {f.value}" for f in guide.fields
    )
    assert "Enable the modules you want" in guide_text
    assert "add-on plugins are off until you turn them on" in guide_text
    assert "/bark help" in guide_text

    # Reference message lists every command with the /bark group prefix
    assert reference.title == "🐺 Bark — Command Reference"
    assert "`/bark roll` — Roll dice" in reference.description
    assert "`/bark trivia start` — Start a trivia game" in reference.description
    # dashboard access info is included
    import config as cfg

    public_url = cfg.config.dashboard.public_url
    field_values = " ".join(field.value for field in reference.fields)
    assert public_url in field_values
    # the invite link is advertised as the SHORT branded URL, never the long
    # discord.com/oauth2 link
    assert f"{public_url}/invite" in field_values
    assert "discord.com/oauth2" not in field_values
    # ephemeral confirmation sent in-channel
    assert interaction.response.messages and "Sent you a DM" in interaction.response.messages[0]


@pytest.mark.asyncio
async def test_help_falls_back_when_dms_disabled():
    from unittest.mock import MagicMock

    captured = _CaptureSend(
        exc=discord.Forbidden(response=MagicMock(status=403), message="no")
    )
    bot = SimpleNamespace(tree=_build_tree())
    module = _make_module(bot)
    interaction = _Interaction(captured.send)

    await module._make_help_command().callback(interaction)

    assert interaction.response.messages and "couldn't dm you" in interaction.response.messages[0].lower()
