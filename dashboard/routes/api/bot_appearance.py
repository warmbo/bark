"""Bot appearance API — avatar, banner, and rich presence controls.

See docs/api-contracts.md#bot-appearance for contract documentation.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from services.instance_auth import can_manage_instance
from services.response import (
    api_error,
    api_forbidden,
    api_success,
)
from services.security import read_upload_limited

MAX_APPEARANCE_UPLOAD_BYTES = 10 * 1024 * 1024

logger = logging.getLogger("bark.api.bot_appearance")

router = APIRouter(tags=["api-bot-appearance"])


def _owner_or_forbidden(request: Request):
    """Bot identity/presence is INSTANCE-GLOBAL — only instance owners may
    change it, not any per-guild admin (a guild admin renaming the shared bot
    would affect every server Bark is in)."""
    if not can_manage_instance(request):
        return api_forbidden("Owner access required")
    return None

# Activity type mapping for Discord
ACTIVITY_TYPES = {
    "playing": 0,
    "streaming": 1,
    "listening": 2,
    "watching": 3,
    "competing": 5,
}


async def _bot_banner_url(bot) -> str | None:
    """Resolve the bot user's banner CDN URL, reliably.

    ``ClientUser.banner`` (discord.py 2.x) is only populated when the user
    was fetched via ``Client.fetch_user`` — the cached self-user from login /
    gateway has it as None even when a banner IS set. Fall back to fetching
    the full user payload (which includes the ``banner`` hash) and build the
    CDN URL directly.
    """
    user = getattr(bot, "user", None)
    try:
        if user and getattr(user, "banner", None):
            return user.banner.url
        if user and getattr(bot, "http", None):
            raw = await bot.http.get_user(user.id)
            banner_hash = (raw or {}).get("banner")
            if banner_hash:
                ext = "gif" if banner_hash.startswith("a_") else "png"
                return f"https://cdn.discordapp.com/banners/{user.id}/{banner_hash}.{ext}"
    except Exception:
        logger.exception("Could not resolve bot banner URL")
    return None


@router.get("/guilds/{guild_id}/bot/appearance")
async def get_bot_appearance(request: Request, guild_id: str):
    """Return the current bot appearance settings from persisted store."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

    from config import config
    from services.presence_store import load_presence
    from services.wallpaper_store import load_wallpaper

    bot = request.state.bot
    user = bot.user
    presence = load_presence(config.data_dir)
    wallpaper = load_wallpaper(config.data_dir)

    data: dict[str, Any] = {
        "avatar_url": user.display_avatar.url if user else None,
        # user.name (not str(user)) — the plain name, no trailing #1234
        # discriminator that Discord appends to bot accounts anyway.
        "username": user.name if user else None,
        "discriminator": user.discriminator if user and hasattr(user, "discriminator") else None,
        "activity_type": presence.get("activity_type", "playing"),
        "activity_name": presence.get("activity_name", ""),
        "wallpaper_invert": wallpaper.get("invert", False),
    }

    data["banner_url"] = await _bot_banner_url(bot)

    return api_success(data)


@router.put("/guilds/{guild_id}/bot/appearance/presence")
async def update_presence(request: Request, guild_id: str):
    """Update the bot's rich presence (activity type + name)."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

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
    except Exception:
        logger.exception("Failed to update presence")
        return api_error("Failed to update presence")


@router.post("/guilds/{guild_id}/bot/appearance/avatar")
async def update_avatar(request: Request, guild_id: str, file: UploadFile = File(...)):
    """Upload a new bot avatar image."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

    if not file.content_type or not file.content_type.startswith("image/"):
        return api_error("File must be an image (JPEG, PNG, or GIF)")

    bot = request.state.bot
    import asyncio

    try:
        image_data = await read_upload_limited(file, MAX_APPEARANCE_UPLOAD_BYTES)
        if len(image_data) > MAX_APPEARANCE_UPLOAD_BYTES:
            return api_error("Image must be under 10MB")

        # Content-Type is client-controlled — validate the actual bytes.
        from services.image_validate import is_image

        if not is_image(image_data):
            return api_error("File contents are not a valid image (JPEG, PNG, GIF, or WebP)")

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
    except Exception:
        logger.exception("Failed to update avatar")
        return api_error("Failed to update avatar")


@router.post("/guilds/{guild_id}/bot/appearance/banner")
async def update_banner(request: Request, guild_id: str, file: UploadFile = File(...)):
    """Upload a new bot banner image (Discord premium feature)."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

    if not file.content_type or not file.content_type.startswith("image/"):
        return api_error("File must be an image (JPEG, PNG, or GIF)")

    import asyncio

    import discord

    bot = request.state.bot
    try:
        image_data = await read_upload_limited(file, MAX_APPEARANCE_UPLOAD_BYTES)
        if len(image_data) > MAX_APPEARANCE_UPLOAD_BYTES:
            return api_error("Image must be under 10MB")

        # Content-Type is client-controlled — validate the actual bytes.
        from services.image_validate import is_image

        if not is_image(image_data):
            return api_error("File contents are not a valid image (JPEG, PNG, GIF, or WebP)")

        # Cap the Discord REST call so a slow API never turns into a 502
        # from the reverse proxy.
        await asyncio.wait_for(bot.user.edit(banner=image_data), timeout=30)
        logger.info("Bot banner updated")
        return api_success(
            {
                "message": "Banner updated",
                "banner_url": await _bot_banner_url(bot),
            }
        )
    except asyncio.TimeoutError:
        logger.error("Banner update timed out")
        return api_error("Banner update timed out — Discord API did not respond in time")
    except discord.Forbidden:
        return api_error("Banner requires a Discord Nitro subscription on the bot owner's account")
    except Exception:
        logger.exception("Failed to update banner")
        return api_error("Failed to update banner")


@router.put("/guilds/{guild_id}/bot/appearance/wallpaper")
async def update_wallpaper(request: Request, guild_id: str):
    """Toggle the instance wallpaper invert treatment (owner-only)."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

    from config import config
    from services.wallpaper_store import save_wallpaper

    body = await request.json()
    invert = bool((body or {}).get("invert", False))
    save_wallpaper(config.data_dir, invert)
    logger.info("Wallpaper invert set to %s", invert)
    return api_success({"message": f"Wallpaper invert {'enabled' if invert else 'disabled'}", "wallpaper_invert": invert})


@router.put("/guilds/{guild_id}/bot/appearance/name")
async def update_bot_name(request: Request, guild_id: str):
    """Change the bot's display name (username)."""
    denied = _owner_or_forbidden(request)
    if denied:
        return denied

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
        return api_error(
            "Cannot change name: insufficient permissions. Rate-limited by Discord (max 2 changes per hour)."
        )
    except Exception:
        logger.exception("Failed to update name")
        return api_error("Failed to update name")
