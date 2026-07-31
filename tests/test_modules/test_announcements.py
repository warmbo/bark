"""Announcements module regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from modules.announcements.module import AnnouncementsModule


@pytest.mark.asyncio
async def test_announce_slash_command_sends_embed_with_embed_keyword():
    module = AnnouncementsModule(MagicMock())
    command = module._make_announce_command()
    interaction = SimpleNamespace(
        guild=SimpleNamespace(me=MagicMock()),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    channel = MagicMock()
    channel.permissions_for.return_value.send_messages = True
    channel.send = AsyncMock()

    await command.callback(
        interaction,
        channel,
        title="Maintenance",
        message="Brief outage",
        embed=True,
    )

    channel.send.assert_awaited_once()
    assert channel.send.await_args.args == ()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(sent_embed, discord.Embed)
    assert sent_embed.title == "Maintenance"
    assert sent_embed.description == "Brief outage"
