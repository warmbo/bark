"""Instance self-update endpoints.

Pulling arbitrary code from the remote and restarting the process is
extremely sensitive, so these endpoints are restricted to instance owners
when OAuth is configured (permissive mode otherwise) — mirroring the plugin
and hosted-instance invite APIs.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request

from config import config
from services.instance_auth import can_manage_instance
from services.response import api_error, api_success
from services.update_service import (
    apply_update_async,
    check_update,
    get_channel,
)

logger = logging.getLogger("bark.dashboard.updates")

router = APIRouter(tags=["updates"])

VALID_CHANNELS = {"main", "dev"}


def _channel_label(channel: str) -> str:
    """Normalize a UI channel value to its state label."""
    return "stable" if channel == "main" else "dev"


@router.get("/instance/update/status")
async def update_status(request: Request, branch: str | None = None):
    """Check the remote for a newer build (owner-only)."""
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    # check_update runs blocking `git fetch` subprocesses (up to 120s per
    # remote) — never run that on the event loop.
    return api_success(await asyncio.to_thread(check_update, branch))


@router.post("/instance/update")
async def perform_update(request: Request, payload: dict):
    """Pull the requested channel and restart the instance (owner-only).

    Channel rule: an instance may move from Stable to Dev, but never back.
    Once the instance's channel is ``dev``, stable-channel updates are
    rejected.
    """
    if not can_manage_instance(request):
        return api_error("Owner access required", status_code=403)
    channel = (payload.get("branch") or config.instance.update_branch).strip()
    if channel not in VALID_CHANNELS:
        return api_error("Channel must be 'main' or 'dev'", status_code=400)

    requested_label = _channel_label(channel)
    if get_channel() == "dev" and requested_label == "stable":
        return api_error(
            "This instance is on the Dev channel — switching back to Stable is not allowed",
            status_code=403,
        )

    # Respond first, then apply + exit in the background so systemd restarts us.
    asyncio.get_event_loop().create_task(apply_update_async(channel))
    return api_success(
        {
            "message": f"Update to '{channel}' started — the instance will restart shortly",
            "branch": channel,
        }
    )
