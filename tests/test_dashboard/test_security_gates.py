"""Regression tests for audit-driven security gates.

Covers:
- bot_appearance (bot identity/presence) is INSTANCE-OWNER gated, not
  per-guild-admin gated (a guild admin must not rename the shared bot)
- SSE /events stream requires moderation.view (not just guild membership)
- non-numeric guild ids return 404 at the middleware boundary (no handler 500)
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner


def _session_cookie(user_id: str, role: str = "viewer") -> str:
    session = {"user": {"id": user_id, "username": "Tester"}, "role": role}
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


@pytest.fixture
def app(db, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"42"})

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    return create_app(bot)


# ── bot_appearance: owner-only ──────────────────────────


@pytest.mark.asyncio
async def test_bot_appearance_rejects_per_guild_admin(app, monkeypatch):
    """A user with admin role in one guild must NOT be able to read/change the
    bot's GLOBAL identity — only instance owners may."""
    from dashboard.routes.api.bot_appearance import get_bot_appearance

    request = MagicMock()
    request.session = {"user": {"id": "43"}, "role": "admin"}  # not the owner
    resp = await get_bot_appearance(request, "1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_bot_appearance_allows_owner(app, monkeypatch):
    from dashboard.routes.api.bot_appearance import get_bot_appearance

    request = MagicMock()
    request.session = {"user": {"id": "42"}, "role": "admin"}
    request.state.bot.user = None
    resp = await get_bot_appearance(request, "1")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bot_appearance_clean_username_and_banner(app, monkeypatch):
    """The appearance payload must return the plain bot name (no #1234) and a
    real banner URL even when discord.py's cached ClientUser.banner is None.

    Regression for 2026-08-10: username came from str(user) (appending the
    discriminator) and banner_url was always None for the cached self-user,
    so the UI showed 'No banner set' while a banner existed.
    """
    import json
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api.bot_appearance import get_bot_appearance

    user = MagicMock()
    user.name = "Bark"
    user.id = 1
    # Simulate a legacy bot where str(user) == "Bark#7343"
    type(user).__str__ = lambda self: f"{self.name}#7343"
    user.discriminator = "7343"
    user.banner = None  # cached self-user: banner not loaded
    user.display_avatar.url = "https://cdn.discordapp.com/avatars/1/a.png"

    http = MagicMock()
    http.get_user = AsyncMock(return_value={"id": "1", "banner": "abc123"})

    bot = MagicMock()
    bot.user = user
    bot.http = http

    request = MagicMock()
    request.session = {"user": {"id": "42"}, "role": "admin"}
    request.state.bot = bot

    resp = await get_bot_appearance(request, "1")
    assert resp.status_code == 200
    data = json.loads(bytes(resp.body).decode("utf-8"))["data"]

    # Plain name — no #7343 discriminator
    assert data["username"] == "Bark"
    assert "#" not in data["username"]
    # Banner resolved via the http fallback into a CDN URL (png ext)
    assert data["banner_url"] == "https://cdn.discordapp.com/banners/1/abc123.png"
    http.get_user.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_bot_banner_url_uses_cached_asset_when_present(app, monkeypatch):
    """When ClientUser.banner IS populated, use it and skip the http fetch."""
    from dashboard.routes.api.bot_appearance import _bot_banner_url

    asset = MagicMock()
    asset.url = "https://cdn.discordapp.com/banners/1/cached.png"
    user = MagicMock()
    user.banner = asset
    bot = MagicMock()
    bot.user = user
    bot.http = MagicMock()

    url = await _bot_banner_url(bot)
    assert url == "https://cdn.discordapp.com/banners/1/cached.png"
    bot.http.get_user.assert_not_called()


# ── SSE stream: moderation.view gate ────────────────────


@pytest.mark.asyncio
async def test_sse_events_reject_viewer(app, monkeypatch):
    """A plain member must not be able to live-stream moderation reasons and
    flagged message content."""
    from dashboard.routes.api.realtime import guild_events_sse

    request = MagicMock()
    request.session = {"user": {"id": "43"}, "role": "viewer"}
    request.state.bot.get_guild.return_value = MagicMock(id=1)
    resp = await guild_events_sse(request, "1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sse_events_allow_owner(app, monkeypatch):
    from fastapi.responses import StreamingResponse

    from dashboard.routes.api.realtime import guild_events_sse

    request = MagicMock()
    request.session = {"user": {"id": "42"}, "role": "admin"}
    request.state.bot.get_guild.return_value = MagicMock(id=1)
    resp = await guild_events_sse(request, "1")
    # Gate passed — the endpoint starts streaming (handled asynchronously).
    assert isinstance(resp, StreamingResponse)


@pytest.mark.asyncio
async def test_sse_events_route_serves_event_stream_not_json(app, monkeypatch):
    """The /guilds/{id}/events route must resolve to the SSE handler, not a
    JSON endpoint. A duplicate JSON route on the same path shadowed the SSE
    stream (registration order), so EventSource aborted with
    'MIME type application/json is not text/event-stream' and reconnected
    endlessly. Regression: the route must live only on the realtime router
    (media_type text/event-stream), not on the guilds router."""
    from dashboard.routes.api import guilds, realtime

    sse_routes = [
        r for r in realtime.router.routes
        if getattr(r, "path", "") == "/guilds/{guild_id}/events"
        and "GET" in getattr(r, "methods", set())
    ]
    # Exactly one SSE route on the realtime router, handled by the streaming
    # endpoint (media_type text/event-stream is set at call time).
    assert len(sse_routes) == 1
    assert sse_routes[0].endpoint.__name__ == "guild_events_sse"

    # The guilds router must NOT also declare the same path — that duplicate
    # is what shadowed the SSE handler and made EventSource abort.
    guild_events = [
        r for r in guilds.router.routes
        if getattr(r, "path", "") == "/guilds/{guild_id}/events"
    ]
    assert guild_events == [], (
        "duplicate /guilds/{guild_id}/events route on the guilds router "
        "shadows the realtime SSE stream"
    )


# ── Non-numeric guild id: 404 at the boundary ───────────


@pytest.mark.asyncio
async def test_garbage_guild_id_returns_404_not_500(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42", role="admin")),
    ) as client:
        response = await client.get("/api/v1/guilds/abc/members")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_garbage_guild_id_404_on_mutation(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42", role="admin")),
    ) as client:
        response = await client.post("/api/v1/guilds/abc/moderation/cases", json={})
    assert response.status_code == 404
