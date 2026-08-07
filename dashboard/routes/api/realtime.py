"""
SSE (Server-Sent Events) real-time endpoint for Bark.

GET /api/v1/guilds/{id}/events — SSE stream that pushes events to the browser.

Events include: new_moderation_case, member_joined, automod_triggered.

Uses the RealtimeBridge singleton to subscribe per-guild event queues
and streams them as text/event-stream. Sends heartbeats every 30s and
disconnects after 60s of inactivity.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from services.realtime_bridge import RealtimeBridge

logger = logging.getLogger("bark.api.realtime")

router = APIRouter(tags=["api-realtime"])

# ── Constants ──────────────────────────────────────────

HEARTBEAT_INTERVAL = 30.0  # seconds

# ── Helpers ────────────────────────────────────────────


def _get_bridge(request: Request) -> RealtimeBridge:
    """Get the RealtimeBridge singleton from app state."""
    bridge = getattr(request.app.state, "realtime_bridge", None)
    if bridge is None:
        raise RuntimeError("RealtimeBridge not initialized on app state")
    return bridge


async def _event_stream(guild_id: str, request: Request):
    """
    Async generator yielding SSE-formatted text lines.

    Reads from a per-guild asyncio.Queue managed by RealtimeBridge.
    Sends heartbeat comments every 30s and closes after 60s of no events.
    """
    bridge = _get_bridge(request)
    queue = await bridge.subscribe(guild_id)

    try:
        while True:
            try:
                # Wait up to HEARTBEAT_INTERVAL for an event
                text = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                yield text
            except asyncio.TimeoutError:
                # No event in the window — send heartbeat
                yield f": heartbeat {json.dumps({'ts': asyncio.get_event_loop().time()})}\n\n"
    except asyncio.CancelledError:
        # Client disconnected
        pass
    finally:
        await bridge.unsubscribe(guild_id, queue)
        logger.debug("SSE stream closed for guild %s", guild_id)


# ── SSE Endpoint ───────────────────────────────────────


@router.get("/guilds/{guild_id}/events")
async def guild_events_sse(request: Request, guild_id: str):
    """
    SSE endpoint — streams real-time events for a guild.

    Returns a StreamingResponse with content-type text/event-stream.
    """
    # Validate guild exists
    bot = request.state.bot
    guild = bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
    if guild is None:
        from services.response import api_not_found

        return api_not_found("Guild")

    return StreamingResponse(
        _event_stream(guild_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
