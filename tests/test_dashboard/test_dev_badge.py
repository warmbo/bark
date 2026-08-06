"""The DEV VERSION watermark renders only when BARK_DEV_BADGE is enabled."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app(monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}

    return create_app(bot)


@pytest.mark.asyncio
async def test_landing_page_shows_dev_badge_when_enabled(app, monkeypatch):
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", True)
    async with AsyncClient(
        transport=ASGITransport(app=app.app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'class="dev-badge-overlay"' in response.text
    assert "DEV VERSION" in response.text


@pytest.mark.asyncio
async def test_landing_page_hides_dev_badge_when_disabled(app, monkeypatch):
    import config

    monkeypatch.setattr(config.config.instance, "dev_badge", False)
    async with AsyncClient(
        transport=ASGITransport(app=app.app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'class="dev-badge-overlay"' not in response.text
