"""Cleanup-loop regression tests: expired attachment-rate entries must be pruned.

Bug: ``_check_attachment_rate`` (ruleset_engine) stores per-user attachment
tracks as plain LISTS under ``_att_<user_id>`` keys inside
``module._message_track``, but ``ModerationModule._cleanup_loop`` called
``deque.popleft()`` on every track. A list has no ``popleft``, so the first
expired attachment entry raised AttributeError, the whole prune iteration
aborted (mention/dup pruning behind it never ran), and the expired entries
leaked forever — failing and re-logging every 5 minutes.
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from modules.moderation.module import ModerationModule


def _make_module() -> ModerationModule:
    """Real module class; the ctx is unused by the cleanup loop."""
    return ModerationModule(cast(Any, SimpleNamespace()))


def _expired(seconds_ago: int = 600) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)


async def _run_cleanup_once(module: ModerationModule, monkeypatch) -> None:
    """Run exactly one iteration of ``_cleanup_loop``.

    The loop sleeps 300s per iteration; the fake sleep returns on the first
    call (letting the prune body run) and raises CancelledError on the second,
    so the coroutine exits cleanly after one full iteration.
    """
    calls = 0

    async def fake_sleep(_seconds):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("modules.moderation.module.asyncio.sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await module._cleanup_loop()


@pytest.mark.asyncio
async def test_cleanup_prunes_expired_attachment_tracks(monkeypatch):
    """Expired ``_att_*`` list tracks must be removed without crashing."""
    module = _make_module()
    tracks: Any = module._message_track
    tracks[1]["_att_100"] = [(_expired(600), 3), (_expired(120), 2)]
    tracks[1]["_att_200"] = [(_expired(300), 1)]

    await _run_cleanup_once(module, monkeypatch)

    assert "_att_100" not in tracks[1]
    assert "_att_200" not in tracks[1]


@pytest.mark.asyncio
async def test_cleanup_keeps_fresh_attachment_tracks(monkeypatch):
    """Entries inside the rate window must survive a cleanup pass unchanged."""
    module = _make_module()
    tracks: Any = module._message_track
    fresh = datetime.now(timezone.utc)
    tracks[1]["_att_100"] = [(_expired(600), 3)]
    tracks[1]["_att_200"] = [(fresh, 1)]

    await _run_cleanup_once(module, monkeypatch)

    assert "_att_100" not in tracks[1]
    assert tracks[1]["_att_200"] == [(fresh, 1)]


@pytest.mark.asyncio
async def test_cleanup_succeeds_repeatedly(monkeypatch):
    """Repeated cleanup passes keep succeeding and keep pruning newly expired
    entries (the bug crashed every iteration, so nothing was ever pruned)."""
    module = _make_module()
    tracks: Any = module._message_track
    tracks[1]["_att_100"] = [(_expired(600), 3)]

    await _run_cleanup_once(module, monkeypatch)
    assert "_att_100" not in tracks[1]

    # Second pass: fresh expired entries appear and must be pruned too.
    tracks[1]["_att_300"] = [(_expired(900), 2)]
    await _run_cleanup_once(module, monkeypatch)
    assert "_att_300" not in tracks[1]


@pytest.mark.asyncio
async def test_cleanup_does_not_abort_mention_pruning(monkeypatch):
    """The AttributeError on a list track used to abort the whole iteration,
    so deque tracks pruned LATER in the loop (mentions) survived too. They
    must now be pruned in the same pass."""
    module = _make_module()
    tracks: Any = module._message_track
    mentions: Any = module._mention_count
    tracks[1]["_att_100"] = [(_expired(600), 3)]  # list track iterated first
    mentions[1][100] = deque([(_expired(600), 2)])

    await _run_cleanup_once(module, monkeypatch)

    assert "_att_100" not in tracks[1]
    assert 100 not in mentions[1]
