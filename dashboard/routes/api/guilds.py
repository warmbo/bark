"""
Guilds API routes.
"""

import re
from datetime import datetime, timezone

import discord
from fastapi import APIRouter, Request, Response

from services.instance_auth import can_manage_instance
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


_CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([^:]+):(\d+)>$")


def _resolve_emoji(key: str) -> tuple[str, str | None]:
    """Turn a stored emoji key into (display label, CDN image URL).

    Custom emoji are persisted as ``<:name:id>`` (static) or ``<a:name:id>``
    (animated) from ``str(PartialEmoji)``. Resolve those to the emoji's name
    plus a Discord CDN image URL so the dashboard can render the actual emoji
    instead of showing the raw ``<:name:id>`` string. Unicode emoji are stored
    as their glyph character and return no URL (the glyph renders directly).
    """
    match = _CUSTOM_EMOJI_RE.match(key)
    if match:
        animated, name, emoji_id = match.group(1) == "a", match.group(2), match.group(3)
        ext = "gif" if animated else "png"
        return name, f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
    return key, None


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
            guild_ids = [row.guild_id for row in access]
            moderator_roles = await get_dashboard_moderator_roles(session, guild_ids)
            admin_roles = await get_dashboard_admin_role(session, guild_ids)
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

        settings = await get_settings(guild_id, "motd", "banner_url", "slug", "theme", "wallpaper_invert")
        motd = settings.get("motd", "")
        custom_banner_url = settings.get("banner_url", "")
        slug = settings.get("slug", "")
        theme = settings.get("theme", "") or "steel"
        wallpaper_invert = settings.get("wallpaper_invert", "0") == "1"
    except Exception:
        motd = ""
        custom_banner_url = ""
        slug = ""
        theme = "steel"
        wallpaper_invert = False

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
        "theme": theme,
        "wallpaper_invert": wallpaper_invert,
        "scheduled_events": scheduled_events,
    }



@router.put("/guilds/{guild_id}/banner")
async def set_guild_banner(request: Request, guild_id: int):
    """Set a custom banner image (URL) shown on the dashboard profile.

    The banner is readable by every dashboard role, but only admins may
    change it (see ``dashboard.banner`` capability).
    """
    if not check_api_permission(request, "dashboard.banner", guild_id):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    url = str((body or {}).get("banner_url") or "").strip()[:2000]

    from services.guild_settings import set_setting

    await set_setting(guild_id, "banner_url", url)
    return api_success({"banner_url": url})


