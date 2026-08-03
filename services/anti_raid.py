"""Anti-raid detection and escalation service for Bark.

Provides:
- RaidDetector — rapid join detection (X users per Y seconds → raid mode)
- AccountAgeGuard — block/kick accounts younger than N days
- WebhookSpamDetector — detect webhook-driven spam
- ContentSpamDetector — detect repeated/similar messages
- EscalationTracker — auto-escalate repeat AutoMod offenders
- MassMentionTracker — track mention rate across messages per user
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger("bark.services.anti_raid")

# Default config (per-guild overrides stored in module config)
DEFAULT_JOIN_THRESHOLD = 5  # joins
DEFAULT_JOIN_WINDOW = 30  # seconds
DEFAULT_ACCOUNT_AGE_DAYS = 3  # min account age
DEFAULT_ESCALATION_STRIKES = 3  # AutoMod violations before escalation
DEFAULT_ESCALATION = {  # strike count → action
    1: "warn",
    3: "timeout",
    5: "kick",
}
DEFAULT_SIMILARITY_RATIO = 0.85  # content similarity threshold
DEFAULT_MENTION_LIMIT = 10  # mentions per 60s


class AntiRaidService:
    """Combined anti-raid, spam, and escalation detection."""

    def __init__(self) -> None:
        # ── Raid detection ──
        self._join_track: dict[int, deque] = defaultdict(lambda: deque(maxlen=200))
        self._raid_mode: dict[int, bool] = {}

        # ── Content spam (repeated messages per user) ──
        self._recent_content: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=20))
        )

        # ── Mass mention tracking per user across messages ──
        self._mention_track: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=60))
        )

        # ── Escalation tracking ──
        self._violation_count: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self._escalation_cooldown: dict[int, dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )

    # ══════════════════════════════════════════════════════
    # RAID DETECTION
    # ══════════════════════════════════════════════════════

    def record_join(
        self,
        guild_id: int,
        threshold: int = DEFAULT_JOIN_THRESHOLD,
        window: int = DEFAULT_JOIN_WINDOW,
    ) -> bool:
        """Record a member join and return True if raid is detected."""
        now = datetime.now(timezone.utc)
        self._join_track[guild_id].append(now)
        return self._check_raid(guild_id, threshold=threshold, window=window)

    def _check_raid(
        self,
        guild_id: int,
        threshold: int = DEFAULT_JOIN_THRESHOLD,
        window: int = DEFAULT_JOIN_WINDOW,
    ) -> bool:
        """Check if join rate exceeds threshold within time window."""
        now = datetime.now(timezone.utc)
        track = self._join_track[guild_id]
        cutoff = now - timedelta(seconds=window)
        # Prune old entries
        while track and track[0] < cutoff:
            track.popleft()
        in_raid = len(track) >= threshold
        self._raid_mode[guild_id] = in_raid
        return in_raid

    # ══════════════════════════════════════════════════════
    # ACCOUNT AGE CHECK
    # ══════════════════════════════════════════════════════

    @staticmethod
    def check_account_age(
        member: discord.Member, min_days: int = DEFAULT_ACCOUNT_AGE_DAYS
    ) -> tuple[bool, str]:
        """Check if member account is old enough. Returns (passed, reason)."""
        if not member.created_at:
            return True, ""
        age = datetime.now(timezone.utc) - member.created_at
        if age.days < min_days:
            return False, f"Account age {age.days}d < {min_days}d minimum"
        return True, ""

    # ══════════════════════════════════════════════════════
    # CONTENT SIMILARITY SPAM
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # WEBHOOK DETECTION
    # ── WEBHOOK DETECTION ──

    # Patterns consolidated from ruleset_engine.py (single source of truth)
    WEBHOOK_PATTERNS = [
        re.compile(r"discord\s+nitro\s+(free|giveaway|generator)", re.IGNORECASE),
        re.compile(r"steamcommunity\.com/gift", re.IGNORECASE),
        re.compile(r"free\s+nitro\s+@everyone", re.IGNORECASE),
        re.compile(r"gift\s*\.?\s*nitro", re.IGNORECASE),
    ]

    SCAM_DOMAINS = [
        "steamcommunit.ru",
        "discord-nitro.xyz",
        "discordgift.com",
        "steam-gift.ru",
        "discord.xyz.gift",
        "free-nitro.pro",
        "steamcommunit.com",
        "nitro-free.xyz",
        "free-discordnitro.com",
        "givvn.com",
        "steamcommunity.vip",
        "steam-list.com",
    ]

    @classmethod
    def check_webhook_scam(cls, message: discord.Message) -> tuple[bool, str]:
        """Check if a message (likely webhook) contains scam/selfbot patterns."""
        content = message.content
        reason_parts = []
        for pat in cls.WEBHOOK_PATTERNS:
            if pat.search(content):
                reason_parts.append("scam pattern")

        for domain in cls.SCAM_DOMAINS:
            if domain in content.lower():
                reason_parts.append(f"scam domain: {domain}")

        suspicious = len(reason_parts) > 0
        return suspicious, "; ".join(reason_parts) if reason_parts else ""

    # ══════════════════════════════════════════════════════
    # MASS MENTION TRACKING
    # ══════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════
    # ESCALATION ENGINE
    # ══════════════════════════════════════════════════════

    async def record_violation(self, guild_id: int, user_id: int) -> tuple[str | None, int]:
        """Record an AutoMod violation. Returns (action_to_take, strike_count) or (None, count)."""
        self._violation_count[guild_id][user_id] += 1
        strikes = self._violation_count[guild_id][user_id]
        now_ts = datetime.now(timezone.utc).timestamp()
        last_esc = self._escalation_cooldown[guild_id][user_id]

        # Only escalate once per 5 minutes to prevent spam
        if now_ts - last_esc < 300:
            return None, strikes

        # Find the highest action for this strike count
        action = None
        for s, a in sorted(DEFAULT_ESCALATION.items()):
            if strikes >= s:
                action = a
        if action:
            self._escalation_cooldown[guild_id][user_id] = now_ts
        return action, strikes

    def reset_violations(self, guild_id: int, user_id: int) -> None:
        self._violation_count[guild_id].pop(user_id, None)
        self._escalation_cooldown[guild_id].pop(user_id, None)
