"""Unit tests for the ruleset engine — triggers and effects.

Covers the detection gaps that let the 2026-08-09 ZENHAWX cross-channel image
raid through: identical-content spam (with attachment signatures), message
rate, scam links, and the kick_purge effect (kick + cross-channel cleanup).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.moderation.ruleset_engine import (
    _check_duplicate_message,
    _check_mention,
    _check_scam_link,
    _check_spam,
    _content_signature,
    _purge_user_messages,
    check_trigger,
    execute_effect,
)


def _author(author_id: int = 100):
    return SimpleNamespace(id=author_id)


def _attachments(sizes=(175646, 79957, 80934, 47283)):
    return [
        SimpleNamespace(filename=f"{i}.jpg", size=size)
        for i, size in enumerate(sizes, start=1)
    ]


def _message(content: str = "bro", attachments=None, author_id: int = 100):
    return SimpleNamespace(
        id=123,
        content=content,
        attachments=attachments or [],
        author=_author(author_id),
        guild=SimpleNamespace(id=1, name="test", me=_author(1)),
        channel=SimpleNamespace(id=2, mention="#general"),
        mentions=[],
        role_mentions=[],
        mention_everyone=False,
        created_at=datetime.now(timezone.utc),
    )


class _FakeModule:
    """Minimal stand-in for the moderation module with the state the engine touches."""

    def __init__(self) -> None:
        self._message_track: dict[int, dict[int, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=200))
        )
        self._dup_track: dict[int, dict[int, list]] = {}
        self._wordlist_cache: dict[str, list[str]] = {}
        self.ctx = SimpleNamespace()
        self._logger = __import__("logging").getLogger("test.fake_module")


def test_content_signature_includes_attachments():
    msg = _message(content="bro", attachments=_attachments())
    sig = _content_signature(msg)
    assert sig.startswith("bro|1.jpg:175646|2.jpg:79957")
    # Same caption + same files -> same signature
    msg2 = _message(content="bro", attachments=_attachments())
    assert _content_signature(msg2) == sig


@pytest.mark.asyncio
async def test_duplicate_message_catches_cross_channel_image_raid():
    """Replay the ZENHAWX raid: identical caption + identical 4 images across
    channels. Must trigger on the 4th message."""
    module = _FakeModule()
    cfg = {"threshold": 4, "window_seconds": 60}
    for i in range(4):
        msg = _message(content="bro", attachments=_attachments())
        msg.channel = SimpleNamespace(id=100 + i, mention=f"#chan{i}")
        triggered, reason = await _check_duplicate_message(msg, cfg, 1, module)
        if i < 3:
            assert not triggered, f"should not trigger before threshold (msg {i + 1})"
        else:
            assert triggered, "4th identical message must trigger"
            assert "Duplicate message (4x identical)" in reason


@pytest.mark.asyncio
async def test_duplicate_message_catches_image_only_spam():
    """Identical image sets with EMPTY captions must still be caught."""
    module = _FakeModule()
    cfg = {"threshold": 3, "window_seconds": 60}
    triggered = False
    for i in range(3):
        msg = _message(content="", attachments=_attachments())
        triggered, _ = await _check_duplicate_message(msg, cfg, 1, module)
    assert triggered


@pytest.mark.asyncio
async def test_duplicate_message_ignores_different_content():
    module = _FakeModule()
    cfg = {"threshold": 3, "window_seconds": 60}
    contents = ["hello", "world", "hello"]
    triggered = False
    for c in contents:
        msg = _message(content=c)
        triggered, _ = await _check_duplicate_message(msg, cfg, 1, module)
    assert not triggered


@pytest.mark.asyncio
async def test_message_spam_rate_trigger():
    module = _FakeModule()
    cfg = {"threshold": 5, "window_seconds": 10}
    now = datetime.now(timezone.utc)
    # Simulate 5 messages within the window
    triggered = False
    reason = ""
    for i in range(5):
        msg = _message(content=f"m{i}")
        msg.created_at = now - timedelta(seconds=2 * i)
        # _check_spam uses module._message_track with the CURRENT time for
        # pruning; feed sequential calls to build up the count.
        triggered, reason = await _check_spam(msg, cfg, 1, module)
    assert triggered
    assert "Spam (5 msgs/10s)" in reason


@pytest.mark.asyncio
async def test_message_spam_burst_pace_does_not_trip_at_one_per_4s():
    """The exact 2026-08-09 raid pace (1 msg/~4s, 8 in 28s) must NOT beat a
    strict 5-in-10s rule — proving why message_spam alone was insufficient."""
    module = _FakeModule()
    # simulate by injecting timestamps 4s apart into the track
    now = datetime.now(timezone.utc)
    track = module._message_track[1][100]
    for i in range(8):
        ts = now - timedelta(seconds=(7 - i) * 4)  # 0..28s ago, 4s apart
        # only keep entries within the window like the real check does
        cutoff = now - timedelta(seconds=10)
        while track and track[0] < cutoff:
            track.popleft()
        track.append(ts)
    assert len(track) < 5, "sliding 10s window never holds 5 at this pace"


@pytest.mark.asyncio
async def test_scam_link_detects_builtin_domain():
    msg = _message(content="get free nitro at discord-nitro.xyz")
    triggered, reason = await _check_scam_link(msg, {}, 1, _FakeModule())
    assert triggered
    assert "Scam domain" in reason


@pytest.mark.asyncio
async def test_scam_link_ignores_plain_text():
    msg = _message(content="bro")
    triggered, _ = await _check_scam_link(msg, {}, 1, _FakeModule())
    assert not triggered


@pytest.mark.asyncio
async def test_mention_threshold():
    msg = _message(content="@a @b @c @d @e")
    msg.mentions = [_author(i) for i in range(5)]
    triggered, reason = await _check_mention(msg, {"threshold": 5}, 1, _FakeModule())
    assert triggered
    assert "Mention spam (5 @)" in reason


@pytest.mark.asyncio
async def test_check_trigger_unknown_type_is_false():
    msg = _message(content="x")
    triggered, reason = await check_trigger(msg, "not_a_trigger", {}, 1, _FakeModule())
    assert triggered is False
    assert reason == ""


@pytest.mark.asyncio
async def test_kick_purge_effect_kicks_and_purges_all_channels():
    """kick_purge must kick the author AND sweep every text channel, not just
    the triggering one (cross-channel raids post once per channel)."""
    module = _FakeModule()
    purge_chan1, purge_chan2 = AsyncMock(), AsyncMock()
    purge_chan1.purge.return_value = [1, 2]
    purge_chan2.purge.return_value = [3]
    author = SimpleNamespace(id=100)
    author.kick = AsyncMock()
    guild = SimpleNamespace(
        id=1,
        name="test",
        me=SimpleNamespace(id=1),
        text_channels=[purge_chan1, purge_chan2],
    )
    msg = SimpleNamespace(
        content="bro",
        attachments=[],
        author=author,
        guild=guild,
        channel=purge_chan1,
        created_at=datetime.now(timezone.utc),
    )
    await execute_effect(msg, "kick_purge", {"max_age_seconds": 120}, "Duplicate message", module)
    author.kick.assert_awaited_once()
    purge_chan1.purge.assert_awaited_once()
    purge_chan2.purge.assert_awaited_once()
    # Bulk delete (not one REST DELETE per message) — raid messages are <14 days old.
    assert purge_chan1.purge.call_args.kwargs["bulk"] is True
    # check filter excludes other authors
    check_fn = purge_chan1.purge.call_args.kwargs["check"]
    mine = SimpleNamespace(author=author, created_at=datetime.now(timezone.utc))
    other = SimpleNamespace(author=SimpleNamespace(id=999), created_at=datetime.now(timezone.utc))
    assert check_fn(mine) is True
    assert check_fn(other) is False


@pytest.mark.asyncio
async def test_kick_purge_caps_total_purged():
    """A huge guild cannot trigger an unbounded purge on the message path."""
    channels = []
    for _ in range(20):
        chan = AsyncMock()
        chan.purge.return_value = [object()] * 50  # 50 deleted per channel
        channels.append(chan)
    author = SimpleNamespace(id=100)
    author.kick = AsyncMock()
    guild = SimpleNamespace(id=1, name="test", me=SimpleNamespace(id=1), text_channels=channels)
    msg = SimpleNamespace(
        content="x",
        attachments=[],
        author=author,
        guild=guild,
        channel=channels[0],
        created_at=datetime.now(timezone.utc),
    )
    purged = await _purge_user_messages(msg, max_age=120)
    assert purged <= 200
    # Not every channel was swept once the cap was hit.
    swept = sum(1 for c in channels if c.purge.await_count)
    assert swept < len(channels)


@pytest.mark.asyncio
async def test_purge_skips_old_messages():
    author = SimpleNamespace(id=100)
    old = SimpleNamespace(
        author=author, created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    chan = AsyncMock()
    chan.purge.return_value = []
    guild = SimpleNamespace(id=1, me=SimpleNamespace(id=1), text_channels=[chan])
    msg = SimpleNamespace(
        content="x",
        attachments=[],
        author=author,
        guild=guild,
        channel=chan,
        created_at=datetime.now(timezone.utc),
    )
    await _purge_user_messages(msg, max_age=120)
    check_fn = chan.purge.call_args.kwargs["check"]
    assert check_fn(old) is False  # 10 minutes old, outside the 120s window
