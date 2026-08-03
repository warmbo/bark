"""Reputation module v1.0.0 — levels, thanks, reactions, voice, messages, tiers, rewards.

Tracks member activity across multiple sources and awards reputation points,
levels, tiers, and configurable rewards.  Features:
- Message, reaction, emoji, thanks, and voice minute scoring
- Level progression with configurable curve
- Named tiers with Unicode symbols and optional role assignment
- Configurable rewards auto-awarded on tier/level milestones
- /thanks command with cooldown
- /reputation leaderboard and rank commands
- Dashboard leaderboard + thanks log + configure tabs
- Optional showoff channel for level-up and reward announcements
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import discord
from fastapi import Query, Request

if TYPE_CHECKING:
    from bot.client import BarkBot

from database.engine import session_scope
from database.models.reputation import (
    ReputationAward,
    ReputationEvent,
    ReputationProfile,
    ReputationReward,
    ReputationTier,
)
from modules.base import (
    BarkModule,
    CommandRegistration,
    EventRegistration,
    PageRegistration,
    PermissionDefinition,
)
from services.reputation_service import (
    check_daily_cap,
    check_weekly_cap,
    compute_decay,
    compute_emoji_points,
    compute_message_points,
    compute_reaction_given_points,
    compute_reaction_received_points,
    compute_thanks_given_points,
    compute_thanks_received_points,
    compute_voice_points,
    level_from_score,
    needs_monthly_reset,
    needs_weekly_reset,
    next_level_progress,
    resolve_tier,
)

logger = logging.getLogger("bark.modules.reputation")

# ── Constants ────────────────────────────────────────────────────────────

EMOJI_RE = re.compile(r"[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]")
THANKS_COOLDOWN_SECONDS = 300  # 5 minutes between thanks to the same user
THANKS_SELF_COOLDOWN_SECONDS = 60  # 1 minute between any thanks by same actor
VOICE_TICK_SECONDS = 60  # Check voice duration every 60s
VOICE_IDLE_TIMEOUT = 120  # Mark member as idle after 2min in same channel
MAX_SHOWOFF_PER_HOUR = 6  # Max showoff announcements per hour per guild


class ReputationModule(BarkModule):
    """Level, thanks, and rewards system for the ZENHAWX community."""

    name = "reputation"
    version = "1.0.0"
    description = "Level system, thanks, reactions, voice rewards, tiers, and showoff channel"
    author = "ZENHAWX"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        # Runtime tracking sets
        self._thanks_cooldowns: dict[tuple[int, int], float] = {}  # (actor, target) -> timestamp
        self._thanks_self_cooldowns: dict[int, float] = {}  # actor_id -> timestamp
        self._showoff_rate_limits: dict[int, list[float]] = defaultdict(
            list
        )  # guild_id -> [timestamps]
        self._voice_activity: dict[int, dict[int, float]] = defaultdict(
            dict
        )  # guild_id -> {user_id -> join_ts}
        self._voice_task: asyncio.Task | None = None
        # Message dedup: guild -> set of recent message_ids (prevents double-counting)
        self._recent_messages: dict[int, set[int]] = defaultdict(set)
        self._message_dedup_minutes = 2

    # ── Registration ─────────────────────────────────────

    def get_events(self) -> list[EventRegistration]:
        return [
            EventRegistration("discord_message", handler="_on_message"),
            EventRegistration("raw_reaction_add", handler="_on_reaction_add"),
            EventRegistration("discord_voice_state", handler="_on_voice_state"),
        ]

    def get_commands(self) -> list[CommandRegistration]:
        return [
            CommandRegistration("reputation", "View your rank or someone else's"),
            CommandRegistration("leaderboard", "Show the top ranked members"),
            CommandRegistration("thanks", "Thank another member for something"),
        ]

    def get_dashboard_pages(self) -> list[PageRegistration]:
        return [
            PageRegistration(
                route="/guild/{guild_id}/modules/reputation",
                label="Reputation",
                icon="trophy",
                category="community",
            )
        ]

    def get_permissions(self) -> list[PermissionDefinition]:
        return [
            PermissionDefinition(name="reputation.manage", label="Manage Reputation Settings"),
            PermissionDefinition(name="reputation.view", label="View Reputation Data"),
        ]

    def get_about(self) -> list[dict]:
        return [
            {
                "title": "What It Does",
                "description": (
                    "Tracks member activity and awards reputation points. "
                    "Members earn points for sending messages, receiving reactions, "
                    "using emoji, spending time in voice channels, and receiving thanks. "
                    "Points unlock levels, tiers with symbols, and configurable rewards."
                ),
            },
            {
                "title": "Sources",
                "description": (
                    "• Messages: 1 point per message\n"
                    "• Reactions received: 2 points each\n"
                    "• Emoji in messages: 1 point per unique emoji\n"
                    "• Voice time: 0.5 points per minute\n"
                    "• Thanks given: 2 points\n"
                    "• Thanks received: 10 points\n\n"
                    "All weights are configurable per guild."
                ),
            },
            {
                "title": "Levels & Tiers",
                "description": (
                    "Level = √(total_score / level_constant). "
                    "Tiers are named rank thresholds with customizable Unicode symbols, "
                    "colors, and optional automatic Discord role assignment."
                ),
            },
            {
                "title": "Showoff Channel",
                "description": (
                    "Configure a Discord channel for level-up, tier-up, and reward "
                    "announcements. Rate-limited to prevent spam."
                ),
            },
        ]

    def get_extra_tabs(self) -> list[dict]:
        return [
            {
                "id": "leaderboard",
                "label": "Leaderboard",
                "template": "module_tabs/reputation_leaderboard.html",
            },
            {
                "id": "thanks",
                "label": "Thanks Log",
                "template": "module_tabs/reputation_thanks.html",
            },
        ]

    def get_api_routes(self):
        """API endpoints for reputation dashboard data."""
        from fastapi import APIRouter

        from services.response import (
            api_error,
            api_not_found,
            api_success,
            check_api_permission,
            get_module_min_role,
        )

        router = APIRouter(tags=["module-reputation"])

        @router.get("/guilds/{guild_id}/modules/reputation/leaderboard")
        async def reputation_leaderboard(
            request: Request,
            guild_id: str,
            limit: int = Query(25, ge=1, le=100),
        ):
            """Return the leaderboard for guild_id."""
            await get_module_min_role("reputation", guild_id)
            if not check_api_permission(request, "reputation.view", guild_id):
                return api_error("Insufficient permissions", status_code=403)
            gid = int(guild_id)
            bot: "BarkBot" = request.state.bot
            guild = bot.get_guild(gid)
            if guild is None:
                return api_not_found("Guild")

            async with session_scope() as session:
                from sqlalchemy import desc, select

                profiles_result = await session.execute(
                    select(ReputationProfile)
                    .where(ReputationProfile.guild_id == str(gid))
                    .order_by(desc(ReputationProfile.total_score))
                    .limit(min(limit, 100))
                )
                profiles = list(profiles_result.scalars().all())

            # Load tiers
            async with session_scope() as session:
                tiers_result = await session.execute(
                    select(ReputationTier).where(ReputationTier.guild_id == str(gid))
                )
                tier_rows = list(tiers_result.scalars().all())
            tier_map = {
                t.name: {"name": t.name, "symbol": t.symbol, "color_hex": t.color_hex}
                for t in tier_rows
                if t.name is not None
            }

            leaderboard = []
            rank = 1
            for p in profiles:
                member = guild.get_member(int(p.user_id))
                if not member:
                    continue
                tier_info = tier_map.get(
                    p.current_tier, {"name": "Unranked", "symbol": "⬜", "color_hex": "#99aab5"}
                )
                leaderboard.append(
                    {
                        "rank": rank,
                        "user_id": p.user_id,
                        "tag": member.display_name,
                        "avatar": member.display_avatar.url if member.display_avatar else None,
                        "level": p.level,
                        "tier": p.current_tier,
                        "symbol": tier_info["symbol"],
                        "color_hex": tier_info["color_hex"],
                        "total_score": round(p.total_score, 1),
                        "messages_count": p.messages_count,
                        "reactions_received": p.reactions_received,
                        "thanks_received": p.thanks_received,
                        "voice_minutes": p.voice_minutes,
                    }
                )
                rank += 1

            return api_success({"leaderboard": leaderboard, "total": len(leaderboard)})

        @router.get("/guilds/{guild_id}/modules/reputation/thanks")
        async def reputation_thanks(
            request: Request,
            guild_id: str,
            limit: int = Query(50, ge=1, le=100),
        ):
            """Return recent thanks."""
            await get_module_min_role("reputation", guild_id)
            if not check_api_permission(request, "reputation.view", guild_id):
                return api_error("Insufficient permissions", status_code=403)
            gid = int(guild_id)

            async with session_scope() as session:
                from sqlalchemy import desc, select

                result = await session.execute(
                    select(ReputationEvent)
                    .where(
                        ReputationEvent.guild_id == str(gid),
                        ReputationEvent.event_type.in_(["thanks", "thanks_given"]),
                    )
                    .order_by(desc(ReputationEvent.created_at))
                    .limit(min(limit, 200))
                )
                events = list(result.scalars().all())

            thanks_list = []
            for ev in events:
                meta = {}
                if ev.metadata_json:
                    try:
                        meta = json.loads(ev.metadata_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                thanks_list.append(
                    {
                        "id": ev.id,
                        "event_type": ev.event_type,
                        "actor_id": ev.actor_id,
                        "target_id": ev.target_id,
                        "points": ev.points,
                        "reason": meta.get("reason", ""),
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                    }
                )

            return api_success({"thanks": thanks_list})

        @router.post("/guilds/{guild_id}/modules/reputation/reset")
        async def reputation_reset(request: Request, guild_id: str, user_id: str):
            """Reset a member's reputation profile (admin action)."""
            await get_module_min_role("reputation", guild_id)
            if not check_api_permission(request, "reputation.manage", guild_id):
                return api_error("Insufficient permissions")
            gid = int(guild_id)

            async with session_scope() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(ReputationProfile).where(
                        ReputationProfile.guild_id == str(gid),
                        ReputationProfile.user_id == str(user_id),
                    )
                )
                profile = result.scalar_one_or_none()
                if profile is None:
                    return api_not_found("ReputationProfile")
                await session.delete(profile)
                await session.commit()

                # Also delete events
                from sqlalchemy import delete

                await session.execute(
                    delete(ReputationEvent).where(
                        ReputationEvent.guild_id == str(gid),
                        ReputationEvent.target_id == str(user_id),
                    )
                )
                await session.commit()

            return api_success({"message": "Reputation reset"})

        return router

    def get_settings_schema(self) -> dict:
        return {
            "type": "object",
            "description": "Configure how reputation is earned, capped, displayed, and rewarded.",
            "properties": {
                "enabled_sources": {
                    "type": "object",
                    "title": "Enabled Sources",
                    "description": "Toggle which activities award reputation points.",
                    "properties": {
                        "messages": {"type": "boolean", "title": "Messages", "default": True},
                        "reactions": {"type": "boolean", "title": "Reactions", "default": True},
                        "emoji": {"type": "boolean", "title": "Emoji Usage", "default": True},
                        "voice": {"type": "boolean", "title": "Voice Time", "default": True},
                        "thanks": {"type": "boolean", "title": "Thanks", "default": True},
                    },
                    "default": {
                        "messages": True,
                        "reactions": True,
                        "emoji": True,
                        "voice": True,
                        "thanks": True,
                    },
                },
                "weights": {
                    "type": "object",
                    "title": "Point Weights",
                    "description": "Points awarded per activity unit.",
                    "properties": {
                        "message": {
                            "type": "number",
                            "title": "Per Message",
                            "default": 1.0,
                            "minimum": 0,
                        },
                        "reaction_received": {
                            "type": "number",
                            "title": "Per Reaction Received",
                            "default": 2.0,
                            "minimum": 0,
                        },
                        "reaction_given": {
                            "type": "number",
                            "title": "Per Reaction Given",
                            "default": 0.5,
                            "minimum": 0,
                        },
                        "emoji": {
                            "type": "number",
                            "title": "Per Unique Emoji",
                            "default": 1.0,
                            "minimum": 0,
                        },
                        "thanks_given": {
                            "type": "number",
                            "title": "Per Thanks Given",
                            "default": 2.0,
                            "minimum": 0,
                        },
                        "thanks_received": {
                            "type": "number",
                            "title": "Per Thanks Received",
                            "default": 10.0,
                            "minimum": 0,
                        },
                        "voice_per_minute": {
                            "type": "number",
                            "title": "Per Voice Minute",
                            "default": 0.5,
                            "minimum": 0,
                        },
                    },
                    "default": {
                        "message": 1.0,
                        "reaction_received": 2.0,
                        "reaction_given": 0.5,
                        "emoji": 1.0,
                        "thanks_given": 2.0,
                        "thanks_received": 10.0,
                        "voice_per_minute": 0.5,
                    },
                },
                "caps": {
                    "type": "object",
                    "title": "Daily / Weekly Caps",
                    "description": "Maximum points a member can earn per period.",
                    "properties": {
                        "daily": {
                            "type": "number",
                            "title": "Daily Cap",
                            "default": 200.0,
                            "minimum": 0,
                        },
                        "weekly": {
                            "type": "number",
                            "title": "Weekly Cap",
                            "default": 1000.0,
                            "minimum": 0,
                        },
                    },
                    "default": {"daily": 200.0, "weekly": 1000.0},
                },
                "level_constant": {
                    "type": "number",
                    "title": "Level Curve Constant",
                    "description": "Higher = slower leveling. level = √(score / constant).",
                    "default": 50.0,
                    "minimum": 1.0,
                },
                "showoff_channel_id": {
                    "type": "string",
                    "format": "channel_select",
                    "title": "Showoff Channel",
                    "description": "Channel for level-up, tier-up, and reward announcements. Leave empty to disable.",
                    "placeholder": "Select a channel...",
                },
                "showoff_level_up": {
                    "type": "boolean",
                    "title": "Announce Level Ups",
                    "description": "Post a message to the showoff channel when someone levels up.",
                    "default": True,
                },
                "showoff_rewards": {
                    "type": "boolean",
                    "title": "Announce Rewards",
                    "description": "Post a message to the showoff channel when someone earns a reward.",
                    "default": True,
                },
                "ignored_channels": {
                    "type": "string",
                    "title": "Ignored Channels",
                    "description": "Comma-separated channel IDs where no reputation is earned.",
                    "placeholder": "123456, 789012",
                    "default": "",
                },
                "ignored_roles": {
                    "type": "string",
                    "format": "role_select",
                    "title": "Ignored Role",
                    "description": "Members with this role earn no reputation.",
                    "placeholder": "No role selected",
                },
            },
        }

    # ── Default tiers ────────────────────────────────────

    async def _ensure_default_tiers(self, guild_id: int) -> None:
        """Create default tier records if none exist for this guild.

        Every 10 levels = one tier advancement.
        """
        async with session_scope() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(ReputationTier).where(ReputationTier.guild_id == str(guild_id))
            )
            existing = result.scalars().first()
            if existing is not None:
                return

            default_tiers = [
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Recruit",
                    symbol="⬜",
                    min_level=0,
                    min_score=0,
                    color_hex="#99aab5",
                    is_default=True,
                    sort_order=0,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Scout",
                    symbol="🥉",
                    min_level=10,
                    min_score=0,
                    color_hex="#cd7f32",
                    sort_order=1,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Warrior",
                    symbol="🥈",
                    min_level=20,
                    min_score=0,
                    color_hex="#c0c0c0",
                    sort_order=2,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Elite",
                    symbol="🥇",
                    min_level=30,
                    min_score=0,
                    color_hex="#ffd700",
                    sort_order=3,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Champion",
                    symbol="💎",
                    min_level=40,
                    min_score=0,
                    color_hex="#e5e4e2",
                    sort_order=4,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Guardian",
                    symbol="🌟",
                    min_level=50,
                    min_score=0,
                    color_hex="#b9f2ff",
                    sort_order=5,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Legend",
                    symbol="👑",
                    min_level=60,
                    min_score=0,
                    color_hex="#ff6b6b",
                    sort_order=6,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Mythic",
                    symbol="🌀",
                    min_level=70,
                    min_score=0,
                    color_hex="#ca9ee6",
                    sort_order=7,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Titan",
                    symbol="⚡",
                    min_level=80,
                    min_score=0,
                    color_hex="#a78bfa",
                    sort_order=8,
                ),
                ReputationTier(
                    guild_id=str(guild_id),
                    name="Immortal",
                    symbol="🔥",
                    min_level=90,
                    min_score=0,
                    color_hex="#ef4444",
                    sort_order=9,
                ),
            ]
            for tier in default_tiers:
                session.add(tier)
            await session.commit()
        self._logger.info("Created default reputation tiers for guild %s", guild_id)

    # ── Lifecycle ───────────────────────────────────────

    async def enable(self) -> None:
        self._logger.info("Enabling reputation module v%s", self.version)
        for guild in self.ctx.guilds:
            guild_id = int(guild.id)
            await self._ensure_default_tiers(guild_id)
        self._voice_task = asyncio.create_task(self._voice_tick_loop())

    async def disable(self) -> None:
        self._logger.info("Disabling reputation module")
        task = self._voice_task
        self._voice_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._voice_activity.clear()
        self._thanks_cooldowns.clear()
        self._thanks_self_cooldowns.clear()
        self._showoff_rate_limits.clear()
        self._recent_messages.clear()

    # ── Scoring helpers ──────────────────────────────────

    async def _add_points(
        self,
        guild_id: int,
        user_id: int,
        points: float,
        event_type: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        message_id: int | None = None,
        channel_id: int | None = None,
        metadata: dict | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Add points to a member's profile and record the event.

        All DB work happens in one session_scope to keep the profile object
        attached.  Returns {profile, leveled_up, new_tier, new_rewards} or None
        if capped/ignored.
        """
        if config is None:
            config = await self.load_dashboard_config(guild_id)

        async with session_scope() as session:
            from sqlalchemy import func, select

            # Get or create profile
            result = await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == str(guild_id),
                    ReputationProfile.user_id == str(user_id),
                )
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                today = date.today()
                profile = ReputationProfile(
                    guild_id=str(guild_id),
                    user_id=str(user_id),
                    week_start=today - timedelta(days=today.weekday()),
                    month_start=today.replace(day=1),
                )
                session.add(profile)
                await session.flush()

            # Weekly/monthly reset
            today = date.today()
            if needs_weekly_reset(profile.week_start, today):
                profile.weekly_score = 0.0
                profile.week_start = today - timedelta(days=today.weekday())
            if needs_monthly_reset(profile.month_start, today):
                profile.monthly_score = 0.0
                profile.month_start = today.replace(day=1)

            # Apply caps to accumulated awards, not to each event in isolation.
            day_start = datetime.combine(today, datetime.min.time())
            daily_earned = (
                await session.execute(
                    select(func.coalesce(func.sum(ReputationEvent.points), 0.0)).where(
                        ReputationEvent.guild_id == str(guild_id),
                        ReputationEvent.target_id == str(user_id),
                        ReputationEvent.created_at >= day_start,
                    )
                )
            ).scalar_one()
            points = check_daily_cap(points, config, float(daily_earned))
            points = check_weekly_cap(points, config, profile.weekly_score)
            if points <= 0:
                return None

            # Decay — handle timezone-naive last_activity from SQLite
            if profile.last_activity:
                now = datetime.now(timezone.utc)
                la = profile.last_activity
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                days_inactive = (now - la).days
                profile.total_score = compute_decay(
                    profile.total_score,
                    max(0, days_inactive),
                    float(config.get("decay_rate", 0.05)),
                )

            old_level = profile.level
            old_tier = profile.current_tier

            profile.total_score += points
            profile.weekly_score += points
            profile.monthly_score += points
            profile.last_activity = datetime.now(timezone.utc)

            # Level math
            level_const = float(config.get("level_constant", 50.0))
            profile.level = level_from_score(profile.total_score, level_const)

            # Update counters by event type
            if event_type == "message":
                profile.messages_count += 1
            elif event_type == "reaction":
                profile.reactions_received += 1
            elif event_type == "thanks":
                profile.thanks_received += 1
            elif event_type == "voice_minute":
                profile.voice_minutes += max(0, int((metadata or {}).get("minutes", 0)))

            # Load tiers for resolution
            tiers_result = await session.execute(
                select(ReputationTier).where(ReputationTier.guild_id == str(guild_id))
            )
            tier_rows = list(tiers_result.scalars().all())
            tier_dicts = [
                {
                    "name": t.name,
                    "symbol": t.symbol,
                    "min_score": t.min_score,
                    "min_level": t.min_level,
                    "color_hex": t.color_hex,
                    "sort_order": t.sort_order,
                    "role_id": t.role_id,
                    "assign_role": t.assign_role,
                }
                for t in tier_rows
            ]
            new_tier_data = resolve_tier(tier_dicts, profile.level, profile.total_score)
            leveled_up = profile.level > old_level
            tier_changed = new_tier_data["name"] != old_tier
            if tier_changed:
                profile.current_tier = new_tier_data["name"]
                if new_tier_data.get("assign_role") and new_tier_data.get("role_id"):
                    await self._assign_tier_role(
                        guild_id, user_id, new_tier_data["role_id"], tier_rows
                    )

            # Record event
            event = ReputationEvent(
                guild_id=str(guild_id),
                actor_id=str(actor_id or user_id),
                target_id=str(user_id),
                event_type=event_type,
                points=points,
                message_id=str(message_id) if message_id else None,
                channel_id=str(channel_id) if channel_id else None,
                metadata_json=json.dumps(metadata) if metadata else None,
            )
            session.add(event)
            await session.flush()

            # Save profile
            session.add(profile)

        # Commit happens when session_scope exits — profile is now detached
        # for subsequent reads, which is fine for read-only check_rewards call.

        # Check rewards (opens its own session)
        new_rewards = []
        if leveled_up or tier_changed:
            new_rewards = await self._check_rewards(guild_id, user_id, profile, config)

        # Showoff
        if (leveled_up or tier_changed or new_rewards) and config.get("showoff_channel_id"):
            await self._send_showoff(
                guild_id,
                user_id,
                profile,
                new_tier_data,
                leveled_up,
                tier_changed,
                new_rewards,
                config,
            )

        return {
            "profile": profile,
            "leveled_up": leveled_up,
            "new_level": profile.level,
            "old_level": old_level,
            "tier_changed": tier_changed,
            "new_tier": new_tier_data["name"],
            "old_tier": old_tier,
            "new_rewards": new_rewards,
        }

    async def _assign_tier_role(
        self, guild_id: int, user_id: int, role_id: str, tiers: list
    ) -> None:
        """Assign the new tier role, remove lower-tier roles."""
        guild = self.ctx.get_guild(guild_id)
        if guild is None:
            return
        member = guild.get_member(user_id)
        if member is None:
            return
        role = guild.get_role(int(role_id))
        if role is None:
            return
        try:
            # Remove other tier roles
            for tier in tiers:
                if tier.assign_role and tier.role_id and str(tier.role_id) != str(role_id):
                    remove_role = guild.get_role(int(tier.role_id))
                    if remove_role and remove_role in member.roles:
                        await member.remove_roles(
                            remove_role, reason="Bark Reputation: tier update"
                        )
            await member.add_roles(role, reason="Bark Reputation: tier achieved")
        except (discord.Forbidden, discord.HTTPException):
            self._logger.exception(
                "Failed to assign tier role for user %s in guild %s", user_id, guild_id
            )

    async def _check_rewards(
        self,
        guild_id: int,
        user_id: int,
        profile: ReputationProfile,
        config: dict,
    ) -> list[dict]:
        """Check for unearned rewards and auto-award them."""
        earned = []
        async with session_scope() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(ReputationReward).where(
                    ReputationReward.guild_id == str(guild_id),
                    ReputationReward.auto_award.is_(True),
                )
            )
            rewards = list(result.scalars().all())

            for reward in rewards:
                profile_meets_tier = (
                    not reward.required_tier
                    or reward.required_tier == "unranked"
                    or reward.required_tier == profile.current_tier
                )
                profile_meets_level = profile.level >= reward.required_level
                if not profile_meets_tier or not profile_meets_level:
                    continue
                # Already awarded?
                award_check = await session.execute(
                    select(ReputationAward).where(
                        ReputationAward.guild_id == str(guild_id),
                        ReputationAward.user_id == str(user_id),
                        ReputationAward.reward_id == reward.id,
                    )
                )
                if award_check.scalar_one_or_none() is not None:
                    continue
                # Award it
                session.add(
                    ReputationAward(
                        guild_id=str(guild_id),
                        user_id=str(user_id),
                        reward_id=reward.id,
                        tier_name=profile.current_tier,
                        level_at_award=profile.level,
                        score_at_award=profile.total_score,
                    )
                )
                earned.append(
                    {
                        "name": reward.name,
                        "reward_type": reward.reward_type,
                        "reward_value": reward.reward_value,
                    }
                )
            if earned:
                await session.commit()
        return earned

    # ── Showoff channel ──────────────────────────────────

    async def _send_showoff(
        self,
        guild_id: int,
        user_id: int,
        profile: ReputationProfile,
        tier_data: dict,
        leveled_up: bool,
        tier_changed: bool,
        new_rewards: list[dict],
        config: dict,
    ) -> None:
        """Post an announcement to the configured showoff channel."""
        # Rate limit
        now = time.time()
        timestamps = self._showoff_rate_limits[guild_id]
        timestamps[:] = [ts for ts in timestamps if now - ts < 3600]
        if len(timestamps) >= MAX_SHOWOFF_PER_HOUR:
            return
        timestamps.append(now)

        channel_id = config.get("showoff_channel_id")
        if not channel_id:
            return
        guild = self.ctx.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, discord.TextChannel):
            return

        member = guild.get_member(user_id)
        if member is None:
            return

        embed = discord.Embed(
            color=discord.Color(int(tier_data.get("color_hex", "#99aab5").lstrip("#"), 16)),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

        if leveled_up:
            embed.add_field(
                name=f"{tier_data['symbol']} Level Up!",
                value=f"Reached **Level {profile.level}**!",
                inline=False,
            )
        if tier_changed:
            embed.add_field(
                name=f"{tier_data['symbol']} New Tier: {tier_data['name']}",
                value=f"Promoted to **{tier_data['name']}**!",
                inline=False,
            )
        if new_rewards:
            reward_names = "\n".join(f"• {r['name']}" for r in new_rewards)
            embed.add_field(name="🎁 Rewards Unlocked", value=reward_names, inline=False)

        if not embed.fields:
            return

        embed.set_footer(text=f"Total Score: {profile.total_score:.0f}")
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _send_showoff_text(
        self,
        guild_id: int,
        user_id: int,
        title: str,
        description: str,
        config: dict,
    ) -> None:
        """Post a plain-text showoff message (for /thanks highlights, etc.)."""
        now = time.time()
        timestamps = self._showoff_rate_limits[guild_id]
        timestamps[:] = [ts for ts in timestamps if now - ts < 3600]
        if len(timestamps) >= MAX_SHOWOFF_PER_HOUR:
            return
        timestamps.append(now)

        channel_id = config.get("showoff_channel_id")
        if not channel_id:
            return
        guild = self.ctx.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(int(channel_id))
        if channel is None or not isinstance(channel, discord.TextChannel):
            return
        try:
            await channel.send(f"**{title}**\n{description}")
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── Event Handlers ───────────────────────────────────

    async def _on_message(self, event_type: str, **data) -> None:
        message = data.get("message")
        if not message or not message.guild or message.author.bot:
            return

        guild_id = int(message.guild.id)
        user_id = int(message.author.id)

        config = await self.load_dashboard_config(guild_id)
        if not config.get("enabled_sources", {}).get("messages", True):
            return

        # Check ignored channels
        ignored = config.get("ignored_channels", "")
        if ignored and str(message.channel.id) in [
            c.strip() for c in ignored.split(",") if c.strip()
        ]:
            return

        # Dedup
        recent = self._recent_messages[guild_id]
        if message.id in recent:
            return
        recent.add(message.id)
        if len(recent) > 5000:
            self._recent_messages[guild_id] = set(list(recent)[-2500:])

        points = compute_message_points(config)

        # Emoji bonus
        if config.get("enabled_sources", {}).get("emoji", True):
            emoji_count = len(EMOJI_RE.findall(message.content))
            if emoji_count:
                emoji_points = compute_emoji_points(config) * emoji_count
                await self._add_points(
                    guild_id,
                    user_id,
                    emoji_points,
                    "emoji",
                    actor_id=user_id,
                    message_id=int(message.id),
                    channel_id=int(message.channel.id),
                    config=config,
                )

        await self._add_points(
            guild_id,
            user_id,
            points,
            "message",
            actor_id=user_id,
            message_id=int(message.id),
            channel_id=int(message.channel.id),
            config=config,
        )

    async def _on_reaction_add(self, event_type: str, **data) -> None:
        payload = data.get("payload")
        if payload is None:
            return
        guild_id = int(payload.guild_id)
        if guild_id not in [g.id for g in self.ctx.guilds]:
            return

        config = await self.load_dashboard_config(guild_id)
        if not config.get("enabled_sources", {}).get("reactions", True):
            return

        # Point the message author for receiving a reaction
        channel = self.ctx.get_guild(guild_id).get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if message is None or message.author.bot:
            return

        target_id = int(message.author.id)
        actor_id = int(payload.user_id)

        # Reaction giver gets small points too
        if config.get("enabled_sources", {}).get("reactions", True):
            given_points = compute_reaction_given_points(config)
            await self._add_points(
                guild_id,
                actor_id,
                given_points,
                "reaction_given",
                actor_id=actor_id,
                target_id=target_id,
                message_id=int(payload.message_id),
                channel_id=int(payload.channel_id),
                config=config,
            )

        # Message author gets received points
        received_points = compute_reaction_received_points(config)
        await self._add_points(
            guild_id,
            target_id,
            received_points,
            "reaction",
            actor_id=actor_id,
            target_id=target_id,
            message_id=int(payload.message_id),
            channel_id=int(payload.channel_id),
            config=config,
        )

    async def _on_voice_state(self, event_type: str, **data) -> None:
        member = data.get("member")
        if not member or member.bot or not member.guild:
            return

        guild_id = int(member.guild.id)
        config = await self.load_dashboard_config(guild_id)
        if not config.get("enabled_sources", {}).get("voice", True):
            return

        after_channel = data.get("after_channel")
        user_id = int(member.id)

        if after_channel is not None:
            # Joined or moved to a channel
            self._voice_activity[guild_id][user_id] = time.time()
        else:
            # Left voice entirely — award points for time spent
            join_ts = self._voice_activity.get(guild_id, {}).pop(user_id, None)
            if join_ts is not None:
                minutes = (time.time() - join_ts) / 60.0
                if minutes >= 0.5:  # At least 30 seconds to count
                    points = compute_voice_points(minutes, config)
                    await self._add_points(
                        guild_id,
                        user_id,
                        points,
                        "voice_minute",
                        actor_id=user_id,
                        metadata={"minutes": minutes},
                        config=config,
                    )

    async def _voice_tick_loop(self) -> None:
        """Periodic tick to credit voice time for active members."""
        try:
            while True:
                await asyncio.sleep(VOICE_TICK_SECONDS)
                await self._credit_voice_tick(time.time())
        except asyncio.CancelledError:
            pass

    async def _credit_voice_tick(self, now: float) -> None:
        """Credit one voice interval without restoring members who left mid-award."""
        for guild_id, activity in list(self._voice_activity.items()):
            guild = self.ctx.get_guild(guild_id)
            if guild is None:
                self._voice_activity.pop(guild_id, None)
                continue
            config = await self.load_dashboard_config(guild_id)
            if not config.get("enabled_sources", {}).get("voice", True):
                continue
            for user_id, join_ts in list(activity.items()):
                elapsed = now - join_ts
                if elapsed < VOICE_TICK_SECONDS:
                    continue
                minutes = elapsed / 60.0
                points = compute_voice_points(minutes, config)
                # Claim this sampled interval before awaiting the DB write. A
                # concurrent leave then sees only post-tick time and cannot
                # award the same interval a second time.
                if activity.get(user_id) != join_ts:
                    continue
                activity[user_id] = now
                try:
                    if points > 0:
                        await self._add_points(
                            guild_id,
                            user_id,
                            points,
                            "voice_minute",
                            actor_id=user_id,
                            metadata={"minutes": minutes},
                            config=config,
                        )
                except Exception:
                    if activity.get(user_id) == now:
                        activity[user_id] = join_ts
                    self._logger.exception(
                        "Failed to credit voice reputation for guild %s user %s",
                        guild_id,
                        user_id,
                    )

    # ── Slash commands ───────────────────────────────────

    def _make_reputation_command(self):
        @discord.app_commands.command(
            name="reputation", description="View your rank or another member's rank"
        )
        @discord.app_commands.describe(member="Member to look up (leave empty for yourself)")
        async def reputation_cmd(
            interaction: discord.Interaction, member: discord.Member | None = None
        ):
            if not interaction.guild:
                return
            await interaction.response.defer(ephemeral=True)
            target = member or interaction.user
            guild_id = int(interaction.guild.id)

            async with session_scope() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(ReputationProfile).where(
                        ReputationProfile.guild_id == str(guild_id),
                        ReputationProfile.user_id == str(target.id),
                    )
                )
                profile = result.scalar_one_or_none()

            if profile is None:
                await interaction.followup.send(
                    f"{target.display_name} has no reputation data yet.", ephemeral=True
                )
                return

            # Look up tier
            async with session_scope() as session:
                from sqlalchemy import select

                t_result = await session.execute(
                    select(ReputationTier).where(
                        ReputationTier.guild_id == str(guild_id),
                        ReputationTier.name == profile.current_tier,
                    )
                )
                tier = t_result.scalar_one_or_none()

            symbol = tier.symbol if tier else "⬜"
            color = int(tier.color_hex.lstrip("#"), 16) if tier else 0x99AAB5
            tier_name = tier.name if tier else "Unranked"

            progress = next_level_progress(
                profile.total_score,
                profile.level,
                float(await self._get_level_constant(guild_id)),
            )
            bar = self._progress_bar(progress["progress"], 12)

            config = await self.load_dashboard_config(guild_id)
            showoff_channel_id = config.get("showoff_channel_id", "")
            showoff_mention = f"<#{showoff_channel_id}>" if showoff_channel_id else "not configured"

            embed = discord.Embed(
                title=f"{symbol} {target.display_name} — Level {profile.level} {tier_name}",
                color=discord.Color(color),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="Total Score", value=f"{profile.total_score:.0f}", inline=True)
            embed.add_field(
                name="Level Progress", value=f"{bar} {progress['percent']}%", inline=False
            )
            embed.add_field(name="Messages", value=str(profile.messages_count), inline=True)
            embed.add_field(
                name="Reactions Received", value=str(profile.reactions_received), inline=True
            )
            embed.add_field(name="Thanks Received", value=str(profile.thanks_received), inline=True)
            embed.add_field(name="Voice Minutes", value=str(profile.voice_minutes), inline=True)
            embed.add_field(name="Weekly Score", value=f"{profile.weekly_score:.0f}", inline=True)
            embed.add_field(name="Showoff Channel", value=showoff_mention, inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)

        return reputation_cmd

    def _make_leaderboard_command(self):
        @discord.app_commands.command(
            name="leaderboard", description="Show the top ranked members in this server"
        )
        @discord.app_commands.describe(hide="Hide the response from others (default: false)")
        async def leaderboard_cmd(interaction: discord.Interaction, hide: bool = True):
            if not interaction.guild:
                return
            await interaction.response.defer(ephemeral=hide)
            guild_id = int(interaction.guild.id)

            async with session_scope() as session:
                from sqlalchemy import desc, select

                result = await session.execute(
                    select(ReputationProfile)
                    .where(ReputationProfile.guild_id == str(guild_id))
                    .order_by(desc(ReputationProfile.total_score))
                    .limit(20)
                )
                profiles = list(result.scalars().all())

            if not profiles:
                await interaction.followup.send("No reputation data yet.", ephemeral=True)
                return

            # Load tiers for symbols
            async with session_scope() as session:
                from sqlalchemy import select

                t_result = await session.execute(
                    select(ReputationTier).where(ReputationTier.guild_id == str(guild_id))
                )
                tiers = {t.name: t for t in t_result.scalars().all()}

            lines = []
            for i, p in enumerate(profiles[:20], 1):
                member = interaction.guild.get_member(int(p.user_id))
                name = member.display_name if member else f"<@{p.user_id}>"
                tier = tiers.get(p.current_tier)
                symbol = tier.symbol if tier else "⬜"
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
                lines.append(
                    f"{medal} {symbol} **{name}** — Level {p.level} — `{p.total_score:.0f}` pts"
                )

            embed = discord.Embed(
                title=f"🏆 {interaction.guild.name} Leaderboard",
                description="\n".join(lines),
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Use /reputation to see your detailed stats")

            await interaction.followup.send(embed=embed, ephemeral=hide)

        return leaderboard_cmd

    def _make_thanks_command(self):
        @discord.app_commands.command(
            name="thanks", description="Thank another member for something"
        )
        @discord.app_commands.describe(
            member="The member you want to thank", reason="What they did"
        )
        async def thanks_cmd(
            interaction: discord.Interaction, member: discord.Member, reason: str = ""
        ):
            if not interaction.guild:
                return
            guild_id = int(interaction.guild.id)
            actor_id = int(interaction.user.id)
            target_id = int(member.id)

            if member.bot:
                await interaction.response.send_message(
                    "Bots don't need thanks! 🤖", ephemeral=True
                )
                return
            if actor_id == target_id:
                await interaction.response.send_message("You can't thank yourself!", ephemeral=True)
                return

            # Cooldown
            now = time.time()
            pair_key = (actor_id, target_id)
            last_pair = self._thanks_cooldowns.get(pair_key, 0)
            if now - last_pair < THANKS_COOLDOWN_SECONDS:
                remaining = int(THANKS_COOLDOWN_SECONDS - (now - last_pair))
                await interaction.response.send_message(
                    f"You can thank {member.display_name} again in {remaining}s.", ephemeral=True
                )
                return
            last_self = self._thanks_self_cooldowns.get(actor_id, 0)
            if now - last_self < THANKS_SELF_COOLDOWN_SECONDS:
                remaining = int(THANKS_SELF_COOLDOWN_SECONDS - (now - last_self))
                await interaction.response.send_message(
                    f"Please wait {remaining}s before sending another thanks.", ephemeral=True
                )
                return

            config = await self.load_dashboard_config(guild_id)
            await interaction.response.defer(ephemeral=True)

            # Points for giver
            given_points = compute_thanks_given_points(config)
            await self._add_points(
                guild_id,
                actor_id,
                given_points,
                "thanks_given",
                actor_id=actor_id,
                target_id=target_id,
                metadata={"reason": reason, "target": str(target_id)},
                config=config,
            )

            # Points for receiver
            received_points = compute_thanks_received_points(config)
            await self._add_points(
                guild_id,
                target_id,
                received_points,
                "thanks",
                actor_id=actor_id,
                target_id=target_id,
                metadata={"reason": reason, "giver": str(actor_id)},
                config=config,
            )

            self._thanks_cooldowns[pair_key] = now
            self._thanks_self_cooldowns[actor_id] = now

            msg = f"{interaction.user.mention} thanked {member.mention}"
            if reason:
                msg += f" — *{reason}*"
            await interaction.followup.send(f"✅ Thank you! {msg}")

            # Optional showoff for thanks highlights
            if config.get("showoff_channel_id"):
                await self._send_showoff_text(
                    guild_id,
                    target_id,
                    f"🙏 {member.display_name} was thanked!",
                    f"By {interaction.user.display_name}" + (f"\n> {reason}" if reason else ""),
                    config,
                )

        return thanks_cmd

    # ── Progress bar helper ──────────────────────────────

    @staticmethod
    def _progress_bar(ratio: float, width: int = 12) -> str:
        filled = int(ratio * width)
        filled = max(0, min(width, filled))
        return "██" * filled + "░░" * (width - filled)

    async def _get_level_constant(self, guild_id: int) -> float:
        config = await self.load_dashboard_config(guild_id)
        return float(config.get("level_constant", 50.0))
