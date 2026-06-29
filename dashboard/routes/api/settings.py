"""
Settings API routes.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database.engine import session_scope
from database.models.logging import LogConfig
from database.models.automod import AutoModConfig
from database.models.guild import GuildSetting

router = APIRouter(tags=["api-settings"])


# ── General Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings")
async def get_all_settings(request: Request, guild_id: int):
    """Get all settings for a guild."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(GuildSetting).where(GuildSetting.guild_id == guild_id)
        )
        settings = {s.key: s.value for s in result.scalars().all()}

        return {"settings": settings}


@router.put("/guilds/{guild_id}/settings/general")
async def update_general_settings(request: Request, guild_id: int):
    """Update general guild settings."""
    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select

        for key, value in data.items():
            result = await session.execute(
                select(GuildSetting).where(
                    GuildSetting.guild_id == guild_id,
                    GuildSetting.key == key,
                )
            )
            setting = result.scalar_one_or_none()

            if setting is None:
                setting = GuildSetting(
                    guild_id=guild_id,
                    key=key,
                    value=str(value),
                )
                session.add(setting)
            else:
                setting.value = str(value)

        await session.commit()
        return {"success": True}


# ── Logging Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings/logging")
async def get_logging_settings(request: Request, guild_id: int):
    """Get logging configuration."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(LogConfig).where(LogConfig.guild_id == guild_id)
        )
        configs = result.scalars().all()

        return {
            "log_configs": [
                {
                    "id": c.id,
                    "event_type": c.event_type,
                    "channel_id": c.channel_id,
                    "enabled": c.enabled,
                }
                for c in configs
            ]
        }


@router.put("/guilds/{guild_id}/settings/logging")
async def update_logging_settings(request: Request, guild_id: int):
    """Update logging configuration."""
    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select

        for item in data.get("configs", []):
            result = await session.execute(
                select(LogConfig).where(
                    LogConfig.guild_id == guild_id,
                    LogConfig.event_type == item.get("event_type"),
                )
            )
            config = result.scalar_one_or_none()

            if config is None:
                config = LogConfig(
                    guild_id=guild_id,
                    event_type=item.get("event_type", ""),
                    channel_id=item.get("channel_id", ""),
                    enabled=item.get("enabled", True),
                )
                session.add(config)
            else:
                if "channel_id" in item:
                    config.channel_id = item["channel_id"]
                if "enabled" in item:
                    config.enabled = item["enabled"]

        await session.commit()
        return {"success": True}


# ── AutoMod Settings ─────────────────────────────────


@router.get("/guilds/{guild_id}/settings/automod")
async def get_automod_settings(request: Request, guild_id: int):
    """Get AutoMod configuration."""
    from sqlalchemy import select

    async with session_scope() as session:
        result = await session.execute(
            select(AutoModConfig).where(AutoModConfig.guild_id == guild_id)
        )
        configs = result.scalars().all()

        return {
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


@router.put("/guilds/{guild_id}/settings/automod")
async def update_automod_settings(request: Request, guild_id: int):
    """Update AutoMod configuration."""
    data = await request.json()

    async with session_scope() as session:
        from sqlalchemy import select

        for item in data.get("configs", []):
            result = await session.execute(
                select(AutoModConfig).where(
                    AutoModConfig.guild_id == guild_id,
                    AutoModConfig.rule_type == item.get("rule_type"),
                )
            )
            config = result.scalar_one_or_none()

            if config is None:
                config = AutoModConfig(
                    guild_id=guild_id,
                    rule_type=item.get("rule_type", ""),
                )
                session.add(config)

            for field in ("enabled", "threshold", "action", "duration", "ignored_roles", "ignored_channels"):
                if field in item:
                    if field in ("ignored_roles", "ignored_channels"):
                        setattr(config, field, json.dumps(item[field]))
                    else:
                        setattr(config, field, item[field])

        await session.commit()
        return {"success": True}