@router.get("/guilds/{guild_id}/diagnostics")
async def guild_diagnostics(request: Request, guild_id: int):
    """Focused diagnostic report for ONE server (owner or guild admin).

    Unlike the instance-wide download, this is scoped to a single guild and is
    meant for "give me a report about this server" — it lists the guild's
    identity, our permission summary, every enabled module's self-reported
    health (via each module's ``diagnose()`` hook, e.g. Reputation flagging that
    it shares the server with another Bark instance), and any multi-instance
    conflicts. Secrets/message content are never included.

    Gated to instance owners (``can_manage_instance``) or guild admins
    (``guild.manage``) — the same bar as other sensitive guild settings.
    """
    if not (
        can_manage_instance(request)
        or check_api_permission(request, "guild.manage", guild_id)
    ):
        return api_forbidden("Owner or guild admin access required")

    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        return api_error("Bot is not running", status_code=503)

    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild not found or bot is not a member")

    from services.diagnostics import render_report

    # Build a focused, guild-scoped runtime report.
    modules_mgr = getattr(bot, "modules", None)
    lines: list[str] = []
    lines.append(f"Bark guild diagnostic report — guild {guild_id}")
    lines.append("=" * 60)
    lines.append(f"Guild        : {getattr(guild, 'name', None)} ({guild_id})")
    lines.append(f"Members      : {getattr(guild, 'member_count', None)}")
    lines.append(f"Owner ID     : {getattr(guild, 'owner_id', '') or '(unknown)'}")
    me = getattr(guild, "me", None) or getattr(bot, "user", None)
    perms = getattr(me, "guild_permissions", None) if me is not None else None
    if perms is not None:
        lines.append(
            "Our perms    : "
            + ", ".join(p for p in dir(perms) if not p.startswith("_") and getattr(perms, p) is True)
        )
    # Other Bark-like bots sharing this server.
    self_id = getattr(getattr(bot, "user", None), "id", None)
    others = []
    members = getattr(guild, "members", None) or getattr(guild, "users", None) or []
    for member in members:
        if not getattr(member, "bot", getattr(member, "bot", False)):
            continue
        uid = getattr(member, "id", None)
        uname = getattr(member, "name", "") or ""
        if uid == self_id or "bark" not in uname.lower():
            continue
        others.append({"id": str(uid), "name": uname, "bot": True})
    if others:
        lines.append(f"⚠ OTHER BARK INSTANCES IN THIS SERVER: {others}")
        lines.append(
            "  Modules that post to channels (Reputation showoff/leaderboard, "
            "Welcome, Logging) may double-post, double-count, or suppress output."
        )
    lines.append("")
    lines.append("[Enabled modules — self-reported health]")
    if modules_mgr is not None:
        try:
            enabled = [
                name
                for name in (modules_mgr.get_all_modules() or {})
                if modules_mgr.is_enabled_for_guild(int(guild_id), name)
            ]
        except Exception:
            enabled = []
        if not enabled:
            lines.append("  (no modules enabled)")
        for name in enabled:
            module = modules_mgr.get_module(name)
            if module is None:
                continue
            lines.append(f"- {name}")
            try:
                rep = await module.diagnose(int(guild_id))
                # Render the structured report compactly.
                text = render_report({"runtime": {"modules": {"items": [{"name": name, "version": getattr(module, "version", None), "enabled_globally": None, "commands": [], "events": [], "dashboard_pages": [], "permissions": [], "per_guild": [{"guild_id": str(guild_id), "report": rep}]}]}, "guilds": {"count": 0, "items": []}, "multi_instance_conflicts": []}})
                # The render puts the module block under [Modules]; trim to just
                # the per-guild lines for readability.
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("guild ") or "OTHER BARK" in stripped or stripped.startswith("⚠") or stripped.startswith("config:") or stripped.startswith("showoff") or stripped.startswith("score_activity") or stripped.startswith("status="):
                        lines.append(f"    {stripped}")
                    elif "double-count" in stripped:
                        lines.append(f"    {stripped}")
            except Exception as exc:
                lines.append(f"    diagnose error: {type(exc).__name__}: {exc}")
    lines.append("")
    lines.append("--- end of guild report ---")
    return Response(
        content="\n".join(lines),
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="bark-guild-{guild_id}-diagnostics.txt"'
        },
    )


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
    # The slug caches (resolve + manifest) must not serve the old mapping for
    # the next TTL window.
    from services.slug_router import invalidate_slug_cache

    invalidate_slug_cache()
    return api_success({"slug": slug, "url": f"/g/{slug}" if slug else None})


# Valid accent themes for the per-guild theme picker.
VALID_THEMES = {
    "steel", "emerald", "violet", "amber", "rose", "cyan", "teal", "orange",
    "synth", "acid", "rottweiler", "dracula", "gold", "hud",
    "aurora", "neon", "ocean", "sunset", "forest", "candy", "slate", "crimson", "honey", "deepspace", "graffiti",
}


@router.put("/guilds/{guild_id}/theme")
async def set_guild_theme(request: Request, guild_id: int):
    """Set a per-guild accent theme (e.g. /guild/{id} renders with it)."""
    if getattr(request.state, "guild_viewer", False):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    theme = str((body or {}).get("theme") or "").strip().lower()

    if theme not in VALID_THEMES:
        return api_error(
            f"Unknown theme '{theme}'. Valid themes: {', '.join(sorted(VALID_THEMES))}.",
            status_code=400,
        )

    from services.guild_settings import set_setting

    await set_setting(guild_id, "theme", theme)
    return api_success({"theme": theme})


