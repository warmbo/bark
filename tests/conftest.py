"""
Pytest configuration for Bark.
"""

import pytest


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch, tmp_path):
    """Set up test environment variables and config overrides."""
    db_path = tmp_path / "test_bark.db"
    monkeypatch.setenv("BARK_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("BARK_BOT_TOKEN", "test_token_12345")
    monkeypatch.setenv("BARK_SECRET_KEY", "test_secret_key")
    monkeypatch.setenv("BARK_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))

    # Directly update the config singleton
    import config as cfg

    cfg.config.database.url = f"sqlite+aiosqlite:///{db_path}"
    cfg.config.data_dir = tmp_path
    cfg.config.bot.token = "test_token_12345"
    cfg.config.dashboard.secret_key = "test_secret_key"
    cfg.config.logging.level = "ERROR"

    # High rate limit for testing — prevents throttling in persistence tests
    cfg.config.dashboard.rate_limit_per_minute = 3000

    # Reset the database engine singleton so it picks up the new config
    import database.engine

    database.engine._engine = None
    database.engine._session_factory = None

    from services.response import reset_permission_state

    reset_permission_state()
    yield
    reset_permission_state()


@pytest.fixture(scope="function")
async def db():
    """Initialize test database and tear down after."""
    from database.engine import close_db, init_db

    await init_db()
    yield
    await close_db()
