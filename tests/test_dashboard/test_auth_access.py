"""Discord OAuth guild catalog and authorization tests."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.permissions import DashboardUser
from services.dashboard_access import (
    build_guild_catalog,
    can_manage_discord_guild,
    derive_dashboard_role,
    get_user_guild_access,
    replace_user_guild_access,
    resolve_dashboard_role,
)


def _session_cookie(data: dict) -> str:
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


def _dashboard_app(bot):
    from dashboard import create_app

    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    return create_app(bot).app


@pytest.mark.asyncio
async def test_dashboard_waits_for_bot_before_listing_connected_servers(monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "")

    guild = MagicMock()
    guild.id = 100
    guild.name = "Connected after startup"
    guild.member_count = 25
    guild.icon = None

    bot = MagicMock()
    bot.guilds = []
    bot.is_ready.return_value = False

    async def finish_connecting():
        bot.guilds = [guild]

    bot.wait_until_ready = AsyncMock(side_effect=finish_connecting)
    app = _dashboard_app(bot)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/dashboard")

    assert response.status_code == 200
    assert "1 connected to Bark" in response.text
    assert "Connected after startup" in response.text
    bot.wait_until_ready.assert_awaited_once()


def test_discord_guild_management_requires_owner_admin_or_manage_guild():
    assert can_manage_discord_guild(owner=True, permissions=0)
    assert can_manage_discord_guild(owner=False, permissions=0x8)
    assert can_manage_discord_guild(owner=False, permissions=0x20)
    assert not can_manage_discord_guild(owner=False, permissions=0x400)


def test_dashboard_role_is_recomputed_from_current_shared_guilds():
    managed = [{"id": "100", "owner": False, "permissions": str(0x20)}]
    member_only = [{"id": "100", "owner": False, "permissions": "0"}]

    assert derive_dashboard_role(managed, {"100"}) == "admin"
    assert derive_dashboard_role(member_only, {"100"}) == "moderator"
    assert derive_dashboard_role(managed, set()) == "viewer"


def test_dashboard_owner_requires_configured_discord_id():
    owners = {"42"}

    assert resolve_dashboard_role("42", owners, "viewer", None) == "owner"
    assert resolve_dashboard_role("99", owners, "admin", None) == "admin"
    assert resolve_dashboard_role("99", owners, "viewer", "owner") == "viewer"


@pytest.mark.asyncio
async def test_logout_requires_post():
    app = _dashboard_app(MagicMock())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/auth/logout")

    assert response.status_code == 405


@pytest.mark.asyncio
async def test_oauth_guild_sync_replaces_stale_rows(db):
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))

    first_login = [
        {"id": "100", "name": "Alpha", "icon": "aaa", "owner": True, "permissions": "0"},
        {"id": "200", "name": "Beta", "icon": None, "owner": False, "permissions": str(0x20)},
    ]
    async with session_scope() as session:
        await replace_user_guild_access(session, "42", first_login)

    second_login = [
        {"id": "200", "name": "Beta Renamed", "icon": "bbb", "owner": False, "permissions": str(0x20)},
        {"id": "300", "name": "Read Only", "icon": None, "owner": False, "permissions": "0"},
    ]
    async with session_scope() as session:
        await replace_user_guild_access(session, "42", second_login)

    async with session_scope() as session:
        rows = await get_user_guild_access(session, "42")

    assert [row.guild_id for row in rows] == ["200", "300"]
    assert rows[0].name == "Beta Renamed"
    assert rows[0].can_manage is True
    assert rows[1].can_manage is False


def test_catalog_includes_every_oauth_guild_and_marks_bot_installation():
    oauth_guilds = [
        type("Access", (), {
            "guild_id": "300", "name": "Read Only", "icon_hash": None,
            "owner": False, "permissions": 0, "can_manage": False,
        })(),
        type("Access", (), {
            "guild_id": "100", "name": "Connected", "icon_hash": None,
            "owner": False, "permissions": 0x20, "can_manage": True,
        })(),
        type("Access", (), {
            "guild_id": "200", "name": "Needs Bark", "icon_hash": "icon",
            "owner": True, "permissions": 0, "can_manage": True,
        })(),
    ]
    bot_guild = type("Guild", (), {
        "id": 100, "name": "Connected", "member_count": 25, "icon": None,
    })()

    catalog = build_guild_catalog(oauth_guilds, [bot_guild], client_id="123")

    assert [guild["id"] for guild in catalog] == ["100", "200", "300"]
    assert [guild["access_tier"] for guild in catalog] == ["connected", "manageable", "other"]
    assert catalog[0]["connected"] is True
    assert catalog[0]["member_count"] == 25
    assert catalog[1]["connected"] is False
    assert "guild_id=200" in catalog[1]["invite_url"]
    assert catalog[2]["can_manage"] is False


@pytest.mark.asyncio
async def test_dashboard_lists_all_discord_servers_after_login(db, monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {"id": "100", "name": "Connected", "permissions": str(0x20)},
                {"id": "200", "name": "Needs Bark", "permissions": str(0x20)},
                {"id": "300", "name": "Read Only", "permissions": "0"},
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Connected"
    bot_guild.member_count = 25
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie(
        {"user": {"id": "42", "username": "Cody"}, "role": "admin"}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard")
        api_response = await client.get("/api/v1/guilds")
    assert response.status_code == 200
    assert "Connected" in response.text
    assert "Needs Bark" in response.text
    assert "Read Only" in response.text
    assert 'id="sidebar-nav-items"' in response.text
    assert 'id="palette-overlay"' in response.text
    assert 'id="palette-input"' in response.text
    assert 'id="palette-results"' in response.text
    assert [
        guild["id"] for guild in api_response.json()["data"]["guilds"]
    ] == ["100", "200", "300"]


@pytest.mark.asyncio
async def test_guild_routes_require_manage_guild_permission(db, monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {"id": "100", "name": "Managed", "permissions": str(0x20)},
                {"id": "300", "name": "Read Only", "permissions": "0"},
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Managed"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie(
        {"user": {"id": "42", "username": "Cody"}, "role": "admin"}
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
        follow_redirects=False,
    ) as client:
        allowed = await client.get("/guild/100")
        denied = await client.get("/guild/300")
        denied_api = await client.get("/api/v1/guilds/300")

    owner_cookie = _session_cookie(
        {"user": {"id": "42", "username": "Cody"}, "role": "owner"}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": owner_cookie},
    ) as client:
        owner_denied = await client.get("/api/v1/guilds/300")

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied_api.status_code == 403
    assert owner_denied.status_code == 403
    assert denied_api.json()["error"] == "You cannot manage this Discord server"
