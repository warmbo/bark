"""Build render payloads from bark's SQLite data (read-only).

The renderers consume a JSON-safe payload (see the plan's payload schema).
The plugin sends a payload-first; the engine can also collect it from its
configured ``BARK_MEDIA_DB_PATH`` for aggregates (leaderboards) or when the
plugin omits data. Every collector degrades gracefully: a missing DB, missing
table, or missing row yields sensible defaults, never an exception.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import sqlalchemy as sa

from .db import fetch_all, fetch_one

logger = logging.getLogger("bark.media.collect")

_Rep = dict[str, Any]

_SCHEMA_KEYS = {
    "reputation_profiles": [
        "total_score", "level", "current_tier", "weekly_score", "monthly_score",
        "thanks_received", "messages_count", "reactions_received", "voice_minutes",
        "last_activity",
    ],
}


def _safe(default: Any) -> Callable:
    """Decorator: any failure in the wrapped collector returns ``default``."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # missing DB/table/column, bad types...
                logger.warning("collect.%s failed (%s) — using default", fn.__name__, exc)
                return default
        return wrapper

    return deco


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


# ── Queries ──────────────────────────────────────────────────────────────

def get_reputation(engine: sa.Engine, guild_id: str, user_id: str) -> dict | None:
    return fetch_one(
        engine,
        """
        SELECT total_score, level, current_tier, weekly_score, monthly_score,
               thanks_received, messages_count, reactions_received, voice_minutes,
               last_activity
        FROM reputation_profiles
        WHERE guild_id = :guild_id AND user_id = :user_id
        """,
        guild_id=str(guild_id), user_id=str(user_id),
    )


def get_tier(engine: sa.Engine, guild_id: str, tier_name: str | None) -> dict | None:
    row = fetch_one(
        engine,
        """
        SELECT name, symbol, min_score, color_hex
        FROM reputation_tiers
        WHERE guild_id = :guild_id AND name = :name
        """,
        guild_id=str(guild_id), name=tier_name or "",
    )
    if row:
        return row
    return fetch_one(
        engine,
        """
        SELECT name, symbol, min_score, color_hex
        FROM reputation_tiers
        WHERE guild_id = :guild_id AND is_default = 1
        LIMIT 1
        """,
        guild_id=str(guild_id),
    )


def get_badges(engine: sa.Engine, guild_id: str, user_id: str, limit: int = 12) -> list[dict]:
    rows = fetch_all(
        engine,
        """
        SELECT r.name, r.description, a.tier_name, a.created_at
        FROM reputation_awards a
        JOIN reputation_rewards r ON r.id = a.reward_id
        WHERE a.guild_id = :guild_id AND a.user_id = :user_id
        ORDER BY a.created_at DESC
        LIMIT :limit
        """,
        guild_id=str(guild_id), user_id=str(user_id), limit=limit,
    )
    return [{"name": r["name"], "description": r["description"] or "", "icon": ""} for r in rows]


def get_favorite_channels(engine: sa.Engine, guild_id: str, user_id: str, limit: int = 3) -> list[dict]:
    rows = fetch_all(
        engine,
        """
        SELECT channel_id, COUNT(*) AS count
        FROM reputation_events
        WHERE guild_id = :guild_id AND actor_id = :user_id AND channel_id IS NOT NULL
        GROUP BY channel_id
        ORDER BY count DESC, channel_id ASC
        LIMIT :limit
        """,
        guild_id=str(guild_id), user_id=str(user_id), limit=limit,
    )
    return [{"channel_id": str(r["channel_id"]), "name": None, "count": int(r["count"])} for r in rows]


def get_activity_bars(
    engine: sa.Engine, guild_id: str, user_id: str, *, today: date | None = None,
    weekly_days: int = 7, monthly_buckets: int = 4,
) -> dict:
    today = today or _today_utc()
    # Fetch enough history for the largest window (weekly bars need 7 days,
    # monthly buckets need monthly_buckets*7).
    window_days = max(weekly_days, monthly_buckets * 7)
    since = (today - timedelta(days=window_days - 1)).isoformat()

    rows = fetch_all(
        engine,
        """
        SELECT DATE(created_at) AS day, COUNT(*) AS count
        FROM reputation_events
        WHERE guild_id = :guild_id AND actor_id = :user_id
          AND created_at >= :since
        GROUP BY day
        """,
        guild_id=str(guild_id), user_id=str(user_id), since=since,
    )
    by_day = {r["day"]: int(r["count"]) for r in rows}

    # Weekly: one bar per day, oldest → newest.
    bars_weekly = [
        by_day.get((today - timedelta(days=i)).isoformat(), 0)
        for i in range(weekly_days - 1, -1, -1)
    ]

    # Monthly: last 28 days bucketed into `monthly_buckets` weekly sums,
    # newest bucket ends today (so the most recent week is included).
    bars_monthly: list[int] = []
    for b in range(monthly_buckets):
        offset = monthly_buckets - 1 - b  # 0 = newest week
        end = today - timedelta(days=offset * 7)
        total = 0
        for d in range(7):
            total += by_day.get((end - timedelta(days=d)).isoformat(), 0)
        bars_monthly.append(total)

    return {"bars_weekly": bars_weekly, "bars_monthly": bars_monthly}


