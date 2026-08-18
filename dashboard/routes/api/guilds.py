"""
Guilds API routes.
"""

from datetime import datetime, timezone

import discord
from fastapi import APIRouter, Request

from services.response import (
    api_error,
    api_forbidden,
    api_not_found,
    api_success,
    check_api_permission,
    get_module_min_role,
)

router = APIRouter(tags=["api-guilds"])


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize persisted UTC datetimes with an explicit timezone offset.

    SQLite returns ``DateTime`` values without tzinfo even when callers stored
    aware UTC values. Browsers interpret offset-free ISO strings as local time,
    which can make old events look new (or even appear to be in the future).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


@router.get("/guilds")
async def list_guilds(request: Request):
    """List every Discord guild visible to the signed-in user."""
    bot = request.state.bot
    from config import config

    user = request.session.get("user") if config.oauth2.enabled else None
    if user:
        from database.engine import session_scope
        from services.dashboard_access import (
            build_guild_catalog,
            get_dashboard_admin_role,
            get_dashboard_moderator_roles,
            get_user_guild_access,
        )

        async with session_scope() as session:
            access = await get_user_guild_access(session, user["id"])
            guild_ids = (row.guild_id for row in access)
            moderator_roles = await get_dashboard_moderator_roles(session, guild_ids)
            admin_roles = await get_dashboard_admin_role(
                session, (row.guild_id for row in access)
            )
        return api_success(
            {
                "guilds": build_guild_catalog(
                    access,
                    bot.guilds,
                    client_id=config.oauth2.client_id,
                    moderator_roles_by_guild=moderator_roles,
                    admin_roles_by_guild=admin_roles,
                    public_url=config.dashboard.public_url,
                )
            }
        )

    guilds = []
    for guild in bot.guilds:
        guilds.append(
            {
                "id": guild.id,
                "name": guild.name,
                "member_count": guild.member_count,
                "owner_id": str(guild.owner_id),
                "icon_url": guild.icon.url if guild.icon else None,
            }
        )
    return api_success({"guilds": guilds})


