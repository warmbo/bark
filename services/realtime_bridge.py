"""
RealtimeBridge — subscribes to EventBus and broadcasts to SSE connections.

Maintains a dict of guild_id → list of asyncio.Queue for live push
to dashboard SSE endpoints. Modules emit events through the EventBus;
this bridge catches them and fans them out to browser connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from services.event_bus import EventBus

logger = logging.getLogger("bark.realtime_bridge")

# ── Event type mapping ────────────────────────────────
# Map EventBus event names → SSE event names with payload extractors
EVENT_MAP: dict[str, tuple[str, callable]] = {
    # Moderation events
    "moderation_case_created": (
        "new_moderation_case",
        lambda **kw: {
            "case_id": kw.get("case_id", 0),
            "action_type": kw.get("action_type", "unknown"),
            "target_tag": kw.get("target_tag", "Unknown"),
            "moderator_tag": kw.get("moderator_tag", "Unknown"),
            "reason": kw.get("reason", ""),
            "guild_id": str(kw.get("guild_id", "")),
        },
    ),
    # Discord member join bridged from bot/client.py
    "discord_member_join": (
        "member_joined",
        lambda **kw: {
            "user_id": str(getattr(kw.get("member"), "id", "")),
            "tag": str(getattr(kw.get("member"), "name", "Unknown")),
            "display_name": getattr(kw.get("member"), "display_name", "Unknown"),
            "guild_id": str(getattr(getattr(kw.get("member"), "guild", None), "id", "")),
        },
    ),
    # Automod triggers
    "automod_triggered": (
        "automod_triggered",
        lambda **kw: {
            "rule": kw.get("rule", "unknown"),
            "action": kw.get("action", "none"),
            "user_tag": kw.get("user_tag", "Unknown"),
            "content": kw.get("content", ""),
            "guild_id": str(kw.get("guild_id", "")),
        },
    ),
}



class RealtimeBridge:
    """
    Bridges EventBus events to SSE browser connections.

    Usage:
        bridge = RealtimeBridge(event_bus)
        await bridge.start()

        # SSE handler subscribes:
        queue = await bridge.subscribe(guild_id)
        # ... read from queue in StreamingResponse ...

        # Cleanup:
        await bridge.unsubscribe(guild_id, queue)
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        # guild_id (str) → list[asyncio.Queue]
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._running = False

    # ── Lifecycle ────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to all mapped EventBus events."""
        if self._running:
            return
        self._running = True
        for event_name in EVENT_MAP:
            self._event_bus.subscribe(event_name, self._on_event, priority=200)
        logger.info(
            "RealtimeBridge started — subscribed to %d event types",
            len(EVENT_MAP),
        )

    async def stop(self) -> None:
        """Unsubscribe from all events and clear queues."""
        if not self._running:
            return
        self._running = False
        for event_name in EVENT_MAP:
            self._event_bus.unsubscribe(event_name, self._on_event)
        async with self._lock:
            self._queues.clear()
        logger.info("RealtimeBridge stopped")

    # ── SSE connection management ────────────────────

    async def subscribe(self, guild_id: str) -> asyncio.Queue:
        """
        Open a new SSE queue for a guild.

        Returns an asyncio.Queue that receives formatted SSE event dicts.
        The caller should read from it in a loop and disconnect on
        asyncio.TimeoutError or None sentinel.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._queues.setdefault(str(guild_id), []).append(queue)
        logger.debug("SSE client subscribed to guild %s (%d total)", guild_id, len(self._queues[str(guild_id)]))
        return queue

    async def unsubscribe(self, guild_id: str, queue: asyncio.Queue) -> None:
        """Remove a queue from the guild's subscriber list."""
        gid = str(guild_id)
        async with self._lock:
            queues = self._queues.get(gid, [])
            if queue in queues:
                queues.remove(queue)
                logger.debug("SSE client unsubscribed from guild %s (%d remaining)", gid, len(queues))
            if not queues:
                self._queues.pop(gid, None)

    def subscriber_count(self, guild_id: str) -> int:
        """Number of active SSE connections for a guild."""
        return len(self._queues.get(str(guild_id), []))

    # ── Event handler ────────────────────────────────

    async def _on_event(self, event_type: str, **data: Any) -> None:
        """
        Handle an EventBus event — format it and push to all listening SSE queues.

        Extracts guild_id from the event data to fan out to the right subscribers.
        """
        mapping = EVENT_MAP.get(event_type)
        if mapping is None:
            return

        sse_event_name, extractor = mapping
        payload = extractor(**data)
        guild_id = payload.get("guild_id", "")

        if not guild_id:
            # Try to infer guild_id from member object
            member = data.get("member")
            if member and hasattr(member, "guild") and member.guild:
                guild_id = str(member.guild.id)
                payload["guild_id"] = guild_id
            else:
                return  # Can't route without a guild_id

        sse_message = {
            "event": sse_event_name,
            "data": payload,
        }

        async with self._lock:
            queues = list(self._queues.get(guild_id, []))

        if not queues:
            return

        text = f"event: {sse_event_name}\ndata: {json.dumps(payload)}\n\n"

        for queue in queues:
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                logger.warning("Queue full for guild %s — dropping event %s", guild_id, sse_event_name)
