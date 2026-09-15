"""Milestone A — authorization freshness and SSE revocation.

Covers:
- ``refresh_member_roles`` keeps the staff-role snapshot fresh on Discord
  member updates (fail closed: unresolved state clears the snapshot).
- ``recheck_api_permission`` re-derives authorization from CURRENT DB state
  for long-lived requests (SSE), so a revoked grant stops promptly.
- the SSE stream revalidates on a fixed cadence regardless of event flow and
  closes (``access_revoked``) when the grant is gone — role removal, guild
  removal — while staying alive and heartbeating for authorized users.
- ``BarkBot.on_member_update`` wires the Discord role change into the DB
  snapshot.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild, GuildSetting
from database.models.permissions import DashboardGuildAccess, DashboardUser
from services.dashboard_access import (
    MODERATOR_ROLES_SETTING,
    refresh_member_roles,
    revoke_user_guild_access,
)

MODERATOR_ROLE = "111"


@pytest.fixture(autouse=True)
def _enable_oauth2(monkeypatch):
    """OAuth must be configured for permission checks to actually run —
    otherwise check_api_permission/recheck_api_permission are permissive and
    these tests would pass vacuously."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")


async def _seed_user_and_guild(user_id: str = "42", guild_id: str = "100") -> None:
    async with session_scope() as session:
        session.add(DashboardUser(discord_id=user_id, username="Tester", role="viewer"))
        session.add(Guild(discord_id=guild_id, name="Test Guild", owner_id=user_id))
        await session.commit()


async def _seed_access(
    user_id: str = "42",
    guild_id: str = "100",
    *,
    owner: bool = False,
    permissions: int = 0,
    roles: str = "",
) -> None:
    await _seed_user_and_guild(user_id, guild_id)
    async with session_scope() as session:
        session.add(
            DashboardGuildAccess(
                user_discord_id=user_id,
                guild_id=guild_id,
                name="Test Guild",
                permissions=permissions,
                owner=owner,
                roles=roles,
            )
        )
        await session.commit()


async def _seed_moderator_role_setting(guild_id: str = "100") -> None:
    async with session_scope() as session:
        session.add(
            GuildSetting(
                guild_id=str(guild_id),
                key=MODERATOR_ROLES_SETTING,
                value=f'["{MODERATOR_ROLE}"]',
            )
        )
        await session.commit()


async def _access_row(user_id: str = "42", guild_id: str = "100") -> DashboardGuildAccess:
    async with session_scope() as session:
        result = await session.execute(
            select(DashboardGuildAccess).where(
                DashboardGuildAccess.user_discord_id == user_id,
                DashboardGuildAccess.guild_id == guild_id,
            )
        )
        return result.scalar_one()


class _FakeBridge:
    """Minimal RealtimeBridge stand-in: per-guild asyncio queues.

    ``maxsize`` mirrors the real bridge's bounded queues (256) so tests can
    exercise the full-queue revocation path; 0 = unbounded.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self.queues: dict[str, list[asyncio.Queue]] = {}
        self.maxsize = maxsize

    async def subscribe(self, guild_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self.queues.setdefault(str(guild_id), []).append(queue)
        return queue

    async def unsubscribe(self, guild_id: str, queue: asyncio.Queue) -> None:
        try:
            self.queues[str(guild_id)].remove(queue)
        except (KeyError, ValueError):
            pass


def _request(bridge: _FakeBridge | None = None) -> MagicMock:
    request = MagicMock()
    request.app.state.realtime_bridge = bridge or _FakeBridge()
    request.state.bot.modules.get_all_modules.return_value = {}
    return request


def _discord_member(role_ids: list[str], *, nickname: str = "Tester") -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        guild=SimpleNamespace(id=100, name="Test Guild"),
        roles=[SimpleNamespace(id=role_id) for role_id in role_ids],
        nick=nickname,
    )


# ── refresh_member_roles ────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_member_roles_updates_staff_roles_snapshot(db):
    await _seed_access("42", "100", roles="111,222")

    async with session_scope() as session:
        updated = await refresh_member_roles(session, "42", "100", ["111", "333"])
        await session.commit()

    assert updated is True
    assert (await _access_row()).roles == "111,333"


@pytest.mark.asyncio
async def test_refresh_member_roles_clears_snapshot_when_unresolved(db):
    """An unresolved member state must not keep a stale staff-role grant."""
    await _seed_access("42", "100", roles="111,222")

    async with session_scope() as session:
        updated = await refresh_member_roles(session, "42", "100", None)
        await session.commit()

    assert updated is True
    assert (await _access_row()).roles == ""


@pytest.mark.asyncio
async def test_refresh_member_roles_returns_false_when_no_access_row(db):
    await _seed_user_and_guild()
    async with session_scope() as session:
        assert await refresh_member_roles(session, "42", "100", ["111"]) is False


# ── recheck_api_permission (fresh DB authorization) ─────


@pytest.mark.asyncio
async def test_recheck_grants_with_configured_staff_role(db):
    await _seed_access("42", "100", roles=MODERATOR_ROLE)
    await _seed_moderator_role_setting()

    from services.response import recheck_api_permission

    assert await recheck_api_permission(_request(), "moderation.view", "100", "42") is True


@pytest.mark.asyncio
async def test_recheck_denies_after_staff_role_removed(db):
    """Role removal while a stream is open: the fresh recheck must flip to
    deny once the member's role snapshot reflects the removal."""
    await _seed_access("42", "100", roles=MODERATOR_ROLE)
    await _seed_moderator_role_setting()

    from services.response import recheck_api_permission

    request = _request()
    assert await recheck_api_permission(request, "moderation.view", "100", "42") is True

    # Staff role removed in Discord → snapshot refreshed by on_member_update.
    async with session_scope() as session:
        await refresh_member_roles(session, "42", "100", [])
        await session.commit()

    assert await recheck_api_permission(request, "moderation.view", "100", "42") is False


