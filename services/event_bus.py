"""
EventBus — internal event system for Bark.

All events (Discord events, moderation actions, module lifecycle)
flow through the EventBus. No module listens directly to Discord.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("bark.event_bus")


class EventBus:
    """
    Central event routing system.

    Modules subscribe to event types. The bus dispatches events to
    all subscribers. Supports async handlers, priority ordering,
    and wildcard subscriptions.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[int, Callable]]] = {}

    # ── Subscription ────────────────────────────────────

    def subscribe(self, event_type: str, handler: Callable, priority: int = 100) -> None:
        """
        Register an event handler.

        Args:
            event_type: Event name (e.g. 'message_create', 'voice_state_change')
            handler: Async callable receiving (event_type, data)
            priority: Lower runs first (default 100)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if any(existing == handler for _, existing in self._subscribers[event_type]):
            logger.debug("Skipped duplicate subscription to '%s'", event_type)
            return
        self._subscribers[event_type].append((priority, handler))
        self._subscribers[event_type].sort(key=lambda x: x[0])
        logger.debug("Subscribed to '%s' (priority %d)", event_type, priority)

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """Remove a handler subscription."""
        if event_type not in self._subscribers:
            return False
        before = len(self._subscribers[event_type])
        self._subscribers[event_type] = [
            (p, h) for p, h in self._subscribers[event_type] if h != handler
        ]
        return len(self._subscribers[event_type]) < before
    async def emit(self, event_type: str, **data: Any) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: Event name
            **data: Event payload as keyword arguments
        """
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return

        for priority, handler in handlers:
            try:
                await handler(event_type, **data)
            except Exception:
                logger.exception("Handler %s failed for event '%s'", handler.__name__, event_type)

    # ── Introspection ──────────────────────────────────

    def get_subscribers(self, event_type: str | None = None) -> dict[str, list[str]]:
        """Return subscriber info for debugging."""
        if event_type:
            return {event_type: [h.__name__ for _, h in self._subscribers.get(event_type, [])]}
        return {
            evt: [h.__name__ for _, h in handlers] for evt, handlers in self._subscribers.items()
        }

    @property
    def event_types(self) -> list[str]:
        return list(self._subscribers.keys())

    def subscriber_count(self, event_type: str) -> int:
        return len(self._subscribers.get(event_type, []))
