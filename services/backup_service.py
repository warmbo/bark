"""Database backup service — consistent SQLite snapshots.

Uses the sqlite3 stdlib backup API (run in a worker thread) so the live DB
can be snapshotted safely while the bot holds it open. Snapshots land in
``<data_dir>/backups/`` as ``bark-backup-<utc timestamp>.db``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger("bark.backup")

# bark-backup-YYYYMMDD-HHMMSS-ffffff.db
BACKUP_RE = re.compile(r"^bark-backup-\d{8}-\d{6}-\d{6}\.db$")


def _backup_dir() -> Path:
    directory = Path(config.data_dir) / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _source_db_path() -> Path:
    """Resolve the sqlite database file from the configured URL.

    Mirrors database/engine.py: relative sqlite paths are resolved against
    ``config.data_dir`` (that is where the engine actually opens the file).
    """
    url = config.database.url
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        raise ValueError(
            f"Database backups require a sqlite database (got: {url.split('://')[0]})"
        )
    rel = url[len(prefix) :]
    path = Path(rel)
    if path.is_absolute():
        return path
    return Path(config.data_dir) / path


def _snapshot_sync(src: Path, dst: Path) -> None:
    """Copy a consistent snapshot of src into dst using the sqlite backup API."""
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(dst)
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def create_backup_sync() -> dict:
    """Create a timestamped DB snapshot and return its metadata.

    Synchronous twin of :func:`create_backup` for worker-thread contexts
    (e.g. the pre-update backup inside ``apply_update``).
    """
    src = _source_db_path()
    if not src.is_file():
        raise FileNotFoundError(f"Database file not found: {src}")
    name = f"bark-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.db"
    dst = _backup_dir() / name
    _snapshot_sync(src, dst)
    size = dst.stat().st_size
    logger.info("Created database backup %s (%d bytes)", name, size)
    return {
        "filename": name,
        "size": size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def create_backup() -> dict:
    """Create a timestamped DB snapshot and return its metadata."""
    return await asyncio.to_thread(create_backup_sync)


def list_backups() -> list[dict]:
    """List stored backups, newest first."""
    entries: list[dict] = []
    directory = _backup_dir()
    if not directory.is_dir():
        return entries
    for path in sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or not BACKUP_RE.match(path.name):
            continue
        entries.append(
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "created_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return entries
