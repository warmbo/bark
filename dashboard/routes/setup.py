"""First-time setup routes.

Only reachable while the instance is unconfigured (``config.needs_setup``);
once ``.env`` exists the wizard redirects away and normal auth takes over.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bark_version import __version__
from config import config
from services.response import api_error, api_success
from services.setup_service import SetupError, is_configured, write_env

logger = logging.getLogger("bark.setup")

router = APIRouter(tags=["setup"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _schedule_restart() -> bool:
    """Exit the process so systemd restarts Bark with the new .env.

    Only when the unit is systemd-managed (Restart=always); a bare python
    run must be restarted by hand. Returns whether a restart was scheduled.
    """
    try:
        if Path("/proc/1/comm").read_text().strip() == "systemd":
            import asyncio

            asyncio.get_event_loop().call_later(2.0, os._exit, 0)
            return True
    except OSError:
        pass
    return False


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Render the first-time setup wizard."""
    if not config.needs_setup:
        return RedirectResponse(url="/", status_code=303)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "pages/setup.html",
        {
            "version": __version__,
            "public_url": config.dashboard.public_url,
            "redirect_uri": f"{config.dashboard.public_url}/auth/callback",
        },
    )


@router.post("/api/setup")
async def submit_setup(request: Request):
    """Validate the form and write ``.env`` (owner-less bootstrap)."""
    if not config.needs_setup:
        return api_error("This instance is already configured", status_code=403)
    if is_configured():
        return api_error(
            "A .env file already exists — delete it to re-run setup",
            status_code=409,
        )
    try:
        payload = await request.json()
    except Exception:
        return api_error("Invalid JSON body", status_code=400)
    try:
        path = write_env(payload)
    except SetupError as exc:
        return api_error(str(exc), status_code=400)
    restarting = _schedule_restart()
    logger.info("Setup complete: %s written (%s)", path, "restarting" if restarting else "manual restart needed")
    return api_success(
        {
            "env_file": str(path),
            "restarting": restarting,
            "message": (
                "Configuration saved — Bark is restarting with your settings."
                if restarting
                else "Configuration saved — restart Bark to finish setup."
            ),
        }
    )
