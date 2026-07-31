"""
Members web routes — member browser and member detail pages.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-members"])


@router.get("/members", response_class=HTMLResponse)
async def member_browser(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    response = templates.TemplateResponse(
        request,
        "pages/members.html",
        {"guild": guild},
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/members/{user_id}", response_class=HTMLResponse)
async def member_detail(request: Request, guild_id: int, user_id: str):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    member = guild.get_member(int(user_id))
    if member is None:
        return HTMLResponse("Member not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "pages/member_detail.html",
        {"guild": guild, "member": member},
    )
