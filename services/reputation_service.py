"""Reputation scoring math — levels, decay, caps, and tier resolution.

Pure functions: no DB access, no Discord calls.  All idempotent, all testable.
"""

import math
from datetime import date, timedelta
from typing import Any

# ── Defaults ─────────────────────────────────────────────────────────────

DEFAULT_VOICE_POINTS_PER_MINUTE = 0.5
DEFAULT_MESSAGE_POINTS = 1.0
DEFAULT_REACTION_RECEIVED_POINTS = 2.0
DEFAULT_REACTION_GIVEN_POINTS = 0.5
DEFAULT_EMOJI_IN_MESSAGE_POINTS = 1.0
DEFAULT_THANKS_GIVEN_POINTS = 2.0
DEFAULT_THANKS_RECEIVED_POINTS = 10.0
DEFAULT_LEVEL_CONSTANT = 50.0
DEFAULT_DAILY_CAP = 200.0
DEFAULT_WEEKLY_CAP = 1000.0
DEFAULT_WEEKLY_DECAY_RATE = 0.05  # 5% per week


# ── Level math ───────────────────────────────────────────────────────────


def score_for_level(level: int, level_constant: float = DEFAULT_LEVEL_CONSTANT) -> float:
    """Minimum total score required to reach *level*."""
    return level_constant * (level**2)


def level_from_score(total_score: float, level_constant: float = DEFAULT_LEVEL_CONSTANT) -> int:
    """Current level for a given total score."""
    return int(math.isqrt(int(total_score / level_constant)))


# ── Point math ───────────────────────────────────────────────────────────


def compute_message_points(config: dict[str, Any]) -> float:
    return float(config.get("weights", {}).get("message", DEFAULT_MESSAGE_POINTS))


def compute_reaction_received_points(config: dict[str, Any]) -> float:
    return float(
        config.get("weights", {}).get("reaction_received", DEFAULT_REACTION_RECEIVED_POINTS)
    )


def compute_reaction_given_points(config: dict[str, Any]) -> float:
    """Points the reactor earns for reacting to someone else's message."""
    return float(config.get("weights", {}).get("reaction_given", DEFAULT_REACTION_GIVEN_POINTS))


def compute_emoji_points(config: dict[str, Any]) -> float:
    return float(config.get("weights", {}).get("emoji", DEFAULT_EMOJI_IN_MESSAGE_POINTS))


def compute_thanks_given_points(config: dict[str, Any]) -> float:
    return float(config.get("weights", {}).get("thanks_given", DEFAULT_THANKS_GIVEN_POINTS))


def compute_thanks_received_points(config: dict[str, Any]) -> float:
    return float(config.get("weights", {}).get("thanks_received", DEFAULT_THANKS_RECEIVED_POINTS))


def compute_voice_points(minutes: float, config: dict[str, Any]) -> float:
    weight = float(
        config.get("weights", {}).get("voice_per_minute", DEFAULT_VOICE_POINTS_PER_MINUTE)
    )
    return minutes * weight


# ── Caps ─────────────────────────────────────────────────────────────────


def check_daily_cap(score: float, config: dict[str, Any], earned: float = 0.0) -> float:
    """Cap *score* contributions at the configured daily limit per member."""
    cap = float(config.get("caps", {}).get("daily", DEFAULT_DAILY_CAP))
    return min(score, max(0.0, cap - earned))


def check_weekly_cap(score: float, config: dict[str, Any], earned: float = 0.0) -> float:
    cap = float(config.get("caps", {}).get("weekly", DEFAULT_WEEKLY_CAP))
    return min(score, max(0.0, cap - earned))


# ── Decay ────────────────────────────────────────────────────────────────


def compute_decay(
    total_score: float, days_since_active: int, rate: float = DEFAULT_WEEKLY_DECAY_RATE
) -> float:
    """Apply weekly-decay rate for inactive periods beyond 7 days.

    Returns the *new* total score after decay (never below 0).
    """
    if days_since_active <= 7:
        return total_score
    inactive_weeks = (days_since_active - 7) / 7.0
    decay_factor = (1.0 - rate) ** inactive_weeks
    return max(0.0, total_score * decay_factor)


# ── Tier resolution ──────────────────────────────────────────────────────


def resolve_tier(tiers: list[dict[str, Any]], level: int, total_score: float) -> dict[str, Any]:
    """Given sorted tiers (highest sort_order first), find the highest applicable.

    Each tier: {name, symbol, min_score, min_level, color_hex, ...}
    Returns the matching tier or a default unranked dict.
    """
    for tier in sorted(tiers, key=lambda t: t.get("sort_order", 0), reverse=True):
        if total_score >= tier.get("min_score", 0) and level >= tier.get("min_level", 0):
            return tier
    return {
        "name": "unranked",
        "symbol": "⬜",
        "color_hex": "#99aab5",
        "min_score": 0,
        "min_level": 0,
    }


# ── Progress ─────────────────────────────────────────────────────────────


def next_level_progress(
    total_score: float, level: int, level_constant: float = DEFAULT_LEVEL_CONSTANT
) -> dict[str, float]:
    """Return {current, needed, progress} toward next level."""
    current_for_level = score_for_level(level, level_constant)
    next_level_needed = score_for_level(level + 1, level_constant) - current_for_level
    progress_so_far = total_score - current_for_level
    ratio = min(1.0, progress_so_far / next_level_needed) if next_level_needed > 0 else 1.0
    return {
        "current": total_score,
        "current_level_score": current_for_level,
        "next_level_score": score_for_level(level + 1, level_constant),
        "progress": round(ratio, 4),
        "percent": round(ratio * 100, 1),
    }


# ── Weekly / monthly rollover ────────────────────────────────────────────


def needs_weekly_reset(last_week_start: date, today: date | None = None) -> bool:
    """True if the weekly tracking window should be reset."""
    if today is None:
        today = date.today()
    # Reset every Monday
    return last_week_start < today - timedelta(days=today.weekday())


def needs_monthly_reset(last_month_start: date, today: date | None = None) -> bool:
    if today is None:
        today = date.today()
    return last_month_start.replace(day=1) < today.replace(day=1)
