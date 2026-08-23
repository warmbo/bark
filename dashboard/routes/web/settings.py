"""
Settings web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import config
from services.response import render_not_found

from services.template_globals import install

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
install(templates)

router = APIRouter(tags=["web-settings"])


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, guild_id: int):
    """Server + instance settings merged into one page.

    Per-server configuration (slug, dashboard access) and instance-wide
    settings (backups, updates, diagnostics, bot customization, instance
    access) now share a single Settings page.
    """
    return await _settings_page(request, guild_id, "pages/settings.html")


async def _settings_page(request: Request, guild_id: int, template: str):
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

    # Owner-only sections (Backups, Updates, Diagnostics, Bot Customization,
    # Hosted Instance Access) are hidden for non-owners. This mirrors the
    # owner gate used by each owner-only API route.
    from services.instance_auth import can_manage_instance

    return templates.TemplateResponse(
        request,
        template,
        {
            "guild": guild,
            "config": config,
            "is_owner": can_manage_instance(request),
        },
    )