@router.put("/guilds/{guild_id}/wallpaper_invert")
async def set_guild_wallpaper_invert(request: Request, guild_id: int):
    """Set whether this server's wallpaper is shown inverted (light-mode negative)."""
    if getattr(request.state, "guild_viewer", False):
        return api_forbidden("Insufficient permissions")

    body = await request.json()
    invert = bool((body or {}).get("invert", False))

    from services.guild_settings import set_setting

    await set_setting(guild_id, "wallpaper_invert", "1" if invert else "0")
    return api_success({"wallpaper_invert": invert})


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

    # Today's date in UTC — the daily stats tables are keyed on it.
    from database.engine import session_scope
    from services.stats_recorder import _today_aware

    today = _today_aware()
    async with session_scope() as session:
        growth_30d = await _guild_growth_30d(session, guild_id)
        growth_series = await _guild_growth_series(session, guild_id, days=30)
        # The daily channel/emoji tables are the source of truth — written on
        # every message/reaction, so the DB builds knowledge over time and
        # always has data (even right after a bot restart).
        db_ch_7d, db_emoji_all = await _snapshot_channel_emoji_totals(session, guild_id, 7)
        db_ch_30d, _ = await _snapshot_channel_emoji_totals(session, guild_id, 30)
        # Today's per-channel counts (exact date — a 1-day window still spans
        # two dates).
        db_ch_today = await _daily_channel_for_day(session, guild_id, today)
        # Today's per-emoji counts.
        today_emoji_rows = await _daily_emoji_for_day(session, guild_id, today)
        # Engagement / activity time-series from data that accumulates over time.
        reputation_series = _zero_fill_series(
            await _reputation_daily_counts(session, guild_id, 30), 30
        )
        audit_series = _zero_fill_series(
            await _audit_daily_counts(session, guild_id, 30), 30
        )
        voice_series = _zero_fill_series(
            await _voice_daily_counts(session, guild_id, 30), 30
        )
        new_members_series = _zero_fill_series(
            await _new_members_daily(session, guild_id, 30), 30
        )
        popular_games = await _popular_games(session, guild_id, days=30)
        top_voice_users = await _top_voice_users(session, guild, days=30)
        reputation_by_type = await _reputation_by_type(session, guild_id)
        top_reputation = await _top_reputation(session, guild)
    online, in_voice = _online_and_voice_counts(guild)

    def _top(d: dict) -> list[dict]:
        rows = []
        for k, v in d.items():
            label, url = _resolve_emoji(k)
            row = {"name": label, "count": v}
            if url:
                row["emoji_url"] = url
            rows.append(row)
        return sorted(rows, key=lambda x: x["count"], reverse=True)[:8]

    channels_today = sorted(db_ch_today.values(), key=lambda c: c["count"], reverse=True)[:8]
    emojis_today = _top(today_emoji_rows)
    top_channels_7d = sorted(db_ch_7d.values(), key=lambda c: c["count"], reverse=True)[:8]
    top_channels_30d = sorted(db_ch_30d.values(), key=lambda c: c["count"], reverse=True)[:8]
    emojis_all_time = _top(db_emoji_all)
    messages_today = sum(c["count"] for c in db_ch_today.values())

    # Resolve live channel names for rows backfilled without one (the migration
    # has no Discord context, so names come from the guild now).
    def _with_channel_names(channels: list[dict]) -> list[dict]:
        id_to_name = {}
        try:
            for ch in getattr(guild, "channels", []) or []:
                if getattr(ch, "id", None):
                    id_to_name[str(ch.id)] = getattr(ch, "name", None) or ""
        except Exception:
            id_to_name = {}
        out = []
        for c in channels:
            cid = str(c.get("channel_id") or c.get("id") or "")
            name = c.get("name") or id_to_name.get(cid, "")
            if not name:
                continue  # skip unresolved (deleted) channels
            out.append({"name": name, "count": c["count"]})
        return out

    channels_today = _with_channel_names(channels_today)
    top_channels_7d = _with_channel_names(top_channels_7d)
    top_channels_30d = _with_channel_names(top_channels_30d)

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
            "messages_today": messages_today,
            "top_channels_today": channels_today,
            "top_channels_7d": top_channels_7d,
            "top_channels_30d": top_channels_30d,
            "top_emojis_today": emojis_today,
            "top_emojis_all_time": emojis_all_time,
            "reputation_series": reputation_series,
            "audit_series": audit_series,
            "voice_series": voice_series,
            "new_members_series": new_members_series,
            "popular_games": popular_games,
            "top_voice_users": top_voice_users,
            "reputation_by_type": reputation_by_type,
            "top_reputation": top_reputation,
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
    trailing ``days`` from the persisted daily stats tables.

    Returns ``(channels, emoji_total)`` where ``channels`` maps channel_id ->
    {"name": str, "count": int} and ``emoji_total`` maps emoji name -> count.
    This is the source of truth for the Statistics page: every message and
    reaction upserts these rows, so the DB always has data (even right after a
    bot restart) and builds knowledge about the server over time.
    """
    from datetime import date, timedelta

    from sqlalchemy import select

    from database.models.analytics import DailyChannelStat, DailyEmojiStat

    since = date.today() - timedelta(days=max(1, days))
    channels: dict[str, dict] = {}
    ch_result = await session.execute(
        select(DailyChannelStat).where(
            DailyChannelStat.guild_id == str(guild_id),
            DailyChannelStat.stat_date >= since,
        )
    )
    for row in ch_result.scalars().all():
        if row.message_count <= 0:
            continue
        agg = channels.setdefault(row.channel_id, {"channel_id": row.channel_id, "name": "", "count": 0})
        agg["count"] += row.message_count
        agg["name"] = row.channel_name or agg["name"]

    emoji_total: dict[str, int] = {}
    em_result = await session.execute(
        select(DailyEmojiStat).where(
            DailyEmojiStat.guild_id == str(guild_id),
            DailyEmojiStat.stat_date >= since,
        )
    )
    for row in em_result.scalars().all():
        if row.count > 0:
            emoji_total[row.emoji_name] = emoji_total.get(row.emoji_name, 0) + row.count
    return channels, emoji_total


async def _daily_channel_for_day(session, guild_id: int, day) -> dict[str, dict]:
    """Return channel_id -> {name, count} for a single day from daily stats."""
    from sqlalchemy import select

    from database.models.analytics import DailyChannelStat

    result = await session.execute(
        select(DailyChannelStat).where(
            DailyChannelStat.guild_id == str(guild_id),
            DailyChannelStat.stat_date == day,
        )
    )
    channels: dict[str, dict] = {}
    for row in result.scalars().all():
        if row.message_count > 0:
            channels[row.channel_id] = {"channel_id": row.channel_id, "name": row.channel_name, "count": row.message_count}
    return channels


async def _daily_emoji_for_day(session, guild_id: int, day) -> dict[str, int]:
    """Return emoji -> count for a single day from the daily emoji stats table."""
    from sqlalchemy import select

    from database.models.analytics import DailyEmojiStat

    result = await session.execute(
        select(DailyEmojiStat).where(
            DailyEmojiStat.guild_id == str(guild_id),
            DailyEmojiStat.stat_date == day,
        )
    )
    return {row.emoji_name: row.count for row in result.scalars().all() if row.count > 0}


def _zero_fill_series(
    counts: dict[str, int], days: int
) -> list[dict]:
    """Expand a {date_iso: count} map into a continuous N-day series with zeros
    so charts always draw a full axis instead of sparse points."""
    from datetime import date, timedelta

    out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = date.today() - timedelta(days=i)
        out.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
    return out


async def _reputation_daily_counts(session, guild_id: int, days: int) -> dict[str, int]:
    """Reputation credit events per day over the trailing window."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.reputation import ReputationEvent

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(
            func.date(ReputationEvent.created_at).label("day"),
            func.count(ReputationEvent.id),
        )
        .where(
            ReputationEvent.guild_id == str(guild_id),
            ReputationEvent.created_at >= since,
        )
        .group_by(func.date(ReputationEvent.created_at))
    )
    return {day: count for day, count in result.all()}