@router.get("/guilds/{guild_id}")
async def get_guild(request: Request, guild_id: int):
    """Get detailed info about a guild."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")
    return api_success(await _serialize_guild(guild, guild_id))


async def _serialize_guild(guild, guild_id: int) -> dict:
    """Serialize the full server profile. Shared by GET /guilds/{id} and the
    dashboard aggregate endpoint so the profile is built in exactly one place."""
    # Resolve owner safely — guild.owner can raise if uncached
    try:
        owner_name = str(guild.owner) if guild.owner else "Unknown"
    except Exception:
        owner_name = "Unknown"

    try:
        banner_url = guild.banner.url if guild.banner else None
    except Exception:
        banner_url = None

    try:
        created_at = guild.created_at.isoformat() if guild.created_at else None
    except Exception:
        created_at = None

    try:
        premium_subscriber_count = guild.premium_subscriber_count
    except Exception:
        premium_subscriber_count = 0

    try:
        verification_level = guild.verification_level.name if guild.verification_level else None
    except Exception:
        verification_level = None

    # Server MOTD + custom banner + URL slug (stored per-guild in GuildSetting).
    try:
        from services.guild_settings import get_settings

        settings = await get_settings(guild_id, "motd", "banner_url", "slug")
        motd = settings.get("motd", "")
        custom_banner_url = settings.get("banner_url", "")
        slug = settings.get("slug", "")
    except Exception:
        motd = ""
        custom_banner_url = ""
        slug = ""

    scheduled_events = []
    try:
        for ev in getattr(guild, "scheduled_events", []) or []:
            # ScheduledEvent cover image (Discord event banner) — ``Asset`` or
            # None. Exposed as cover_url so the dashboard can show it. Guard
            # against non-str Asset.url so a malformed/None cover never crashes
            # the whole dashboard payload (JSON-serialization safety).
            cover_url = None
            try:
                _cover = getattr(ev, "cover_image", None)
                if _cover and getattr(_cover, "url", None):
                    _url = _cover.url
                    if isinstance(_url, str):
                        cover_url = _url
            except Exception:
                cover_url = None
            scheduled_events.append(
                {
                    "id": str(ev.id),
                    # Coerce to str defensively: ScheduledEvent.name/status are
                    # plain strings in production, but a malformed event or a
                    # test double can expose a non-str — never let a single bad
                    # event break the whole dashboard JSON payload.
                    "name": str(ev.name) if ev.name else "",
                    "description": str(ev.description) if ev.description else None,
                    "start_time": ev.start_time.isoformat() if ev.start_time else None,
                    "end_time": ev.end_time.isoformat() if ev.end_time else None,
                    "status": str(ev.status).split(".")[-1] if ev.status else None,
                    "entity_type": str(ev.entity_type).split(".")[-1] if ev.entity_type else None,
                    "url": ev.url,
                    "user_count": getattr(ev, "user_count", 0),
                    "channel_name": ev.channel.name if getattr(ev, "channel", None) else None,
                    "cover_url": cover_url,
                }
            )
    except Exception:
        scheduled_events = []

    return {
        "id": guild.id,
        "name": guild.name,
        "member_count": guild.member_count,
        "owner_id": str(guild.owner_id),
        "owner_name": owner_name,
        "icon_url": guild.icon.url if guild.icon else None,
        "banner_url": banner_url,
        "description": guild.description,
        "premium_tier": guild.premium_tier,
        "premium_subscriber_count": premium_subscriber_count,
        "max_members": guild.max_members,
        "channels": len(guild.channels),
        "roles": len(guild.roles),
        "emojis": len(guild.emojis),
        "created_at": created_at,
        "verification_level": verification_level,
        "features": list(guild.features or []),
        "motd": motd,
        "custom_banner_url": custom_banner_url,
        "slug": slug,
        "scheduled_events": scheduled_events,
    }



@router.put("/guilds/{guild_id}/banner")
async def set_guild_banner(request: Request, guild_id: int):
    """Set a custom banner image (URL) shown on the dashboard profile."""
    if getattr(request.state, "guild_viewer", False):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    url = str((body or {}).get("banner_url") or "").strip()[:2000]

    from services.guild_settings import set_setting

    await set_setting(guild_id, "banner_url", url)
    return api_success({"banner_url": url})


@router.put("/guilds/{guild_id}/slug")
async def set_guild_slug(request: Request, guild_id: int):
    """Set a custom URL slug (e.g. /g/my-server) that links to this server."""
    if getattr(request.state, "guild_viewer", False):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    slug = str((body or {}).get("slug") or "").strip().lower()

    import re

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting
    from services.guild_settings import set_setting

    if slug:
        # Friendly URL slug: lowercase letters, digits, hyphens. 3-32 chars.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,31}", slug):
            return api_error(
                "Slug must be 3-32 characters (lowercase letters, digits, hyphens).",
                status_code=400,
            )
        # Slug must be unique across guilds.
        async with session_scope() as session:
            clash = (
                await session.execute(
                    select(GuildSetting).where(
                        GuildSetting.key == "slug",
                        GuildSetting.value == slug,
                        GuildSetting.guild_id != str(guild_id),
                    )
                )
            ).scalars().first()
        if clash is not None:
            return api_error("That slug is already in use by another server.", status_code=409)

    await set_setting(guild_id, "slug", slug)
    return api_success({"slug": slug, "url": f"/g/{slug}" if slug else None})


@router.put("/guilds/{guild_id}/motd")
async def set_guild_motd(request: Request, guild_id: int):
    """Set the server's message-of-the-day shown on the dashboard profile."""
    if getattr(request.state, "guild_viewer", False):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    text = str((body or {}).get("motd") or "").strip()[:1000]

    from services.guild_settings import set_setting

    await set_setting(guild_id, "motd", text)
    return api_success({"motd": text})


