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


@pytest.mark.asyncio
async def test_announce_slash_command_embeds_image_url_in_embed_mode():
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
        title="Update",
        message="New build deployed.",
        embed=True,
        image_url="https://example.com/screenshot.png",
    )

    channel.send.assert_awaited_once()
    assert channel.send.await_args.args == ()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(sent_embed, discord.Embed)
    assert sent_embed.title == "Update"
    assert sent_embed.image.url == "https://example.com/screenshot.png"


@pytest.mark.asyncio
async def test_announce_slash_command_sends_text_with_image_embed_when_not_embed():
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
        message="Patch notes linked below.",
        embed=False,
        image_url="https://example.com/patch.png",
    )

    channel.send.assert_awaited_once()
    assert channel.send.await_args.kwargs["content"] == "Patch notes linked below."
    img_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(img_embed, discord.Embed)
    assert img_embed.image.url == "https://example.com/patch.png"


@pytest.mark.asyncio
async def test_announce_slash_command_appends_watch_video_link_in_embed():
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
        message="New trailer.",
        embed=True,
        video_url="https://www.youtube.com/watch?v=demo",
    )

    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(sent_embed, discord.Embed)
    assert sent_embed.description == "New trailer.\n\n[Watch Video](https://www.youtube.com/watch?v=demo)"
