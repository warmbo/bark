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


async def resolve_slug(slug: str) -> int | None:
    """Return the guild id for a slug (case-insensitive), or None if unknown."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    async with session_scope() as session:
        row = (
            await session.execute(
                select(GuildSetting).where(
                    GuildSetting.key == "slug",
                    GuildSetting.value == slug.lower(),
                )
            )
        ).scalars().first()
    return int(row.guild_id) if row is not None else None


async def get_guild_slug(guild_id: int) -> str | None:
    """Return the slug for a guild id, or None if it has none."""
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
    return (row.value or None) if row is not None else None


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
