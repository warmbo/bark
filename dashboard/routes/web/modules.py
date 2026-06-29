"""
Modules web routes.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from database.engine import session_scope
from database.models.module import ModuleConfig

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["web-modules"])


@router.get("/modules", response_class=HTMLResponse)
async def modules_page(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    all_modules = bot.modules.get_all_modules()

    return templates.TemplateResponse(
        request,
        "pages/modules.html",
        {"guild": guild, "modules": all_modules},
    )


@router.get("/modules/{module_name}", response_class=HTMLResponse)
async def module_detail_page(request: Request, guild_id: int, module_name: str):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    module = bot.modules.get_module(module_name)
    if module is None:
        return HTMLResponse("Module not found", status_code=404)

    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == guild_id,
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

    module_data = {
        "version": module.version,
        "description": module.description,
        "author": module.author,
        "enabled": db_config.enabled if db_config else False,
        "priority": db_config.priority if db_config else 100,
        "config": json.loads(db_config.config) if db_config and db_config.config else {},
        "settings_schema": module.get_settings_schema(),
        "commands": [
            {"name": c.name, "description": c.description, "slash": c.slash}
            for c in module.get_commands()
        ],
        "events": [e.event_name for e in module.get_events()],
        "dashboard_pages": [
            {"route": p.route, "label": p.label}
            for p in module.get_dashboard_pages()
        ],
    }

    return templates.TemplateResponse(
        request,
        "pages/module_detail.html",
        {
            "guild": guild,
            "module_name": module_name,
            "module_data": module_data,
        },
    )
