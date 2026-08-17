"""Tests for the database backup service."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from services.backup_service import BACKUP_RE, create_backup, list_backups


@pytest.mark.asyncio
async def test_create_backup_makes_valid_snapshot(db):
    entry = await create_backup()
    assert BACKUP_RE.match(entry["filename"])
    assert entry["size"] > 0
    assert entry["created_at"]

    # Snapshot must be a valid sqlite file with the real schema.
    from services.backup_service import _backup_dir

    path = _backup_dir() / entry["filename"]
    assert path.is_file()
    con = sqlite3.connect(path)
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        con.close()
    assert any("guilds" in t for t in [r[0] for r in tables])


@pytest.mark.asyncio
async def test_list_backups_newest_first(db):
    first = await create_backup()
    second = await create_backup()
    entries = list_backups()
    assert [e["filename"] for e in entries] == [second["filename"], first["filename"]]
    assert all(e["size"] > 0 for e in entries)


def test_backup_filename_regex():
    assert BACKUP_RE.match("bark-backup-20260809-171343-123456.db")
    assert not BACKUP_RE.match("passwd")
    assert not BACKUP_RE.match("bark-backup.db")
    assert not BACKUP_RE.match("bark-backup-20260809-171343-123456.db/../../etc/passwd")
    assert not BACKUP_RE.match("..%2F..%2Fetc%2Fpasswd")


def test_source_db_path_parses_sqlite_url(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(
        config.config.database, "url", f"sqlite+aiosqlite:///{tmp_path}/x.db"
    )
    from services.backup_service import _source_db_path

    assert _source_db_path() == tmp_path / "x.db"


def test_stage_database_restore_accepts_legacy_bark_database(monkeypatch, tmp_path):
    """A v0.2 SQLite backup can be validated and staged for next startup."""
    import config
    from services.backup_service import stage_database_restore_sync

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    legacy = tmp_path / "legacy-v0.2.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE guilds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id VARCHAR(32) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL
        );
        INSERT INTO guilds (discord_id, name) VALUES ('123', 'Legacy Guild');
        CREATE TABLE module_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id VARCHAR(32) NOT NULL,
            module_name VARCHAR(64) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100,
            config TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    connection.commit()
    connection.close()

    result = stage_database_restore_sync(legacy, source_name="my-old-bark.db")

    assert result["restart_required"] is True
    assert result["source_name"] == "my-old-bark.db"
    staged = tmp_path / "restore" / "restore-pending.db"
    marker = tmp_path / "restore" / "restore-pending.json"
    assert staged.read_bytes()[:16] == b"SQLite format 3\x00"
    metadata = json.loads(marker.read_text())
    assert metadata["sha256"] == result["sha256"]
    assert "guilds" in metadata["tables"]


def test_stage_database_restore_rejects_non_sqlite(monkeypatch, tmp_path):
    import config
    from services.backup_service import InvalidBackupError, stage_database_restore_sync

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    invalid = tmp_path / "fake.db"
    invalid.write_text("not a sqlite database")

    with pytest.raises(InvalidBackupError, match="SQLite"):
        stage_database_restore_sync(invalid, source_name="fake.db")


def test_stage_database_restore_rejects_newer_migration(monkeypatch, tmp_path):
    import config
    from services.backup_service import InvalidBackupError, stage_database_restore_sync

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    newer = tmp_path / "newer.db"
    with sqlite3.connect(newer) as connection:
        connection.execute("CREATE TABLE guilds (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO schema_migrations VALUES ('9999_future_schema')")

    with pytest.raises(InvalidBackupError, match="newer or incompatible"):
        stage_database_restore_sync(newer, source_name="future.db")


def test_live_database_foreign_key_validation_rejects_dangling_rows(monkeypatch, tmp_path):
    import config
    from services.backup_service import InvalidBackupError, validate_live_database_foreign_keys

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    monkeypatch.setattr(config.config.database, "url", "sqlite+aiosqlite:///bark.db")
    path = tmp_path / "bark.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE guilds (id INTEGER PRIMARY KEY);
            CREATE TABLE module_configs (
                id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL REFERENCES guilds(id)
            );
            INSERT INTO module_configs VALUES (1, 999);
            """
        )

    with pytest.raises(InvalidBackupError, match="foreign-key validation"):
        validate_live_database_foreign_keys()


def test_apply_pending_restore_swaps_database_and_keeps_rollback(monkeypatch, tmp_path):
    import config
    from services.backup_service import (
        apply_pending_restore_sync,
        stage_database_restore_sync,
    )

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    monkeypatch.setattr(config.config.database, "url", "sqlite+aiosqlite:///bark.db")

    current = tmp_path / "bark.db"
    con = sqlite3.connect(current)
    con.execute("CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id TEXT, name TEXT)")
    con.execute("INSERT INTO guilds VALUES (1, 'old', 'Current')")
    con.commit()
    con.close()

    incoming = tmp_path / "incoming.db"
    con = sqlite3.connect(incoming)
    con.execute("CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id TEXT, name TEXT)")
    con.execute("INSERT INTO guilds VALUES (1, 'new', 'Restored')")
    con.commit()
    con.close()
    stage_database_restore_sync(incoming, source_name="v0.2.db")

    result = apply_pending_restore_sync()

    assert result is not None
    assert Path(result["rollback_path"]).is_file()
    con = sqlite3.connect(current)
    try:
        assert con.execute("SELECT name FROM guilds").fetchone()[0] == "Restored"
    finally:
        con.close()
    assert not (tmp_path / "restore" / "restore-pending.json").exists()


def test_failed_migration_can_roll_back_applied_restore(monkeypatch, tmp_path):
    import config
    from services.backup_service import (
        apply_pending_restore_sync,
        rollback_applied_restore_sync,
        stage_database_restore_sync,
    )

    monkeypatch.setattr(config.config, "data_dir", tmp_path)
    monkeypatch.setattr(config.config.database, "url", "sqlite+aiosqlite:///bark.db")
    current = tmp_path / "bark.db"
    incoming = tmp_path / "incoming.db"
    for path, name in ((current, "Current"), (incoming, "Restored")):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE guilds (id INTEGER PRIMARY KEY, discord_id TEXT, name TEXT)"
            )
            connection.execute("INSERT INTO guilds VALUES (1, '1', ?)", (name,))

    stage_database_restore_sync(incoming, source_name="v0.2.db")
    applied = apply_pending_restore_sync()
    assert applied is not None

    assert rollback_applied_restore_sync(applied, reason="migration failed") is True
    with sqlite3.connect(current) as connection:
        assert connection.execute("SELECT name FROM guilds").fetchone()[0] == "Current"

    status = json.loads(Path(applied["applied_marker"]).read_text())
    assert status["status"] == "rolled_back"
    assert status["rollback_reason"] == "migration failed"
