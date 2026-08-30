"""End-to-end regression tests for named hosted-instance invite redemption.

The real Virulan invite (production row #7) reached Discord OAuth and Virulan
logged in, but the invite stayed Pending and no InstanceAccess row was created.
The tests below exercise the same browser-visible sequence through the real
ASGI routes, signed session cookie, OAuth state, callback, and database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import json
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.permissions import InstanceAccess, InstanceInvite
from services.instance_invites import create_instance_invite


class _DiscordResponse:
    def __init__(self, status_code: int, payload: dict | list):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _DiscordClient:
    """Minimal httpx.AsyncClient replacement for Discord's three OAuth calls."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        return _DiscordResponse(200, {"access_token": "test-access-token"})

    async def get(self, url, **kwargs):
        if url.endswith("/users/@me"):
            return _DiscordResponse(
                200,
                {
                    "id": "7007",
                    "username": "Virulan",
                    "global_name": "Virulan",
                    "avatar": None,
                },
            )
        if url.endswith("/users/@me/guilds"):
            # Bark is already present in this guild. This was the production
            # condition that let login succeed while silently skipping invite
            # consumption.
            return _DiscordResponse(
                200,
                [
                    {
                        "id": "999",
                        "name": "Viru Server",
                        "owner": True,
                        "permissions": "8",
                        "icon": None,
                    }
                ],
            )
        raise AssertionError(f"Unexpected Discord URL: {url}")


def _app(monkeypatch):
    import config
    import dashboard.routes.auth as auth_routes
    from dashboard import create_app

    monkeypatch.setattr(config.config.dashboard, "force_https", False)
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"42"})
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", _DiscordClient)

    guild = MagicMock()
    guild.id = 999
    guild.get_member.return_value = None
    bot = MagicMock()
    bot.guilds = [guild]
    bot.user = None
    bot.is_ready.return_value = True
    bot.is_connected.return_value = True
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    return create_app(bot).app


@pytest.mark.asyncio
async def test_named_invite_is_consumed_even_when_login_already_has_shared_guild(db, monkeypatch):
    app = _app(monkeypatch)
    async with session_scope() as session:
        invite, token = await create_instance_invite(
            session,
            created_by_discord_id="42",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        invite.note = "Virulan"
        await session.flush()
        invite_id = invite.id

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Recipient opens the exact named share URL.
        share = await client.get(f"/auth/share/{token}", follow_redirects=False)
        assert share.status_code == 302, dict(share.headers)
        assert share.headers["location"] == "/auth/login"

        # 2. Bark starts Discord OAuth and preserves the invite in the session.
        login = await client.get(share.headers["location"], follow_redirects=False)
        assert login.status_code == 302
        authorize_url = login.headers["location"]
        assert authorize_url.startswith("https://discord.com/api/oauth2/authorize?")
        state = parse_qs(urlsplit(authorize_url).query)["state"][0]

        # 3. Discord returns a verified user who already shares a Bark guild.
        callback = await client.get(
            f"/auth/callback?code=discord-code&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 307, dict(callback.headers)
        assert callback.headers["location"] == "/dashboard"

    # 4. A successful named-link login MUST consume the pending invite and
    # create the durable access grant, even though shared-guild admission alone
    # would also have allowed the login.
    async with session_scope() as session:
        row = await session.get(InstanceInvite, invite_id)
        grant = await session.get(InstanceAccess, 1)
        assert row is not None
        assert row.redeemed_at is not None
        assert row.redeemed_by_discord_id == "7007"
        assert grant is not None
        assert grant.discord_user_id == "7007"
        assert grant.revoked_at is None


@pytest.mark.asyncio
async def test_named_invite_is_consumed_for_already_authenticated_recipient(db, monkeypatch):
    """Opening a named link while already signed in must redeem it immediately.

    /auth/login intentionally short-circuits authenticated sessions, so staging
    the token and routing through login can never reach the OAuth callback.
    """
    import config

    app = _app(monkeypatch)
    async with session_scope() as session:
        invite, token = await create_instance_invite(
            session,
            created_by_discord_id="42",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        invite.note = "Already signed in"
        await session.flush()
        invite_id = invite.id

    session_data = {
        "user": {"id": "7007", "username": "Virulan"},
        "role": "viewer",
    }
    payload = base64.b64encode(json.dumps(session_data).encode())
    cookie = TimestampSigner(config.config.dashboard.secret_key).sign(payload).decode()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        share = await client.get(f"/auth/share/{token}", follow_redirects=False)
        assert share.status_code == 302
        assert share.headers["location"] == "/dashboard"

    async with session_scope() as session:
        row = await session.get(InstanceInvite, invite_id)
        assert row is not None
        assert row.redeemed_at is not None
        assert row.redeemed_by_discord_id == "7007"


@pytest.mark.asyncio
async def test_revoked_access_grant_can_be_removed_by_owner(db, monkeypatch):
    """The owner must be able to hard-remove a revoked access grant from the
    list (there was no way to delete one before)."""
    import config

    app = _app(monkeypatch)
    async with session_scope() as session:
        session.add(InstanceAccess(discord_user_id="210812020075790337", role="admin"))
        await session.flush()

    owner_session = {"user": {"id": "42", "username": "Owner"}, "role": "admin"}
    payload = base64.b64encode(json.dumps(owner_session).encode())
    cookie = TimestampSigner(config.config.dashboard.secret_key).sign(payload).decode()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        resp = await client.delete("/api/v1/instance/access/210812020075790337/remove")
        assert resp.status_code == 200
        assert resp.json()["data"]["removed"] is True

    async with session_scope() as session:
        from sqlalchemy import select

        row = (
            await session.execute(
                select(InstanceAccess).where(
                    InstanceAccess.discord_user_id == "210812020075790337"
                )
            )
        ).scalar_one_or_none()
    assert row is None, "revoked access grant was hard-deleted"


@pytest.mark.asyncio
async def test_remove_access_requires_owner_and_missing_grant_404s(db, monkeypatch):
    import config

    app = _app(monkeypatch)
    non_owner = {"user": {"id": "999", "username": "Member"}, "role": "viewer"}
    payload = base64.b64encode(json.dumps(non_owner).encode())
    cookie = TimestampSigner(config.config.dashboard.secret_key).sign(payload).decode()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        denied = await client.delete("/api/v1/instance/access/210812020075790337/remove")
        assert denied.status_code == 403

    owner_session = {"user": {"id": "42", "username": "Owner"}, "role": "admin"}
    payload = base64.b64encode(json.dumps(owner_session).encode())
    cookie = TimestampSigner(config.config.dashboard.secret_key).sign(payload).decode()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        missing = await client.delete("/api/v1/instance/access/nobody/remove")
        assert missing.status_code == 404
