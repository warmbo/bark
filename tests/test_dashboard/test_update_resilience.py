"""Resilience tests for the post-update disconnect scenarios (2026-08-10)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import app as app_module


def test_ready_watchdog_exits_when_bot_never_connects(monkeypatch):
    """A hung gateway handshake must exit so systemd can restart the service."""
    exits = []
    monkeypatch.setattr(app_module.os, "_exit", lambda code: exits.append(code))

    bot = MagicMock()

    async def never_ready():
        await asyncio.sleep(999)

    bot.wait_until_ready = never_ready

    asyncio.run(app_module.bot_ready_watchdog(bot, timeout=0.05))
    assert exits == [1], "watchdog must exit(1) when the bot never becomes ready"


def test_ready_watchdog_returns_when_ready(monkeypatch):
    """A normally connecting bot must never be killed."""
    exits = []
    monkeypatch.setattr(app_module.os, "_exit", lambda code: exits.append(code))

    bot = MagicMock()

    async def ready():
        return None

    bot.wait_until_ready = ready

    asyncio.run(app_module.bot_ready_watchdog(bot, timeout=5))
    assert exits == [], "watchdog must not exit when the bot connects"


@pytest.fixture
def offline_app(db, monkeypatch):
    from dashboard import create_app

    import config as cfg

    monkeypatch.setattr(cfg.config.oauth2, "owner_discord_ids", {"42"})
    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    bot.get_guild.return_value = None  # bot offline -> every guild lookup misses
    bot.is_ready.return_value = False
    return create_app(bot), bot


@pytest.mark.asyncio
async def test_guild_page_shows_offline_state_when_bot_not_ready(offline_app):
    """While the bot is not connected, guild pages explain instead of 404ing."""
    dashboard, bot = offline_app
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app), base_url="http://test"
    ) as client:
        response = await client.get("/guild/221627370375872512")
    assert response.status_code == 200
    assert "isn't available right now" in response.text
    assert "Bark hasn't connected to Discord yet" in response.text


@pytest.mark.asyncio
async def test_guild_page_404s_when_ready_but_not_member(offline_app):
    """Once ready, a genuinely absent guild still 404s (not an offline page)."""
    dashboard, bot = offline_app
    bot.is_ready.return_value = True
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app), base_url="http://test"
    ) as client:
        response = await client.get("/guild/221627370375872512")
    assert response.status_code == 404


def test_home_module_exports_watchdog_timeout():
    assert app_module.BOT_CONNECT_TIMEOUT == 90
