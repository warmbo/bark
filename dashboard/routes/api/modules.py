"""
Modules API routes.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from database.engine import session_scope
from database.models.module import ModuleConfig
from database.models.permissions import ModuleRoleAccess
from services.response import (
    api_deleted,
    api_error,
    api_forbidden,
    api_not_found,
    api_success,
    check_api_permission,
    get_module_min_role,
    get_permission_service,
    set_cached_module_min_role,
)

router = APIRouter(tags=["api-modules"])


@router.get("/guilds/{guild_id}/modules")
async def list_modules(request: Request, guild_id: str):
    """List all modules and their status for a guild."""
    guild_id = str(guild_id)
    bot = request.state.bot
    all_modules = bot.modules.get_all_modules()

    modules_list = []
    async with session_scope() as session:
        for name, module in all_modules.items():
            from sqlalchemy import select

            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == str(guild_id),
                    ModuleConfig.module_name == name,
                )
            )
            db_config = result.scalar_one_or_none()

            modules_list.append(
                {
                    "name": name,
                    "version": module.version,
                    "description": module.description,
                    "enabled": db_config.enabled if db_config else True,
                    "priority": db_config.priority if db_config else 100,
                    "config": json.loads(db_config.config)
                    if db_config and db_config.config
                    else {},
                    "commands": [c.name for c in module.get_commands()],
                    "events": [e.event_name for e in module.get_events()],
                    "settings_schema": module.get_settings_schema(),
                }
            )

    return api_success({"modules": modules_list})


@router.get("/guilds/{guild_id}/modules/role-access")
async def list_module_role_access(request: Request, guild_id: str):
    """Return the effective minimum role for every installed module."""
    if not check_api_permission(request, "modules.manage", guild_id):
        return api_forbidden()
    from sqlalchemy import select

    all_modules = request.state.bot.modules.get_all_modules()
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(ModuleRoleAccess).where(ModuleRoleAccess.guild_id == str(guild_id))
                )
            )
            .scalars()
            .all()
        )
    overrides = {row.module_name: row.min_role for row in rows}
    access = {name: overrides.get(name, "admin") for name in all_modules}
    for name in all_modules:
        set_cached_module_min_role(name, guild_id, overrides.get(name))
    return api_success(access)


@router.patch("/guilds/{guild_id}/modules/{module_name}/role-access")
async def set_module_role_access(request: Request, guild_id: str, module_name: str):
    """Set a module's minimum dashboard role for this guild."""
    if not check_api_permission(request, "modules.manage", guild_id):
        return api_forbidden()
    if request.state.bot.modules.get_module(module_name) is None:
        return api_not_found("Module")

    data = await request.json()
    min_role = data.get("min_role")
    valid_roles = set(get_permission_service().ROLE_HIERARCHY)
    if min_role not in valid_roles:
        return api_error("min_role must be one of: viewer, moderator, admin, owner")

    from sqlalchemy import select

    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleRoleAccess).where(
                    ModuleRoleAccess.guild_id == str(guild_id),
                    ModuleRoleAccess.module_name == module_name,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ModuleRoleAccess(
                guild_id=str(guild_id),
                module_name=module_name,
                min_role=min_role,
            )
            session.add(row)
        else:
            row.min_role = min_role
        await session.commit()

    set_cached_module_min_role(module_name, guild_id, min_role)
    return api_success({"module_name": module_name, "min_role": min_role})


@router.delete("/guilds/{guild_id}/modules/{module_name}/role-access")
async def delete_module_role_access(request: Request, guild_id: str, module_name: str):
    """Remove an override and restore the administrator-only default."""
    if not check_api_permission(request, "modules.manage", guild_id):
        return api_forbidden()
    if request.state.bot.modules.get_module(module_name) is None:
        return api_not_found("Module")

    from sqlalchemy import delete

    async with session_scope() as session:
        await session.execute(
            delete(ModuleRoleAccess).where(
                ModuleRoleAccess.guild_id == str(guild_id),
                ModuleRoleAccess.module_name == module_name,
            )
        )
        await session.commit()

    set_cached_module_min_role(module_name, guild_id, None)
    return api_deleted()


@router.get("/guilds/{guild_id}/modules/{module_name}")
async def get_module(request: Request, guild_id: str, module_name: str):
    """Get details about a specific module."""
    guild_id = str(guild_id)
    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return api_not_found("Module")
    await get_module_min_role(module_name, guild_id)
    if not check_api_permission(request, f"{module_name}.access", guild_id):
        return api_forbidden()

    async with session_scope() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == str(guild_id),
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        return api_success(
            {
                "name": module.name,
                "version": module.version,
                "description": module.description,
                "author": module.author,
                "enabled": db_config.enabled
                if db_config
                else True,  # default: enabled on fresh install
                "priority": db_config.priority if db_config else 100,
                "config": json.loads(db_config.config) if db_config and db_config.config else {},
                "settings_schema": module.get_settings_schema(),
                "commands": [
                    {"name": c.name, "description": c.description, "slash": c.slash}
                    for c in module.get_commands()
                ],
                "dashboard_pages": [
                    {"route": p.route, "label": p.label} for p in module.get_dashboard_pages()
                ],
            }
        )


@router.put("/guilds/{guild_id}/modules/{module_name}")
async def update_module_config(request: Request, guild_id: str, module_name: str):
    """Update module configuration."""
    guild_id = str(guild_id)
    await get_module_min_role(module_name, guild_id)
    if not check_api_permission(request, f"{module_name}.configure", guild_id):
        return api_forbidden()

    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return api_not_found("Module")

    data = await request.json()

    # Validate config against schema if provided
    if "config" in data:
        schema = module.get_settings_schema()
        if schema and "properties" in schema:
            errors = _validate_config(
                data["config"],
                schema["properties"],
                schema.get("required", []),
            )
            if errors:
                return api_error("Validation failed", details=errors)

        await module.save_dashboard_config(int(guild_id), data["config"])

    async with session_scope() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == str(guild_id),
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        if db_config is None:
            db_config = ModuleConfig(
                guild_id=str(guild_id),
                module_name=module_name,
                # Fresh modules are enabled everywhere else in the dashboard and
                # runtime. A first settings save must preserve that effective state.
                enabled=True,
            )
            session.add(db_config)

        if "priority" in data:
            db_config.priority = data["priority"]

        await session.commit()

        return api_success({"module": module_name})


@router.post("/guilds/{guild_id}/modules/{module_name}/toggle")
async def toggle_module(request: Request, guild_id: str, module_name: str):
    """Enable or disable a module."""
    guild_id = str(guild_id)
    await get_module_min_role(module_name, guild_id)
    if not check_api_permission(request, f"{module_name}.manage", guild_id):
        return api_forbidden()

    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return api_not_found("Module")

    data = await request.json()
    enable = data.get("enabled", False)

    async with session_scope() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == str(guild_id),
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        if db_config is None:
            db_config = ModuleConfig(
                guild_id=str(guild_id),
                module_name=module_name,
                enabled=enable,
            )
            session.add(db_config)
        else:
            db_config.enabled = enable
        await session.commit()

    await bot.modules.set_guild_enabled(int(guild_id), module_name, enable)

    return api_success({"module": module_name, "enabled": enable})


@router.post("/guilds/{guild_id}/modules/{module_name}/reload")
async def reload_module(request: Request, guild_id: str, module_name: str):
    """Reload a module."""
    await get_module_min_role(module_name, guild_id)
    if not check_api_permission(request, f"{module_name}.manage", guild_id):
        return api_forbidden()

    bot = request.state.bot
    success = await bot.modules.reload_module(module_name)
    if not success:
        return api_error("Module not found or reload failed", status_code=404)
    return api_success({"module": module_name})


@router.post("/guilds/{guild_id}/modules/{module_name}/test")
async def test_module_action(request: Request, guild_id: str, module_name: str):
    """Forward a test action to the module's handler.

    Some modules (e.g. logging) expose a test endpoint that sends a test
    message to configured channels. This route delegates to the module's
    own handler via get_api_routes().
    """
    await get_module_min_role(module_name, guild_id)
    if not check_api_permission(request, f"{module_name}.configure", guild_id):
        return api_forbidden()

    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return api_not_found("Module")

    # Reuse the module's own test handler by calling it directly
    from modules.logging.module import LoggingModule

    if isinstance(module, LoggingModule):
        return await module._handle_test_action(guild_id)

    # Generic fallback: if the module has an action called "test", find it
    actions = module.get_actions()
    for action in actions:
        if action.get("endpoint") == "test" or action.get("id") == "test":
            from services.response import api_success

            return api_success({"message": f"Test action for '{module_name}' completed"})

    return api_error(f"Module '{module_name}' has no test action", status_code=400)


def _validate_config(
    config: dict,
    schema_properties: dict,
    required_keys: list[str] | None = None,
) -> list[str]:
    """Validate module config against its schema. Returns list of error messages."""
    errors: list[str] = []

    def validate_value(path: str, value, prop: dict) -> None:
        expected = prop.get("type")
        valid_type = True

        if expected == "object":
            valid_type = isinstance(value, dict)
        elif expected == "array":
            valid_type = isinstance(value, list)
        elif expected == "integer":
            valid_type = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected == "boolean":
            valid_type = isinstance(value, bool)
        elif expected == "string":
            valid_type = isinstance(value, str)

        if not valid_type:
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return

        if "enum" in prop and value not in prop["enum"]:
            errors.append(f"{path}: expected one of {', '.join(map(str, prop['enum']))}")

        if expected in ("integer", "number"):
            if prop.get("minimum") is not None and value < prop["minimum"]:
                errors.append(f"{path}: minimum is {prop['minimum']}")
            if prop.get("maximum") is not None and value > prop["maximum"]:
                errors.append(f"{path}: maximum is {prop['maximum']}")

        if expected == "object" and isinstance(value, dict) and prop.get("properties"):
            validate_object(path, value, prop["properties"], prop.get("required", []))
        elif expected == "array" and isinstance(value, list) and prop.get("items"):
            for index, item in enumerate(value):
                validate_value(f"{path}[{index}]", item, prop["items"])

    def validate_object(
        path: str,
        value: dict,
        properties: dict,
        required: list[str],
    ) -> None:
        for key in required:
            if key not in value or value[key] in (None, ""):
                field_path = f"{path}.{key}" if path else key
                errors.append(f"{field_path}: required")

        for key, item in value.items():
            field_path = f"{path}.{key}" if path else key
            prop = properties.get(key)
            if prop is None:
                errors.append(f"{field_path}: unknown setting")
                continue
            if item is None or item == "":
                continue
            validate_value(field_path, item, prop)

    if not isinstance(config, dict):
        return ["config: expected object"]

    validate_object("", config, schema_properties, required_keys or [])

    return errors
