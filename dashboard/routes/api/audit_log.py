"""Audit log dashboard API — direct Discord audit log access."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request

from services.response import api_success, api_not_found, api_error

router = APIRouter(tags=["api-auditlog"])


@router.get("/guilds/{guild_id}/audit-log")
async def get_audit_log(request: Request, guild_id: int, limit: int = 50, category: str = ""):
    """Return guild audit log entries, optionally filtered by category."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    entries = []
    try:
        if guild.me.guild_permissions.view_audit_log:
            async for entry in guild.audit_logs(limit=limit, oldest_first=False):
                action_name = str(entry.action)
                entries.append({
                    "id": entry.id,
                    "action": action_name,
                    "user_id": str(entry.user.id) if entry.user else None,
                    "user_tag": str(entry.user) if entry.user else "Unknown",
                    "target_id": str(entry.target.id) if entry.target else None,
                    "reason": entry.reason or "",
                    "created_at": entry.created_at.isoformat(),
                })
    except Exception as e:
        return api_error(f"Audit log error: {e}")

    if category:
        entries = [e for e in entries if category in str(e.get("action", "")).lower()]

    return api_success({"entries": entries[:limit], "total": len(entries)})


@router.get("/guilds/{guild_id}/audit-log/summary")
async def get_audit_log_summary(request: Request, guild_id: int):
    """Return audit log summary counts by timeframe."""
    bot = request.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return api_not_found("Guild")

    entries = []
    try:
        if guild.me.guild_permissions.view_audit_log:
            async for entry in guild.audit_logs(limit=100, oldest_first=False):
                entries.append({
                    "action": str(entry.action),
                    "created_at": entry.created_at.isoformat(),
                })
    except Exception as e:
        return api_error(f"Audit log error: {e}")

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    recent_hour = [e for e in entries if e["created_at"] > hour_ago.isoformat()]
    recent_day = [e for e in entries if e["created_at"] > day_ago.isoformat()]

    # Count by action type
    by_action = {}
    for e in entries:
        act = e["action"]
        by_action[act] = by_action.get(act, 0) + 1

    return api_success({
        "last_hour": len(recent_hour),
        "last_24h": len(recent_day),
        "total": len(entries),
        "by_action": by_action,
        "recent": recent_day[:10],
    })
