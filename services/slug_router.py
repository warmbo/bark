"""Slug-based guild routing middleware.

Rewrites ``/g/{slug}[/<page>]`` requests to ``/guild/{guild_id}[/<page>]``
*internally* so every existing guild route (dashboard, members, stats,
settings, modules, moderation) serves under the human-friendly slug path with
NO numeric guild id exposed in the URL and NO redirect.

Resolution is a single DB lookup done by Bark itself, so it works behind ANY
reverse proxy with zero extra configuration — the proxy just passes ``/g/*``
straight through and Bark maps the slug to the guild. The slug lives in the
per-guild ``GuildSetting`` table, so it is part of the backed-up database and
carries from install to install (it is never a Caddy/nginx rewrite rule that
lives in per-host proxy config).

Known-slug paths are rewritten before the router matches, so AuthMiddleware /
SecurityMiddleware (registered inside this one) see the canonical
``/guild/{id}`` path and apply the same gates as a direct id URL.
"""

from __future__ import annotations

import logging
import re

from fastapi import Request

logger = logging.getLogger("bark.slug")

# Matches /g/{slug} or /g/{slug}/<page> but NOT /guild/... (the char after the
# leading "/g" must be a slash, so "guild" never matches).
_SLUG_PATH = re.compile(r"^/g/(?P<slug>[^/]+)(?P<rest>/.*)?$")

# Slug ↔ guild-id mappings change only via PUT /guilds/{id}/slug, so a small
# TTL cache removes a DB query from every /g/* request and every manifest
# fetch without any staleness that matters in practice.
_CACHE_TTL_SECONDS = 60.0
_slug_to_id: dict[str, tuple[float, int]] = {}
_id_to_slug: dict[str, tuple[float, str | None]] = {}


def invalidate_slug_cache(guild_id: int | str | None = None) -> None:
    """Drop cached slug mapping(s). Called after slug writes."""
    if guild_id is None:
        _slug_to_id.clear()
        _id_to_slug.clear()
    else:
        _id_to_slug.pop(str(guild_id), None)
        # A stale forward mapping can only be fixed wholesale — cheap either way.
        _slug_to_id.clear()


async def resolve_slug(slug: str) -> int | None:
    """Return the guild id for a slug (case-insensitive), or None if unknown."""
    import time

    key = slug.lower()
    now = time.monotonic()
    cached = _slug_to_id.get(key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    async with session_scope() as session:
        row = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.key == "slug",
                    GuildSetting.value == key,
                )
            )
        ).scalars().first()
    guild_id = int(row.guild_id) if row is not None else None
    _slug_to_id[key] = (now, guild_id) if guild_id is not None else (now, -1)
    return guild_id


async def get_guild_slug(guild_id: int) -> str | None:
    """Return the slug for a guild id, or None if it has none."""
    import time

    key = str(guild_id)
    now = time.monotonic()
    cached = _id_to_slug.get(key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    async with session_scope() as session:
        row = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.key == "slug",
                    GuildSetting.guild_id == str(guild_id),
                )
            )
        ).scalars().first()
    slug = (row.value or None) if row is not None else None
    _id_to_slug[key] = (now, slug)
    return slug


async def slug_rewrite_middleware(request: Request, call_next):
    """Rewrite ``/g/{slug}[/<page>]`` to ``/guild/{guild_id}[/<page>]``.

    The browser keeps the slug in the address bar (this is an internal
    scope rewrite, not a redirect); only the request path handed to the
    router changes. The original path + slug are stashed on the shared scope
    state so templates can still render slug-based URLs (e.g. og:url).
    """
    path = request.scope.get("path", "")
    match = _SLUG_PATH.match(path)
    if match:
        slug = match.group("slug")
        rest = match.group("rest") or ""
        guild_id = await resolve_slug(slug)
        if guild_id is not None:
            # Share with inner middleware/endpoints via the shared scope state
            # dict (Request.state reads/writes scope["state"]).
            scope_state = request.scope.setdefault("state", {})
            scope_state["guild_slug"] = slug
            scope_state["original_path"] = path

            rewritten = f"/guild/{guild_id}{rest}"
            request.scope["path"] = rewritten
            if "raw_path" in request.scope:
                request.scope["raw_path"] = rewritten.encode("utf-8")
    return await call_next(request)