@router.get("/guilds/{guild_id}/stats")
async def get_guild_stats(request: Request, guild_id: int):
    """Get live guild + engagement statistics for the Statistics page.

    Viewable by any member of a connected server (safe read). Deliberately
    excludes moderation data (cases, AutoMod) — that stays private to admins
    and mods in the moderation workspace.
    """
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from database.engine import session_scope

    async with session_scope() as session:
        growth_30d = await _guild_growth_30d(session, guild_id)
        growth_series = await _guild_growth_series(session, guild_id, days=30)
        # Durable channel/emoji breakdowns persisted by the data collector —
        # survives bot restarts that clear the in-memory counters.
        db_ch_7d, db_emoji_all = await _snapshot_channel_emoji_totals(session, guild_id, 7)
        db_ch_30d, _ = await _snapshot_channel_emoji_totals(session, guild_id, 30)
    online, in_voice = _online_and_voice_counts(guild)

    # Today's message/emoji activity (tracked live by the bot).
    msgs = {}
    msg_stats_fn = getattr(bot, "message_stats", None)
    if callable(msg_stats_fn):
        try:
            result = msg_stats_fn(guild_id)
            if isinstance(result, dict):
                msgs = result
        except Exception:
            msgs = {}
    # Use today's live counters when the bot has data this session; otherwise
    # fall back to the persisted snapshot (which survives restarts). The
    # snapshot for "today" is written by the collector on its first tick, so a
    # just-restarted bot still has yesterday's + today's recorded breakdowns.
    live_channels = msgs.get("channels", {})
    live_messages = int(msgs.get("messages", 0) or 0)
    today_snapshot_channels = {k: v for k, v in db_ch_7d.items()}
    # If the in-memory counter has any activity, prefer it for "today";
    # otherwise the persisted 7d window's most recent day is a safe stand-in.
    if live_messages > 0:
        channels_today = sorted(
            live_channels.values(), key=lambda c: c["count"], reverse=True
        )[:8]
    else:
        channels_today = sorted(
            today_snapshot_channels.values(), key=lambda c: c["count"], reverse=True
        )[:8]
    emojis_today = sorted(
        msgs.get("emojis", {}).items(), key=lambda kv: kv[1], reverse=True
    )[:8]

    # Trailing-window top channels (7d / 30d) + all-time emoji. Combine the
    # persisted snapshots (durable, survive restarts) with today's live counts
    # and the in-memory session history (richest for the current session).
    def _merge_sources(
        db_map: dict[str, dict], in_memory: list[dict]
    ) -> list[dict]:
        merged = {k: dict(v) for k, v in db_map.items()}
        for ch_id, entry in live_channels.items():
            agg = merged.setdefault(str(ch_id), {"name": entry["name"], "count": 0})
            agg["count"] += int(entry.get("count", 0) or 0)
            agg["name"] = entry["name"]
        for entry in in_memory:
            ch_id = str(entry.get("id") or entry.get("channel_id") or entry.get("name"))
            count = 0
            try:
                count = int(entry.get("count", 0) or 0)
            except (ValueError, TypeError):
                count = 0
            name = entry.get("name") or ch_id
            agg = merged.setdefault(ch_id, {"name": name, "count": 0})
            agg["count"] += count
            agg["name"] = name
        return sorted(merged.values(), key=lambda c: c["count"], reverse=True)[:8]

    in_mem_7d: list[dict] = []
    in_mem_30d: list[dict] = []
    top_channels_fn = getattr(bot, "top_channels", None)
    if callable(top_channels_fn):
        try:
            r7 = top_channels_fn(guild_id, 7)
            r30 = top_channels_fn(guild_id, 30)
            if isinstance(r7, list):
                in_mem_7d = r7
            if isinstance(r30, list):
                in_mem_30d = r30
        except Exception:
            in_mem_7d, in_mem_30d = [], []

    top_channels_7d = _merge_sources(db_ch_7d, in_mem_7d)
    top_channels_30d = _merge_sources(db_ch_30d, in_mem_30d)
    all_time_emojis = dict(db_emoji_all)
    for name, count in msgs.get("emoji_total", {}).items():
        try:
            all_time_emojis[name] = all_time_emojis.get(name, 0) + int(count or 0)
        except (ValueError, TypeError):
            pass
    emojis_all_time = [
        {"name": k, "count": v}
        for k, v in sorted(all_time_emojis.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    return api_success(
        {
            "members": guild.member_count,
            "members_online": online,
            "bot_count": sum(1 for m in guild.members if m.bot),
            "channels": len(guild.channels),
            "text_channels": len(guild.text_channels),
            "voice_channels": len(guild.voice_channels),
            "roles": len(guild.roles),
            "boosts": guild.premium_subscription_count,
            "boost_tier": guild.premium_tier,
            "emojis": len(guild.emojis),
            "in_voice": in_voice,
            "growth_30d": growth_30d,
            "growth_series": growth_series,
            "messages_today": live_messages,
            "top_channels_today": channels_today,
            "top_channels_7d": top_channels_7d,
            "top_channels_30d": top_channels_30d,
            "top_emojis_today": [{"name": k, "count": v} for k, v in emojis_today],
            "top_emojis_all_time": emojis_all_time,
        }
    )


async def _guild_growth_series(session, guild_id: int, days: int = 30) -> list[dict]:
    """Return the guild's member count per day (oldest first) from snapshots."""
    from datetime import date, timedelta

    from sqlalchemy import select

    from database.models.analytics import ActivitySnapshot

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(ActivitySnapshot)
        .where(
            ActivitySnapshot.guild_id == str(guild_id),
            ActivitySnapshot.snapshot_date >= since,
        )
        .order_by(ActivitySnapshot.snapshot_date)
    )
    return [
        {
            "date": row.snapshot_date.isoformat(),
            "members": row.total_members,
        }
        for row in result.scalars().all()
    ]


async def _snapshot_channel_emoji_totals(
    session, guild_id: int, days: int
) -> tuple[dict[str, dict], dict[str, int]]:
    """Aggregate per-channel message counts and all-time emoji counts over the
    trailing ``days`` from persisted activity snapshots.

    Returns ``(channels, emoji_total)`` where ``channels`` maps channel_id ->
    {"name": str, "count": int} and ``emoji_total`` maps emoji name -> count.
    This is the durable source for the Statistics page: the in-memory bot
    counters reset on restart, but these daily breakdowns survive in the DB.
    """
    import json
    from datetime import date, timedelta

    from sqlalchemy import select

    from database.models.analytics import ActivitySnapshot

    since = date.today() - timedelta(days=max(1, days))
    result = await session.execute(
        select(ActivitySnapshot)
        .where(
            ActivitySnapshot.guild_id == str(guild_id),
            ActivitySnapshot.snapshot_date >= since,
        )
        .order_by(ActivitySnapshot.snapshot_date)
    )
    channels: dict[str, dict] = {}
    emoji_total: dict[str, int] = {}
    for row in result.scalars().all():
        try:
            day_channels = json.loads(row.channel_messages or "{}")
        except (json.JSONDecodeError, TypeError):
            day_channels = {}
        for ch_id, entry in day_channels.items():
            try:
                count = int(entry.get("count", 0) or 0)
            except (ValueError, TypeError):
                count = 0
            if count <= 0:
                continue
            agg = channels.setdefault(str(ch_id), {"name": "", "count": 0})
            agg["count"] += count
            agg["name"] = entry.get("name") or agg["name"]
        try:
            day_emojis = json.loads(row.emoji_counts or "{}")
        except (json.JSONDecodeError, TypeError):
            day_emojis = {}
        for name, count in day_emojis.items():
            try:
                count = int(count or 0)
            except (ValueError, TypeError):
                count = 0
            if count > 0:
                emoji_total[name] = emoji_total.get(name, 0) + count
    return channels, emoji_total


@router.get("/guilds/{guild_id}/dashboard")
async def get_guild_dashboard(request: Request, guild_id: int):
    """Aggregate endpoint for the server overview page: the profile, the
    viewer/role flag, and add-on dashboard widget cards — one round-trip."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")
    profile = await _serialize_guild(guild, guild_id)
    viewer = getattr(request.state, "guild_viewer", False)
    cards = []
    modules = []
    try:
        cards = await bot.modules.get_dashboard_cards(guild_id)
        # Enabled modules summary (title, workspace link, widget count).
        widgets_by_module: dict[str, int] = {}
        for card in cards:
            m = card.get("module")
            if m:
                widgets_by_module[m] = widgets_by_module.get(m, 0) + 1
        for mname, module in bot.modules.get_all_modules().items():
            if not bot.modules.is_enabled_for_guild(guild_id, mname):
                continue
            # Slash commands come from the SAME get_commands() registration the
            # /bark dispatcher uses — one source drives both surfaces.
            commands = []
            try:
                commands = [
                    {"name": c.name, "description": c.description, "slash": bool(c.slash)}
                    for c in module.get_commands()
                ]
            except Exception:
                commands = []
            modules.append(
                {
                    "name": mname,
                    "title": getattr(module, "title", "") or mname.replace("_", " ").title(),
                    "description": getattr(module, "description", "") or "",
                    "link": f"/guild/{guild_id}/modules/{mname}",
                    "widgets": widgets_by_module.get(mname, 0),
                    "commands": commands,
                }
            )
        modules.sort(key=lambda m: m["title"].lower())
    except Exception:
        cards = []
        modules = []
    return api_success({"viewer": viewer, "guild": profile, "cards": cards, "modules": modules})


@router.get("/guilds/{guild_id}/events")
async def get_guild_server_events(request: Request, guild_id: int):
    """Return recent Discord server events (member joins/leaves) for the dashboard.

    Viewable by any member of a connected server (safe read). The feed is a
    bounded in-memory ring tracked by the bot since startup.
    """
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")
    events = (
        bot.recent_server_events(guild_id, limit=30)
        if hasattr(bot, "recent_server_events")
        else []
    )
    return api_success({"events": events, "total": len(events)})


async def _guild_growth_30d(session, guild_id: int) -> int:
    """Sum new members recorded by activity snapshots over the last 30 days."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.analytics import ActivitySnapshot

    return (
        await session.execute(
            select(func.sum(ActivitySnapshot.new_members)).where(
                ActivitySnapshot.guild_id == str(guild_id),
                ActivitySnapshot.snapshot_date >= date.today() - timedelta(days=30),
            )
        )
    ).scalar() or 0


def _online_and_voice_counts(guild) -> tuple[int, int]:
    """Count members currently online and members sitting in voice channels."""
    online = sum(1 for member in guild.members if member.status is not discord.Status.offline)
    in_voice = sum(len(channel.members) for channel in guild.voice_channels)
    return online, in_voice


@router.get("/guilds/{guild_id}/roles")
async def get_guild_roles(request: Request, guild_id: int):
    """List all roles in a guild for filtering."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    return api_success(
        {
            "roles": [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "color": str(r.color) if r.color else None,
                    # ADMINISTRATOR permission (0x8) — these roles grant
                    # dashboard admin access regardless of the configured
                    # moderator role. ``permissions`` is a discord.Permissions
                    # object (``.value`` bitfield); tests mock it as an int.
                    "administrator": bool(
                        getattr(r.permissions, "value", r.permissions) & 0x8
                    ),
                }
                for r in guild.roles[1:]
            ]
        }
    )


@router.get("/guilds/{guild_id}/channels")
async def get_guild_channels(request: Request, guild_id: int):
    """List text or voice channels in a guild for schema-backed selectors."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    channel_type = request.query_params.get("type", "text")
    if channel_type not in ("text", "voice"):
        return api_error("Channel type must be 'text' or 'voice'", status_code=400)

    if channel_type == "voice":
        channels: list[discord.abc.GuildChannel] = [
            c for c in guild.channels if isinstance(c, discord.VoiceChannel)
        ]
    else:
        channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
    channels.sort(
        key=lambda x: (
            x.category.name if x.category is not None else "",
            x.position,
        )
    )
    return api_success(
        {
            "channels": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "parent_name": c.category.name if c.category is not None else None,
                    "type": str(c.type),
                }
                for c in channels
            ]
        }
    )


