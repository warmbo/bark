"""
Health and diagnostics API endpoint.

Provides comprehensive system health reporting:
- Module health (enabled/disabled, uptime)
- Database connection health
- Bot connection status
- Guild summary
- Version info
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import text

from services.response import api_success

router = APIRouter(tags=["api-health"])
logger = logging.getLogger("bark.api.health")

_start_time = datetime.now(timezone.utc)


@router.get("/health")
async def health_check(request: Request):
    """Comprehensive system health check.

    This endpoint is public (used by uptime monitors), so it deliberately
    exposes no per-guild or per-module internals: no bot username, no guild
    count, no module inventory or versions.
    """
    bot = request.state.bot

    # Bot status
    bot_ready = bot.is_ready() if hasattr(bot, "is_ready") else False
    bot_connected = bot.is_connected() if hasattr(bot, "is_connected") else bot_ready

    # Database health
    db_healthy = False
    try:
        from database.engine import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            db_healthy = True
    except Exception as exc:
        logger.warning("Database health check failed (%s)", type(exc).__name__)

    uptime_seconds = int((datetime.now(timezone.utc) - _start_time).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return api_success(
        {
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
            },
            "database": {
                "healthy": db_healthy,
                "status": "connected" if db_healthy else "unavailable",
            },
        }
    )
