"""Database backup service — consistent SQLite snapshots.

Uses the sqlite3 stdlib backup API (run in a worker thread) so the live DB
can be snapshotted safely while the bot holds it open. Snapshots land in
``<data_dir>/backups/`` as ``bark-backup-<utc timestamp>.db``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger("bark.backup")

# bark-backup-YYYYMMDD-HHMMSS-ffffff.db
BACKUP_RE = re.compile(r"^bark-backup-\d{8}-\d{6}-\d{6}\.db$")
RESTORE_DB_NAME = "restore-pending.db"
RESTORE_MARKER_NAME = "restore-pending.json"
_RESTORE_STAGE_LOCK = threading.Lock()


class InvalidBackupError(ValueError):
    """Raised when an uploaded file is not a usable Bark SQLite backup."""


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


def _restore_dir() -> Path:
    directory = Path(config.data_dir) / "restore"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_database_backup(path: Path) -> dict:
    """Validate SQLite structure and Bark identity without modifying the file."""
    if not path.is_file() or path.stat().st_size < 16:
        raise InvalidBackupError("Backup is not a SQLite database")
    with path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\x00":
            raise InvalidBackupError("Backup is not a SQLite database")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise InvalidBackupError(f"SQLite integrity check failed: {integrity}")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            migrations: list[str] = []
            if "schema_migrations" in tables:
                migrations = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ]
                # Import lazily so the ordinary backup path stays lightweight.
                from database.migrations import MIGRATIONS

                known = {version for version, _action in MIGRATIONS}
                unknown = sorted(set(migrations) - known)
                if unknown:
                    raise InvalidBackupError(
                        "Database backup was created by a newer or incompatible "
                        f"Bark release (unknown migration: {unknown[-1]})"
                    )
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise InvalidBackupError(f"Backup is not a valid SQLite database: {exc}") from exc
    if "guilds" not in tables:
        raise InvalidBackupError("SQLite file is not a Bark backup (guilds table missing)")
    return {
        "tables": sorted(tables),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "schema_version": migrations[-1] if migrations else "legacy",
    }


def validate_live_database_foreign_keys() -> None:
    """Reject a migrated restore if it still contains dangling references."""
    path = _source_db_path()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        violations = connection.execute("PRAGMA foreign_key_check").fetchmany(10)
        if violations:
            sample = ", ".join(f"{row[0]}:{row[1]}" for row in violations[:3])
            raise InvalidBackupError(
                f"Restored database failed foreign-key validation ({sample})"
            )
    finally:
        connection.close()


def stage_database_restore_sync(source: Path, *, source_name: str) -> dict:
    """Validate and atomically stage a v0.2/v0.3 database for next startup.

    The live database is never touched by the upload request. Startup applies
    the staged file before opening SQLAlchemy, then normal ordered migrations
    bring older schemas forward.
    """
    _source_db_path()
    metadata = validate_database_backup(source)
    directory = _restore_dir()
    token = uuid.uuid4().hex
    staged_tmp = directory / f"{RESTORE_DB_NAME}.{token}.tmp"
    marker_tmp = directory / f"{RESTORE_MARKER_NAME}.{token}.tmp"
    staged = directory / RESTORE_DB_NAME
    marker = directory / RESTORE_MARKER_NAME
    try:
        shutil.copyfile(source, staged_tmp)
        # Validate the candidate before it can replace a previously valid pair.
        metadata = validate_database_backup(staged_tmp)
        payload = {
            **metadata,
            "source_name": Path(source_name).name,
            "staged_at": datetime.now(timezone.utc).isoformat(),
            "restart_required": True,
        }
        marker_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # Prevent simultaneous owner uploads from crossing DB and marker pairs.
        with _RESTORE_STAGE_LOCK:
            os.replace(staged_tmp, staged)
            os.replace(marker_tmp, marker)
    finally:
        staged_tmp.unlink(missing_ok=True)
        marker_tmp.unlink(missing_ok=True)
    logger.warning("Staged database restore from %s for next restart", payload["source_name"])
    return payload


async def stage_database_restore(source: Path, *, source_name: str) -> dict:
    return await asyncio.to_thread(
        stage_database_restore_sync, source, source_name=source_name
    )


def has_pending_database_restore() -> bool:
    directory = _restore_dir()
    return (directory / RESTORE_DB_NAME).is_file() and (
        directory / RESTORE_MARKER_NAME
    ).is_file()


def _quarantine_pending_restore(*paths: Path, reason: str) -> None:
    """Move inconsistent restore artifacts aside so Bark can still boot."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    moved: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        quarantine = path.parent / f"restore-quarantine-{timestamp}-{path.name}"
        try:
            os.replace(path, quarantine)
            moved.append(str(quarantine))
        except OSError:
            logger.exception("Could not quarantine pending restore artifact %s", path)
    logger.error("Ignored invalid pending database restore: %s; quarantined=%s", reason, moved)


