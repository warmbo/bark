"""
Health and diagnostics API endpoint.

Provides comprehensive system health reporting:
- Module health (enabled/disabled, uptime)
- Database connection health
- Bot connection status
- Guild summary
- Version info
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import text

from services.response import api_success

router = APIRouter(tags=["api-health"])

_start_time = datetime.now(timezone.utc)


@router.get("/health")
async def health_check(request: Request):
    """Comprehensive system health check."""
    bot = request.state.bot

    # Bot status
    bot_ready = bot.is_ready() if hasattr(bot, "is_ready") else False
    bot_connected = bot.is_connected() if hasattr(bot, "is_connected") else bot_ready

    # Module health
    modules = {}
    if bot_ready:
        try:
            for name, module in bot.modules.get_all_modules().items():
                modules[name] = {
                    "version": module.version,
                    "enabled": module.enabled,
                    "commands": len(module.get_commands()),
                    "events": len(module.get_events()),
                    "settings": bool(module.get_settings_schema()),
                    "actions": len(module.get_actions()) if hasattr(module, "get_actions") else 0,
                }
        except Exception as e:
            modules = {"error": str(e)}

    # Database health
    db_healthy = False
    try:
        from database.engine import get_engine
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_healthy = True
    except Exception as e:
        db_healthy = str(e)

    uptime_seconds = int((datetime.now(timezone.utc) - _start_time).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return api_success({
        "status": "healthy" if (bot_ready and db_healthy) else "degraded",
        "version": getattr(request.app.state, "version", "unknown"),
        "uptime": {
            "seconds": uptime_seconds,
            "display": f"{hours}h {minutes}m {seconds}s",
            "started_at": _start_time.isoformat(),
        },
        "bot": {
            "connected": bot_connected,
            "ready": bot_ready,
            "guilds": len(bot.guilds) if bot_ready else 0,
            "user": str(bot.user) if bot_ready and bot.user else None,
        },
        "database": {
            "healthy": db_healthy if isinstance(db_healthy, bool) else False,
            "status": "connected" if db_healthy is True else f"error: {db_healthy}",
        },
        "modules": {
            "total": len(modules),
            "enabled": sum(1 for m in modules.values() if m.get("enabled")),
            "list": modules,
        },
        "memory": {
            "total_events": len(bot.modules.event_bus.event_types) if hasattr(bot, "modules") else 0,
        },
    })