@pytest.mark.asyncio
async def test_recheck_denies_when_access_row_revoked(db):
    """Guild removal revokes the access row; the fresh recheck must deny."""
    await _seed_access("42", "100", owner=True)

    from services.response import recheck_api_permission

    request = _request()
    assert await recheck_api_permission(request, "moderation.view", "100", "42") is True

    async with session_scope() as session:
        await revoke_user_guild_access(session, "42", "100")
        await session.commit()

    assert await recheck_api_permission(request, "moderation.view", "100", "42") is False


@pytest.mark.asyncio
async def test_recheck_fails_closed_on_db_error(db, monkeypatch):
    """A resolution error must deny, never silently keep the stream open."""
    await _seed_access("42", "100", owner=True)
    import services.dashboard_access as dashboard_access_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(dashboard_access_module, "get_user_guild_access_row", _boom)

    from services.response import recheck_api_permission

    assert await recheck_api_permission(_request(), "moderation.view", "100", "42") is False


# ── SSE stream revalidation ─────────────────────────────


async def _open_stream(monkeypatch, request: MagicMock, guild_id: str = "100", user_id: str = "42"):
    import dashboard.routes.api.realtime as realtime_module

    # Short intervals so tests drive real revalidation ticks instead of
    # waiting 30s. The auth watcher runs on its own cadence independent of
    # event flow, which is the busy-stream guarantee.
    monkeypatch.setattr(realtime_module, "AUTH_REVALIDATE_INTERVAL", 0.02)
    monkeypatch.setattr(realtime_module, "HEARTBEAT_INTERVAL", 0.02)
    return realtime_module._event_stream(guild_id, request, user_id)


