"""Audit log dashboard API — direct Discord audit log access."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

from services.response import api_error, api_not_found, api_success

router = APIRouter(tags=["api-auditlog"])


@router.get("/guilds/{guild_id}/audit-log")
async def get_audit_log(
    request: Request,
    guild_id: int,
    limit: int = Query(50, ge=1, le=100),
    category: str = Query("", max_length=64),
):
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
                entries.append(
                    {
                        "id": entry.id,
                        "action": action_name,
                        "user_id": str(entry.user.id) if entry.user else None,
                        "user_tag": str(entry.user) if entry.user else "Unknown",
                        "target_id": str(entry.target.id) if entry.target else None,
                        "reason": entry.reason or "",
                        "created_at": entry.created_at.isoformat(),
                    }
                )
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
                entries.append(
                    {
                        "action": str(entry.action),
                        "created_at": entry.created_at.isoformat(),
                    }
                )
    except Exception as e:
        return api_error(f"Audit log error: {e}")

    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    recent_hour = [entry for entry in entries if entry["created_at"] > hour_ago.isoformat()]
    recent_day = [entry for entry in entries if entry["created_at"] > day_ago.isoformat()]

    # Count by action type
    by_action: dict[str, int] = {}
    for entry in entries:
        act = entry["action"]
        by_action[act] = by_action.get(act, 0) + 1

    return api_success(
        {
            "last_hour": len(recent_hour),
            "last_24h": len(recent_day),
            "total": len(entries),
            "by_action": by_action,
            "recent": recent_day[:10],
        }
    )