async def _reputation_by_type(session, guild_id: int) -> list[dict]:
    """Reputation credit totals broken down by event type (pie chart)."""
    from sqlalchemy import func, select

    from database.models.reputation import ReputationEvent

    result = await session.execute(
        select(
            ReputationEvent.event_type,
            func.sum(ReputationEvent.points).label("points"),
        )
        .where(ReputationEvent.guild_id == str(guild_id))
        .group_by(ReputationEvent.event_type)
    )
    labels = {
        "message": "Messages",
        "reaction": "Reactions",
        "emoji": "Emojis",
        "thanks": "Thanks",
        "voice_minute": "Voice",
    }
    return [
        {"name": labels.get(et, et), "count": int(points or 0)}
        for et, points in result.all()
        if points
    ]


async def _audit_daily_counts(session, guild_id: int, days: int) -> dict[str, int]:
    """Audit-log (moderation/system) events per day over the trailing window."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.moderation import AuditLog

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(func.date(AuditLog.created_at).label("day"), func.count(AuditLog.id))
        .where(
            AuditLog.guild_id == str(guild_id),
            AuditLog.created_at >= since,
        )
        .group_by(func.date(AuditLog.created_at))
    )
    return {day: count for day, count in result.all()}


async def _voice_daily_counts(session, guild_id: int, days: int) -> dict[str, int]:
    """Voice session joins per day over the trailing window."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.voice import VoiceSession

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(func.date(VoiceSession.joined_at).label("day"), func.count(VoiceSession.id))
        .where(
            VoiceSession.guild_id == str(guild_id),
            VoiceSession.joined_at >= since,
        )
        .group_by(func.date(VoiceSession.joined_at))
    )
    return {day: count for day, count in result.all()}


