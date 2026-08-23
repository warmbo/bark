"""
Home web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.response import render_not_found

from services.template_globals import install

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
install(templates)

router = APIRouter(tags=["web-home"])


@router.get("/g/{slug}", include_in_schema=False)
async def guild_slug_page(request: Request, slug: str):
    """Unknown-slug 404.

    Known slugs are rewritten to ``/guild/{guild_id}`` by the slug rewrite
    middleware (see ``services/slug_router.py``) BEFORE routing, so this route
    only ever runs for a slug that resolves to nothing. It exists to render a
    friendly not-found page instead of a bare 404.
    """
    return render_not_found(
        request, templates,
        title="Server not found",
        message="That link isn't available through this dashboard.",
        hint="The custom link may have been removed or was never set.",
        back_href="/dashboard",
    )


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
        return render_not_found(
            request, templates,
            title="Server not found",
            message="That server isn't available through this dashboard.",
            hint="It may have been removed or Bark may have lost access to it.",
            back_href="/dashboard",
            guild_id=guild_id,
        )

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
