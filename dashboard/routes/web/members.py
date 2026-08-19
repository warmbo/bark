"""
Members web routes — member browser and member detail pages.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.response import render_not_found

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-members"])


@router.get("/members", response_class=HTMLResponse)
async def member_browser(request: Request, guild_id: int):
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
        return render_not_found(
            request, templates,
            title="Server not found",
            message="That server isn't available through this dashboard.",
            hint="It may have been removed or Bark may have lost access to it.",
            back_href="/dashboard",
            guild_id=guild_id,
        )

    try:
        member_id = int(user_id)
    except (TypeError, ValueError):
        return render_not_found(
            request, templates,
            title="Member not found",
            message="That member doesn't exist on this server.",
            back_href=f"/guild/{guild_id}/members",
            back_label="Back to Members",
            icon_name="users",
            guild_id=guild_id,
        )
    member = guild.get_member(member_id)
    if member is None:
        return render_not_found(
            request, templates,
            title="Member not found",
            message="That member doesn't exist on this server.",
            back_href=f"/guild/{guild_id}/members",
            back_label="Back to Members",
            icon_name="users",
            guild_id=guild_id,
        )

    return templates.TemplateResponse(
        request,
        "pages/member_detail.html",
        {"guild": guild, "member": member},
    )