async def _new_members_daily(session, guild_id: int, days: int) -> dict[str, int]:
    """New members joined per day from member snapshots."""
    from datetime import date, timedelta

    from sqlalchemy import select

    from database.models.analytics import ActivitySnapshot

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(ActivitySnapshot.snapshot_date, ActivitySnapshot.new_members).where(
            ActivitySnapshot.guild_id == str(guild_id),
            ActivitySnapshot.snapshot_date >= since,
        )
    )
    return {d.isoformat(): int(n or 0) for d, n in result.all() if n}


async def _popular_games(session, guild_id: int, days: int = 30, limit: int = 8) -> list[dict]:
    """Most-recorded games on managed voice channels over the trailing window."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.analytics import VoiceGameStat

    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(
            VoiceGameStat.game_name,
            func.count(VoiceGameStat.id).label("count"),
        )
        .where(
            VoiceGameStat.guild_id == str(guild_id),
            VoiceGameStat.recorded_at >= since,
        )
        .group_by(VoiceGameStat.game_name)
        .order_by(func.count(VoiceGameStat.id).desc())
        .limit(limit)
    )
    return [{"name": name, "count": count} for name, count in result.all() if count]


async def _top_voice_users(session, guild, days: int = 30, limit: int = 8) -> list[dict]:
    """Members with the most voice time (in minutes) over the trailing window."""
    from datetime import date, timedelta

    from sqlalchemy import func, select

    from database.models.voice import VoiceSession

    guild_id = int(guild.id)
    since = date.today() - timedelta(days=days)
    result = await session.execute(
        select(
            VoiceSession.user_id,
            VoiceSession.user_tag,
            func.sum(VoiceSession.duration_seconds).label("seconds"),
            func.count(VoiceSession.id).label("sessions"),
        )
        .where(
            VoiceSession.guild_id == str(guild_id),
            VoiceSession.duration_seconds.is_not(None),
            VoiceSession.joined_at >= since,
        )
        .group_by(VoiceSession.user_id, VoiceSession.user_tag)
        .order_by(func.sum(VoiceSession.duration_seconds).desc())
        .limit(limit)
    )
    out = []
    for uid, tag, seconds, sessions in result.all():
        minutes = int((seconds or 0) // 60)
        if minutes > 0:
            member = None
            if guild:
                try:
                    member = guild.get_member(int(uid)) if hasattr(guild, "get_member") else None
                except (ValueError, TypeError):
                    member = None
            display = str(getattr(member, "display_name", None) or tag or uid)
            avatar = None
            if member is not None and getattr(member, "display_avatar", None):
                avatar = member.display_avatar.url
            out.append({"name": display, "id": str(uid), "avatar_url": avatar, "count": minutes, "sessions": int(sessions or 0)})
    return out


async def _top_reputation(session, guild, limit: int = 8) -> list[dict]:
    """Top reputation profiles by total score (leaderboard snapshot)."""
    from sqlalchemy import select

    from database.models.reputation import ReputationProfile

    guild_id = int(guild.id)
    result = await session.execute(
        select(
            ReputationProfile.user_id,
            ReputationProfile.total_score,
        )
        .where(ReputationProfile.guild_id == str(guild_id))
        .order_by(ReputationProfile.total_score.desc())
        .limit(limit)
    )
    out = []
    for uid, score in result.all():
        if not score:
            continue
        member = None
        if guild:
            try:
                member = guild.get_member(int(uid)) if hasattr(guild, "get_member") else None
            except (ValueError, TypeError):
                member = None
        display = str(getattr(member, "display_name", None) or uid)
        avatar = None
        if member is not None and getattr(member, "display_avatar", None):
            avatar = member.display_avatar.url
        out.append({"name": display, "id": str(uid), "avatar_url": avatar, "count": int(score or 0)})
    return out




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

    # Live panel data: who's online/on voice, boost progress, and the emoji
    # wall. Never let any of these crash the overview page.
    live = _dashboard_live_data(guild)
    return api_success(
        {
            "viewer": viewer,
            "guild": profile,
            "cards": cards,
            "modules": modules,
            **live,
        }
    )


def _member_brief(member) -> dict:
    """Small, JSON-safe profile for an online/voice member.

    Every field is str-coerced and exception-guarded so a mock or a member with
    a partial/unresolved attribute can NEVER leak a non-JSON-serializable object
    (e.g. a MagicMock display_name) into the dashboard payload — that would 500
    the whole overview page (hit live on the test server: `Object of type
    MagicMock is not JSON serializable`).
    """
    def _safe_str(value, fallback: str) -> str:
        try:
            v = str(value).strip()
            return v if v and "MagicMock" not in v else fallback
        except Exception:
            return fallback

    try:
        _avatar = getattr(member, "display_avatar", None)
        avatar = getattr(_avatar, "url", None) if _avatar else None
        avatar = _safe_str(avatar, "") if avatar else None
    except Exception:
        avatar = None
    try:
        status = str(getattr(member, "status", None) or "offline").split(".")[-1]
        if status not in ("online", "idle", "dnd", "offline"):
            status = "offline"
    except Exception:
        status = "offline"
    return {
        "id": _safe_str(getattr(member, "id", ""), ""),
        "name": _safe_str(
            getattr(member, "display_name", None) or getattr(member, "name", ""),
            "Unknown",
        ),
        "avatar_url": avatar,
        "status": status,
    }


def _dashboard_live_data(guild) -> dict:
    """Assemble the 'live' overview panels (online presence, voice, boost,
    emoji wall). Defensive: any failure in a single member/channel never 500s
    the dashboard."""
    # ── Online presence ────────────────────────────────────────────────
    presence_counts = {"online": 0, "idle": 0, "dnd": 0, "offline": 0}
    online_members: list[dict] = []
    try:
        members = list(getattr(guild, "members", []) or [])
    except Exception:
        members = []
    for member in members:
        try:
            status = str(getattr(member, "status", None) or discord.Status.offline).split(".")[-1]
        except Exception:
            status = "offline"
        if status not in presence_counts:
            status = "offline"
        presence_counts[status] += 1
        if status != "offline" and len(online_members) < 100:
            online_members.append(_member_brief(member))

    # ── Voice channels (Discord-embed style: channel -> members) ───────
    voice: list[dict] = []
    try:
        for channel in getattr(guild, "voice_channels", []) or []:
            channel_members = []
            try:
                channel_members = list(getattr(channel, "members", []) or [])
            except Exception:
                channel_members = []
            if not channel_members:
                continue
            voice.append(
                {
                    "id": str(getattr(channel, "id", "")),
                    "name": str(getattr(channel, "name", "") or "Voice"),
                    "members": [_member_brief(m) for m in channel_members[:50]],
                }
            )
    except Exception:
        voice = []

    online_total = presence_counts["online"] + presence_counts["idle"] + presence_counts["dnd"]

    # ── Emoji wall ─────────────────────────────────────────────────────
    emojis = []
    try:
        for emoji in getattr(guild, "emojis", []) or []:
            try:
                url = getattr(emoji, "url", None) or None
                animated = bool(getattr(emoji, "animated", False))
            except Exception:
                url, animated = None, False
            if url and isinstance(url, str):
                emojis.append(
                    {
                        "id": str(getattr(emoji, "id", "") or ""),
                        "name": str(getattr(emoji, "name", "") or "emoji"),
                        "url": url,
                        "animated": animated,
                    }
                )
    except Exception:
        emojis = []

    # ── Quick commands + role spotlight were removed as front-page panels
    # (2026-08-21, Cody: "Quick Commands seems useless. Roles is useless.").
    # The enabled-modules summary above still carries command metadata for the
    # Modules page; we simply don't surface a dedicated front-page launcher.

    return {
        "presence": {
            "total": online_total,
            "online": presence_counts["online"],
            "idle": presence_counts["idle"],
            "dnd": presence_counts["dnd"],
            "offline": presence_counts["offline"],
            "members": online_members,
        },
        "voice": voice,
        "emojis": emojis,
    }


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


@router.get("/guilds/{guild_id}/emojis")
async def list_guild_emojis(request: Request, guild_id: int):
    """Return the server's custom emojis for use in composers (e.g. the
    Announcements message box). Any member of the server may read them — the
    same visibility the dashboard already exposes via the emoji wall."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    emojis = []
    try:
        for emoji in getattr(guild, "emojis", []) or []:
            try:
                url = str(getattr(emoji, "url", "") or "")
                animated = bool(getattr(emoji, "animated", False))
            except Exception:
                url, animated = "", False
            if url:
                emojis.append(
                    {
                        "id": str(getattr(emoji, "id", "") or ""),
                        "name": str(getattr(emoji, "name", "") or "emoji"),
                        "url": url,
                        "animated": animated,
                    }
                )
    except Exception:
        emojis = []
    emojis.sort(key=lambda e: e["name"].lower())
    return api_success({"emojis": emojis})
