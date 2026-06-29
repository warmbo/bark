"""
Modules API routes.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.engine import session_scope
from database.models.module import ModuleConfig

router = APIRouter(tags=["api-modules"])


@router.get("/guilds/{guild_id}/modules")
async def list_modules(request: Request, guild_id: int):
    """List all modules and their status for a guild."""
    bot = request.state.bot
    all_modules = bot.modules.get_all_modules()

    modules_list = []
    async with session_scope() as session:
        for name, module in all_modules.items():
            from sqlalchemy import select
            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == guild_id,
                    ModuleConfig.module_name == name,
                )
            )
            db_config = result.scalar_one_or_none()

            modules_list.append({
                "name": name,
                "version": module.version,
                "description": module.description,
                "enabled": db_config.enabled if db_config else False,
                "priority": db_config.priority if db_config else 100,
                "config": json.loads(db_config.config) if db_config and db_config.config else {},
                "commands": [c.name for c in module.get_commands()],
                "events": [e.event_name for e in module.get_events()],
                "settings_schema": module.get_settings_schema(),
            })

    return {"modules": modules_list}


@router.get("/guilds/{guild_id}/modules/{module_name}")
async def get_module(request: Request, guild_id: int, module_name: str):
    """Get details about a specific module."""
    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return JSONResponse({"error": "Module not found"}, status_code=404)

    async with session_scope() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == guild_id,
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        return {
            "name": module.name,
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
            "dashboard_pages": [
                {"route": p.route, "label": p.label}
                for p in module.get_dashboard_pages()
            ],
        }


@router.put("/guilds/{guild_id}/modules/{module_name}")
async def update_module_config(request: Request, guild_id: int, module_name: str):
    """Update module configuration."""
    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return JSONResponse({"error": "Module not found"}, status_code=404)

    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == guild_id,
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        if db_config is None:
            db_config = ModuleConfig(
                guild_id=guild_id,
                module_name=module_name,
                enabled=False,
            )
            session.add(db_config)

        if "config" in data:
            db_config.config = json.dumps(data["config"])
        if "priority" in data:
            db_config.priority = data["priority"]

        await session.commit()

        return {"success": True, "module": module_name}


@router.post("/guilds/{guild_id}/modules/{module_name}/toggle")
async def toggle_module(request: Request, guild_id: int, module_name: str):
    """Enable or disable a module."""
    bot = request.state.bot
    module = bot.modules.get_module(module_name)
    if module is None:
        return JSONResponse({"error": "Module not found"}, status_code=404)

    data = await request.json()
    enable = data.get("enabled", False)

    async with session_scope() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ModuleConfig).where(
                ModuleConfig.guild_id == guild_id,
                ModuleConfig.module_name == module_name,
            )
        )
        db_config = result.scalar_one_or_none()

        if db_config is None:
            db_config = ModuleConfig(
                guild_id=guild_id,
                module_name=module_name,
                enabled=enable,
            )
            session.add(db_config)
        else:
            db_config.enabled = enable
        await session.commit()

    if enable:
        await bot.modules.enable_module(module_name)
    else:
        await bot.modules.disable_module(module_name)

    return {"success": True, "module": module_name, "enabled": enable}


@router.post("/guilds/{guild_id}/modules/{module_name}/reload")
async def reload_module(request: Request, guild_id: int, module_name: str):
    """Reload a module."""
    bot = request.state.bot
    success = await bot.modules.reload_module(module_name)
    if not success:
        return JSONResponse({"error": "Module not found or reload failed"}, status_code=404)
    return {"success": True, "module": module_name}
