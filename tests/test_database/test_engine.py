"""Database engine safety tests."""

from database.engine import _safe_database_url


def test_database_url_logging_redacts_password():
    rendered = _safe_database_url("postgresql+asyncpg://bark:super-secret@db/bark")

    assert "super-secret" not in rendered
    assert "***" in rendered
