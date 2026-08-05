"""Standardized API response helpers.

Every API endpoint returns responses through these helpers
to ensure consistent structure across all endpoints.

See docs/api-contracts.md for full API contract documentation.
"""

import logging
from typing import Any

from fastapi.responses import JSONResponse

from services.permission_service import PermissionService

logger = logging.getLogger("bark.services.response")
_permission_service = PermissionService()
# ``check_api_permission`` intentionally remains synchronous because it is also
# called by AuthMiddleware. Async route handlers prime this small cache through
# ``get_module_min_role`` before performing their definitive permission check.
_module_role_cache: dict[tuple[str, str], str | None] = {}


def get_permission_service() -> PermissionService:
    """Return the singleton PermissionService instance."""
    return _permission_service


def _module_name_for_action(request, action: str, guild_id=None) -> str | None:
    """Resolve an action prefix to a registered/loaded module name."""
    if guild_id is None:
        from services.security import _guild_id_from_path

        path = getattr(getattr(request, "url", None), "path", "")
        guild_id = _guild_id_from_path(path)
    if guild_id is None or "." not in action:
        return None
    owner = _permission_service.get_module_for_action(action)
    prefix = owner or action.split(".", 1)[0]
    key = (str(guild_id), prefix)
    if key in _module_role_cache:
        return prefix

    bot = getattr(getattr(request, "state", None), "bot", None)
    manager = getattr(bot, "modules", None)
    if manager is None:
        return None
    try:
        modules = manager.get_all_modules()
    except (AttributeError, TypeError):
        return None
    return prefix if isinstance(modules, dict) and prefix in modules else None


async def get_module_min_role(module_name: str, guild_id: int | str) -> str | None:
    """Return a module's per-guild role override, or ``None`` when unset.

    Looking up an unset module is cached as well so the synchronous permission
    check can apply the documented default of administrator access.
    """
    key = (str(guild_id), module_name)
    if key in _module_role_cache:
        return _module_role_cache[key]

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.permissions import ModuleRoleAccess

    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleRoleAccess).where(
                    ModuleRoleAccess.guild_id == str(guild_id),
                    ModuleRoleAccess.module_name == module_name,
                )
            )
        ).scalar_one_or_none()
    min_role = row.min_role if row is not None else None
    _module_role_cache[key] = min_role
    return min_role


def set_cached_module_min_role(module_name: str, guild_id: int | str, min_role: str | None) -> None:
    """Keep permission enforcement coherent immediately after API writes."""
    _module_role_cache[(str(guild_id), module_name)] = min_role


def clear_module_role_cache(module_name: str) -> None:
    """Drop cached per-guild min roles for a module (used on plugin removal)."""
    for key in [key for key in _module_role_cache if key[1] == module_name]:
        _module_role_cache.pop(key, None)


def reset_permission_state() -> None:
    """Clear in-memory permission state for reloads and isolated test runs."""
    _module_role_cache.clear()
    _permission_service.clear_module_permissions()


async def load_module_role_access_cache() -> None:
    """Load persisted overrides for synchronous middleware checks at startup."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.permissions import ModuleRoleAccess

    async with session_scope() as session:
        rows = (await session.execute(select(ModuleRoleAccess))).scalars().all()
    _module_role_cache.clear()
    for row in rows:
        set_cached_module_min_role(row.module_name, row.guild_id, row.min_role)


def check_api_permission(request, action: str, guild_id=None) -> bool:
    """Check if the current session has permission for an action.

    Returns True when OAuth2 is not configured (permissive mode).
    When OAuth2 is configured, checks the user's role from the session. Module
    actions use their per-guild override, or administrator access when unset.
    """
    from config import config

    if not config.oauth2.enabled:
        return True  # No OAuth2 configured — permissive
    user_role = request.session.get("role", "viewer")
    if guild_id is None:
        from services.security import _guild_id_from_path

        path = getattr(getattr(request, "url", None), "path", "")
        guild_id = _guild_id_from_path(path)
    module_name = _module_name_for_action(request, action, guild_id)
    if module_name is not None:
        required = _module_role_cache.get((str(guild_id), module_name), "admin") or "admin"
    else:
        required = _permission_service.get_required_role_for_action(action)
    result = _permission_service.role_has_access(user_role, required)
    if not result:
        logger.warning(
            "Permission denied: role=%s required=%s action=%s", user_role, required, action
        )
    return result


def get_capabilities(request) -> dict[str, bool]:
    """Expose the same capabilities enforced by mutation middleware."""
    bot = getattr(getattr(request, "state", None), "bot", None)
    modules = getattr(bot, "modules", None)
    if modules is not None:
        try:
            _permission_service.discover_module_permissions(modules.get_all_modules())
        except (AttributeError, TypeError):
            logger.debug("Module capabilities unavailable for this request")

    from config import config

    if not config.oauth2.enabled:
        return {action: True for action in _permission_service.get_all_actions()}
    return _permission_service.capabilities_for_role(request.session.get("role", "viewer"))


async def get_guild_capabilities(request, guild_id: int | str) -> dict[str, bool]:
    """Return capabilities using the same per-guild module roles as enforcement."""
    bot = getattr(getattr(request, "state", None), "bot", None)
    manager = getattr(bot, "modules", None)
    modules: dict = {}
    if manager is not None:
        try:
            modules = manager.get_all_modules()
            _permission_service.discover_module_permissions(modules)
        except (AttributeError, TypeError):
            logger.debug("Module capabilities unavailable for this request")
            modules = {}

    for module_name in modules:
        await get_module_min_role(module_name, guild_id)

    from config import config

    actions = _permission_service.get_all_actions()
    if not config.oauth2.enabled:
        return {action: True for action in actions}
    return {action: check_api_permission(request, action, guild_id) for action in sorted(actions)}


def api_success(data: Any = None, status_code: int = 200) -> JSONResponse:
    """Return a standardized success response."""
    body = {"success": True}
    if data is not None:
        body["data"] = data
    return JSONResponse(content=body, status_code=status_code)


def api_error(message: str, status_code: int = 400, details: Any = None) -> JSONResponse:
    """Return a standardized error response."""
    body = {"success": False, "error": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(content=body, status_code=status_code)


def api_created(data: Any = None) -> JSONResponse:
    """Return a 201 Created response."""
    return api_success(data=data, status_code=201)


def api_deleted() -> JSONResponse:
    """Return a 200 response confirming deletion."""
    return api_success({"deleted": True})


def api_not_found(resource: str = "Resource") -> JSONResponse:
    """Return a 404 response."""
    return api_error(f"{resource} not found", status_code=404)


def api_forbidden(message: str = "Insufficient permissions") -> JSONResponse:
    """Return a 403 response."""
    return api_error(message, status_code=403)


def api_paginated(items: list, total: int, page: int = 0, limit: int = 50) -> JSONResponse:
    """Return a paginated success response with standard page metadata."""
    return api_success(
        {
            "items": items,
            "total": total,
            "page": page,
            "pages": max(1, (total + limit - 1) // limit) if limit > 0 else 1,
        }
    )
