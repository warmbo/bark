"""
Statistics web route — server stats / charts page.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.response import render_not_found

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-stats"])


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return render_not_found(
            request, templates,
            title="Server not found",
            message="That server isn't available through this dashboard.",
            hint="It may have been removed or Bark may have lost access to it.",
            back_href="/dashboard",
            guild_id=guild_id,
        )

    response = templates.TemplateResponse(
        request,
        "pages/stats.html",
        {"guild": guild, "bot": bot, "active_page": "stats"},
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
