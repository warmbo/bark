"""
Manifest API — consolidated guild metadata for dashboard rendering.

Returns everything a page needs to render navigation, search,
quick actions, and cross-module links in a single endpoint.
"""

from fastapi import APIRouter, Request

from database.engine import session_scope
from services.response import api_not_found, api_success, get_guild_capabilities

router = APIRouter(tags=["api-manifest"])

CORE_PAGES = [
    {
        "route": "/guild/{guild_id}",
        "label": "Dashboard",
        "icon": "layout-dashboard",
        "category": "",
    },
    {
        "route": "/guild/{guild_id}/members",
        "label": "Members",
        "icon": "users",
        "category": "community",
    },
    {
        "route": "/guild/{guild_id}/modules",
        "label": "Modules",
        "icon": "puzzle",
        "category": "settings",
    },
    {
        "route": "/guild/{guild_id}/settings",
        "label": "General",
        "icon": "settings",
        "category": "settings",
    },
]


# Case count — cached dict with 30s TTL
_case_count_cache: dict[int, tuple[int, float]] = {}
_CASE_CACHE_TTL = 30.0


def _get_cached_case_count(guild_id: int, count: int) -> int:
    import time

    now = time.monotonic()
    cached = _case_count_cache.get(guild_id)
    if cached is not None and (now - cached[1]) < _CASE_CACHE_TTL:
        return cached[0]
    _case_count_cache[guild_id] = (count, now)
    return count


@router.get("/guilds/{guild_id}/manifest")
async def get_guild_manifest(request: Request, guild_id: int):
    """Return full navigation and action manifest for a guild."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    pages_list: list[dict[str, object]] = [
        {**page, "route": page["route"].replace("{guild_id}", str(guild_id))} for page in CORE_PAGES
    ]
    modules_list: list[dict[str, object]] = []
    actions_list: list[dict[str, object]] = []

    enabled_by_module = await _load_enabled_modules(guild_id)
    for name, module in bot.modules.get_all_modules().items():
        pages = module.get_dashboard_pages()
        actions = module.get_actions()
        modules_list.append(
            _module_entry(
                name,
                module,
                guild_id,
                enabled_by_module,
                actions,
                is_plugin=bot.modules.is_plugin(name),
            )
        )
        pages_list.extend(
            _module_pages(
                name,
                module,
                guild_id,
                enabled_by_module,
                pages,
                is_plugin=bot.modules.is_plugin(name),
            )
        )
        actions_list.extend(_module_actions(name, module, guild_id, actions))
    categories = _build_navigation(pages_list)
    case_count = await _count_cases(guild_id)

    return api_success(
        {
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "icon_url": guild.icon.url if guild.icon else None,
            },
            "modules": modules_list,
            "pages": pages_list,
            "actions": actions_list,
            "categories": {
                key: value
                for key, value in sorted(
                    categories.items(),
                    key=lambda item: float(str(item[1].get("priority", 99)) or 99),
                )
            },
            "stats": {
                "members": guild.member_count,
                "total_cases": case_count,
                "modules_enabled": sum(1 for entry in modules_list if entry["enabled"]),
                "modules_total": len(modules_list),
            },
            "capabilities": await get_guild_capabilities(request, guild_id),
        }
    )


async def _load_enabled_modules(guild_id: int) -> dict[str, bool]:
    """Return module name -> enabled flag from persisted module configs."""
    from sqlalchemy import select

    from database.models.module import ModuleConfig

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
    return {config.module_name: config.enabled for config in configs}


def _module_entry(
    name: str,
    module,
    guild_id: int,
    enabled_by_module: dict[str, bool],
    actions: list[dict],
    is_plugin: bool = False,
) -> dict[str, object]:
    """Describe a module for the manifest, including its command surface."""
    return {
        "name": name,
        "label": name.replace("_", " ").title(),
        "version": module.version,
        "description": module.description,
        "enabled": enabled_by_module.get(name, True),
        "is_plugin": is_plugin,
        "commands": [command.name for command in module.get_commands()],
        "settings_schema": bool(module.get_settings_schema()),
        "actions_count": len(actions),
        "url": f"/guild/{guild_id}/modules/{name}",
    }


def _module_pages(
    name: str,
    module,
    guild_id: int,
    enabled_by_module: dict[str, bool],
    pages,
    is_plugin: bool = False,
) -> list[dict[str, object]]:
    """Render a module's dashboard pages into manifest entries."""
    rendered = []
    for page in pages:
        rendered.append(
            {
                "route": page.route.replace("{guild_id}", str(guild_id)),
                "label": page.label,
                "icon": page.icon or "puzzle",
                "category": page.category or "",
                "module": name,
                "is_plugin": is_plugin,
                "enabled": enabled_by_module.get(name, True),
            }
        )
    # Plugins without custom dashboard pages still need a nav entry so they
    # appear under "Add-on Modules" in the sidebar (linked to the module page).
    if not rendered and is_plugin:
        rendered.append(
            {
                "route": f"/guild/{guild_id}/modules/{name}",
                "label": name.replace("_", " ").title(),
                "icon": "puzzle",
                "category": "",
                "module": name,
                "is_plugin": True,
                "enabled": enabled_by_module.get(name, True),
            }
        )
    return rendered


def _module_actions(
    name: str,
    module,
    guild_id: int,
    actions: list[dict],
) -> list[dict[str, object]]:
    """Render a module's quick actions into manifest entries."""
    return [
        {
            "label": action.get("label", name),
            "url": f"/guild/{guild_id}/modules/{name}",
            "icon": "zap",
            "module": name,
        }
        for action in actions
    ]


def _build_navigation(pages_list: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """Group manifest pages into navigation categories by page metadata."""
    core_pages = [
        page
        for page in pages_list
        if not page.get("category") and not page.get("is_plugin")
    ]
    community_pages = [
        page
        for page in pages_list
        if page.get("category") == "community" and not page.get("module")
    ]
    default_module_pages = [
        page for page in pages_list if page.get("module") and not page.get("is_plugin")
    ]
    plugin_module_pages = [
        page for page in pages_list if page.get("module") and page.get("is_plugin")
    ]
    settings_pages = [page for page in pages_list if page.get("category") == "settings"]

    categories: dict[str, dict[str, object]] = {}
    if core_pages:
        categories["_core"] = {
            "label": "Pages",
            "icon": "layout-dashboard",
            "priority": -1,
            "pages": core_pages,
        }
    if community_pages:
        categories["community"] = {
            "label": "Community",
            "icon": "users",
            "priority": 2,
            "pages": community_pages,
        }
    if default_module_pages:
        categories["_modules"] = {
            "label": "Modules",
            "icon": "puzzle",
            "priority": 3,
            "pages": default_module_pages,
        }
    if plugin_module_pages:
        categories["_plugins"] = {
            "label": "Add-on Modules",
            "icon": "puzzle",
            "priority": 3.5,
            "pages": plugin_module_pages,
        }
    if settings_pages:
        categories["settings"] = {
            "label": "Settings",
            "icon": "settings",
            "priority": 4,
            "pages": settings_pages,
        }
    return categories


async def _count_cases(guild_id: int) -> int:
    """Count moderation cases for the guild, cached briefly."""
    from sqlalchemy import func, select

    from database.models.moderation import ModerationCase

    async with session_scope() as session:
        count = (
            await session.execute(
                select(func.count(ModerationCase.id)).where(
                    ModerationCase.guild_id == str(guild_id)
                )
            )
        ).scalar() or 0
    return _get_cached_case_count(guild_id, count)
