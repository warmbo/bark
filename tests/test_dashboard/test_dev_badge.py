"""The DEV VERSION watermark renders only when BARK_DEV_BADGE is enabled."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "dashboard" / "templates" / "pages"


def test_every_page_template_carries_the_dev_badge():
    """Every page must either extend base.html (which includes the badge) or
    include components/dev_badge.html directly — no page can bypass it."""
    offenders = []
    for path in sorted(PAGES.glob("*.html")):
        src = path.read_text(encoding="utf-8")
        if 'extends "base.html"' in src:
            continue
        if "components/dev_badge.html" in src:
            continue
        offenders.append(path.name)
    assert offenders == [], f"pages missing the dev-badge include: {offenders}"


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
    assert "dev-badge-corner" not in response.text  # corner badge removed
    assert "DEV VERSION" in response.text  # tiled pattern (inline style data URI)


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
