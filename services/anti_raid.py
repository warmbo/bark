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
import time
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
DEFAULT_ESCALATION = {  # strike count → action
    1: "warn",
    3: "timeout",
    5: "kick",
}


class AntiRaidService:
    """Combined anti-raid, spam, and escalation detection."""

    MAX_TRACKED_USERS_PER_GUILD = 10_000
    VIOLATION_STATE_TTL_SECONDS = 86_400

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
        self._violation_seen: dict[int, dict[int, float]] = defaultdict(dict)

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
        now_ts = datetime.now(timezone.utc).timestamp()
        self._violation_seen[guild_id][user_id] = now_ts
        self._prune_violation_state(guild_id, now_ts)
        self._violation_count[guild_id][user_id] += 1
        strikes = self._violation_count[guild_id][user_id]
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

    def _prune_violation_state(self, guild_id: int, now_ts: float) -> None:
        """Expire inactive users and cap per-guild in-memory escalation state."""
        seen = self._violation_seen[guild_id]
        cutoff = now_ts - self.VIOLATION_STATE_TTL_SECONDS
        stale_users = [user_id for user_id, timestamp in seen.items() if timestamp < cutoff]
        for user_id in stale_users:
            self.reset_violations(guild_id, user_id)

        while len(seen) > self.MAX_TRACKED_USERS_PER_GUILD:
            oldest_user = min(seen, key=seen.__getitem__)
            self.reset_violations(guild_id, oldest_user)

    def reset_violations(self, guild_id: int, user_id: int) -> None:
        self._violation_count[guild_id].pop(user_id, None)
        self._escalation_cooldown[guild_id].pop(user_id, None)
        self._violation_seen[guild_id].pop(user_id, None)

    # ── Content/mention tracker eviction ─────────────────
    # The per-user deques are bounded, but the (guild, user) keys themselves
    # are never evicted — a user who posted once a year ago keeps an entry
    # forever. Called from the moderation module's periodic cleanup loop.

    def prune_trackers(self, guild_id: int, user_id: int) -> None:
        """Drop an idle user's content/mention tracking entries."""
        self._recent_content[guild_id].pop(user_id, None)
        if not self._recent_content[guild_id]:
            self._recent_content.pop(guild_id, None)
        self._mention_track[guild_id].pop(user_id, None)
        if not self._mention_track[guild_id]:
            self._mention_track.pop(guild_id, None)

    def prune_idle_users(self, guild_id: int, idle_seconds: int) -> int:
        """Evict users whose content/mention entries are older than the idle
        window; returns the number of user entries removed."""
        removed = 0
        for tracker in (self._recent_content, self._mention_track):
            by_user = tracker.get(guild_id)
            if not by_user:
                continue
            cutoff = time.time() - idle_seconds
            for user_id, deque_ref in list(by_user.items()):
                # Deques store datetimes (recent_content) or tuples with a
                # datetime first (mention_track). Compare the newest entry;
                # an empty deque is immediately idle.
                newest = None
                for entry in deque_ref:
                    candidate = entry[0] if isinstance(entry, tuple) else entry
                    if newest is None or candidate > newest:
                        newest = candidate
                if newest is None:
                    newest = datetime.now(timezone.utc)  # empty — treat as idle
                if newest.timestamp() < cutoff:
                    by_user.pop(user_id, None)
                    removed += 1
            if not by_user:
                tracker.pop(guild_id, None)
        return removed