def _member_name(guild, user_id: str | None, fallback: str | None = None) -> str:
    """Resolve a Discord user ID to a display name via the guild cache."""
    if user_id:
        try:
            member = guild.get_member(int(user_id))
        except (TypeError, ValueError):
            member = None  # non-numeric actor IDs like "dashboard"
        if member is not None:
            return str(getattr(member, "display_name", None) or member)
    return fallback or user_id or "Unknown"


async def _load_case_items(session, guild_id: int, guild) -> list[dict]:
    """Recent moderation cases, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import ModerationCase

    labels = {
        "warn": "Warning issued",
        "timeout": "Timeout applied",
        "kick": "Member kicked",
        "ban": "Member banned",
        "unban": "Member unbanned",
    }
    icons = {"warn": "⚠️", "kick": "👢", "ban": "🔨", "timeout": "⏱"}
    result = await session.execute(
        select(ModerationCase)
        .where(ModerationCase.guild_id == str(guild_id))
        .order_by(desc(ModerationCase.created_at))
        .limit(10)
    )
    items = []
    for case in result.scalars():
        target = _member_name(guild, case.target_id, case.target_tag)
        moderator = _member_name(guild, case.moderator_id, case.moderator_tag)
        label = labels.get(case.action_type, case.action_type.replace("_", " ").title())
        items.append(
            {
                "type": "case",
                "category": "moderation",
                "action": case.action_type,
                "label": label,
                "description": f"{label}: {target}",
                "target": target,
                "target_id": case.target_id,
                "moderator": moderator,
                "reason": case.reason or "",
                "case_number": case.case_number,
                "timestamp": _utc_iso(case.created_at),
                "icon": icons.get(case.action_type, "📝"),
            }
        )
    return items


async def _load_audit_items(session, guild_id: int, guild) -> list[dict]:
    """Recent audit-log entries, newest first."""
    import json

    from sqlalchemy import desc, select

    from database.models.moderation import AuditLog

    messaging_actions = {"message_edit", "message_delete", "link_posted"}
    audit_labels = {
        "warn": "Warning issued",
        "timeout": "Timeout applied",
        "kick": "Member kicked",
        "ban": "Member banned",
        "unban": "Member unbanned",
        "vc_kick": "Kicked from voice",
        "member_update": "Member updated",
        "member_role_update": "Role changed",
        "member_join": "Member joined",
        "member_leave": "Member left",
        "voice_join": "Joined voice",
        "voice_leave": "Left voice",
        "voice_move": "Moved voice",
        "message_edit": "Message edited",
        "message_delete": "Message deleted",
        "link_posted": "Link posted",
        "automod_triggered": "AutoMod triggered",
        "backup_created": "Database backup created",
    }
    icons = {
        "kick": "👢",
        "ban": "🔨",
        "unban": "🔓",
        "member_update": "✏️",
        "member_role_update": "🎭",
        "member_join": "📥",
        "member_leave": "📤",
        "voice_join": "🔊",
        "voice_leave": "🔇",
        "voice_move": "🔄",
        "message_edit": "✏️",
        "message_delete": "🗑️",
        "link_posted": "🔗",
        "automod_triggered": "🚨",
        "backup_created": "💾",
    }
    moderation_actions = {"warn", "timeout", "kick", "ban", "unban", "vc_kick", "automod_triggered"}
    voice_actions = {"voice_join", "voice_leave", "voice_move"}
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.guild_id == str(guild_id))
        .order_by(desc(AuditLog.created_at))
        .limit(10)
    )
    items = []
    for entry in result.scalars():
        try:
            details = json.loads(entry.details) if isinstance(entry.details, str) else entry.details
        except (json.JSONDecodeError, TypeError):
            details = {}
        actor = _member_name(guild, entry.actor_id, details.get("actor_tag"))
        messaging = entry.action in messaging_actions
        channel = details.get("channel") or ""
        label = audit_labels.get(entry.action, entry.action.replace("_", " ").title())
        if messaging:
            # For messaging events target_id is the *message* id, not a user —
            # describe the actor and channel instead.
            location = f" in {channel}" if channel else ""
            if entry.action == "message_edit":
                description = f"Message edited by {actor}{location}"
            elif entry.action == "message_delete":
                description = f"Message deleted by {actor}{location}"
            else:
                description = f"Link posted by {actor}{location}"
            target = actor
        else:
            target = _member_name(guild, entry.target_id, details.get("target_tag"))
            description = f"{label}: {target}"
        category = (
            "moderation"
            if entry.action in moderation_actions
            else "messaging"
            if messaging
            else "voice"
            if entry.action in voice_actions
            else "system"
        )
        items.append(
            {
                "type": "audit",
                "category": category,
                "action": entry.action,
                "label": label,
                "description": description,
                "target": target,
                "target_id": entry.target_id,
                "moderator": actor,
                "reason": "",
                "timestamp": _utc_iso(entry.created_at),
                "icon": icons.get(entry.action, "📋"),
            }
        )
    return items


async def _load_voice_items(session, guild_id: int, guild) -> list[dict]:
    """Recent voice-session joins, newest first."""
    from sqlalchemy import desc, select

    from database.models.voice import VoiceSession

    result = await session.execute(
        select(VoiceSession)
        .where(VoiceSession.guild_id == str(guild_id))
        .order_by(desc(VoiceSession.joined_at))
        .limit(15)
    )
    items = []
    for session_row in result.scalars():
        user = _member_name(guild, session_row.user_id, session_row.user_tag)
        items.append(
            {
                "type": "voice",
                "category": "voice",
                "action": "voice_join",
                "label": "Joined voice",
                "description": f"{user} joined voice ({session_row.channel_name or 'unknown'})",
                "target": user,
                "target_id": session_row.user_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(session_row.joined_at),
                "icon": "🎧",
                "duration": session_row.duration_seconds,
            }
        )
    return items


async def _load_warning_items(session, guild_id: int, guild) -> list[dict]:
    """Recently created warnings, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import Warning as WarningModel

    result = await session.execute(
        select(WarningModel)
        .where(WarningModel.guild_id == str(guild_id))
        .order_by(desc(WarningModel.created_at))
        .limit(10)
    )
    items = []
    for warning in result.scalars():
        user = _member_name(guild, warning.user_id)
        moderator = _member_name(guild, warning.moderator_id)
        items.append(
            {
                "type": "warning",
                "category": "moderation",
                "action": "warning",
                "label": "Warning issued",
                "description": f"Warning issued: {user}",
                "target": user,
                "target_id": warning.user_id,
                "moderator": moderator,
                "reason": warning.reason or "",
                "timestamp": _utc_iso(warning.created_at),
                "icon": "⚠️",
            }
        )
    return items


