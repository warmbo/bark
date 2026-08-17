"""Application startup and shutdown lifecycle tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app
from config import ConfigurationError


@pytest.mark.asyncio
async def test_main_enters_setup_mode_without_token(monkeypatch):
    """An unconfigured instance boots the setup wizard, never the bot/DB."""
    monkeypatch.setattr(app.config.bot, "token", "")
    init_db = AsyncMock(side_effect=AssertionError("database startup must not run"))
    monkeypatch.setattr(app, "init_db", init_db)
    run_setup = AsyncMock()
    monkeypatch.setattr("dashboard.setup_app.run_setup", run_setup)

    await app.main()

    run_setup.assert_awaited_once()
    init_db.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_validates_configuration_when_token_present(monkeypatch):
    """With a token configured, startup validation still runs (and its
    ConfigurationError propagates before the database starts)."""
    monkeypatch.setattr(app.config.bot, "token", "test_token_12345")
    monkeypatch.setattr(
        app.config,
        "validate_startup",
        MagicMock(side_effect=ConfigurationError("BARK_BOT_TOKEN is required")),
    )
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


@pytest.mark.asyncio
async def test_main_applies_pending_database_restore_before_init(monkeypatch):
    calls = []
    bot = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    dashboard = SimpleNamespace(run=AsyncMock())

    monkeypatch.setattr(app.config, "validate_startup", MagicMock())
    monkeypatch.setattr(
        app,
        "apply_pending_restore_sync",
        MagicMock(side_effect=lambda: calls.append("restore")),
    )
    monkeypatch.setattr(app, "init_db", AsyncMock(side_effect=lambda: calls.append("init")))
    monkeypatch.setattr(app, "close_db", AsyncMock())
    monkeypatch.setattr(app, "BarkBot", MagicMock(return_value=bot))
    monkeypatch.setattr(app, "create_app", MagicMock(return_value=dashboard))

    await app.main()

    assert calls[:2] == ["restore", "init"]


@pytest.mark.asyncio
async def test_main_rolls_back_restore_when_migration_fails(monkeypatch):
    restore = {"rollback_path": "/tmp/rollback.db"}
    rollback = MagicMock()
    close_db = AsyncMock()
    monkeypatch.setattr(app.config, "validate_startup", MagicMock())
    monkeypatch.setattr(app, "apply_pending_restore_sync", MagicMock(return_value=restore))
    monkeypatch.setattr(app, "rollback_applied_restore_sync", rollback)
    monkeypatch.setattr(app, "close_db", close_db)
    monkeypatch.setattr(app, "init_db", AsyncMock(side_effect=RuntimeError("bad migration")))

    with pytest.raises(RuntimeError, match="bad migration"):
        await app.main()

    close_db.assert_awaited_once()
    rollback.assert_called_once_with(restore, reason="bad migration")


@pytest.mark.asyncio
async def test_main_rolls_back_restore_when_foreign_key_validation_fails(monkeypatch):
    restore = {"rollback_path": "/tmp/rollback.db"}
    rollback = MagicMock()
    close_db = AsyncMock()
    monkeypatch.setattr(app.config, "validate_startup", MagicMock())
    monkeypatch.setattr(app, "apply_pending_restore_sync", MagicMock(return_value=restore))
    monkeypatch.setattr(app, "rollback_applied_restore_sync", rollback)
    monkeypatch.setattr(app, "close_db", close_db)
    monkeypatch.setattr(app, "init_db", AsyncMock())
    monkeypatch.setattr(
        app,
        "validate_live_database_foreign_keys",
        MagicMock(side_effect=RuntimeError("dangling foreign key")),
    )

    with pytest.raises(RuntimeError, match="dangling foreign key"):
        await app.main()

    close_db.assert_awaited_once()
    rollback.assert_called_once_with(restore, reason="dangling foreign key")
