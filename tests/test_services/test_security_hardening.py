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
    # Model a real discord.Member so the actor role-hierarchy check compares
    # concrete ints (MagicMock top_role.position is not comparable).
    member.top_role.position = 20
    member.guild_permissions.administrator = True
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


@pytest.mark.asyncio
async def test_mod_action_fails_closed_when_actor_not_a_live_member(monkeypatch):
    """A removed/absent actor (session id that no longer resolves to a cached
    member) must not be able to moderate — fail closed instead of acting on a
    stale login snapshot."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    target = MagicMock(bot=False, id=42)
    guild = MagicMock(id=1)
    guild.me.guild_permissions.moderate_members = True

    # The target resolves, but the actor (session user id 999) does not.
    def get_member(uid: int):
        return target if uid == 42 else None

    guild.get_member.side_effect = get_member
    bot = MagicMock()
    bot.get_guild.return_value = guild

    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(actions, "check_api_permission", lambda *_a, **_k: True)

    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={"user": {"id": "999"}},
        json=AsyncMock(return_value={"target_id": "42", "duration": 30}),
    )
    resp = await actions._mod_action(request, "1", "timeout", _async_noop)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mod_action_proceeds_when_no_session_actor(monkeypatch):
    """Permissive mode (no session user id) still proceeds — there is no actor
    to verify, so the bot-only check applies (backward-compatible)."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    target = MagicMock(bot=False, id=42)
    guild = MagicMock(id=1)
    guild.me.guild_permissions.moderate_members = True
    guild.get_member.return_value = target
    bot = MagicMock()
    bot.get_guild.return_value = guild

    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(actions, "check_api_permission", lambda *_a, **_k: True)

    calls = {}

    async def fake_create_case(*args, **kwargs):
        calls["action_type"] = kwargs.get("action_type")
        return 7

    from services.moderation_service import ModerationService

    monkeypatch.setattr(ModerationService, "create_case", staticmethod(fake_create_case))
    monkeypatch.setattr(ModerationService, "log_audit", staticmethod(_async_noop))
    monkeypatch.setattr(ModerationService, "add_warning", staticmethod(_async_noop))

    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={"user": {}},  # no actor id → permissive
        json=AsyncMock(return_value={"target_id": "42", "duration": 30}),
    )
    resp = await actions._mod_action(request, "1", "timeout", _async_noop)
    assert resp.status_code == 200
    assert calls.get("action_type") == "timeout"


@pytest.mark.asyncio
async def test_create_case_gates_permission_in_handler(monkeypatch):
    """Defense-in-depth: POST /moderation/cases must be gated in-handler (not
    only by middleware), so a middleware short-circuit can't open case creation."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import dashboard.routes.api.moderation as mod

    monkeypatch.setattr(mod, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "check_api_permission", lambda *_a, **_k: False)

    request = SimpleNamespace(
        state=SimpleNamespace(bot=MagicMock()),
        session={},
        json=AsyncMock(return_value={}),
    )
    resp = await mod.create_case(request, "1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_case_permits_when_authorized(monkeypatch):
    """An authorized caller reaches case creation (permissive default True)."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import dashboard.routes.api.moderation as mod

    monkeypatch.setattr(mod, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "check_api_permission", lambda *_a, **_k: True)
    # Guild exists so the handler proceeds past the gate.
    bot = MagicMock()
    bot.get_guild.return_value = object()
    bot.modules.event_bus = MagicMock()
    monkeypatch.setattr(
        mod.ModerationService,
        "create_case",
        AsyncMock(return_value=7),
    )
    monkeypatch.setattr(mod, "emit_moderation_case_created", AsyncMock())

    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={"user": {"id": "42"}},
        json=AsyncMock(return_value={"action_type": "warn", "target_id": "10"}),
    )
    resp = await mod.create_case(request, "1")
    assert resp.status_code == 200
