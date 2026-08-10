"""Render cache — content-hash keying, TTL, LRU disk guard.

Key = sha256(kind|guild|user|theme|art_mode|payload_hash). Payloads are
JSON-stable so identical requests hit the cache; TTL makes freshness a
plugin decision (passed per request).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .config import get_config


def cache_key(kind: str, guild_id, user_id, theme: str, art_mode: str,
              payload: dict | None) -> str:
    h = hashlib.sha256()
    parts = [
        kind,
        str(guild_id or ""),
        str(user_id or ""),
        theme,
        art_mode,
        json.dumps(payload or {}, sort_keys=True, default=str),
    ]
    h.update("|".join(parts).encode("utf-8"))
    return h.hexdigest()[:24]


def cache_dir(kind: str) -> Path:
    d = Path(get_config().data_dir) / "media-cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def put(kind: str, key: str, ext: str, data: bytes) -> Path:
    path = cache_dir(kind) / f"{key}.{ext}"
    tmp = path.with_suffix(f".{ext}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def get(kind: str, key: str, ext: str, ttl_s: int) -> Path | None:
    path = cache_dir(kind) / f"{key}.{ext}"
    if not path.is_file():
        return None
    if ttl_s and time.time() - path.stat().st_mtime > ttl_s:
        return None
    return path


def cleanup(max_bytes: int | None = None) -> int:
    """LRU-evict expired/oversize entries; returns bytes freed."""
    max_bytes = max_bytes if max_bytes is not None else get_config().cache_max_bytes
    root = Path(get_config().data_dir) / "media-cache"
    if not root.is_dir():
        return 0
    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if total <= max_bytes:
        return 0
    freed = 0
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        freed += p.stat().st_size
        p.unlink(missing_ok=True)
        if total - freed <= max_bytes:
            break
    return freed
