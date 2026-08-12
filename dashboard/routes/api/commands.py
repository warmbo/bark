"""Per-guild command settings API — prefix and @mention trigger.

Prefixes are per-guild: an admin changes the command prefix their server
uses (e.g. ``bark!`` → ``!``) from the dashboard, and it applies to new
messages immediately without a restart. See
``services/command_prefix.py`` for the persistence + resolution layer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from services.command_prefix import (
    get_guild_command_settings,
    set_guild_mention,
    set_guild_prefix,
)
from services.response import api_error, api_forbidden, api_success, check_api_permission

logger = logging.getLogger("bark.api.commands")

router = APIRouter(tags=["api-commands"])


@router.get("/guilds/{guild_id}/commands/settings")
async def get_command_settings(request: Request, guild_id: int):
    """Return the guild's current command prefix + mention trigger."""
    if not check_api_permission(request, "settings.general", guild_id):
        return api_forbidden()
    settings = await get_guild_command_settings(guild_id)
    return api_success(settings)


@router.put("/guilds/{guild_id}/commands/settings")
async def update_command_settings(request: Request, guild_id: int):
    """Update the guild's command prefix and/or @mention trigger."""
    if not check_api_permission(request, "settings.general", guild_id):
        return api_forbidden()

    body = await request.json()
    errors = []

    if "prefix" in body:
        try:
            prefix = await set_guild_prefix(guild_id, str(body.get("prefix", "")))
        except (ValueError, RuntimeError) as exc:
            errors.append(str(exc))
            prefix = None
    else:
        prefix = None

    if "mention" in body:
        mention = await set_guild_mention(guild_id, bool(body.get("mention", False)))
    else:
        mention = None

    if errors:
        return api_error("; ".join(errors))

    settings = await get_guild_command_settings(guild_id)
    if prefix is not None:
        settings["prefix"] = prefix
    if mention is not None:
        settings["mention"] = mention
    logger.info("Command settings updated for guild %s: %s", guild_id, settings)
    return api_success(settings)