def get_leaderboard(engine: sa.Engine, guild_id: str, limit: int = 10) -> list[dict]:
    rows = fetch_all(
        engine,
        """
        SELECT user_id, total_score, level, current_tier, messages_count
        FROM reputation_profiles
        WHERE guild_id = :guild_id
        ORDER BY total_score DESC
        LIMIT :limit
        """,
        guild_id=str(guild_id), limit=limit,
    )
    out = []
    for idx, r in enumerate(rows, start=1):
        out.append({
            "rank": idx,
            "user_id": str(r["user_id"]),
            "score": float(r["total_score"]),
            "level": int(r["level"]),
            "tier": r["current_tier"] or "unranked",
        })
    return out


# ── Payload builders ─────────────────────────────────────────────────────

@_safe({})
def collect_reputation_block(engine: sa.Engine, guild_id: str, user_id: str) -> dict:
    rep = get_reputation(engine, guild_id, user_id)
    if not rep:
        return {}
    tier = get_tier(engine, guild_id, rep.get("current_tier"))
    score = float(rep.get("total_score") or 0.0)

    # Tier curve → progress toward the NEXT tier (score between min scores).
    tiers = fetch_all(
        engine,
        """
        SELECT name, min_score FROM reputation_tiers
        WHERE guild_id = :guild_id ORDER BY min_score ASC
        """,
        guild_id=str(guild_id),
    )
    tier_progress = 0.0
    next_tier = None
    next_tier_min_score = None
    tier_min_score = 0.0
    if tiers:
        current = (tier or {}).get("name") or rep.get("current_tier")
        names = [t["name"] for t in tiers]
        idx = names.index(current) if current in names else -1
        if idx >= 0:
            tier_min_score = float(tiers[idx]["min_score"] or 0.0)
            if idx + 1 < len(tiers):
                nxt_name = tiers[idx + 1]["name"]
                nxt_min = float(tiers[idx + 1]["min_score"] or 0.0)
                span = nxt_min - tier_min_score
                if span > 0:
                    # meaningful target: expose progress + label
                    next_tier = nxt_name
                    next_tier_min_score = nxt_min
                    tier_progress = min(max((score - tier_min_score) / span, 0.0), 1.0)
                # degenerate (equal thresholds) → no next-tier label/progress
            else:
                tier_progress = 1.0  # top tier — full bar

    return {
        "score": score,
        "level": int(rep.get("level") or 0),
        "tier": (tier or {}).get("name") or rep.get("current_tier") or "unranked",
        "tier_symbol": (tier or {}).get("symbol") or "",
        "tier_color": (tier or {}).get("color_hex") or "#99aab5",
        "tier_min_score": tier_min_score,
        "next_tier": next_tier,
        "next_tier_min_score": next_tier_min_score,
        "tier_progress": tier_progress,
        "weekly": float(rep.get("weekly_score") or 0.0),
        "monthly": float(rep.get("monthly_score") or 0.0),
        "thanks": int(rep.get("thanks_received") or 0),
        "messages": int(rep.get("messages_count") or 0),
        "reactions": int(rep.get("reactions_received") or 0),
        "voice_minutes": int(rep.get("voice_minutes") or 0),
        "last_activity": rep.get("last_activity"),
    }


@_safe({})
def collect_activity_block(engine: sa.Engine, guild_id: str, user_id: str, *, today: date | None = None) -> dict:
    return get_activity_bars(engine, guild_id, user_id, today=today)


@_safe([])
def collect_badges_block(engine: sa.Engine, guild_id: str, user_id: str) -> list[dict]:
    return get_badges(engine, guild_id, user_id)


@_safe([])
def collect_favorites_block(engine: sa.Engine, guild_id: str, user_id: str) -> list[dict]:
    return get_favorite_channels(engine, guild_id, user_id)


def build_profile_payload(
    engine: sa.Engine,
    guild_id: str | int,
    user_id: str | int,
    *,
    user: dict | None = None,
    roles: list[dict] | None = None,
    today: date | None = None,
) -> dict:
    """Assemble the full profile payload the renderer consumes.

    ``user``/``roles`` come from the plugin (live Discord data). Everything
    else is collected from the DB; missing data yields empty/default blocks.
    """
    guild_id = str(guild_id)
    user_id = str(user_id)
    user = user or {}
    return {
        "user": {
            "id": user_id,
            "display_name": user.get("display_name") or user.get("username") or user_id,
            "username": user.get("username") or user_id,
            "avatar_url": user.get("avatar_url"),
            "banner_url": user.get("banner_url"),
            "accent_color": user.get("accent_color"),
            "is_bot": bool(user.get("is_bot", False)),
            "joined_at": user.get("joined_at"),
            "presence": user.get("presence", "offline"),
        },
        "roles": roles or [],
        "reputation": collect_reputation_block(engine, guild_id, user_id),
        "activity": collect_activity_block(engine, guild_id, user_id, today=today),
        "badges": collect_badges_block(engine, guild_id, user_id),
        "favorites": collect_favorites_block(engine, guild_id, user_id),
    }


@_safe([])
def build_leaderboard_payload(engine: sa.Engine, guild_id: str | int, limit: int = 10) -> list[dict]:
    return get_leaderboard(engine, str(guild_id), limit)
