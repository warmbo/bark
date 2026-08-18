"""
Manifest API — consolidated guild metadata for dashboard rendering.

Returns everything a page needs to render navigation, search,
quick actions, and cross-module links in a single endpoint.
"""

from fastapi import APIRouter, Request

from database.engine import session_scope
from services.response import api_not_found, api_success, get_guild_capabilities

router = APIRouter(tags=["api-manifest"])


def _repo_plugin_entries() -> list[dict[str, object]]:
    """Best-effort remote catalog from the public bark-plugins README.

    Only rows whose File cell is a markdown link to a real ``plugins/*.py``
    file are surfaced as installable. The README also carries a "Plugin ideas
    (not yet built)" table (backtick file names, no link) — those are skipped
    so the catalog never lists plugins that can't actually be installed. The
    file path is extracted from the link so download/install works.
    """
    try:
        import re
        import urllib.request

        file_link = re.compile(
            r"\[`?plugins/([a-z0-9_]+)\.py`?\]\(plugins/\1\.py\)"
        )
        with urllib.request.urlopen(
            "https://raw.githubusercontent.com/warmbo/bark-plugins/main/README.md",
            timeout=2,
        ) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "plugin":
            continue
        match = file_link.fullmatch(cells[1])
        if not match:
            continue  # planned/header rows (no markdown link to a .py)
        file_name = f"plugins/{match.group(1)}.py"
        rows.append(
            {
                "name": cells[0],
                "file": file_name,
                "label": cells[0],
                "description": cells[2],
                "source": "warmbo/bark-plugins",
                "url": f"https://github.com/warmbo/bark-plugins/blob/main/{file_name}",
            }
        )
    return rows


@router.get("/guilds/plugin-catalog")
async def get_plugin_catalog(request: Request):
    return api_success({"plugins": _repo_plugin_entries()})


CORE_PAGES = [
    {
        "route": "/guild/{guild_id}",
        "label": "Dashboard",
        "icon": "layout-dashboard",
        "category": "",
        "role": "server_user",
    },
    {
        "route": "/guild/{guild_id}/members",
        "label": "Members",
        "icon": "users",
        "category": "community",
        "role": "server_mod",
    },
    {
        "route": "/guild/{guild_id}/stats",
        "label": "Statistics",
        "icon": "bar-chart-3",
        "category": "community",
        "role": "server_user",
    },
    {
        "route": "/guild/{guild_id}/modules",
        "label": "Modules",
        "icon": "puzzle",
        "category": "settings",
        "role": "server_admin",
    },
    {
        "route": "/guild/{guild_id}/settings",
        "label": "Settings",
        "icon": "settings",
        "category": "settings",
        "role": "server_admin",
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

    guild_meta = {
        "id": str(guild.id),
        "name": guild.name,
        "member_count": guild.member_count,
        "icon_url": guild.icon.url if guild.icon else None,
    }

    # View-only members (no admin/moderator rights in this server) get a
    # stripped manifest: the sidebar shows only the Dashboard entry and no
    # module or management surfaces are advertised.
    if getattr(request.state, "guild_viewer", False):
        dashboard_page = {**CORE_PAGES[0], "route": f"/guild/{guild_id}"}
        # Viewers can see the read-only Dashboard and Statistics pages, but no
        # module or management surfaces.
        stats_page = {**CORE_PAGES[2], "route": f"/guild/{guild_id}/stats"}
        viewer_pages = [dashboard_page, stats_page]
        return api_success(
            {
                "guild": guild_meta,
                "viewer": True,
                "modules": [],
                "pages": viewer_pages,
                "actions": [],
                "categories": _build_navigation(viewer_pages),
                "stats": {
                    "members": guild.member_count,
                    "total_cases": None,
                    "modules_enabled": 0,
                    "modules_total": 0,
                },
                "capabilities": {},
            }
        )

    pages_list: list[dict[str, object]] = [
        {**page, "route": page["route"].replace("{guild_id}", str(guild_id))} for page in CORE_PAGES
    ]
    if getattr(request.app.state, "is_bark_dev", False):
        pages_list.append(
            {
                "route": f"/guild/{guild_id}/plugins",
                "label": "Plugin Catalog",
                "icon": "package",
                "category": "settings",
            }
        )
    modules_list: list[dict[str, object]] = []
    actions_list: list[dict[str, object]] = []

    # Authoritative per-guild enablement (from the module manager's runtime
    # state, which defaults add-on/plugin modules to OFF and core to ON).
    # Coerced to a JSON-safe bool.
    enabled_by_module = {
        name: bool(bot.modules.is_enabled_for_guild(guild_id, name))
        for name in bot.modules.get_all_modules()
    }
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
            "guild": guild_meta,
            "viewer": False,
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
    """Render a module's dashboard pages into manifest entries.

    Only modules that are ENABLED for this guild appear in the left-pane
    navigation. An add-on that is uploaded but not enabled (or a core module
    switched off for this server) is managed from the Modules page and stays
    out of the sidebar until it's active.
    """
    if not enabled_by_module.get(name, True):
        return []
    rendered = []
    for page in pages:
        rendered.append(
            {
                "route": page.route.replace("{guild_id}", str(guild_id)),
                "label": page.label,
                # Add-on (plugin) modules all share the puzzle-piece icon so a
                # single plugin's custom icon can't break nav consistency.
                "icon": "puzzle" if is_plugin else (page.icon or "puzzle"),
                "category": page.category or "",
                "module": name,
                "is_plugin": is_plugin,
                "enabled": enabled_by_module.get(name, True),
                "role": "server_mod",
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
                "role": "server_mod",
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
