"""The dashboard must show the running app's version, not a placeholder."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import bark_version


def _dashboard_app(bot):
    from dashboard import create_app

    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    return create_app(bot).app


@pytest.mark.asyncio
async def test_dashboard_pages_render_the_app_version():
    """Both the landing page and the authenticated shell show the version, so a
    silently degraded version (see test_version.py) would be visible here."""
    bot = MagicMock()
    bot.guilds = []
    app = _dashboard_app(bot)
    version = bark_version.__version__

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/", "/dashboard"):
            response = await client.get(path)
            assert response.status_code == 200, path
            assert version in response.text, f"{path} does not show version {version}"