async def _load_reputation_items(session, guild_id: int, guild) -> list[dict]:
    """Notable reputation events, newest first.

    Per-message scoring (message, reaction, emoji, voice minutes) is too noisy
    for the feed and is filtered out.
    """
    from sqlalchemy import desc, select

    from database.models.reputation import ReputationEvent

    noisy_events = {
        "message",
        "reaction",
        "reaction_given",
        "reaction_received",
        "emoji",
        "voice_minute",
    }
    labels = {
        "thanks": "Thanked",
        "award": "Awarded",
        "tier_up": "Tiered up",
        "level_up": "Leveled up",
    }
    icons = {"thanks": "🙏", "award": "🏆", "tier_up": "⬆️", "level_up": "⭐"}
    result = await session.execute(
        select(ReputationEvent)
        .where(
            ReputationEvent.guild_id == str(guild_id),
            # Filter noisy per-message scoring in SQL, not Python — fetching 50
            # recent rows and discarding most of them could return an empty
            # feed on a busy server even when notable events exist.
            ReputationEvent.event_type.notin_(list(noisy_events)),
        )
        .order_by(desc(ReputationEvent.created_at))
        .limit(50)
    )
    items = []
    for event in result.scalars():
        target = _member_name(guild, event.target_id)
        actor = _member_name(guild, event.actor_id)
        label = labels.get(event.event_type, event.event_type.replace("_", " ").title())
        items.append(
            {
                "type": "reputation",
                "category": "reputation",
                "action": event.event_type,
                "label": label,
                "description": f"{actor} {label.lower()} {target} (+{event.points:g})",
                "target": target,
                "target_id": event.target_id,
                "moderator": actor,
                "reason": "",
                "timestamp": _utc_iso(event.created_at),
                "icon": icons.get(event.event_type, "🏆"),
            }
        )
    return items


