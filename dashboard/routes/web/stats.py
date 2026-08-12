"""
Statistics web route — server stats / charts page.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-stats"])


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    response = templates.TemplateResponse(
        request,
        "pages/stats.html",
        {"guild": guild, "bot": bot, "active_page": "stats"},
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
