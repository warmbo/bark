"""
SSE (Server-Sent Events) real-time endpoint for Bark.

GET /api/v1/guilds/{id}/events — SSE stream that pushes events to the browser.

Events include: new_moderation_case, member_joined, automod_triggered.

Uses the RealtimeBridge singleton to subscribe per-guild event queues
and streams them as text/event-stream. Sends heartbeats every 30s.

Authorization is checked when the stream opens (moderation.view, like the
activity feed — the stream carries moderation reasons and flagged message
content) and then REVALIDATED every ``AUTH_REVALIDATE_INTERVAL`` seconds
against current DB membership/capability state, on its own timer that runs
regardless of event flow. When the grant is gone — a staff role removed, the
user removed from the server, or the bot kicked from the guild — the stream
emits an ``access_revoked`` event and closes, so revoked access stops
promptly even on a busy stream instead of streaming on with the role the
user had when they connected.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from services.realtime_bridge import RealtimeBridge

logger = logging.getLogger("bark.api.realtime")

router = APIRouter(tags=["api-realtime"])

# ── Constants ──────────────────────────────────────────

HEARTBEAT_INTERVAL = 30.0  # seconds
# How often a live stream re-derives the client's authorization from the DB.
# Kept at the heartbeat cadence: one timer, bounded 30s staleness for a
# revoked grant (busy or idle stream alike).
AUTH_REVALIDATE_INTERVAL = 30.0  # seconds

# Sentinel placed on the stream's own queue by the auth watcher when the
# revalidation fails; the reader closes the stream on sight.
_REVOKED = object()

# The per-guild queues are bounded and lossy (the bridge drops events with
# put_nowait when full), so the revocation signal can never be delivered
# *only* through the queue: on a full queue the watcher sets this flag
# instead, and the reader checks it before every item it would yield.
# Revocation must outrank queued events — one extra event after a revoke is
# acceptable, an unbounded tail of stale sensitive data is not.


# ── Helpers ────────────────────────────────────────────


def _get_bridge(request: Request) -> RealtimeBridge:
    """Get the RealtimeBridge singleton from app state."""
    bridge = getattr(request.app.state, "realtime_bridge", None)
    if bridge is None:
        raise RuntimeError("RealtimeBridge not initialized on app state")
    return bridge


async def _event_stream(guild_id: str, request: Request, user_id: str):
    """
    Async generator yielding SSE-formatted text lines.

    Reads from a per-guild asyncio.Queue managed by RealtimeBridge and sends
    heartbeat comments every HEARTBEAT_INTERVAL. A separate auth watcher task
    re-derives the client's permission from fresh DB state every
    AUTH_REVALIDATE_INTERVAL — independently of event flow, so a busy stream
    still stops promptly once access is revoked.
    """
    bridge = _get_bridge(request)
    queue = await bridge.subscribe(guild_id)

    # Set by the auth watcher when the grant is gone AND the queue was too
    # full to hold the _REVOKED sentinel. The reader checks it before every
    # item it would yield, so a full/lossy queue can neither block the
    # watcher nor delay closure behind a long tail of queued events.
    revoked = asyncio.Event()

    async def _auth_watch() -> None:
        # Runs on its own cadence: a stream that is constantly receiving
        # events never hits the heartbeat timeout, so revalidation must not
        # piggyback on it or a busy stream would never re-check.
        try:
            while True:
                await asyncio.sleep(AUTH_REVALIDATE_INTERVAL)
                try:
                    from services.response import recheck_api_permission

                    ok = await recheck_api_permission(
                        request, "moderation.view", guild_id, user_id
                    )
                except Exception:
                    # recheck_api_permission is itself fail-closed, but a
                    # residual error (import/config/cache lookup) must not
                    # kill this task silently — that would leave the stream
                    # open with no revalidation at all. Fail closed: revoke.
                    logger.exception(
                        "Authorization recheck raised for user %s guild %s — "
                        "closing stream",
                        user_id,
                        guild_id,
                    )
                    ok = False
                if not ok:
                    # put_nowait: never block on a full queue. The sentinel is
                    # the fast path; a full queue falls back to the flag.
                    try:
                        queue.put_nowait(_REVOKED)
                    except asyncio.QueueFull:
                        revoked.set()
                    return
        except asyncio.CancelledError:
            pass

    watcher = asyncio.create_task(_auth_watch())
    try:
        while True:
            if revoked.is_set():
                # Authorization was revoked while the stream was open — tell
                # the client truthfully, then close instead of streaming on.
                yield 'event: access_revoked\ndata: {"reason": "authorization_revoked"}\n\n'
                break
            try:
                # Wait up to HEARTBEAT_INTERVAL for an event
                text = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # No event in the window — send heartbeat
                yield f": heartbeat {json.dumps({'ts': asyncio.get_event_loop().time()})}\n\n"
                continue
            if text is _REVOKED:
                yield 'event: access_revoked\ndata: {"reason": "authorization_revoked"}\n\n'
                break
            yield text
    except asyncio.CancelledError:
        # Client disconnected
        pass
    finally:
        watcher.cancel()
        # Join the watcher: an un-awaited cancelled task can linger ("Task was
        # destroyed but it is pending") and an un-retrieved exception from it
        # would log spuriously. suppress() so teardown during cancellation is
        # not itself cancelled.
        with suppress(asyncio.CancelledError):
            await watcher
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
    if not guild_id.isdigit():
        from services.response import api_not_found

        return api_not_found("Guild")
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        from services.response import api_not_found

        return api_not_found("Guild")

    # The SSE stream carries moderation reasons and flagged message content —
    # gate it like the activity feed (moderation.view), not just membership.
    from services.response import api_forbidden, check_api_permission

    if not check_api_permission(request, "moderation.view", guild_id):
        return api_forbidden("Insufficient permissions")

    # The stream outlives the request, so the connect-time role is not enough:
    # hold the user id for periodic revalidation against fresh DB state.
    user = request.session.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        return api_forbidden("Insufficient permissions")

    return StreamingResponse(
        _event_stream(guild_id, request, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
