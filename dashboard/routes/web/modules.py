"""
Modules web routes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import config
from database.engine import session_scope
from database.models.module import ModuleConfig
from database.models.permissions import ModuleRoleAccess
from services.response import check_api_permission, set_cached_module_min_role

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
    plugin_names = bot.modules.plugin_names()
    from sqlalchemy import select

    async with session_scope() as session:
        configs = (
            (
                await session.execute(
                    select(ModuleConfig).where(ModuleConfig.guild_id == str(guild_id))
                )
            )
            .scalars()
            .all()
        )
    module_states = {config.module_name: config.enabled for config in configs}

    return templates.TemplateResponse(
        request,
        "pages/modules.html",
        {
            "guild": guild,
            "modules": all_modules,
            "module_states": module_states,
            "plugin_names": plugin_names,
            "config": config,
        },
    )


def _ensure_nested_config(raw: dict, schema: dict) -> dict:
    """Walk the schema and ensure every object property has a nested dict
    in the config, so the template never hits .get() on a string."""
    result = dict(raw)
    props = schema.get("properties", {})
    for key, prop in props.items():
        if prop.get("type") == "object" and prop.get("properties"):
            if key not in result or not isinstance(result[key], dict):
                result[key] = {}
            sub_props = prop["properties"]
            for sub_key in sub_props:
                if sub_key not in result[key]:
                    result[key][sub_key] = sub_props[sub_key].get("default", "")
    return result


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
                ModuleConfig.guild_id == str(guild_id),
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()
        role_access = (
            await session.execute(
                select(ModuleRoleAccess).where(
                    ModuleRoleAccess.guild_id == str(guild_id),
                    ModuleRoleAccess.module_name == module_name,
                )
            )
        ).scalar_one_or_none()

    set_cached_module_min_role(
        module_name,
        guild_id,
        role_access.min_role if role_access else None,
    )
    if not check_api_permission(request, f"{module_name}.access", guild_id):
        return HTMLResponse("Insufficient permissions", status_code=403)
    # Module hooks keep specialized modules on one authoritative config store.
    raw_config = await module.load_dashboard_config(guild_id)
    schema = module.get_settings_schema()
    safe_config = _ensure_nested_config(raw_config, schema)
    minimum_role = role_access.min_role if role_access else "admin"
    role_rank = {"viewer": 0, "moderator": 1, "admin": 2, "owner": 3}
    current_role = request.session.get("role", "admin")
    can_manage_module = role_rank.get(current_role, -1) >= role_rank[minimum_role]

    # Extra tabs render via ``{% include tab.template %}`` — a plugin may
    # declare a tab whose template file is missing, which would 500 the page.
    # Only keep tabs whose template exists on disk.
    extra_tabs = []
    for tab in module.get_extra_tabs():
        template = (tab or {}).get("template")
        if not template:
            continue
        if (TEMPLATES_DIR / template).is_file():
            extra_tabs.append(tab)

    module_data = {
        "version": module.version,
        "description": module.description,
        "author": module.author,
        "enabled": db_config.enabled if db_config else True,
        "priority": db_config.priority if db_config else 100,
        "config": safe_config,
        "settings_schema": schema,
        "commands": [
            {"name": c.name, "description": c.description, "slash": c.slash}
            for c in module.get_commands()
        ],
        "events": [e.event_name for e in module.get_events()],
        "dashboard_pages": [
            {"route": p.route, "label": p.label} for p in module.get_dashboard_pages()
        ],
        "actions": module.get_actions(),
        "about": module.get_about(),
        "extra_tabs": extra_tabs,
        "role_access_override": role_access.min_role if role_access else None,
        "minimum_role": minimum_role,
        "can_manage_module": can_manage_module,
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


@router.get("/plugins", response_class=HTMLResponse)
async def plugin_catalog_page(request: Request, guild_id: int):
    bot = request.state.bot
    guild = bot.get_guild(guild_id)

    if guild is None:
        return HTMLResponse("Guild not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "pages/plugin_catalog.html",
        {"guild": guild},
    )
