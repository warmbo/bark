"""Bot appearance API — avatar, banner, and rich presence controls.

See docs/api-contracts.md#bot-appearance for contract documentation.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from services.response import (
    api_error,
    api_forbidden,
    api_success,
    check_api_permission,
)

logger = logging.getLogger("bark.api.bot_appearance")

router = APIRouter(tags=["api-bot-appearance"])

# Activity type mapping for Discord
ACTIVITY_TYPES = {
    "playing": 0,
    "streaming": 1,
    "listening": 2,
    "watching": 3,
    "competing": 5,
}

ACTIVITY_TYPE_NAMES = {v: k for k, v in ACTIVITY_TYPES.items()}


@router.get("/guilds/{guild_id}/bot/appearance")
async def get_bot_appearance(request: Request, guild_id: str):
    """Return the current bot appearance settings from persisted store."""
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Insufficient permissions")

    from config import config
    from services.presence_store import load_presence

    bot = request.state.bot
    user = bot.user
    presence = load_presence(config.data_dir)

    data: dict[str, Any] = {
        "avatar_url": user.display_avatar.url if user else None,
        "username": str(user) if user else None,
        "discriminator": user.discriminator if user and hasattr(user, "discriminator") else None,
        "activity_type": presence.get("activity_type", "playing"),
        "activity_name": presence.get("activity_name", ""),
    }

    # Try banner — discord.py 2.x supports user.banner
    try:
        if user and user.banner:
            data["banner_url"] = user.banner.url
    except Exception:
        data["banner_url"] = None

    return api_success(data)


@router.put("/guilds/{guild_id}/bot/appearance/presence")
async def update_presence(request: Request, guild_id: str):
    """Update the bot's rich presence (activity type + name)."""
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Insufficient permissions")

    import discord

    body = await request.json()
    activity_type = str(body.get("activity_type", "playing")).strip()
    activity_name = str(body.get("activity_name", "")).strip()

    if activity_type not in ACTIVITY_TYPES:
        return api_error(f"Invalid activity type. Valid: {', '.join(ACTIVITY_TYPES.keys())}")

    if not activity_name:
        return api_error("Activity name is required")

    bot = request.state.bot
    try:
        act = discord.Activity(
            type=discord.ActivityType(ACTIVITY_TYPES[activity_type]),
            name=activity_name,
        )
        await bot.change_presence(activity=act)
        # Persist so it survives restarts
        from config import config
        from services.presence_store import save_presence

        save_presence(config.data_dir, activity_type, activity_name)
        logger.info("Presence updated: %s %s", activity_type, activity_name)
        return api_success({"message": f"Presence set to {activity_type} {activity_name}"})
    except Exception as exc:
        logger.exception("Failed to update presence")
        return api_error(f"Failed to update presence: {exc}")


@router.post("/guilds/{guild_id}/bot/appearance/avatar")
async def update_avatar(request: Request, guild_id: str, file: UploadFile = File(...)):
    """Upload a new bot avatar image."""
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Insufficient permissions")

    if not file.content_type or not file.content_type.startswith("image/"):
        return api_error("File must be an image (JPEG, PNG, or GIF)")

    bot = request.state.bot
    import asyncio

    try:
        image_data = await file.read()
        if len(image_data) > 10 * 1024 * 1024:
            return api_error("Image must be under 10MB")

        # Discord's REST call can hang (large uploads, API latency); cap it so
        # the reverse proxy never sees a silent upstream and returns 502.
        await asyncio.wait_for(bot.user.edit(avatar=image_data), timeout=30)
        logger.info("Bot avatar updated")
        return api_success(
            {
                "message": "Avatar updated",
                "avatar_url": bot.user.display_avatar.url,
            }
        )
    except asyncio.TimeoutError:
        logger.error("Avatar update timed out")
        return api_error("Avatar update timed out — Discord API did not respond in time")
    except Exception as exc:
        logger.exception("Failed to update avatar")
        return api_error(f"Failed to update avatar: {exc}")


@router.post("/guilds/{guild_id}/bot/appearance/banner")
async def update_banner(request: Request, guild_id: str, file: UploadFile = File(...)):
    """Upload a new bot banner image (Discord premium feature)."""
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Insufficient permissions")

    if not file.content_type or not file.content_type.startswith("image/"):
        return api_error("File must be an image (JPEG, PNG, or GIF)")

    import asyncio

    import discord

    bot = request.state.bot
    try:
        image_data = await file.read()
        if len(image_data) > 10 * 1024 * 1024:
            return api_error("Image must be under 10MB")

        # Cap the Discord REST call so a slow API never turns into a 502
        # from the reverse proxy.
        await asyncio.wait_for(bot.user.edit(banner=image_data), timeout=30)
        logger.info("Bot banner updated")
        return api_success(
            {
                "message": "Banner updated",
                "banner_url": bot.user.banner.url if bot.user.banner else None,
            }
        )
    except asyncio.TimeoutError:
        logger.error("Banner update timed out")
        return api_error("Banner update timed out — Discord API did not respond in time")
    except discord.Forbidden:
        return api_error("Banner requires a Discord Nitro subscription on the bot owner's account")
    except Exception as exc:
        logger.exception("Failed to update banner")
        return api_error(f"Failed to update banner: {exc}")


@router.put("/guilds/{guild_id}/bot/appearance/name")
async def update_bot_name(request: Request, guild_id: str):
    """Change the bot's display name (username)."""
    if not check_api_permission(request, "guild.manage", guild_id):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    new_name = str(body.get("name", "")).strip()
    if not new_name or len(new_name) < 2 or len(new_name) > 32:
        return api_error("Name must be between 2 and 32 characters")

    import asyncio

    import discord

    bot = request.state.bot
    try:
        await asyncio.wait_for(bot.user.edit(username=new_name), timeout=30)
        logger.info("Bot name updated to %s", new_name)
        return api_success({"message": f"Bot name changed to {new_name}"})
    except asyncio.TimeoutError:
        logger.error("Name update timed out")
        return api_error("Name update timed out — Discord API did not respond in time")
    except discord.Forbidden:
        return api_error("Cannot change name: insufficient permissions. Rate-limited by Discord (max 2 changes per hour).")
    except Exception as exc:
        logger.exception("Failed to update name")
        return api_error(f"Failed to update name: {exc}")
