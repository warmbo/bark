"""Per-guild command prefix resolution and persistence.

Each server can set its own command prefix (e.g. ``bark!``, ``!``, ``$``) plus
whether Discord @mentions also trigger commands. Prefixes are stored in the
per-guild ``GuildSetting`` table and cached in-memory so the bot's per-message
prefix lookup never hits the database more than once per guild (until the
setting changes or the cache is invalidated). An unset guild resolves to the
instance default (``config.bot.command_prefix``, default ``bark!``).
"""

from __future__ import annotations

import logging

from config import config

logger = logging.getLogger("bark.command_prefix")

# GuildSetting keys
PREFIX_SETTING = "command_prefix"
MENTION_SETTING = "command_mention"

DEFAULT_PREFIX = "bark!"

MAX_PREFIX_LENGTH = 10

# guild_id (str) -> resolved value; negative-cached so unset guilds don't
# re-query the DB on every message.
_prefix_cache: dict[str, str] = {}
_mention_cache: dict[str, bool] = {}


def _default_prefix() -> str:
    return (config.bot.command_prefix or DEFAULT_PREFIX).strip() or DEFAULT_PREFIX


async def _read_setting(guild_id: str, key: str) -> str | None:
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(GuildSetting).where(
                        GuildSetting.guild_id == str(guild_id),
                        GuildSetting.key == key,
                    )
                )
            ).scalar_one_or_none()
            return row.value if row is not None else None
    except Exception:
        logger.exception("Failed to read guild setting %s for %s", key, guild_id)
        return None


async def _write_setting(guild_id: str, key: str, value: str) -> bool:
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(GuildSetting).where(
                        GuildSetting.guild_id == str(guild_id),
                        GuildSetting.key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(GuildSetting(guild_id=str(guild_id), key=key, value=value))
            else:
                row.value = value
            await session.commit()
        return True
    except Exception:
        logger.exception("Failed to write guild setting %s for %s", key, guild_id)
        return False


async def resolve_guild_prefix(guild_id) -> str:
    """The command prefix for a guild (cached; falls back to the default)."""
    key = str(guild_id)
    if key in _prefix_cache:
        return _prefix_cache[key]
    raw = await _read_setting(key, PREFIX_SETTING)
    resolved = (raw or _default_prefix()).strip() or DEFAULT_PREFIX
    _prefix_cache[key] = resolved
    return resolved


async def guild_uses_mention(guild_id) -> bool:
    """Whether ``@Bark <command>`` also triggers commands for this guild."""
    key = str(guild_id)
    if key in _mention_cache:
        return _mention_cache[key]
    raw = await _read_setting(key, MENTION_SETTING)
    enabled = (raw or "").strip().lower() in ("1", "true", "yes", "on")
    _mention_cache[key] = enabled
    return enabled


async def resolve_guild_prefixes(bot, guild_id) -> list[str]:
    """All accepted prefixes for a guild: ``[prefix]`` plus mention triggers."""
    prefixes = [await resolve_guild_prefix(guild_id)]
    if await guild_uses_mention(guild_id):
        uid = getattr(getattr(bot, "user", None), "id", None)
        if uid is not None:
            prefixes += [f"<@{uid}> ", f"<@!{uid}> "]
    return prefixes


def invalidate_guild(guild_id) -> None:
    """Drop the cached prefix/mention for a guild so the next lookup re-reads."""
    key = str(guild_id)
    _prefix_cache.pop(key, None)
    _mention_cache.pop(key, None)


def invalidate_all() -> None:
    _prefix_cache.clear()
    _mention_cache.clear()


async def set_guild_prefix(guild_id, prefix: str) -> str:
    """Persist a validated prefix; returns the normalized prefix."""
    prefix = (prefix or "").strip()
    if not prefix:
        raise ValueError("Command prefix cannot be empty.")
    if len(prefix) > MAX_PREFIX_LENGTH:
        raise ValueError(f"Command prefix must be {MAX_PREFIX_LENGTH} characters or fewer.")
    if not await _write_setting(guild_id, PREFIX_SETTING, prefix):
        raise RuntimeError("Failed to save command prefix.")
    _prefix_cache[str(guild_id)] = prefix
    return prefix


async def set_guild_mention(guild_id, enabled: bool) -> bool:
    """Persist whether @mentions trigger commands for a guild."""
    await _write_setting(guild_id, MENTION_SETTING, "true" if enabled else "false")
    _mention_cache[str(guild_id)] = bool(enabled)
    return bool(enabled)


async def get_guild_command_settings(guild_id) -> dict:
    """Current per-guild command settings (prefix + mention toggle)."""
    return {
        "prefix": await resolve_guild_prefix(guild_id),
        "mention": await guild_uses_mention(guild_id),
    }