async def _load_role_items(session, guild_id: int, guild) -> list[dict]:
    """Recent role assignments, newest first, with rule trigger names."""
    from sqlalchemy import desc, select

    from database.models.role_manager import RoleAssignment, RoleRule

    async def fetch_assignments() -> list:
        result = await session.execute(
            select(RoleAssignment)
            .where(RoleAssignment.guild_id == str(guild_id))
            .order_by(desc(RoleAssignment.created_at))
            .limit(10)
        )
        return list(result.scalars())

    assignments = await fetch_assignments()
    rule_ids = {row.rule_id for row in assignments if row.rule_id}
    rule_names: dict[int, str] = {}
    if rule_ids:
        rules_result = await session.execute(select(RoleRule).where(RoleRule.id.in_(rule_ids)))
        for rule in rules_result.scalars():
            rule_names[rule.id] = rule.name

    items = []
    for row in assignments:
        user = _member_name(guild, row.user_id)
        try:
            role = guild.get_role(int(row.role_id)) if row.role_id else None
        except (TypeError, ValueError):
            role = None
        role_name = str(getattr(role, "name", None) or row.role_id or "role")
        action = "assigned" if row.action == "add" else "removed"
        trigger = f" ({rule_names.get(row.rule_id, 'manual')})" if row.rule_id else ""
        label = f"Role {action}"
        items.append(
            {
                "type": "role",
                "category": "roles",
                "action": f"role_{row.action}",
                "label": label,
                "description": f"{label} '{role_name}' for {user}{trigger}",
                "target": user,
                "target_id": row.user_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(row.created_at),
                "icon": "🎭",
            }
        )
    return items


