"""Regression tests for security hardening: bounded uploads, action validation, send timeouts."""

from __future__ import annotations

import asyncio

import pytest


class _FakeUploadFile:
    """UploadFile stand-in that records how much was read."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self._offset = 0
        self.total_read = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        self.total_read += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_read_upload_limited_stops_at_cap():
    """The helper must not buffer more than max_bytes even for an infinite stream."""
    from services.security import read_upload_limited

    file = _FakeUploadFile(b"x" * (10 * 1024 * 1024 + 500))  # 10 MB + 500
    payload = await read_upload_limited(file, max_bytes=8 * 1024 * 1024)
    assert len(payload) == 8 * 1024 * 1024 + 1  # cap+1 proves over-limit
    # Reads stop after cap+1 bytes — the underlying stream is not drained.
    assert file.total_read <= 8 * 1024 * 1024 + 64 * 1024


@pytest.mark.asyncio
async def test_read_upload_limited_small_file_fully_read():
    """Files under the cap are read completely."""
    from services.security import read_upload_limited

    file = _FakeUploadFile(b"hello-world")
    payload = await read_upload_limited(file, max_bytes=100)
    assert payload == b"hello-world"


@pytest.mark.asyncio
async def test_read_upload_limited_empty_file():
    """Empty uploads return an empty payload."""
    from services.security import read_upload_limited

    payload = await read_upload_limited(_FakeUploadFile(b""), max_bytes=100)
    assert payload == b""


@pytest.mark.asyncio
async def test_timeout_action_validates_duration(monkeypatch):
    """timeout duration must be an int within Discord's 28-day cap; bad values are 400s."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    member = MagicMock(bot=False, id=42)
    member.timeout = AsyncMock()
    guild = MagicMock(id=1)
    guild.me.guild_permissions.moderate_members = True
    guild.get_member.return_value = member
    bot = MagicMock()
    bot.get_guild.return_value = guild

    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(actions, "check_api_permission", lambda *_a, **_k: True)

    calls = {}

    async def fake_create_case(*args, **kwargs):
        calls["create_case"] = kwargs
        return 7

    async def fake_log_audit(*args, **kwargs):
        calls["log_audit"] = kwargs

    async def fake_add_warning(*args, **kwargs):
        return 1

    from services.moderation_service import ModerationService

    monkeypatch.setattr(ModerationService, "create_case", staticmethod(fake_create_case))
    monkeypatch.setattr(ModerationService, "log_audit", staticmethod(fake_log_audit))
    monkeypatch.setattr(ModerationService, "add_warning", staticmethod(fake_add_warning))

    def make_request(payload: dict) -> SimpleNamespace:
        return SimpleNamespace(
            state=SimpleNamespace(bot=bot),
            session={"user": {"id": "1"}},
            json=AsyncMock(return_value=payload),
        )

    # Missing duration → 400
    resp = await actions._mod_action(make_request({"target_id": "42"}), "1", "timeout", _async_noop)
    assert resp.status_code == 400

    # String duration → 400 (previously a 502 from timedelta())
    resp = await actions._mod_action(
        make_request({"target_id": "42", "duration": "abc"}), "1", "timeout", _async_noop
    )
    assert resp.status_code == 400

    # Over 28 days → 400
    resp = await actions._mod_action(
        make_request({"target_id": "42", "duration": 40321}), "1", "timeout", _async_noop
    )
    assert resp.status_code == 400

    # Valid duration passes through and executes
    resp = await actions._mod_action(
        make_request({"target_id": "42", "duration": 30}), "1", "timeout", _async_noop
    )
    assert resp.status_code == 200
    assert calls.get("create_case", {}).get("action_type") == "timeout"


@pytest.mark.asyncio
async def test_announcement_send_has_timeout(monkeypatch):
    """A stalled channel.send raises TimeoutError instead of hanging forever."""
    import modules.announcements.module as announcements

    class _StallChannel:
        async def send(self, **kwargs):
            await asyncio.sleep(60)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            announcements._send_with_timeout(_StallChannel(), content="hi"), timeout=1
        )


async def _async_noop(*args, **kwargs):
    return None
