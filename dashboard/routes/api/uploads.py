"""
Image upload API for Discord markdown content fields.

Uploaded images are stored under ``<data_dir>/uploads`` and served back at a
public URL (``<public_url>/media/uploads/<name>``) so Discord can fetch them
when the markdown is posted to a channel.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile

from config import config
from services.response import (
    api_error,
    api_forbidden,
    api_success,
    check_api_permission,
)

router = APIRouter(tags=["api-uploads"])

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# Actions whose holders are allowed to attach images to Discord-facing content.
_CONTENT_EDIT_PERMISSIONS = (
    "announcements.post",
    "welcome.configure",
    "moderation.view",
)


def uploads_directory() -> Path:
    """Return the directory where uploaded images are stored."""
    return Path(config.data_dir) / "uploads"


def _can_upload(request: Request, guild_id: str) -> bool:
    """Return whether the caller may attach images to Discord content."""
    return any(
        check_api_permission(request, action, guild_id) for action in _CONTENT_EDIT_PERMISSIONS
    )


@router.get("/guilds/{guild_id}/uploads")
async def list_uploads(request: Request, guild_id: str):
    """Return previously uploaded images for reuse in Discord markdown."""
    if not _can_upload(request, guild_id):
        return api_forbidden()

    directory = uploads_directory()
    if not directory.exists():
        return api_success({"items": []})

    public_base = config.dashboard.public_url.rstrip("/")
    items = []
    for path in sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_TYPES.values():
            items.append(
                {
                    "url": f"{public_base}/media/uploads/{path.name}",
                    "name": path.name,
                }
            )
    return api_success({"items": items})


@router.delete("/guilds/{guild_id}/uploads/{name}")
async def delete_upload(request: Request, guild_id: str, name: str):
    """Delete a previously uploaded image so it stops appearing in the library."""
    if not _can_upload(request, guild_id):
        return api_forbidden()

    # Guard against path traversal: only bare filenames with an allowed image suffix.
    if "/" in name or "\\" in name or ".." in name:
        return api_error("Invalid filename", status_code=400)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_IMAGE_TYPES.values():
        return api_error("Only PNG, JPEG, GIF, and WebP images can be deleted", status_code=400)

    directory = uploads_directory()
    target = directory / name
    if not target.is_file():
        return api_error("Upload not found", status_code=404)

    try:
        target.unlink()
    except OSError:
        return api_error("Could not delete upload", status_code=500)
    return api_success({"deleted": name})


@router.post("/guilds/{guild_id}/uploads")
async def upload_image(request: Request, guild_id: str, file: UploadFile = File(...)):
    """Upload an image and return a public URL for use in Discord markdown."""
    if not _can_upload(request, guild_id):
        return api_forbidden()

    extension = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if extension is None:
        return api_error("Only PNG, JPEG, GIF, and WebP images are supported", status_code=400)

    payload = await file.read()
    if len(payload) == 0:
        return api_error("Uploaded file is empty", status_code=400)
    if len(payload) > MAX_UPLOAD_BYTES:
        return api_error("Image exceeds the 8 MB limit", status_code=413)

    directory = uploads_directory()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{extension}"
    (directory / name).write_bytes(payload)

    public_base = config.dashboard.public_url.rstrip("/")
    return api_success({"url": f"{public_base}/media/uploads/{name}"})
