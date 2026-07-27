"""Persistent presence store — saves/loads bot activity across restarts.

Uses a JSON file in the data directory.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("bark.services.presence_store")

_ACTIVITY_TYPES = {
    "playing": 0,
    "streaming": 1,
    "listening": 2,
    "watching": 3,
    "competing": 5,
}


def _store_path(data_dir: Path) -> Path:
    return data_dir / "bot_presence.json"


def load_presence(data_dir: Path) -> dict[str, Any]:
    """Load persisted presence settings, or return defaults."""
    path = _store_path(data_dir)
    if not path.exists():
        return {"activity_type": "playing", "activity_name": "with the dashboard"}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"activity_type": "playing", "activity_name": "with the dashboard"}
        return {
            "activity_type": data.get("activity_type", "playing"),
            "activity_name": data.get("activity_name", "with the dashboard"),
        }
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read presence store, using defaults")
        return {"activity_type": "playing", "activity_name": "with the dashboard"}


def save_presence(data_dir: Path, activity_type: str, activity_name: str) -> None:
    """Persist presence settings to disk."""
    path = _store_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "activity_type": activity_type,
            "activity_name": activity_name,
        }, indent=2))
        logger.info("Presence saved: %s %s", activity_type, activity_name)
    except OSError as exc:
        logger.error("Failed to save presence: %s", exc)


async def restore_presence(bot) -> None:
    """Restore the bot's presence from persisted settings on startup."""
    import discord
    from config import config

    presence = load_presence(config.data_dir)
    atype = _ACTIVITY_TYPES.get(presence.get("activity_type", "playing"), 0)
    aname = presence.get("activity_name", "with the dashboard")
    try:
        act = discord.Activity(type=discord.ActivityType(atype), name=aname)
        await bot.change_presence(activity=act)
        logger.info("Presence restored: %s %s", presence["activity_type"], aname)
    except Exception as exc:
        logger.warning("Could not restore presence: %s", exc)
