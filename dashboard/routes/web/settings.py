"""
Settings web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import config

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-settings"])


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    # Owner-only sections (Backups, Updates, Diagnostics, Bot Customization,
    # Hosted Instance Access) are hidden for non-owners. This mirrors the
    # owner gate used by each owner-only API route.
    from services.instance_auth import can_manage_instance

    return templates.TemplateResponse(
        request,
        "pages/settings.html",
        {
            "guild": guild,
            "config": config,
            "is_owner": can_manage_instance(request),
        },
    )
