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

# GuildSetting keys holding the dashboard staff roles a server owner has
# designated. Moderator roles are a JSON array of role IDs; the admin role is
# a single role ID (or empty). Nothing else grants dashboard privileges —
# Discord's ADMINISTRATOR/MANAGE_GUILD permissions are deliberately NOT
# treated as dashboard admin/moderator (requirement: no role is implied admin
# beyond what is configured, plus the server/instance owners).
MODERATOR_ROLES_SETTING = "dashboard_moderator_roles"
ADMIN_ROLE_SETTING = "dashboard_admin_role"


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


def parse_admin_role_id(value: str | None) -> str | None:
    """Parse the persisted single admin-role setting (JSON string or plain)."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, str) and parsed:
            return parsed
    except (TypeError, ValueError):
        pass
    return str(value).strip() or None


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


async def get_dashboard_admin_role(
    session: AsyncSession,
    guild_ids: Iterable[str],
) -> dict[str, str | None]:
    """Load each guild's owner-configured dashboard admin role.

    Returns a mapping of guild_id to the single role ID that counts as
    "admin" for that server (None when unconfigured).
    """
    from sqlalchemy import select

    from database.models.guild import GuildSetting

    ids = [str(guild_id) for guild_id in guild_ids]
    if not ids:
        return {}
    result = await session.execute(
        select(GuildSetting).where(
            GuildSetting.guild_id.in_(ids),
            GuildSetting.key == ADMIN_ROLE_SETTING,
        )
    )
    return {
        row.guild_id: parse_admin_role_id(row.value)
        for row in result.scalars().all()
    }


def user_ready_to_manage(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
    admin_role_id: str | None = None,
    *,
    is_instance_owner: bool = False,
) -> bool:
    """Return whether the user can manage this server in the dashboard.

    Grants come ONLY from: running this Bark instance (its owner), being the
    server owner, holding the owner-configured admin role, or holding one of
    the owner-configured moderator roles. Discord's ADMINISTRATOR/MANAGE_GUILD
    permissions are intentionally not treated as dashboard privileges (explicit
    staff roles only). ``is_instance_owner`` is the person who set up this
    Bark instance — they can manage every server their own bot is in, even when
    they are not the Discord server owner and hold no configured staff role
    (so two owners' Bark bots can share a server without blocking each other).
    """
    if is_instance_owner or access.owner:
        return True
    member_roles = _roles_from_access(access)
    if admin_role_id and admin_role_id in member_roles:
        return True
    return bool(member_roles & moderator_role_ids)


def role_from_access_with_staff_roles(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
    admin_role_id: str | None = None,
    *,
    is_instance_owner: bool = False,
) -> str:
    """Map a persisted access snapshot to a dashboard role tier.

    Honors real Discord authority first (server owner / ADMINISTRATOR →
    ``admin``, MANAGE_GUILD → ``moderator``), then the server owner's
    configured staff roles (admin role → ``admin``, moderator roles →
    ``moderator``). The Bark instance owner → ``admin`` only when explicitly
    passed. Used by the request middleware so API gating matches the
    per-server "Ready to manage" shown on the server list.
    """
    if is_instance_owner or access.owner:
        return "admin"
    if access.permissions & DISCORD_ADMINISTRATOR:
        return "admin"
    if access.permissions & DISCORD_MANAGE_GUILD:
        return "moderator"
    member_roles = _roles_from_access(access)
    if admin_role_id and admin_role_id in member_roles:
        return "admin"
    if member_roles & moderator_role_ids:
        return "moderator"
    return "viewer"


def can_manage_discord_guild(*, owner: bool, permissions: int) -> bool:
    """Return whether Discord grants server-management access."""
    return owner or bool(permissions & (DISCORD_ADMINISTRATOR | DISCORD_MANAGE_GUILD))


def can_manage_server(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
    admin_role_id: str | None = None,
) -> bool:
    """Whether the user can manage a server in the dashboard.

    Grants come from real Discord authority — being the server owner, holding
    Discord's ADMINISTRATOR or MANAGE_GUILD permission on it, or holding one of
    the server owner's configured staff roles. Running the Bark instance grants
    nothing here: the instance owner is treated like any other member unless
    they hold a real grant in that server.
    """
    if can_manage_discord_guild(owner=access.owner, permissions=access.permissions):
        return True
    member_roles = _roles_from_access(access)
    if admin_role_id and admin_role_id in member_roles:
        return True
    return bool(member_roles & moderator_role_ids)


def manage_reason(
    access: DashboardGuildAccess,
    moderator_role_ids: set[str],
    admin_role_id: str | None = None,
) -> str | None:
    """Human-readable reason a user can manage a server, else ``None``."""
    if access.owner:
        return "You own this server"
    if access.permissions & DISCORD_ADMINISTRATOR:
        return "You have Discord administrator on this server"
    if access.permissions & DISCORD_MANAGE_GUILD:
        return "You manage this server on Discord"
    member_roles = _roles_from_access(access)
    if admin_role_id and admin_role_id in member_roles:
        return "You have this server's Admin role"
    if member_roles & moderator_role_ids:
        return "You have this server's Moderator role"
    return None


def role_from_access(*, owner: bool, permissions: int) -> str:
    """Map Discord guild permissions to the dashboard role tier for that guild.

    Server owners and Discord ADMINISTRATOR holders are admins; MANAGE_GUILD
    holders are moderators. Mirrors ``derive_dashboard_role`` and the per-guild
    ``role_from_access_with_staff_roles``.
    """
    if owner or permissions & DISCORD_ADMINISTRATOR:
        return "admin"
    if permissions & DISCORD_MANAGE_GUILD:
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
    # Discord snowflakes may deserialize as int while owner ids are strings;
    # normalize both sides so a real owner isn't demoted by a type mismatch.
    if str(discord_user_id) in {str(oid) for oid in owner_discord_ids}:
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


async def revoke_user_guild_access(
    session: AsyncSession,
    discord_user_id: str,
    guild_id: int | str,
) -> bool:
    """Revoke a dashboard user's access to a guild (member left / was removed).

    The dashboard's admission + authorization reads the persisted
    ``DashboardGuildAccess`` snapshot written at OAuth login. Without a live
    membership check this snapshot is stale: a user removed from a server (or
    a server removed from the bot) keeps their dashboard access and their
    prior manage tier until they log in again. ``on_member_remove`` /
    ``on_guild_remove`` call this so removal takes effect immediately instead
    of at the next login.

    Returns True when a row was actually deleted (so callers can log a
    meaningful change), False when there was nothing to revoke.
    """
    result = await session.execute(
        delete(DashboardGuildAccess).where(
            DashboardGuildAccess.user_discord_id == discord_user_id,
            DashboardGuildAccess.guild_id == str(guild_id),
        )
    )
    return (getattr(result, "rowcount", 0) or 0) > 0


def build_bot_invite_url(client_id: str, guild_id: str) -> str:
    """Build the server-targeted Discord OAuth install URL for Bark.

    This is the *real* Discord redirect target, used server-side by the
    ``/invite`` route to send humans to Discord. It is deliberately NOT what
    the UI surfaces: the user-facing invite link is always the branded
    ``{public_url}/invite`` (see ``build_guild_catalog`` and
    ``config.dashboard.invite_url``), which resolves here via the /invite page.

    ``guild_id`` is optional: when provided the install targets that server and
    ``disable_guild_select`` is set so Discord doesn't ask which server. When
    empty (the generic /invite link), ``disable_guild_select`` MUST be omitted —
    otherwise Discord gets contradictory params (skip the picker but no guild to
    target) and the install fails.
    """
    if not client_id:
        return ""
    params = {
        "client_id": client_id,
        "scope": "bot applications.commands",
        "permissions": "8",
    }
    if guild_id:
        params["guild_id"] = guild_id
        params["disable_guild_select"] = "true"
    query = urllib.parse.urlencode(params)
    return f"https://discord.com/oauth2/authorize?{query}"


def build_guild_catalog(
    oauth_guilds: Sequence[DashboardGuildAccess],
    bot_guilds: Iterable[Any],
    *,
    client_id: str,
    moderator_roles_by_guild: dict[str, set[str]] | None = None,
    admin_roles_by_guild: dict[str, str | None] | None = None,
    is_instance_owner: bool = False,
    public_url: str = "",
) -> list[dict[str, Any]]:
    """Merge a user's complete Discord server list with live bot state.

    ``moderator_roles_by_guild`` carries each guild's owner-configured
    moderator role IDs and ``admin_roles_by_guild`` the owner-configured
    admin role (see ``get_dashboard_moderator_roles`` /
    ``get_dashboard_admin_role``); they drive the per-server
    ``ready_to_manage`` flag shown as "Ready to manage". ``is_instance_owner``
    marks the person running this Bark instance, who can manage every server
    their bot is in. ``public_url`` is the dashboard base URL; each guild's
    ``invite_url`` is the canonical branded ``{public_url}/invite`` link
    (the /invite route resolves it to the real Discord OAuth URL).
    """
    installed = {str(guild.id): guild for guild in bot_guilds}
    moderator_roles_by_guild = moderator_roles_by_guild or {}
    admin_roles_by_guild = admin_roles_by_guild or {}
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
        guild_moderator_roles = moderator_roles_by_guild.get(access.guild_id, set())
        guild_admin_role = admin_roles_by_guild.get(access.guild_id)
        can_manage = can_manage_server(access, guild_moderator_roles, guild_admin_role)
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
                "ready_to_manage": can_manage,
                "manage_reason": manage_reason(access, guild_moderator_roles, guild_admin_role),
                "access_tier": access_tier,
                "invite_url": f"{public_url.rstrip('/')}/invite" if public_url else "",
            }
        )
    tier_order = {"connected": 0, "manageable": 1, "other": 2}
    return sorted(
        catalog,
        key=lambda item: (tier_order[item["access_tier"]], item["name"].casefold()),
    )