def apply_pending_restore_sync() -> dict | None:
    """Apply a validated staged database before SQLAlchemy opens the live DB.

    A consistent copy of the previous live database is retained in backups as
    an explicit rollback artifact. Ordered migrations run immediately after
    this function from ``app.main``.
    """
    directory = _restore_dir()
    marker = directory / RESTORE_MARKER_NAME
    staged = directory / RESTORE_DB_NAME
    if not marker.is_file() and not staged.is_file():
        return None
    if not marker.is_file() or not staged.is_file():
        _quarantine_pending_restore(marker, staged, reason="incomplete artifact pair")
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _quarantine_pending_restore(marker, staged, reason=f"invalid marker: {exc}")
        return None
    try:
        metadata = validate_database_backup(staged)
    except (InvalidBackupError, OSError) as exc:
        _quarantine_pending_restore(marker, staged, reason=f"invalid database: {exc}")
        return None
    if payload.get("sha256") != metadata["sha256"]:
        _quarantine_pending_restore(marker, staged, reason="checksum mismatch")
        return None

    try:
        live = _source_db_path()
    except ValueError as exc:
        _quarantine_pending_restore(marker, staged, reason=str(exc))
        return None
    live.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    rollback: Path | None = _backup_dir() / f"bark-backup-{timestamp}.db"
    if live.is_file():
        try:
            _snapshot_sync(live, rollback)
        except sqlite3.DatabaseError:
            # A corrupt live DB is a primary reason an owner may need restore.
            # Keep its raw bytes for forensics without blocking recovery.
            rollback.unlink(missing_ok=True)
            shutil.copy2(live, rollback)
            logger.exception("Live database was corrupt; retained a raw rollback copy")
    else:
        rollback = None

    # WAL sidecars belong to the old file and must never be replayed over the
    # replacement. At this point startup has not created the SQLAlchemy engine.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{live}{suffix}")
        sidecar.unlink(missing_ok=True)
    os.replace(staged, live)
    applied = directory / f"restore-applied-{timestamp}.json"
    payload.update(
        {
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "rollback_path": str(rollback) if rollback is not None else "",
            "applied_marker": str(applied),
        }
    )
    try:
        applied.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        # The swap succeeded; an audit-marker failure must not block migrations
        # or leave startup retrying the same restore indefinitely.
        logger.exception("Could not write applied database restore marker")
    finally:
        marker.unlink(missing_ok=True)
    logger.warning("Applied staged database restore; rollback=%s", rollback)
    return payload


def rollback_applied_restore_sync(applied: dict, *, reason: str) -> bool:
    """Restore the pre-import snapshot when migrations reject an uploaded DB."""
    live = _source_db_path()
    rollback_value = str(applied.get("rollback_path") or "")
    rollback = Path(rollback_value) if rollback_value else None
    if rollback is not None:
        validate_database_backup(rollback)
        replacement = _restore_dir() / "restore-rollback.tmp"
        shutil.copy2(rollback, replacement)
        validate_database_backup(replacement)
        for suffix in ("-wal", "-shm"):
            Path(f"{live}{suffix}").unlink(missing_ok=True)
        os.replace(replacement, live)
    else:
        # First-install restores have no previous database to recover.
        live.unlink(missing_ok=True)

    status = dict(applied)
    status.update(
        {
            "status": "rolled_back",
            "rollback_reason": reason,
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    marker_value = str(applied.get("applied_marker") or "")
    marker = Path(marker_value) if marker_value else _restore_dir() / "restore-rolled-back.json"
    marker.write_text(json.dumps(status, indent=2), encoding="utf-8")
    logger.critical("Database restore rolled back after startup failure: %s", reason)
    return True


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
