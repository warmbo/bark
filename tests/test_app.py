"""Application startup and shutdown lifecycle tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app
from config import ConfigurationError


@pytest.mark.asyncio
async def test_main_validates_configuration_before_database_start(monkeypatch):
    monkeypatch.setattr(app.config.bot, "token", "")
    init_db = AsyncMock(side_effect=AssertionError("database startup must not run"))
    monkeypatch.setattr(app, "init_db", init_db)

    with pytest.raises(ConfigurationError, match="BARK_BOT_TOKEN"):
        await app.main()

    init_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_closes_bot_and_database_after_services_stop(monkeypatch):
    bot = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    dashboard = SimpleNamespace(run=AsyncMock())
    close_db = AsyncMock()

    monkeypatch.setattr(app.config, "validate_startup", MagicMock())
    monkeypatch.setattr(app, "init_db", AsyncMock())
    monkeypatch.setattr(app, "close_db", close_db)
    monkeypatch.setattr(app, "BarkBot", MagicMock(return_value=bot))
    monkeypatch.setattr(app, "create_app", MagicMock(return_value=dashboard))

    await app.main()

    bot.close.assert_awaited_once()
    close_db.assert_awaited_once()
