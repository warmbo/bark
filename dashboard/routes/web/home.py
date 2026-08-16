"""
Home web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-home"])


@router.get("/g/{slug}", include_in_schema=False)
async def guild_slug_redirect(request: Request, slug: str):
    """Resolve a custom URL slug to the numeric guild page (e.g. /g/my-server)."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    async with session_scope() as session:
        row = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.key == "slug",
                    GuildSetting.value == slug.lower(),
                )
            )
        ).scalars().first()
    if row is None:
        return HTMLResponse("Server not found", status_code=404)
    return RedirectResponse(url=f"/guild/{row.guild_id}", status_code=302)


@router.get("/guild/{guild_id}", response_class=HTMLResponse)
async def guild_overview(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        # Distinguish "bot offline" from "not a member of this server": while
        # the bot hasn't reached Discord ready every guild lookup misses, so
        # show an explanatory offline page instead of a bare 404 loop.
        if not bot.is_ready():
            return templates.TemplateResponse(
                request,
                "pages/guild_offline.html",
                {"guild_id": guild_id, "bot": bot, "active_page": "overview"},
            )
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
