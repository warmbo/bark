"""Instance database backup endpoints.

Backup snapshots are sensitive (full DB contents), so these endpoints are
restricted to instance owners when OAuth is configured (permissive mode
otherwise) — mirroring the updates/plugin APIs.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from config import config
from services.backup_service import BACKUP_RE, _backup_dir, create_backup, list_backups
from services.response import api_error, api_success

logger = logging.getLogger("bark.dashboard.backups")

router = APIRouter(tags=["backups"])


def _can_manage_instance(request: Request) -> bool:
    """Owner-only when OAuth is configured; permissive otherwise."""
    if config.oauth2.enabled and config.oauth2.owner_discord_ids:
        user = request.session.get("user") or {}
        return user.get("id") in config.oauth2.owner_discord_ids
    return True


@router.get("/instance/backups")
async def get_backups(request: Request):
    """List stored database backups (owner-only)."""
    if not _can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    return api_success({"backups": list_backups()})


@router.post("/instance/backup")
async def backup_now(request: Request):
    """Create a fresh database snapshot (owner-only)."""
    if not _can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    try:
        entry = await create_backup()
    except Exception as exc:  # noqa: BLE001 - surface the failure cleanly
        logger.exception("Backup creation failed")
        return api_error(f"Backup failed: {exc}", status_code=500)
    return api_success(entry)


@router.get("/instance/backup/{filename}")
async def download_backup(request: Request, filename: str):
    """Download a stored backup snapshot (owner-only)."""
    if not _can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    if not BACKUP_RE.match(filename) or "/" in filename or "\\" in filename or ".." in filename:
        return api_error("Invalid backup filename", status_code=400)
    path = _backup_dir() / filename
    if not path.is_file():
        return api_error("Backup not found", status_code=404)
    return FileResponse(path, media_type="application/octet-stream", filename=filename)
