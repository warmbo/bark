"""Render orchestration: cache-first profile rendering + CDN avatar fetch.

The plugin can send a full payload (it has live Discord data) or let the
engine collect from its configured ``BARK_MEDIA_DB_PATH``. Outputs land in
the media cache; the plugin reads the file path directly (same host).
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from . import collect
from .cache import cache_dir, cache_key, get as cache_get, put as cache_put
from .config import get_config
from .db import connect_readonly
from .renderers import render
from .themes import resolve_theme

logger = logging.getLogger("bark.media.service")

_OUTPUT_EXT = {"png": "png", "gif": "gif"}


async def fetch_avatar(avatar_url: str | None) -> Image.Image | None:
    """Download (with CDN cache) and open an avatar image; None on any failure.

    Animated avatars: the first frame is used (Pillow opens GIFs as frame 0).
    """
    if not avatar_url:
        return None
    digest = hashlib.sha256(avatar_url.encode("utf-8")).hexdigest()[:20]
    cdn_dir = Path(get_config().data_dir) / "cdn-cache"
    cdn_dir.mkdir(parents=True, exist_ok=True)
    cached = cdn_dir / f"{digest}.img"
    try:
        if cached.is_file():
            data = cached.read_bytes()
        else:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(avatar_url)
                resp.raise_for_status()
                data = resp.content
            cached.write_bytes(data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except (httpx.HTTPError, OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning("avatar fetch failed for %s: %s", avatar_url, exc)
        return None


async def collect_payload(kind: str, guild_id: str, user_id: str) -> dict:
    """Engine-side data blocks (reputation/activity/badges/favorites).

    The plugin merges these with LIVE Discord facts (user/roles/channel
    names) it supplies itself — the engine never touches Discord.
    """
    empty = {"reputation": {}, "activity": {}, "badges": [], "favorites": []}
    if not get_config().media_db_path:
        return empty
    engine = connect_readonly(get_config().media_db_path)
    if kind != "profile":
        return empty
    return {
        "reputation": collect.collect_reputation_block(engine, guild_id, user_id),
        "activity": collect.collect_activity_block(engine, guild_id, user_id),
        "badges": collect.collect_badges_block(engine, guild_id, user_id),
        "favorites": collect.collect_favorites_block(engine, guild_id, user_id),
    }


async def render_job(kind: str, guild_id: str, user_id: str, theme_name: str | None,
                     art_mode: str, payload: dict | None, output: str,
                     cache_ttl_s: int) -> tuple[str, int]:
    """Run one render job: cache-first, collect-if-needed, render, persist.

    Returns (absolute file path, size in bytes).
    """
    ext = _OUTPUT_EXT.get(output or "png", "png")
    payload = dict(payload or {})

    # Enrich missing data blocks from the engine's DB (plugin sends live
    # Discord facts; the DB supplies reputation/activity/badges/favorites).
    if get_config().media_db_path and kind == "profile":
        engine = connect_readonly(get_config().media_db_path)
        if not payload:
            payload = collect.build_profile_payload(engine, guild_id, user_id)
        else:
            for key, fn in (
                ("reputation", collect.collect_reputation_block),
                ("activity", collect.collect_activity_block),
                ("badges", collect.collect_badges_block),
                ("favorites", collect.collect_favorites_block),
            ):
                if not payload.get(key):
                    payload[key] = fn(engine, guild_id, user_id)

    theme = resolve_theme(theme_name)
    key = cache_key(kind, guild_id, user_id, theme.name, art_mode, payload)
    hit = cache_get(kind, key, ext, cache_ttl_s)
    if hit is not None:
        return str(hit), hit.stat().st_size

    avatar = await fetch_avatar((payload.get("user") or {}).get("avatar_url"))
    img = render(kind, payload, theme, avatar=avatar)
    buf = io.BytesIO()
    img.save(buf, format="PNG" if ext == "png" else "GIF")
    path = cache_put(kind, key, ext, buf.getvalue())
    return str(path), path.stat().st_size
