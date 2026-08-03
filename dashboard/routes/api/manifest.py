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
        "label": "All Modules",
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

    modules_list = []
    pages_list: list[dict[str, object]] = [
        {**p, "route": p["route"].replace("{guild_id}", str(guild_id))} for p in CORE_PAGES
    ]
    actions_list = []

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
    enabled_by_module = {config.module_name: config.enabled for config in configs}

    for name, module in bot.modules.get_all_modules().items():
        mod_pages = module.get_dashboard_pages()
        mod_actions = module.get_actions()

        module_entry = {
            "name": name,
            "label": name.replace("_", " ").title(),
            "version": module.version,
            "description": module.description,
            "enabled": enabled_by_module.get(name, True),
            "commands": [c.name for c in module.get_commands()],
            "settings_schema": bool(module.get_settings_schema()),
            "actions_count": len(mod_actions),
            "url": f"/guild/{guild_id}/modules/{name}",
        }

        # Gather module pages
        for pg in mod_pages:
            route = pg.route.replace("{guild_id}", str(guild_id))
            cat = pg.category or ""
            pages_list.append(
                {
                    "route": route,
                    "label": pg.label,
                    "icon": pg.icon or "puzzle",
                    "category": cat,
                    "module": name,
                    "enabled": enabled_by_module.get(name, True),
                }
            )

        # Add quick actions to manifest
        for act in mod_actions:
            actions_list.append(
                {
                    "label": act.get("label", name),
                    "url": f"/guild/{guild_id}/modules/{name}",
                    "icon": "zap",
                    "module": name,
                }
            )

        modules_list.append(module_entry)

    # Compute category-groups for navigation

    # Core pages (no label in sidebar)
    core_pages = [p for p in pages_list if not p.get("category")]
    categories: dict[str, dict[str, object]] = {}
    if core_pages:
        categories["_core"] = {
            "label": "Pages",
            "icon": "layout-dashboard",
            "priority": -1,
            "pages": core_pages,
        }

    # Community pages (members, etc.)
    community_pages = [
        p for p in pages_list if p.get("category") == "community" and not p.get("module")
    ]
    if community_pages:
        categories["community"] = {
            "label": "Community",
            "icon": "users",
            "priority": 2,
            "pages": community_pages,
        }

    # All module pages under a single "Modules" section
    module_pages = [p for p in pages_list if p.get("module")]
    if module_pages:
        categories["_modules"] = {
            "label": "Modules",
            "icon": "puzzle",
            "priority": 3,
            "pages": module_pages,
        }

    # Settings pages
    settings_pages = [p for p in pages_list if p.get("category") == "settings"]
    if settings_pages:
        categories["settings"] = {
            "label": "Settings",
            "icon": "settings",
            "priority": 4,
            "pages": settings_pages,
        }

    # Stats snapshot
    from sqlalchemy import func

    from database.models.moderation import ModerationCase

    async with session_scope() as session:
        case_count = (
            await session.execute(
                select(func.count(ModerationCase.id)).where(
                    ModerationCase.guild_id == str(guild_id)
                )
            )
        ).scalar() or 0
    case_count = _get_cached_case_count(guild_id, case_count)

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
                k: v
                for k, v in sorted(
                    categories.items(),
                    key=lambda x: int(str(x[1].get("priority", 99)) or 99),
                )
            },
            "stats": {
                "members": guild.member_count,
                "total_cases": case_count,
                "modules_enabled": sum(1 for m in modules_list if m["enabled"]),
                "modules_total": len(modules_list),
            },
            "capabilities": await get_guild_capabilities(request, guild_id),
        }
    )
