"""Instance database backup endpoints.

Backup snapshots are sensitive (full DB contents), so these endpoints are
restricted to instance owners when OAuth is configured (permissive mode
otherwise) — mirroring the updates/plugin APIs.
"""

from __future__ import annotations

import logging
import os
import signal
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request, UploadFile
from fastapi.responses import FileResponse

from services.backup_service import (
    BACKUP_RE,
    InvalidBackupError,
    _backup_dir,
    create_backup,
    has_pending_database_restore,
    list_backups,
    stage_database_restore,
)
from services.instance_auth import can_manage_instance
from services.response import api_error, api_success

logger = logging.getLogger("bark.dashboard.backups")

router = APIRouter(tags=["backups"])
MAX_RESTORE_BYTES = 512 * 1024 * 1024


def _request_process_restart() -> None:
    """Ask systemd/supervisor to restart Bark after the response is sent."""
    os.kill(os.getpid(), signal.SIGTERM)


@router.get("/instance/backups")
async def get_backups(request: Request):
    """List stored database backups (owner-only)."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    return api_success({"backups": list_backups()})


@router.post("/instance/backup")
async def backup_now(request: Request):
    """Create a fresh database snapshot (owner-only)."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    try:
        entry = await create_backup()
    except Exception as exc:  # noqa: BLE001 - surface the failure cleanly
        logger.exception("Backup creation failed")
        return api_error(f"Backup failed: {exc}", status_code=500)
    return api_success(entry)


@router.post("/instance/backup/restore")
async def restore_database_backup(request: Request, file: UploadFile):
    """Validate and stage a v0.2/v0.3 SQLite database for next restart."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".db"):
        return api_error("Database restore requires a .db file", status_code=400)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="bark-restore-upload-", suffix=".db", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_RESTORE_BYTES:
                    return api_error("Database backup exceeds the 512 MiB limit", status_code=413)
                handle.write(chunk)
        entry = await stage_database_restore(temp_path, source_name=filename)
    except InvalidBackupError as exc:
        return api_error(str(exc), status_code=400)
    except Exception:  # noqa: BLE001 - log details, return a safe message
        logger.exception("Database restore staging failed")
        return api_error("Database restore could not be staged", status_code=500)
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return api_success({**entry, "staged": True})


@router.post("/instance/backup/restore/apply")
async def apply_database_restore(
    request: Request, background_tasks: BackgroundTasks
):
    """Restart Bark so a staged database is swapped and migrated at startup."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    if not has_pending_database_restore():
        return api_error("No database restore is staged", status_code=409)
    restart = getattr(request.app.state, "request_process_restart", _request_process_restart)
    background_tasks.add_task(restart)
    return api_success({"restarting": True})


@router.get("/instance/backup/{filename}")
async def download_backup(request: Request, filename: str):
    """Download a stored backup snapshot (owner-only)."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    if not BACKUP_RE.match(filename) or "/" in filename or "\\" in filename or ".." in filename:
        return api_error("Invalid backup filename", status_code=400)
    path = _backup_dir() / filename
    if not path.is_file():
        return api_error("Backup not found", status_code=404)
    return FileResponse(path, media_type="application/octet-stream", filename=filename)
