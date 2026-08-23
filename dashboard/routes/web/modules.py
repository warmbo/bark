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
from services.dashboard_access import user_is_guild_member
from services.response import (
    render_not_found,
    set_cached_module_min_role,
)

from services.template_globals import install

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
install(templates)
router = APIRouter(tags=["web-modules"])

# Module-specific tab templates now live in each module's own ``templates/``
# directory (e.g. ``moderation/templates/moderation_cases.html``) rather than
# the shared ``dashboard/templates/module_tabs/`` tree. The dashboard Jinja
# loader searches the project root, so a tab path of
# ``<module>/templates/<file>.html`` resolves directly; this helper mirrors
# that resolution for the on-disk existence check below.
REPO_ROOT = Path(__file__).parent.parent.parent.parent


def _resolve_module_template(template: str) -> Path:
    """Resolve a module tab template to an on-disk path.

    ``template`` is already a repo-relative path such as
    ``modules/moderation/templates/moderation_cases.html``; return it joined
    to the repo root so the existence gate matches what Jinja will ``include``.
    """
    return REPO_ROOT / template

# Mirror the dashboard app loader: module tab templates are colocated under
# each module's own ``templates/`` directory, so the project root must be a
# search path for ``{% include %}`` to resolve them.
templates.env.loader.searchpath.append(str(REPO_ROOT))


@router.get("/modules", response_class=HTMLResponse)
async def modules_page(request: Request, guild_id: int):
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

    all_modules = bot.modules.get_all_modules()
    plugin_names = bot.modules.plugin_names()
    command_prefix = f"/{bot.modules.command_group_name()} "
    # Authoritative per-guild state straight from the runtime: persisted rows
    # win, and modules with no row fall back to the per-module default (core
    # modules default enabled; add-on plugins default disabled). Building the
    # dict here (not in the template) keeps the card exactly in sync with
    # what the bot actually dispatches.
    module_states = {
        name: bot.modules.is_enabled_for_guild(guild_id, name)
        for name in all_modules
    }

    return templates.TemplateResponse(
        request,
        "pages/modules.html",
        {
            "guild": guild,
            "modules": all_modules,
            "module_states": module_states,
            "plugin_names": plugin_names,
            "command_prefix": command_prefix,
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
        return render_not_found(
            request, templates,
            title="Server not found",
            message="That server isn't available through this dashboard.",
            hint="It may have been removed or Bark may have lost access to it.",
            back_href="/dashboard",
            guild_id=guild_id,
        )

    module = bot.modules.get_module(module_name)
    if module is None:
        return render_not_found(
            request, templates,
            title="Module not found",
            message="That module doesn't exist on this server.",
            hint="It may have been removed, renamed, or disabled — check the Modules page for everything available.",
            back_href=f"/guild/{guild_id}/modules",
            back_label="Back to Modules",
            icon_name="puzzle",
            guild_id=guild_id,
        )

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
    # Any member of the guild may open a module page — AuthMiddleware already
    # enforced membership on the way in, so this is defense-in-depth. Module
    # *mutations* stay role-gated; the page only hides controls it can't use.
    # Permissive (no-OAuth) instances open the page to everyone, matching
    # check_api_permission's permissive shortcut.
    if config.oauth2.enabled:
        user_id = (request.session.get("user") or {}).get("id")
        if not user_id:
            return HTMLResponse("Insufficient permissions", status_code=403)
        async with session_scope() as session:
            is_member = await user_is_guild_member(session, str(user_id), guild_id)
        if not is_member:
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
    # Module tabs now resolve from the module's own ``templates/`` directory
    # (self-contained per-module UI) with no shared ``module_tabs/`` coupling;
    # only keep tabs whose template exists on disk.
    extra_tabs = []
    for tab in module.get_extra_tabs():
        template = (tab or {}).get("template")
        if not template:
            continue
        if _resolve_module_template(template).is_file():
            extra_tabs.append(tab)

    module_data = {
        "version": module.version,
        "description": module.description,
        "author": module.author,
        # Authoritative per-guild state (persisted row or the per-module
        # default: core enabled, add-on plugins disabled).
        "enabled": bot.modules.is_enabled_for_guild(guild_id, module_name),
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
        "show_configure_tab": module.show_configure_tab,
        "config_layout": module.config_layout,
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
            "command_prefix": f"/{bot.modules.command_group_name()} ",
        },
    )


@router.get("/plugins", response_class=HTMLResponse)
async def plugin_catalog_page(request: Request, guild_id: int):
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

    return templates.TemplateResponse(
        request,
        "pages/plugin_catalog.html",
        {"guild": guild},
    )
