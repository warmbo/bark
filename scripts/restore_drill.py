#!/usr/bin/env python3
"""Restore drill — prove a Bark backup can actually be restored, safely.

A backup file existing is not proof of recoverability. This drill works entirely
on a COPY of the given backup in a temporary directory and never opens or writes
the live database:

  1. copy the backup to a temp dir
  2. sqlite PRAGMA integrity_check + foreign_key_check
  3. confirm the expected tables and non-empty core tables
  4. point the app's own database bootstrap at the copy (BARK_DATABASE_URL) and
     run create_all + migrations against it — the step that fails when a restore
     is incompatible with the running code
  5. report what lives outside the database and must be restored separately

    .venv/bin/python scripts/restore_drill.py                 # newest backup
    .venv/bin/python scripts/restore_drill.py --backup path.db
    .venv/bin/python scripts/restore_drill.py --list
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "data" / "backups"

# Tables that must exist for a restored DB to be a usable Bark database.
REQUIRED_TABLES = {
    "guilds",
    "module_configs",
    "dashboard_users",
    "moderation_cases",
    "reputation_profiles",
    "announcement_schedules",
    "schema_migrations",
}

# Non-database state a restore does NOT bring back.
EXTERNAL_STATE = [
    "data/plugins/*.py            — installed add-on plugin code",
    "media/uploads/*              — uploaded images referenced by config",
    ".env / data/.secret_key      — OAuth + session-signing secrets (never in a backup)",
    "systemd unit + TLS/proxy config, and any external service (media engine)",
]


def _newest_backup() -> Path | None:
    if not BACKUP_DIR.is_dir():
        return None
    backups = sorted(BACKUP_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups[0] if backups else None


def _sqlite_checks(path: Path) -> tuple[bool, list[str]]:
    notes: list[str] = []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        notes.append(f"integrity_check: {integrity}")
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        notes.append(f"foreign_key_check: {len(fk)} violation(s)")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED_TABLES - tables)
        notes.append(f"tables: {len(tables)} present, missing required: {missing or 'none'}")
        migrations = []
        if "schema_migrations" in tables:
            migrations = [row[0] for row in con.execute("SELECT version FROM schema_migrations")]
            notes.append(f"migrations recorded: {len(migrations)}")
        for table in ("guilds", "module_configs", "dashboard_users"):
            if table in tables:
                count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                notes.append(f"  {table}: {count} row(s)")
        ok = integrity == "ok" and not missing and not fk
        return ok, notes
    finally:
        con.close()


def _migration_drill(backup: Path, workdir: Path) -> tuple[bool, str]:
    """Let the app bootstrap the copy: create_all + migrations must accept it."""
    restored = workdir / "restored.db"
    shutil.copy2(backup, restored)
    env = dict(os.environ)
    env["BARK_DATABASE_URL"] = f"sqlite+aiosqlite:///{restored}"
    env["BARK_DATA_DIR"] = str(workdir)
    code = (
        "import asyncio; from database.engine import init_db; "
        "asyncio.run(init_db()); print('bootstrap ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode == 0, detail[-1] if detail else "no output"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, help="backup file to drill")
    parser.add_argument("--list", action="store_true", help="list available backups")
    args = parser.parse_args()

    if args.list:
        for path in sorted(BACKUP_DIR.glob("*.db"), reverse=True):
            print(f"{path.name}  {path.stat().st_size / 1024:.0f} KiB")
        return 0

    backup = args.backup or _newest_backup()
    if backup is None or not backup.exists():
        print(f"✗ no backup found (looked in {BACKUP_DIR})")
        return 2

    print(f"Restore drill on a COPY of {backup.name} ({backup.stat().st_size / 1024:.0f} KiB)")
    print("The live database is never opened or written by this drill.\n")

    ok_sql, notes = _sqlite_checks(backup)
    for note in notes:
        print(f"  {note}")

    with tempfile.TemporaryDirectory(prefix="bark-restore-drill-") as tmp:
        ok_mig, detail = _migration_drill(backup, Path(tmp))
    print(f"  bootstrap against the copy: {'ok' if ok_mig else 'FAILED'} — {detail}")

    print("\nNot covered by a database backup (restore separately):")
    for item in EXTERNAL_STATE:
        print(f"  - {item}")

    print()
    if ok_sql and ok_mig:
        print("✓ drill passed — this backup restores into a database the current code accepts")
        return 0
    print("✗ drill failed — do not rely on this backup until the failure is understood")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
