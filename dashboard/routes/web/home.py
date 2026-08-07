"""
Home web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-home"])


@router.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_overview(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    # View-only members (no admin/moderator rights in this server) get a
    # read-only metrics/status page — no modules, no management surfaces.
    if getattr(request.state, "guild_viewer", False):
        return templates.TemplateResponse(
            request,
            "pages/guild_viewer.html",
            {"guild": guild, "bot": bot, "active_page": "overview"},
        )

    return templates.TemplateResponse(
        request,
        "pages/guild.html",
        {"guild": guild, "bot": bot, "active_page": "overview"},
    )
