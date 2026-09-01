"""Debounce for voice-state logging events.

Discord's gateway (and Auto Voice's join-to-create + move + cleanup cascade)
can fire several ``on_voice_state_update`` events for the same member within a
few hundred milliseconds. Naively posting one embed per event floods the
logging channel with duplicate joins/moves/leaves for a single real action.

This module collapses rapid, identical voice transitions for the same member
into one log entry. A transition is keyed by (guild, member, before_channel,
after_channel); if the same key arrives again within ``WINDOW_SECONDS`` it is
treated as a duplicate of the already-logged event and suppressed.
"""

from __future__ import annotations

import threading
import time

WINDOW_SECONDS = 2.0

# key: (guild_id:int, member_id:int, before_channel_id:int|None, after_channel_id:int|None)
# value: monotonic timestamp of the last logged occurrence.
_LAST_LOGGED: dict[tuple[int, int, int | None, int | None], float] = {}
_lock = threading.Lock()


def should_log(
    *,
    guild_id: int,
    member_id: int,
    before_channel_id: int | None,
    after_channel_id: int | None,
    now: float | None = None,
) -> bool:
    """Return True if this transition should be logged (not a rapid duplicate)."""
    now = now if now is not None else time.monotonic()
    key = (int(guild_id), int(member_id), before_channel_id, after_channel_id)
    with _lock:
        last = _LAST_LOGGED.get(key)
        if last is not None and (now - last) < WINDOW_SECONDS:
            return False
        _LAST_LOGGED[key] = now
        # Bound the cache so a long-running process doesn't grow unboundedly.
        if len(_LAST_LOGGED) > 2000:
            _LAST_LOGGED.clear()
            _LAST_LOGGED[key] = now
        return True


def reset() -> None:
    """Clear the dedup cache (used by tests)."""
    with _lock:
        _LAST_LOGGED.clear()