@pytest.mark.asyncio
async def test_sse_stream_closes_after_staff_role_removed_while_open(db, monkeypatch):
    await _seed_access("42", "100", roles=MODERATOR_ROLE)
    await _seed_moderator_role_setting()

    request = _request()
    stream = await _open_stream(monkeypatch, request)

    # Authorized: the stream yields (heartbeat) instead of closing.
    first = await asyncio.wait_for(stream.__anext__(), timeout=1)
    assert first.startswith(": heartbeat")

    # Staff role removed in Discord while the stream is open.
    async with session_scope() as session:
        await refresh_member_roles(session, "42", "100", [])
        await session.commit()

    # The revalidation tick closes the stream with a truthful revoked event.
    # (A heartbeat may interleave if the tick races the 0.02s heartbeat
    # timeout under load — consume until the stream actually closes.)
    items = []
    for _ in range(4):
        items.append(await asyncio.wait_for(stream.__anext__(), timeout=2))
        if items[-1].startswith("event: access_revoked"):
            break
    else:
        pytest.fail("stream never closed with access_revoked after role removal")

    assert items[-1].startswith("event: access_revoked")
    assert "authorization_revoked" in items[-1]

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_sse_stream_closes_after_guild_access_revoked_while_open(db, monkeypatch):
    await _seed_access("42", "100", owner=True)

    request = _request()
    stream = await _open_stream(monkeypatch, request)

    first = await asyncio.wait_for(stream.__anext__(), timeout=1)
    assert first.startswith(": heartbeat")

    # Bot left the guild / access row revoked while the stream is open.
    async with session_scope() as session:
        await revoke_user_guild_access(session, "42", "100")
        await session.commit()

    items = []
    for _ in range(4):
        items.append(await asyncio.wait_for(stream.__anext__(), timeout=2))
        if items[-1].startswith("event: access_revoked"):
            break
    else:
        pytest.fail("stream never closed with access_revoked after guild access revoked")

    assert items[-1].startswith("event: access_revoked")

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_sse_stream_keeps_heartbeating_while_authorized(db, monkeypatch):
    """A still-authorized stream must survive revalidation ticks and keep
    heartbeating — revocation logic must not kill healthy connections."""
    await _seed_access("42", "100", owner=True)

    request = _request()
    stream = await _open_stream(monkeypatch, request)
    try:
        chunks = []
        for _ in range(3):
            chunks.append(await asyncio.wait_for(stream.__anext__(), timeout=1))
        assert all(chunk.startswith(": heartbeat") for chunk in chunks)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_sse_stream_revocation_not_delayed_by_full_queue(db, monkeypatch):
    """A full, lossy event queue must not block the watcher or bury the
    revocation signal behind queued events — the stream closes promptly."""
    await _seed_access("42", "100", owner=True)

    bridge = _FakeBridge(maxsize=2)
    request = _request(bridge)
    stream = await _open_stream(monkeypatch, request)
    # Prime the generator so it has actually subscribed to the bridge.
    await asyncio.wait_for(stream.__anext__(), timeout=1)
    queue = bridge.queues["100"][0]
    # Fill the bounded queue to capacity, then revoke while it is full.
    queue.put_nowait("event: new_moderation_case\ndata: {}\n\n")
    queue.put_nowait("event: member_joined\ndata: {}\n\n")

    async with session_scope() as session:
        await revoke_user_guild_access(session, "42", "100")
        await session.commit()

    items = []
    for _ in range(6):  # 2 buffered events + heartbeat + revoked, worst case
        items.append(await asyncio.wait_for(stream.__anext__(), timeout=2))
        if items[-1].startswith("event: access_revoked"):
            break
    else:
        pytest.fail("stream never closed with access_revoked after revocation")

    assert items[-1].startswith("event: access_revoked")
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_sse_stream_closes_when_recheck_raises(db, monkeypatch):
    """A recheck that RAISES (not just returns False) must still fail closed:
    a dead watcher must not leave the stream open with no revalidation."""
    await _seed_access("42", "100", owner=True)

    import services.response as response_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("recheck boom")

    monkeypatch.setattr(response_module, "recheck_api_permission", _boom)

    request = _request()
    stream = await _open_stream(monkeypatch, request)

    # The first recheck tick raises at 0.02s — it can beat the first heartbeat
    # timeout, so accept either order until the stream closes.
    items = []
    for _ in range(3):
        items.append(await asyncio.wait_for(stream.__anext__(), timeout=2))
        if items[-1].startswith("event: access_revoked"):
            break
    else:
        pytest.fail("stream never closed with access_revoked after recheck raised")

    assert items[-1].startswith("event: access_revoked")
    assert "authorization_revoked" in items[-1]

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1)


# ── bot/client.py on_member_update ──────────────────────


@pytest.mark.asyncio
async def test_on_member_update_refreshes_staff_role_snapshot(db):
    from bot.client import BarkBot

    await _seed_access("42", "100", roles="111,222")
    bot = SimpleNamespace(modules=SimpleNamespace(event_bus=SimpleNamespace(emit=MagicMock())))

    before = _discord_member(["111", "222"], nickname="Old Nick")
    after = _discord_member(["111"], nickname="New Nick")
    # Deliberate fakes — not real discord.Member/BarkBot objects.
    await BarkBot.on_member_update(bot, before, after)  # type: ignore[arg-type]

    assert (await _access_row()).roles == "111"


@pytest.mark.asyncio
async def test_on_member_update_skips_write_when_roles_unchanged(db):
    from bot.client import BarkBot

    await _seed_access("42", "100", roles="111,222")
    bot = SimpleNamespace(modules=SimpleNamespace(event_bus=SimpleNamespace(emit=MagicMock())))

    before = _discord_member(["111", "222"], nickname="Old Nick")
    after = _discord_member(["111", "222"], nickname="New Nick")
    # Deliberate fakes — not real discord.Member/BarkBot objects.
    await BarkBot.on_member_update(bot, before, after)  # type: ignore[arg-type]

    # Only a role change touches the snapshot — nickname-only updates don't.
    assert (await _access_row()).roles == "111,222"
