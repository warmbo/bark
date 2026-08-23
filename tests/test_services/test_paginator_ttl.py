"""Regression tests for ReactionPaginator session lifecycle.

Paginated guidance menus are tracked by message id; without eviction the
tracking dict grows without bound on long-running instances (``close`` is
never called by callers today). Sessions must expire after SESSION_TTL_SECONDS.
"""

from types import SimpleNamespace

import services.paginator as paginator_module
from services.paginator import ReactionPaginator


def _make_session(pag: ReactionPaginator, message_id: int, age_seconds: float = 0.0):
    import time

    pag._sessions[message_id] = {
        "pages": [SimpleNamespace(), SimpleNamespace()],
        "index": 0,
        "created": time.monotonic() - age_seconds,
        "author_id": 1,
    }


def test_prune_expired_drops_only_old_sessions():
    pag = ReactionPaginator()
    _make_session(pag, 111, age_seconds=0)
    _make_session(pag, 222, age_seconds=paginator_module.SESSION_TTL_SECONDS + 10)

    pag._prune_expired()

    assert 111 in pag._sessions, "fresh session survives pruning"
    assert 222 not in pag._sessions, "expired session is evicted"


def test_send_prunes_before_tracking_new_message():
    import time

    pag = ReactionPaginator()
    # Seed an expired entry as `send` would have created it an hour ago.
    pag._sessions[999] = {
        "pages": [],
        "index": 0,
        "created": time.monotonic() - paginator_module.SESSION_TTL_SECONDS - 5,
        "author_id": 1,
    }
    _make_session(pag, 888, age_seconds=paginator_module.SESSION_TTL_SECONDS + 5)

    pag._prune_expired()
    assert 888 not in pag._sessions
    assert 999 not in pag._sessions
