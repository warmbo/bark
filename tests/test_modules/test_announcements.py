"""Announcements module regression tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from modules.announcements.module import AnnouncementsModule, _parse_embed_color


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


@pytest.mark.asyncio
async def test_post_announcement_maps_media_picker_payload(db, monkeypatch):
    """The dashboard media picker sends [{'type','url'}] items that map to embed image + watch-video."""
    import base64
    import json
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from itsdangerous import TimestampSigner

    import config
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.permissions import DashboardUser
    from services.bark_context import BarkContext
    from services.dashboard_access import replace_user_guild_access

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Owner", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x8)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"announcements": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    guild = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel
    bot.get_guild.return_value = guild

    dashboard = create_app(bot)
    module = AnnouncementsModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    session = {
        "user": {"id": "42", "username": "Owner"},
        "role": "admin",
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    cookie = TimestampSigner("test_secret_key").sign(payload).decode("utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/announcements/post",
            json={
                "channel_id": "55",
                "message": "Check this out",
                "as_embed": True,
                "media": [
                    {"type": "image", "url": "https://example.com/a.png"},
                    {"type": "video", "url": "https://youtube.com/watch?v=abc"},
                ],
            },
        )

    assert response.status_code == 200
    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(sent_embed, discord.Embed)
    assert sent_embed.image.url == "https://example.com/a.png"
    assert "Watch Video" in (sent_embed.description or "")
    assert "https://youtube.com/watch?v=abc" in (sent_embed.description or "")


def test_parse_embed_color_accepts_hex_and_falls_back_to_blurple():
    """#RRGGBB (with or without the hash) maps to the exact 24-bit color;
    missing or malformed values degrade to blurple without raising."""
    assert _parse_embed_color("#FF5500").value == 0xFF5500
    assert _parse_embed_color("ff5500").value == 0xFF5500
    assert _parse_embed_color("#FF5500").value == discord.Color(0xFF5500).value
    # Invalid / empty inputs fall back to blurple.
    assert _parse_embed_color(None) == discord.Color.blurple()
    assert _parse_embed_color("") == discord.Color.blurple()
    assert _parse_embed_color("red") == discord.Color.blurple()
    assert _parse_embed_color("#12345") == discord.Color.blurple()


def test_full_width_spacer_has_large_intrinsic_width():
    """The invisible spacer must be wider than any small image so Discord
    expands the embed to its maximum width (the 1px height keeps it hidden)."""
    import struct
    from pathlib import Path

    spacer = Path(__file__).resolve().parents[2] / "dashboard" / "static" / "img" / "spacer-wide.png"
    data = spacer.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width >= 1600, "spacer intrinsic width must exceed Discord's max embed width"
    assert height == 1, "spacer must stay invisible (1px tall)"


@pytest.mark.asyncio
async def test_announce_slash_command_uses_custom_embed_color():
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
        title="Rally",
        message="Game night!",
        embed=True,
        color="#FF5500",
    )

    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert sent_embed.color.value == 0xFF5500


@pytest.mark.asyncio
async def test_post_announcement_applies_embed_color(db, monkeypatch):
    """The dashboard color picker value flows through to the sent embed color."""
    import base64
    import json
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from itsdangerous import TimestampSigner

    import config
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.permissions import DashboardUser
    from services.bark_context import BarkContext
    from services.dashboard_access import replace_user_guild_access

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Owner", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x8)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"announcements": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    guild = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel
    bot.get_guild.return_value = guild

    dashboard = create_app(bot)
    module = AnnouncementsModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    session = {
        "user": {"id": "42", "username": "Owner"},
        "role": "admin",
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    cookie = TimestampSigner("test_secret_key").sign(payload).decode("utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/announcements/post",
            json={
                "channel_id": "55",
                "message": "Colorful update",
                "as_embed": True,
                "embed_color": "#22C55E",
            },
        )

    assert response.status_code == 200
    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert sent_embed.color.value == 0x22C55E


@pytest.mark.asyncio
async def test_post_announcement_invalid_color_falls_back_to_blurple(db, monkeypatch):
    """A malformed color from a stale dashboard must not break posting."""
    import base64
    import json
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from itsdangerous import TimestampSigner

    import config
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.permissions import DashboardUser
    from services.bark_context import BarkContext
    from services.dashboard_access import replace_user_guild_access

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Owner", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x8)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"announcements": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    guild = MagicMock()
    channel = MagicMock()
    channel.send = AsyncMock()
    guild.get_channel.return_value = channel
    bot.get_guild.return_value = guild

    dashboard = create_app(bot)
    module = AnnouncementsModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    session = {
        "user": {"id": "42", "username": "Owner"},
        "role": "admin",
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    cookie = TimestampSigner("test_secret_key").sign(payload).decode("utf-8")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/announcements/post",
            json={
                "channel_id": "55",
                "message": "Broken color",
                "as_embed": True,
                "embed_color": "not-a-color",
            },
        )

    assert response.status_code == 200
    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert sent_embed.color == discord.Color.blurple()


@pytest.mark.asyncio
async def test_announce_embed_without_image_gets_full_width_spacer():
    """Text-only embeds attach an invisible wide spacer so Discord renders them full width."""

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
        message="Plain text announcement.",
        embed=True,
    )

    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(sent_embed, discord.Embed)
    assert sent_embed.image.url is not None
    assert sent_embed.image.url.endswith("/static/img/spacer-wide.png")
    # Three inline NBSP fields survive Discord's sanitizer (unlike U+200B) and
    # force the full-width row layout.
    assert len(sent_embed.fields) == 3
    assert all(f.inline for f in sent_embed.fields)
    assert all(f.name == "\u00a0" and f.value == "\u00a0" for f in sent_embed.fields)
    # The footer is padded with invisible width so the embed can never hug a
    # small image or short text.
    assert sent_embed.footer.text is not None
    assert len(sent_embed.footer.text) > 100
    assert sent_embed.footer.text.endswith("\u00a0")


@pytest.mark.asyncio
async def test_announce_embed_with_image_does_not_use_spacer():
    """Real images keep the embed image; the full-width triggers remain."""
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
        message="With an image.",
        embed=True,
        image_url="https://example.com/real.png",
    )

    channel.send.assert_awaited_once()
    sent_embed = channel.send.await_args.kwargs["embed"]
    assert sent_embed.image.url == "https://example.com/real.png"
    # Full-width trigger still present even with a real image.
    assert len(sent_embed.fields) == 3
