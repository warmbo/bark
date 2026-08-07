"""
Owner-only API for installing and removing single-file Bark plugins.

Plugins are uploaded as a single ``.py`` file and stored in the instance's
plugins directory. Installing a plugin executes its code, so these endpoints
are restricted to instance owners when OAuth is configured (permissive mode
otherwise), mirroring the hosted-instance invite API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Request, UploadFile

from config import config
from services.plugin_manager import MAX_PLUGIN_BYTES, PluginValidationError
from services.response import api_deleted, api_error, api_success
from services.security import read_upload_limited

logger = logging.getLogger("bark.dashboard.plugins")

router = APIRouter(tags=["plugins"])


def _can_manage_plugins(request: Request) -> bool:
    """Owner-only when OAuth is configured; permissive otherwise."""
    if config.oauth2.enabled and config.oauth2.owner_discord_ids:
        user = request.session.get("user") or {}
        return user.get("id") in config.oauth2.owner_discord_ids
    return True


@router.get("/instance/plugins")
async def list_plugins(request: Request):
    """Return metadata for every installed plugin."""
    if not _can_manage_plugins(request):
        return api_error("Owner access required", status_code=403)
    bot = request.state.bot
    return api_success({"plugins": bot.modules.list_plugins()})


@router.post("/instance/plugins")
async def install_plugin(request: Request, file: UploadFile = File(...)):
    """Install a single-file plugin module."""
    if not _can_manage_plugins(request):
        return api_error("Owner access required", status_code=403)
    payload = await read_upload_limited(file, MAX_PLUGIN_BYTES)
    try:
        metadata = await request.state.bot.modules.install_plugin(
            payload, file.filename or ""
        )
    except PluginValidationError as exc:
        return api_error(str(exc), status_code=400)
    except Exception as exc:
        logger.exception("Plugin install failed")
        return api_error(f"Plugin install failed: {exc}", status_code=500)
    return api_success(metadata)


@router.delete("/instance/plugins/{name}")
async def uninstall_plugin(request: Request, name: str):
    """Safely remove a plugin: disable, deregister, and delete its file."""
    if not _can_manage_plugins(request):
        return api_error("Owner access required", status_code=403)
    bot = request.state.bot
    if not bot.modules.is_plugin(name):
        return api_error("Plugin not found", status_code=404)
    if await bot.modules.uninstall_plugin(name):
        return api_deleted()
    return api_error("Plugin could not be removed", status_code=500)
