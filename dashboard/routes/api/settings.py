"""
Settings API routes.
"""

import json

from fastapi import APIRouter, Request

from database.engine import session_scope
from database.models.automod import AutoModConfig
from database.models.guild import GuildSetting
from services.response import (
    api_error,
    api_forbidden,
    api_success,
    check_api_permission,
    get_module_min_role,
)

router = APIRouter(tags=["api-settings"])

# ── Config Health ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings/health")
async def settings_health(request: Request, guild_id: int):
    """Check configuration health for all modules in this guild."""
    from sqlalchemy import select

    from dashboard.routes.api.modules import _validate_config
    from database.models.module import ModuleConfig

    bot = request.state.bot
    results = []
    async with session_scope() as session:
        db_configs = (
            (
                await session.execute(
                    select(ModuleConfig).where(ModuleConfig.guild_id == str(guild_id))
                )
            )
            .scalars()
            .all()
        )
        mapping = {c.module_name: c for c in db_configs}
        for name, module in bot.modules.get_all_modules().items():
            issues = []
            cfg = mapping.get(name)
            parsed = {}
            if cfg and cfg.config:
                try:
                    parsed = json.loads(cfg.config)
                except (json.JSONDecodeError, TypeError):
                    issues.append("config is not valid JSON")
                    parsed = {}
            schema = module.get_settings_schema()
            if schema and parsed:
                validation_errors = _validate_config(parsed, schema.get("properties", {}))
                issues.extend(validation_errors)
            enabled = cfg.enabled if cfg else False
            results.append(
                {
                    "module": name,
                    "enabled": enabled,
                    "has_config": bool(cfg),
                    "issues": issues,
                    "healthy": not issues,
                }
            )
    unhealthy = [r for r in results if not r["healthy"]]
    return api_success(
        {
            "healthy": len(unhealthy) == 0,
            "modules": results,
            "issue_count": len(unhealthy),
        }
    )


# ── General Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings")
async def get_all_settings(request: Request, guild_id: int):
    """Get all settings for a guild."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(GuildSetting).where(GuildSetting.guild_id == str(guild_id))
        )
        settings = {s.key: s.value for s in result.scalars().all()}

        return api_success({"settings": settings})


@router.put("/guilds/{guild_id}/settings/general")
async def update_general_settings(request: Request, guild_id: int):
    """Update general guild settings."""
    if not check_api_permission(request, "settings.general"):
        return api_forbidden()
    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select

        for key, value in data.items():
            result = await session.execute(
                select(GuildSetting).where(
                    GuildSetting.guild_id == str(guild_id),
                    GuildSetting.key == key,
                )
            )
            setting = result.scalar_one_or_none()

            if setting is None:
                setting = GuildSetting(
                    guild_id=str(guild_id),
                    key=key,
                    value=str(value),
                )
                session.add(setting)
            else:
                setting.value = str(value)

        await session.commit()
        return api_success({"updated": True})


# ── Logging Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings/logging")
async def get_logging_settings(request: Request, guild_id: int):
    """Get logging configuration."""
    module = request.state.bot.modules.get_module("logging")
    if module is None:
        return api_error("Logging module not found", status_code=404)
    config = await module.load_dashboard_config(guild_id)
    return api_success(
        {
            "log_configs": [
                {
                    "event_type": event_type,
                    "channel_id": values.get("channel_id", ""),
                    "enabled": values.get("enabled", False),
                }
                for event_type, values in config.items()
                if isinstance(values, dict)
            ]
        }
    )


@router.put("/guilds/{guild_id}/settings/logging")
async def update_logging_settings(request: Request, guild_id: int):
    """Update logging configuration."""
    await get_module_min_role("logging", guild_id)
    if not check_api_permission(request, "logging.configure", guild_id):
        return api_forbidden()
    data = await request.json()

    module = request.state.bot.modules.get_module("logging")
    if module is None:
        return api_error("Logging module not found", status_code=404)
    config = await module.load_dashboard_config(guild_id)
    for item in data.get("configs", []):
        event_type = item.get("event_type")
        if not event_type:
            continue
        existing = config.get(event_type, {})
        config[event_type] = {
            "channel_id": str(item.get("channel_id", existing.get("channel_id", ""))),
            "enabled": bool(item.get("enabled", existing.get("enabled", True))),
        }
    await module.save_dashboard_config(guild_id, config)
    return api_success({"updated": True})


# ── AutoMod Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings/automod")
async def get_automod_settings(request: Request, guild_id: int):
    """Get AutoMod configuration."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(AutoModConfig).where(AutoModConfig.guild_id == str(guild_id))
        )
        configs = result.scalars().all()

        return api_success(
            {
                "automod_configs": [
                    {
                        "id": c.id,
                        "rule_type": c.rule_type,
                        "enabled": c.enabled,
                        "threshold": c.threshold,
                        "action": c.action,
                        "duration": c.duration,
                        "ignored_roles": json.loads(c.ignored_roles),
                        "ignored_channels": json.loads(c.ignored_channels),
                    }
                    for c in configs
                ]
            }
        )


@router.put("/guilds/{guild_id}/settings/automod")
async def update_automod_settings(request: Request, guild_id: int):
    """Update AutoMod configuration."""
    if not check_api_permission(request, "settings.automod"):
        return api_forbidden()
    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select

        for item in data.get("configs", []):
            result = await session.execute(
                select(AutoModConfig).where(
                    AutoModConfig.guild_id == str(guild_id),
                    AutoModConfig.rule_type == item.get("rule_type"),
                )
            )
            config = result.scalar_one_or_none()

            if config is None:
                config = AutoModConfig(
                    guild_id=str(guild_id),
                    rule_type=item.get("rule_type", ""),
                )
                session.add(config)

            for field in (
                "enabled",
                "threshold",
                "action",
                "duration",
                "ignored_roles",
                "ignored_channels",
            ):
                if field in item:
                    if field in ("ignored_roles", "ignored_channels"):
                        setattr(config, field, json.dumps(item[field]))
                    else:
                        setattr(config, field, item[field])

        await session.commit()
        return api_success({"updated": True})
