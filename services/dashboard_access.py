"""Discord OAuth guild access persistence and dashboard catalog helpers."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.permissions import DashboardGuildAccess

DISCORD_ADMINISTRATOR = 0x8
DISCORD_MANAGE_GUILD = 0x20

# GuildSetting key holding the JSON array of role IDs a server owner has
# designated as "moderator" for dashboard access. When set, members holding
# one of these roles are shown as ready to manage that server.
MODERATOR_ROLES_SETTING = "dashboard_moderator_roles"


def parse_moderator_role_ids(value: str | None) -> set[str]:
    """Parse the persisted moderator-roles setting into a set of role IDs.

    Accepts the canonical JSON array (``["111","222"]``) as well as a plain
    comma-separated list for hand-edited backups.
    """
    if not value:
        return set()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return {str(item) for item in parsed if str(item)}
    except (TypeError, ValueError):
        pass
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _roles_from_access(access: DashboardGuildAccess) -> set[str]:
    """Return the role IDs snapshotted for this access row."""
    return {role for role in (getattr(access, "roles", "") or "").split(",") if role}


async def get_dashboard_moderator_roles(
    session: AsyncSession,
    guild_ids: Iterable[str],
) -> dict[str, set[str]]:
    """Load each guild's owner-configured dashboard moderator roles.

    Returns a mapping of guild_id to the set of role IDs that count as
    "moderator" for that server (empty set when unconfigured).
    """
    from sqlalchemy import select

    from database.models.guild import GuildSetting

    ids = [str(guild_id) for guild_id in guild_ids]
    if not ids:
        return {}
    result = await session.execute(
        select(GuildSetting).where(
            GuildSetting.guild_id.in_(ids),
            GuildSetting.key == MODERATOR_ROLES_SETTING,
        )
    )
    return {
        row.guild_id: parse_moderator_role_ids(row.value)
        for row in result.scalars().all()
    }


def user_ready_to_manage(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
) -> bool:
    """Return whether the user has admin or moderator rights in this server.

    Admin rights come from Discord itself (server owner or the
    ADMINISTRATOR permission). Moderator rights come from the MANAGE_GUILD
    permission or from holding one of the roles the server owner designated
    as moderator for dashboard access (per-server via the
    ``dashboard_moderator_roles`` setting).
    """
    if access.owner:
        return True
    if access.permissions & (DISCORD_ADMINISTRATOR | DISCORD_MANAGE_GUILD):
        return True
    return bool(_roles_from_access(access) & moderator_role_ids)


def role_from_access_with_staff_roles(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
) -> str:
    """Map a persisted access snapshot to a dashboard role tier.

    Like ``role_from_access`` but also honours the server owner's
    configured moderator roles: holding one of those roles upgrades the
    user to ``moderator`` even without Discord management permissions.
    Used by the request middleware so API gating matches the per-server
    "Ready to manage" shown on the server list.
    """
    if access.owner or (access.permissions & DISCORD_ADMINISTRATOR):
        return "admin"
    if (access.permissions & DISCORD_MANAGE_GUILD) or (
        _roles_from_access(access) & moderator_role_ids
    ):
        return "moderator"
    return "viewer"


def can_manage_discord_guild(*, owner: bool, permissions: int) -> bool:
    """Return whether Discord grants server-management access."""
    return owner or bool(permissions & (DISCORD_ADMINISTRATOR | DISCORD_MANAGE_GUILD))


def role_from_access(*, owner: bool, permissions: int) -> str:
    """Map Discord guild permissions to the dashboard role tier for that guild.

    Mirrors ``derive_dashboard_role`` at guild granularity: an owner or
    ADMINISTRATOR is admin, a MANAGE_GUILD holder is moderator, and every
    other member is a read-only viewer.
    """
    if owner or (_permission_value(permissions) & DISCORD_ADMINISTRATOR):
        return "admin"
    if _permission_value(permissions) & DISCORD_MANAGE_GUILD:
        return "moderator"
    return "viewer"


def derive_dashboard_role(
    guilds: Iterable[dict[str, Any]],
    bot_guild_ids: set[str],
) -> str:
    """Derive the global UI role from the user's current shared guilds.

    Tiering matches Discord permissions: an owner or ADMINISTRATOR of any
    shared guild becomes admin; a MANAGE_GUILD holder becomes moderator;
    every other member of a shared guild is a read-only viewer. Users who
    share no guild with the bot are viewers too (they have nothing to see).
    """
    tiers = {"viewer": 0, "moderator": 1, "admin": 2}
    best = 0
    for guild in guilds:
        if str(guild.get("id")) not in bot_guild_ids:
            continue
        role = role_from_access(
            owner=bool(guild.get("owner", False)),
            permissions=_permission_value(guild.get("permissions")),
        )
        best = max(best, tiers[role])
    return {0: "viewer", 1: "moderator", 2: "admin"}[best]


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
    *,
    roles_by_guild: dict[str, list[str]] | None = None,
) -> None:
    """Replace a user's cached OAuth guild snapshot after a successful login.

    ``roles_by_guild`` carries the member's Discord role IDs per guild as
    resolved from the bot's member cache at login; it feeds per-server
    "Ready to manage" gating (owner-configured moderator roles).
    """
    roles_by_guild = roles_by_guild or {}
    await session.execute(
        delete(DashboardGuildAccess).where(DashboardGuildAccess.user_discord_id == discord_user_id)
    )
    for guild in guilds:
        permissions = _permission_value(guild.get("permissions"))
        owner = bool(guild.get("owner", False))
        guild_id = str(guild["id"])
        member_roles = roles_by_guild.get(guild_id)
        session.add(
            DashboardGuildAccess(
                user_discord_id=discord_user_id,
                guild_id=guild_id,
                name=str(guild.get("name") or "Unknown server"),
                icon_hash=guild.get("icon"),
                permissions=permissions,
                owner=owner,
                can_manage=can_manage_discord_guild(
                    owner=owner,
                    permissions=permissions,
                ),
                roles=",".join(member_roles) if member_roles else "",
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


async def get_user_guild_access_row(
    session: AsyncSession,
    discord_user_id: str,
    guild_id: int | str,
) -> DashboardGuildAccess | None:
    """Return the persisted Discord access snapshot for one guild.

    The snapshot is written at login from Discord's OAuth payload, so it is
    the authoritative per-guild owner/permission record available without a
    fresh Discord call.
    """
    result = await session.execute(
        select(DashboardGuildAccess).where(
            DashboardGuildAccess.user_discord_id == discord_user_id,
            DashboardGuildAccess.guild_id == str(guild_id),
        )
    )
    return result.scalar_one_or_none()


async def user_is_guild_member(
    session: AsyncSession,
    discord_user_id: str,
    guild_id: int | str,
) -> bool:
    """Return whether Discord reported the user as a member of the guild.

    Any guild the user belongs to (regardless of permissions) has an access
    row written at login, so membership is a separate, broader check than
    ``user_can_manage_guild``.
    """
    result = await session.execute(
        select(DashboardGuildAccess.user_discord_id).where(
            DashboardGuildAccess.user_discord_id == discord_user_id,
            DashboardGuildAccess.guild_id == str(guild_id),
        )
    )
    return result.scalar_one_or_none() is not None


async def user_shares_guild_with_bot(
    session: AsyncSession,
    discord_user_id: str,
    bot_guild_ids: set[str],
) -> bool:
    """Return whether the user is a member of any guild where Bark is installed.

    This is the admission criterion for the dashboard: anyone who belongs to
    a server Bark is in can sign in and view it (login always required).
    A user may belong to several Bark servers, so the row scan is capped at
    one match rather than assuming uniqueness.
    """
    if not bot_guild_ids:
        return False
    result = await session.execute(
        select(DashboardGuildAccess.user_discord_id)
        .where(
            DashboardGuildAccess.user_discord_id == discord_user_id,
            DashboardGuildAccess.guild_id.in_(list(bot_guild_ids)),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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
    moderator_roles_by_guild: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Merge a user's complete Discord server list with live bot state.

    ``moderator_roles_by_guild`` carries each guild's owner-configured
    moderator role IDs (see ``get_dashboard_moderator_roles``); it drives the
    per-server ``ready_to_manage`` flag shown as "Ready to manage".
    """
    installed = {str(guild.id): guild for guild in bot_guilds}
    moderator_roles_by_guild = moderator_roles_by_guild or {}
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
            "connected" if guild is not None else "manageable" if access.can_manage else "other"
        )
        catalog.append(
            {
                "id": access.guild_id,
                "name": getattr(guild, "name", None) or access.name,
                "icon_url": icon_url,
                "member_count": getattr(guild, "member_count", None),
                "connected": guild is not None,
                "can_manage": access.can_manage,
                "ready_to_manage": user_ready_to_manage(
                    access,
                    moderator_roles_by_guild.get(access.guild_id, set()),
                ),
                "access_tier": access_tier,
                "invite_url": build_bot_invite_url(client_id, access.guild_id),
            }
        )
    tier_order = {"connected": 0, "manageable": 1, "other": 2}
    return sorted(
        catalog,
        key=lambda item: (tier_order[item["access_tier"]], item["name"].casefold()),
    )
