"""Per-guild key/value settings backed by GuildSetting.

Centralizes server settings (MOTD, custom banner, staff roles, …) so the
dashboard and modules read/write them through one service instead of
hand-rolling GuildSetting queries. A ``None``/empty value deletes the key.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import GuildSetting


async def get_setting(guild_id: int | str, key: str, default: str = "") -> str:
    """Return one setting's value (or ``default`` when unset)."""
    values = await get_settings(guild_id, key)
    return values.get(key, default)


async def get_settings(guild_id: int | str, *keys: str) -> dict[str, str]:
    """Return the given settings for a guild in one query."""
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.guild_id == str(guild_id),
                    GuildSetting.key.in_(keys),
                )
            )
        ).scalars().all()
        return {row.key: row.value for row in rows}


async def set_setting(guild_id: int | str, key: str, value: Any) -> None:
    """Upsert a setting; empty/None value deletes the key."""
    value_str = "" if value is None else str(value)
    async with session_scope() as session:
        row = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.guild_id == str(guild_id),
                    GuildSetting.key == key,
                )
            )
        ).scalars().first()
        if value_str:
            if row:
                row.value = value_str
            else:
                session.add(GuildSetting(guild_id=str(guild_id), key=key, value=value_str))
        elif row:
            await session.delete(row)
