"""Discord OAuth guild access persistence and dashboard catalog helpers."""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.permissions import DashboardGuildAccess

DISCORD_ADMINISTRATOR = 0x8
DISCORD_MANAGE_GUILD = 0x20


def can_manage_discord_guild(*, owner: bool, permissions: int) -> bool:
    """Return whether Discord grants server-management access."""
    return owner or bool(permissions & (DISCORD_ADMINISTRATOR | DISCORD_MANAGE_GUILD))


def derive_dashboard_role(
    guilds: Iterable[dict[str, Any]],
    bot_guild_ids: set[str],
) -> str:
    """Derive the global UI role from the user's current shared guilds."""
    shared = [guild for guild in guilds if str(guild.get("id")) in bot_guild_ids]
    if any(
        can_manage_discord_guild(
            owner=bool(guild.get("owner", False)),
            permissions=_permission_value(guild.get("permissions")),
        )
        for guild in shared
    ):
        return "admin"
    return "moderator" if shared else "viewer"


def resolve_dashboard_role(
    discord_user_id: str,
    owner_discord_ids: set[str],
    derived_role: str,
    existing_role: str | None,
) -> str:
    """Resolve dashboard role without allowing a first-login owner claim."""
    if discord_user_id in owner_discord_ids:
        return "owner"
    if not owner_discord_ids and existing_role == "owner":
        return "owner"
    return derived_role


def _permission_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def replace_user_guild_access(
    session: AsyncSession,
    discord_user_id: str,
    guilds: Iterable[dict[str, Any]],
) -> None:
    """Replace a user's cached OAuth guild snapshot after a successful login."""
    await session.execute(
        delete(DashboardGuildAccess).where(
            DashboardGuildAccess.user_discord_id == discord_user_id
        )
    )
    for guild in guilds:
        permissions = _permission_value(guild.get("permissions"))
        owner = bool(guild.get("owner", False))
        session.add(
            DashboardGuildAccess(
                user_discord_id=discord_user_id,
                guild_id=str(guild["id"]),
                name=str(guild.get("name") or "Unknown server"),
                icon_hash=guild.get("icon"),
                permissions=permissions,
                owner=owner,
                can_manage=can_manage_discord_guild(
                    owner=owner,
                    permissions=permissions,
                ),
            )
        )
    await session.flush()


async def get_user_guild_access(
    session: AsyncSession,
    discord_user_id: str,
) -> list[DashboardGuildAccess]:
    """Return every server Discord reported for this user."""
    result = await session.execute(
        select(DashboardGuildAccess)
        .where(DashboardGuildAccess.user_discord_id == discord_user_id)
        .order_by(DashboardGuildAccess.guild_id)
    )
    return list(result.scalars().all())


async def user_can_manage_guild(
    session: AsyncSession,
    discord_user_id: str,
    guild_id: int | str,
) -> bool:
    """Check the user's latest Discord OAuth permissions for one guild."""
    result = await session.execute(
        select(DashboardGuildAccess.can_manage).where(
            DashboardGuildAccess.user_discord_id == discord_user_id,
            DashboardGuildAccess.guild_id == str(guild_id),
        )
    )
    return bool(result.scalar_one_or_none())


def build_bot_invite_url(client_id: str, guild_id: str) -> str:
    """Build a server-targeted Discord install URL for Bark."""
    if not client_id:
        return ""
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "scope": "bot applications.commands",
            "permissions": "8",
            "guild_id": guild_id,
            "disable_guild_select": "true",
        }
    )
    return f"https://discord.com/oauth2/authorize?{query}"


def build_guild_catalog(
    oauth_guilds: Sequence[DashboardGuildAccess],
    bot_guilds: Iterable[Any],
    *,
    client_id: str,
) -> list[dict[str, Any]]:
    """Merge a user's complete Discord server list with live bot state."""
    installed = {str(guild.id): guild for guild in bot_guilds}
    catalog: list[dict[str, Any]] = []
    for access in oauth_guilds:
        guild = installed.get(access.guild_id)
        icon_url = (
            f"https://cdn.discordapp.com/icons/{access.guild_id}/{access.icon_hash}.png"
            if access.icon_hash
            else None
        )
        if guild is not None and getattr(guild, "icon", None):
            icon_url = guild.icon.url
        access_tier = (
            "connected" if guild is not None
            else "manageable" if access.can_manage
            else "other"
        )
        catalog.append(
            {
                "id": access.guild_id,
                "name": getattr(guild, "name", None) or access.name,
                "icon_url": icon_url,
                "member_count": getattr(guild, "member_count", None),
                "connected": guild is not None,
                "can_manage": access.can_manage,
                "access_tier": access_tier,
                "invite_url": build_bot_invite_url(client_id, access.guild_id),
            }
        )
    tier_order = {"connected": 0, "manageable": 1, "other": 2}
    return sorted(
        catalog,
        key=lambda item: (tier_order[item["access_tier"]], item["name"].casefold()),
    )
