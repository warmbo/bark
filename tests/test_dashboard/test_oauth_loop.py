"""OAuth loop regression tests.

A login rejection (uninvited user, cancelled flow, state mismatch, token
failure) used to redirect to /dashboard?auth_error=X — but /dashboard is
auth-gated, so AuthMiddleware bounced to /auth/login → Discord authorize →
the user authorized again → rejected again: an infinite loop (observed
2026-08-06 on bark-dev, mobile Chrome). Auth failures must land on the
PUBLIC landing page (/) where the error is surfaced, and /auth/login must
not re-fire the Discord flow for an already-authenticated user.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from dashboard.routes.auth import AUTH_ERROR_MESSAGES


def _dashboard_app(bot):
    from dashboard import create_app

    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    return create_app(bot).app


@pytest.fixture
def oauth_app(monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"42"})

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.is_ready.return_value = False
    bot.is_connected.return_value = False
    return _dashboard_app(bot)


@pytest.mark.asyncio
async def test_auth_error_lands_on_public_landing_not_dashboard(oauth_app):
    """A failed callback must redirect to the PUBLIC landing page (/) — never
    to /dashboard, which is auth-gated and would start the login loop."""
    async with AsyncClient(
        transport=ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        # state mismatch (no oauth_state in session)
        response = await client.get(
            "/auth/callback?code=x&state=wrong", follow_redirects=False
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/?auth_error=invalid_state"


@pytest.mark.asyncio
async def test_auth_error_surfaces_message_on_landing(oauth_app):
    """Following the auth_error redirect shows a human-readable banner on the
    public landing page."""
    async with AsyncClient(
        transport=ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        response = await client.get("/?auth_error=no_shared_guild")
    assert response.status_code == 200
    assert AUTH_ERROR_MESSAGES["no_shared_guild"] in response.text
    assert "auth-error-banner" in response.text


@pytest.mark.asyncio
async def test_login_short_circuits_when_already_authenticated(oauth_app, monkeypatch):
    """/auth/login must NOT re-fire the Discord authorize URL for a user who
    already has a session — that was a second loop entry point."""
    import base64
    import json

    from itsdangerous import TimestampSigner

    import config

    secret_key = config.config.dashboard.secret_key or "test_secret_key"
    payload = base64.b64encode(
        json.dumps({"user": {"id": "42", "username": "Cody"}, "role": "admin"}).encode()
    )
    cookie = TimestampSigner(secret_key).sign(payload).decode()

    async with AsyncClient(
        transport=ASGITransport(app=oauth_app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert "discord.com/api/oauth2/authorize" not in response.headers["location"]


@pytest.mark.asyncio
async def test_callback_denied_redirects_to_landing(oauth_app):
    """Discord's 'denied' error should land on the landing page, not loop."""
    async with AsyncClient(
        transport=ASGITransport(app=oauth_app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/auth/callback?error=access_denied", follow_redirects=False
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/?auth_error=denied"
