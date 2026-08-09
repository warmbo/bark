"""Tests for the database backup service."""

from __future__ import annotations

import sqlite3

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
