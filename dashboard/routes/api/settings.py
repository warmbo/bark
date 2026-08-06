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

# ── Backup & Restore (settings + module stats) ──────

BACKUP_FORMAT = "bark-backup"
BACKUP_VERSION = 1


@router.get("/guilds/{guild_id}/settings/export")
async def export_settings(request: Request, guild_id: int):
    """Export all guild settings + module configs/stats as an editable JSON file."""
    if not check_api_permission(request, "settings.general"):
        return api_forbidden()

    from datetime import datetime, timezone

    from sqlalchemy import select

    from database.models.guild import GuildSetting
    from database.models.module import ModuleConfig

    async with session_scope() as session:
        setting_rows = await session.execute(
            select(GuildSetting).where(GuildSetting.guild_id == str(guild_id))
        )
        settings = {s.key: s.value for s in setting_rows.scalars().all()}

        module_rows = await session.execute(
            select(ModuleConfig).where(ModuleConfig.guild_id == str(guild_id))
        )
        module_configs = {m.module_name: m for m in module_rows.scalars().all()}

    modules = {}
    bot = request.state.bot
    manager = getattr(bot, "modules", None)
    all_modules = manager.get_all_modules() if manager else {}
    for name, module in all_modules.items():
        entry = {"enabled": True, "priority": 100, "config": {}, "stats": {}}
        dbc = module_configs.get(name)
        if dbc is not None:
            entry["enabled"] = bool(dbc.enabled)
            entry["priority"] = dbc.priority if dbc.priority is not None else 100
            if dbc.config:
                try:
                    entry["config"] = json.loads(dbc.config)
                except json.JSONDecodeError:
                    entry["config"] = {}
        try:
            entry["stats"] = await module.export_stats(guild_id)
        except Exception:
            entry["stats"] = {}
        modules[name] = entry

    return api_success(
        {
            "backup": {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "guild_id": str(guild_id),
                "settings": settings,
                "modules": modules,
            }
        }
    )


@router.post("/guilds/{guild_id}/settings/import")
async def import_settings(request: Request, guild_id: int):
    """Apply an exported backup (settings + module configs/stats)."""
    if not check_api_permission(request, "settings.general"):
        return api_forbidden()

    from sqlalchemy import select

    from database.models.guild import GuildSetting
    from database.models.module import ModuleConfig

    body = await request.json()
    backup = body.get("backup") or body
    if backup.get("format") != BACKUP_FORMAT:
        return api_error("Not a bark backup file (missing 'bark-backup' format marker)")
    if int(backup.get("version", 0)) != BACKUP_VERSION:
        return api_error(f"Unsupported backup version: {backup.get('version')}")

    report: list[str] = []

    # Settings
    settings = backup.get("settings") or {}
    restored_settings = 0
    async with session_scope() as session:
        for key, value in settings.items():
            result = await session.execute(
                select(GuildSetting).where(
                    GuildSetting.guild_id == str(guild_id),
                    GuildSetting.key == key,
                )
            )
            setting = result.scalar_one_or_none()
            if setting is None:
                setting = GuildSetting(
                    guild_id=str(guild_id), key=key, value=str(value)
                )
                session.add(setting)
            else:
                setting.value = str(value)
            restored_settings += 1
        await session.commit()
    report.append(f"settings: restored {restored_settings} key(s)")

    # Module configs + stats
    modules = backup.get("modules") or {}
    bot = request.state.bot
    manager = getattr(bot, "modules", None)
    all_modules = manager.get_all_modules() if manager else {}

    restored_configs = 0
    for name, entry in modules.items():
        module = all_modules.get(name)
        config = entry.get("config") or {}
        enabled = bool(entry.get("enabled", True))
        if module is not None:
            try:
                await module.save_dashboard_config(guild_id, config)
                restored_configs += 1
            except Exception:
                report.append(f"{name}: config failed to apply")
            try:
                if manager is not None and enabled and not manager.is_enabled_for_guild(guild_id, name):
                    await manager.set_guild_enabled(guild_id, name, True)
            except Exception:
                pass
        else:
            # Module not loaded (e.g. plugin not installed) — still persist
            # the config row so it takes effect when the module is installed.
            async with session_scope() as session:
                result = await session.execute(
                    select(ModuleConfig).where(
                        ModuleConfig.guild_id == str(guild_id),
                        ModuleConfig.module_name == name,
                    )
                )
                dbc = result.scalar_one_or_none()
                if dbc is None:
                    dbc = ModuleConfig(
                        guild_id=str(guild_id), module_name=name, enabled=enabled
                    )
                    session.add(dbc)
                dbc.enabled = enabled
                dbc.config = json.dumps(config)
                await session.commit()
            restored_configs += 1
        stats = entry.get("stats") or {}
        if stats and module is not None:
            try:
                report.extend(await module.import_stats(guild_id, stats))
            except Exception:
                report.append(f"{name}: stats failed to import")
    report.append(f"modules: restored {restored_configs} configuration(s)")

    return api_success({"imported": True, "report": report})


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