async def _load_note_items(session, guild_id: int, guild) -> list[dict]:
    """Recent user notes, newest first."""
    from sqlalchemy import desc, select

    from database.models.moderation import UserNote

    result = await session.execute(
        select(UserNote)
        .where(UserNote.guild_id == str(guild_id))
        .order_by(desc(UserNote.created_at))
        .limit(10)
    )
    items = []
    for note in result.scalars():
        user = _member_name(guild, note.user_id)
        author = _member_name(guild, note.author_id)
        items.append(
            {
                "type": "note",
                "category": "notes",
                "action": "note_added",
                "label": "Note added",
                "description": f"Note added: {user}",
                "target": user,
                "target_id": note.user_id,
                "moderator": author,
                "reason": note.content[:120],
                "timestamp": _utc_iso(note.created_at),
                "icon": "📝",
            }
        )
    return items


async def _load_auto_voice_items(session, guild_id: int, guild) -> list[dict]:
    """Recent temporary voice channels created by auto_voice, newest first."""
    from sqlalchemy import desc, select

    from database.models.auto_voice import AutoVoiceChannel

    result = await session.execute(
        select(AutoVoiceChannel)
        .where(AutoVoiceChannel.guild_id == str(guild_id))
        .order_by(desc(AutoVoiceChannel.created_at))
        .limit(10)
    )
    items = []
    for channel in result.scalars():
        owner = _member_name(guild, channel.owner_id)
        items.append(
            {
                "type": "auto_voice",
                "category": "voice",
                "action": "voice_channel_created",
                "label": "Voice channel created",
                "description": f"Temp voice channel created: {owner}",
                "target": owner,
                "target_id": channel.owner_id,
                "moderator": None,
                "reason": "",
                "timestamp": _utc_iso(channel.created_at),
                "icon": "🎙️",
            }
        )
    return items


ACTIVITY_SOURCE_LOADERS = (
    _load_case_items,
    _load_audit_items,
    _load_voice_items,
    _load_warning_items,
    _load_reputation_items,
    _load_role_items,
    _load_note_items,
    _load_auto_voice_items,
)


@router.get("/guilds/{guild_id}/activity")
async def get_guild_activity(request: Request, guild_id: int):
    """Aggregated recent activity feed — cases, audit logs, voice sessions, warnings.

    Each item carries ``type``, ``category`` (moderation / messaging / voice /
    roles / reputation / notes / system), a human ``label``, and usernames
    resolved from the guild member cache when possible.
    """
    await get_module_min_role("moderation", guild_id)
    if not check_api_permission(request, "moderation.view", guild_id):
        return api_forbidden("Insufficient permissions")

    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    from database.engine import session_scope

    items: list[dict] = []
    async with session_scope() as session:
        for loader in ACTIVITY_SOURCE_LOADERS:
            items.extend(await loader(session, guild_id, guild))

    # Sort all by timestamp descending, take top 40
    items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return api_success({"activity": items[:40]})
