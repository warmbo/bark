"""Discord OAuth guild catalog and authorization tests."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.guild import Guild
from database.models.permissions import DashboardUser, InstanceAccess
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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
    owner = [{"id": "100", "owner": True, "permissions": "0"}]
    admin_perm = [{"id": "100", "owner": False, "permissions": str(0x8)}]
    manage_perm = [{"id": "100", "owner": False, "permissions": str(0x20)}]
    member_only = [{"id": "100", "owner": False, "permissions": "0"}]

    # Global role tiering follows Discord permissions: owner/ADMINISTRATOR ->
    # admin, MANAGE_GUILD -> moderator, plain member -> viewer.
    assert derive_dashboard_role(owner, {"100"}) == "admin"
    assert derive_dashboard_role(admin_perm, {"100"}) == "admin"
    assert derive_dashboard_role(manage_perm, {"100"}) == "moderator"
    assert derive_dashboard_role(member_only, {"100"}) == "viewer"
    assert derive_dashboard_role(manage_perm, set()) == "viewer"


def test_dashboard_owner_requires_configured_discord_id():
    owners = {"42"}

    assert resolve_dashboard_role("42", owners, "viewer", None) == "owner"
    assert resolve_dashboard_role("99", owners, "admin", None) == "admin"
    assert resolve_dashboard_role("99", owners, "viewer", "owner") == "viewer"


@pytest.mark.asyncio
async def test_logout_requires_post():
    app = _dashboard_app(MagicMock())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
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
        {
            "id": "200",
            "name": "Beta Renamed",
            "icon": "bbb",
            "owner": False,
            "permissions": str(0x20),
        },
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
        type(
            "Access",
            (),
            {
                "guild_id": "300",
                "name": "Read Only",
                "icon_hash": None,
                "owner": False,
                "permissions": 0,
                "can_manage": False,
            },
        )(),
        type(
            "Access",
            (),
            {
                "guild_id": "100",
                "name": "Connected",
                "icon_hash": None,
                "owner": False,
                "permissions": 0x20,
                "can_manage": True,
            },
        )(),
        type(
            "Access",
            (),
            {
                "guild_id": "200",
                "name": "Needs Bark",
                "icon_hash": "icon",
                "owner": True,
                "permissions": 0,
                "can_manage": True,
            },
        )(),
    ]
    bot_guild = type(
        "Guild",
        (),
        {
            "id": 100,
            "name": "Connected",
            "member_count": 25,
            "icon": None,
        },
    )()

    catalog = build_guild_catalog(oauth_guilds, [bot_guild], client_id="123", public_url="http://test.local")

    assert [guild["id"] for guild in catalog] == ["100", "200", "300"]
    assert [guild["access_tier"] for guild in catalog] == ["connected", "manageable", "other"]
    assert catalog[0]["connected"] is True
    assert catalog[0]["member_count"] == 25
    assert catalog[1]["connected"] is False
    # Invite link is the canonical branded landing URL, not the raw Discord OAuth URL.
    assert catalog[1]["invite_url"].endswith("/invite")
    assert catalog[2]["can_manage"] is False


@pytest.mark.asyncio
async def test_dashboard_lists_all_discord_servers_after_login(db, monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))
        session.add(InstanceAccess(discord_user_id="42"))
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
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "admin"})

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
    assert [guild["id"] for guild in api_response.json()["data"]["guilds"]] == ["100", "200", "300"]


@pytest.mark.asyncio
async def test_guild_routes_open_for_granted_members_of_connected_servers(db, monkeypatch):
    """Only members with a manage grant (server owner or configured staff role)
    can open a connected server's dashboard; others are denied. Servers Bark is
    not in have nothing behind /guild/{id} (403)."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {"id": "100", "name": "Connected", "permissions": str(0x20), "owner": True},
                {"id": "300", "name": "Read Only", "permissions": "0", "owner": False},
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Connected"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        allowed = await client.get("/guild/100")
        denied = await client.get("/guild/300")
        denied_api = await client.get("/api/v1/guilds/300")

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied_api.status_code == 403
    assert "Bark isn't installed" in denied_api.json()["error"]


@pytest.mark.asyncio
async def test_plain_member_gets_view_only_not_mutation(db, monkeypatch):
    """A plain member of a connected server can open the read-only status page
    but cannot mutate — no manage grant means view-only, not a lock."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {"id": "100", "name": "Connected", "permissions": "0", "owner": False},
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Connected"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        view = await client.get("/guild/100")
        denied_write = await client.post("/api/v1/guilds/100/notes", json={"note": "hi"})

    assert view.status_code == 200
    assert "View only" in view.text
    assert denied_write.status_code == 403


class _FakeResponse:
    """Minimal stand-in for httpx.Response in OAuth callback tests."""

    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeDiscordClient:
    """Mocks the OAuth callback's httpx.AsyncClient usage."""

    def __init__(self, *, user: dict, guilds: list[dict]):
        self.user = user
        self.guilds = guilds

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, **kwargs):
        if "oauth2/token" in url:
            return _FakeResponse(200, {"access_token": "tok"})
        return _FakeResponse(500, {})

    async def get(self, url: str, **kwargs):
        if "users/@me/guilds" in url:
            return _FakeResponse(200, self.guilds)
        if "users/@me" in url:
            return _FakeResponse(200, self.user)
        return _FakeResponse(500, {})


@pytest.mark.asyncio
async def test_oauth_callback_admits_member_of_bark_server_without_invite(db, monkeypatch):
    """A Discord user who belongs to a server where Bark is installed can sign
    in and see the dashboard — no dashboard invite required. Membership is the
    admission criterion; invites are for adding Bark to a server."""
    import config
    import dashboard.routes.auth as auth_module

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"42"})

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}

    fake = _FakeDiscordClient(
        user={"id": "999", "username": "member", "avatar": None, "global_name": None},
        guilds=[{"id": "100", "name": "War Lab", "permissions": "0"}],
    )
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda **kw: fake)

    from dashboard import create_app

    app = create_app(bot).app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        # Prime oauth_state exactly like /auth/login does.
        client.cookies.set("session", _session_cookie({"oauth_state": "state-123"}))
        response = await client.get("/auth/callback?code=abc&state=state-123")

    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_oauth_callback_rejects_user_with_no_shared_guild(db, monkeypatch):
    """A Discord user who is not in any server where Bark is installed is
    rejected with a clear landing-page message — never a login loop."""
    import config
    import dashboard.routes.auth as auth_module

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"42"})

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}

    fake = _FakeDiscordClient(
        user={"id": "777", "username": "stranger", "avatar": None, "global_name": None},
        guilds=[{"id": "555", "name": "Elsewhere", "permissions": "0"}],
    )
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", lambda **kw: fake)

    from dashboard import create_app

    app = create_app(bot).app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        client.cookies.set("session", _session_cookie({"oauth_state": "state-456"}))
        response = await client.get("/auth/callback?code=abc&state=state-456")

    assert response.status_code == 302
    assert response.headers["location"] == "/?auth_error=no_shared_guild"


def _module_stub():
    """Return a minimal module object for rendering the module detail page."""
    module = MagicMock()
    module.version = "1.0.0"
    module.description = "Announcements"
    module.author = "test"
    module.load_dashboard_config = AsyncMock(return_value={})
    module.get_settings_schema.return_value = {"properties": {}}
    module.get_extra_tabs.return_value = []
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_actions.return_value = []
    module.get_about.return_value = ""
    return module


@pytest.mark.asyncio
async def test_module_page_open_to_owner_with_stale_session_role(db, monkeypatch):
    """Reported prod case: a user invited before Bark joined their own server
    carries a stale login-time role in their session cookie. The module page
    must still open for the server owner — the middleware re-derives the role
    for this guild from the persisted Discord snapshot on every request."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="moderator"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {
                    "id": "100",
                    "name": "Lil Gups",
                    "permissions": str(2147483647),
                    "owner": True,
                }
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Lil Gups"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    bot.modules.get_module.return_value = _module_stub()
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "moderator"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        response = await client.get("/guild/100/modules/announcements")

    assert response.status_code == 200
    assert "Insufficient permissions" not in response.text
    assert 'data-user-role="admin"' in response.text
    assert 'data-can-manage="true"' in response.text


@pytest.mark.asyncio
async def test_non_granted_member_gets_view_only(db, monkeypatch):
    """A plain member (no manage grant) sees only the view-only status page:
    management pages redirect to it, the manifest strips to a single Dashboard
    entry, and writes are denied."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": "0", "owner": False}],
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
    bot.modules.get_module.return_value = _module_stub()
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        module_page = await client.get("/guild/100/modules/announcements")
        members_page = await client.get("/guild/100/members")
        status_page = await client.get("/guild/100")
        manifest = await client.get("/api/v1/guilds/100/manifest")
        denied_write = await client.post(
            "/api/v1/guilds/100/notes",
            json={"user_id": "999", "content": "hi"},
        )

    assert module_page.status_code == 303
    assert module_page.headers["location"] == "/guild/100"
    assert members_page.status_code == 303
    assert members_page.headers["location"] == "/guild/100"
    assert status_page.status_code == 200
    assert "View only" in status_page.text
    assert manifest.status_code == 200
    data = manifest.json()["data"]
    assert data["viewer"] is True
    # Viewers can reach the read-only Dashboard and Statistics pages (but no
    # module/management surfaces).
    viewer_routes = [p["route"] for p in data["pages"]]
    assert "/guild/100" in viewer_routes
    assert "/guild/100/stats" in viewer_routes
    assert data["modules"] == []
    assert denied_write.status_code == 403


@pytest.mark.asyncio
async def test_configured_moderator_role_opens_module_page(db, monkeypatch):
    """A member holding a role the server owner configured as moderator is
    not view-only: module pages open and API role is upgraded to moderator."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        session.add(InstanceAccess(discord_user_id="42"))
        session.add(Guild(discord_id="100", name="Connected", owner_id="99"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": "0", "owner": False}],
            roles_by_guild={"100": ["555"]},
        )
        from database.models.guild import GuildSetting

        session.add(
            GuildSetting(
                guild_id="100",
                key="dashboard_moderator_roles",
                value='["555"]',
            )
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
    bot.modules.get_module.return_value = _module_stub()
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        module_page = await client.get("/guild/100/modules/announcements")
        status_page = await client.get("/guild/100")
        manifest = await client.get("/api/v1/guilds/100/manifest")

    assert module_page.status_code == 200
    assert 'data-user-role="moderator"' in module_page.text
    assert "You have view-only access" not in status_page.text
    assert manifest.json()["data"]["viewer"] is False


@pytest.mark.asyncio
async def test_module_mutation_allowed_for_owner_with_stale_session_role(db, monkeypatch):
    """The stale cookie role must not block a server owner from mutating their
    own guild: the middleware refreshes the role before the mutation check."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="moderator"))
        session.add(InstanceAccess(discord_user_id="42"))
        session.add(Guild(discord_id="100", name="Lil Gups", owner_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {
                    "id": "100",
                    "name": "Lil Gups",
                    "permissions": str(2147483647),
                    "owner": True,
                }
            ],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Lil Gups"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "moderator"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        response = await client.post(
            "/api/v1/guilds/100/notes",
            json={"user_id": "999", "content": "hi"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_in_two_bark_servers_does_not_500_admission(db, monkeypatch):
    """Reported prod case: an invited user who belongs to MORE than one server
    where Bark is installed previously crashed the admission check with
    MultipleResultsFound (scalar_one_or_none on a multi-row scan), 500ing every
    request. Membership in any Bark server must admit them."""
    import config
    from database.models.guild import GuildSetting

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="moderator"))
        session.add(InstanceAccess(discord_user_id="42"))
        session.add(Guild(discord_id="100", name="First Bark Server", owner_id="42"))
        session.add(Guild(discord_id="200", name="Second Bark Server", owner_id="42"))
        # Configured moderator role in BOTH servers — under the explicit-roles
        # model this is what grants dashboard moderation (permissions alone
        # never do).
        session.add(
            GuildSetting(guild_id="100", key="dashboard_moderator_roles", value='["555"]')
        )
        session.add(
            GuildSetting(guild_id="200", key="dashboard_moderator_roles", value='["555"]')
        )
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [
                {"id": "100", "name": "First Bark Server", "permissions": str(0x20)},
                {"id": "200", "name": "Second Bark Server", "permissions": str(2147483647)},
            ],
            roles_by_guild={"100": ["555"], "200": ["555"]},
        )

    bot_guilds = []
    for guild_id in (100, 200):
        guild = MagicMock()
        guild.id = guild_id
        guild.name = f"Bark Server {guild_id}"
        guild.icon = None
        bot_guilds.append(guild)
    bot = MagicMock()
    bot.guilds = bot_guilds
    bot.get_guild.side_effect = lambda guild_id: next(
        (g for g in bot_guilds if g.id == guild_id), None
    )
    app = _dashboard_app(bot)
    bot.modules.get_module.return_value = _module_stub()
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "moderator"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        response = await client.get("/guild/200/modules/announcements")

    assert response.status_code == 200
    # Guild 200's user has full Discord permissions (administrator) -> admin.
    assert 'data-user-role="admin"' in response.text


# ── Per-server "Ready to manage" (owner-configured moderator roles) ──


def test_parse_moderator_role_ids_accepts_json_and_csv():
    from services.dashboard_access import parse_moderator_role_ids

    assert parse_moderator_role_ids(None) == set()
    assert parse_moderator_role_ids("") == set()
    assert parse_moderator_role_ids('["111","222"]') == {"111", "222"}
    assert parse_moderator_role_ids("111, 222") == {"111", "222"}
    assert parse_moderator_role_ids("not-json") == {"not-json"}


def test_user_ready_to_manage_owner_or_configured_staff_roles_only():
    from services.dashboard_access import user_ready_to_manage

    mod_roles = {"555"}
    admin_role = "777"

    def access(**overrides):
        base = {
            "guild_id": "100",
            "name": "Server",
            "permissions": 0,
            "owner": False,
            "roles": "",
        }
        base.update(overrides)
        return type("Access", (), base)()

    # Server owner is always ready to manage.
    assert user_ready_to_manage(access(owner=True), mod_roles, admin_role)
    # Holding the owner-configured admin role grants access…
    assert user_ready_to_manage(access(roles="111,777"), mod_roles, admin_role)
    # …or a configured moderator role.
    assert user_ready_to_manage(access(roles="111,555,666"), mod_roles, admin_role)
    # A plain member without any staff role is not ready to manage.
    assert not user_ready_to_manage(access(roles="111,666"), mod_roles, admin_role)
    assert not user_ready_to_manage(access(), mod_roles, admin_role)
    # Discord permissions NEVER imply dashboard access (explicit roles only).
    assert not user_ready_to_manage(access(permissions=0x8), mod_roles, admin_role)
    assert not user_ready_to_manage(access(permissions=0x20), mod_roles, admin_role)
    assert not user_ready_to_manage(access(permissions=0x8), set(), None)
    assert not user_ready_to_manage(access(permissions=0x20), set(), None)
    # The Bark instance owner manages every server their bot is in, even as a
    # plain member with no configured staff role — so two owners' bots can
    # share a server without blocking each other.
    assert user_ready_to_manage(access(), mod_roles, admin_role, is_instance_owner=True)
    assert user_ready_to_manage(access(roles=""), mod_roles, None, is_instance_owner=True)
    assert user_ready_to_manage(access(roles="111,666"), mod_roles, admin_role, is_instance_owner=True)


def test_parse_admin_role_id_accepts_json_and_plain():
    from services.dashboard_access import parse_admin_role_id

    assert parse_admin_role_id(None) is None
    assert parse_admin_role_id("") is None
    assert parse_admin_role_id('"555"') == "555"
    assert parse_admin_role_id("555") == "555"


@pytest.mark.asyncio
async def test_get_dashboard_admin_role_loads_per_guild_setting(db):
    from database.models.guild import Guild, GuildSetting
    from services.dashboard_access import get_dashboard_admin_role

    async with session_scope() as session:
        session.add(Guild(discord_id="100", name="Alpha"))
        session.add(Guild(discord_id="200", name="Beta"))
        session.add(
            GuildSetting(guild_id="100", key="dashboard_admin_role", value='"777"')
        )
        await session.flush()

    async with session_scope() as session:
        roles = await get_dashboard_admin_role(session, ["100", "200", "300"])

    assert roles == {"100": "777"}
    assert roles.get("200") is None
    assert roles.get("300") is None


def test_role_from_access_tiers_from_discord_authority_and_configured_roles():
    from services.dashboard_access import role_from_access, role_from_access_with_staff_roles

    # Login-time derivation: owner / ADMINISTRATOR -> admin, MANAGE_GUILD -> mod.
    assert role_from_access(owner=True, permissions=0) == "admin"
    assert role_from_access(owner=False, permissions=0x8) == "admin"
    assert role_from_access(owner=False, permissions=0x20) == "moderator"
    assert role_from_access(owner=False, permissions=0) == "viewer"

    # Per-guild middleware derivation: Discord authority + configured roles.
    def access(**overrides):
        base = {"guild_id": "100", "permissions": 0, "owner": False, "roles": ""}
        base.update(overrides)
        return type("Access", (), base)()

    assert role_from_access_with_staff_roles(access(owner=True), {"555"}, "777") == "admin"
    assert role_from_access_with_staff_roles(access(roles="111,777"), {"555"}, "777") == "admin"
    assert role_from_access_with_staff_roles(access(roles="111,555"), {"555"}, "777") == "moderator"
    assert role_from_access_with_staff_roles(access(roles="111,666"), {"555"}, "777") == "viewer"
    # Discord permissions map to roles too (consistent with derive_dashboard_role).
    assert role_from_access_with_staff_roles(access(permissions=0x8), {"555"}, "777") == "admin"
    assert role_from_access_with_staff_roles(access(permissions=0x20), {"555"}, "777") == "moderator"
    assert role_from_access_with_staff_roles(access(permissions=0x8), set(), None) == "admin"
    # The Bark instance owner is admin for every server their bot is in, even
    # without server ownership or a configured staff role.
    assert role_from_access_with_staff_roles(
        access(), {"555"}, "777", is_instance_owner=True
    ) == "admin"
    assert role_from_access_with_staff_roles(
        access(roles=""), set(), None, is_instance_owner=True
    ) == "admin"


@pytest.mark.asyncio
async def test_get_dashboard_moderator_roles_loads_per_guild_setting(db):
    from database.models.guild import Guild, GuildSetting
    from services.dashboard_access import get_dashboard_moderator_roles

    async with session_scope() as session:
        session.add(Guild(discord_id="100", name="Alpha"))
        session.add(Guild(discord_id="200", name="Beta"))
        session.add(
            GuildSetting(
                guild_id="100",
                key="dashboard_moderator_roles",
                value='["555","666"]',
            )
        )
        await session.flush()

    async with session_scope() as session:
        roles = await get_dashboard_moderator_roles(session, ["100", "200", "300"])

    assert roles == {"100": {"555", "666"}}
    assert roles.get("200", set()) == set()
    assert roles.get("300", set()) == set()


@pytest.mark.asyncio
async def test_replace_user_guild_access_persists_roles_snapshot(db):
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Alpha", "permissions": "0"}],
            roles_by_guild={"100": ["555", "666"]},
        )

    async with session_scope() as session:
        rows = await get_user_guild_access(session, "42")

    assert rows[0].roles == "555,666"
    assert rows[0].can_manage is False


def test_catalog_marks_ready_to_manage_per_server_from_configured_roles():
    from services.dashboard_access import build_guild_catalog

    def access(guild_id, permissions=0, roles=""):
        return type(
            "Access",
            (),
            {
                "guild_id": guild_id,
                "name": f"Server {guild_id}",
                "icon_hash": None,
                "owner": False,
                "permissions": permissions,
                "can_manage": False,
                "roles": roles,
            },
        )()

    oauth_guilds = [
        access("100", roles="555"),   # holds configured moderator role
        access("200"),                # plain member of a connected server
        access("300"),                # uninstalled server, can manage
    ]
    bot_guilds = []
    for guild_id in (100, 200):
        guild = type(
            "Guild",
            (),
            {"id": guild_id, "name": f"Server {guild_id}", "member_count": 5, "icon": None},
        )()
        bot_guilds.append(guild)

    catalog = build_guild_catalog(
        oauth_guilds,
        bot_guilds,
        client_id="123",
        moderator_roles_by_guild={"100": {"555"}},
        public_url="http://test.local",
    )
    by_id = {entry["id"]: entry for entry in catalog}

    assert by_id["100"]["access_tier"] == "connected"
    assert by_id["100"]["ready_to_manage"] is True
    assert by_id["200"]["access_tier"] == "connected"
    assert by_id["200"]["ready_to_manage"] is False
    assert by_id["300"]["access_tier"] == "other"
    assert by_id["300"]["ready_to_manage"] is False


def test_catalog_instance_owner_does_not_grant_blanket_manage():
    """Running the Bark instance grants nothing per-server: the instance owner
    is treated like any other member unless they own the server or hold a
    configured staff role there."""
    from services.dashboard_access import build_guild_catalog

    def access(guild_id, roles=""):
        return type(
            "Access",
            (),
            {
                "guild_id": guild_id,
                "name": f"Server {guild_id}",
                "icon_hash": None,
                "owner": False,
                "permissions": 0,
                "can_manage": False,
                "roles": roles,
            },
        )()

    bot_guilds = [
        type(
            "Guild", (), {"id": 100, "name": "Server 100", "member_count": 5, "icon": None}
        )()
    ]

    # A plain member of a connected server is NOT manageable — even when they
    # are the Bark instance owner.
    catalog = build_guild_catalog([access("100")], bot_guilds, client_id="123", is_instance_owner=True)
    assert catalog[0]["access_tier"] == "connected"
    assert catalog[0]["ready_to_manage"] is False
    assert catalog[0]["manage_reason"] is None


def test_catalog_manage_reason_explains_the_grant():
    """Each manageable server carries a human-readable reason for the grant."""
    from services.dashboard_access import build_guild_catalog

    def access(guild_id, *, owner=False, roles="", permissions=0):
        return type(
            "Access",
            (),
            {
                "guild_id": guild_id,
                "name": f"Server {guild_id}",
                "icon_hash": None,
                "owner": owner,
                "permissions": permissions,
                "can_manage": False,
                "roles": roles,
            },
        )()

    bot_guilds = [
        type(
            "Guild", (), {"id": gid, "name": f"Server {gid}", "member_count": 5, "icon": None}
        )()
        for gid in (100, 200, 300, 400)
    ]
    catalog = build_guild_catalog(
        [
            access("100", owner=True),
            access("200", roles="111"),
            access("300", roles="222"),
            access("400"),
        ],
        bot_guilds,
        client_id="123",
        moderator_roles_by_guild={"200": {"111"}},
        admin_roles_by_guild={"300": "222"},
        public_url="http://test.local",
    )
    by_id = {e["id"]: e for e in catalog}
    assert by_id["100"]["manage_reason"] == "You own this server"
    assert by_id["200"]["manage_reason"] == "You have this server's Moderator role"
    assert by_id["300"]["manage_reason"] == "You have this server's Admin role"
    assert by_id["400"]["manage_reason"] is None
    assert by_id["400"]["ready_to_manage"] is False


@pytest.mark.asyncio
async def test_dashboard_shows_view_only_for_connected_server_without_staff_rights(db, monkeypatch):
    """A member of a connected server without admin/moderator rights sees the
    card as view-only — "Ready to manage" is per-server, not blanket."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        session.add(InstanceAccess(discord_user_id="42"))
        session.add(Guild(discord_id="100", name="Connected", owner_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": "0"}],
            roles_by_guild={"100": ["111"]},
        )
        from database.models.guild import GuildSetting

        session.add(
            GuildSetting(
                guild_id="100",
                key="dashboard_moderator_roles",
                value='["555"]',
            )
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
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard")

    assert response.status_code == 200
    assert "Connected to Bark" in response.text
    assert "View only" in response.text
    # The card stays openable (a connected link) — non-granted members get the
    # view-only status page, not a lock.
    assert 'class="guild-card guild-card-connected"' in response.text


@pytest.mark.asyncio
async def test_dashboard_ready_to_manage_for_owner_configured_moderator_role(db, monkeypatch):
    """A member holding the server's configured moderator role is shown as
    ready to manage that server."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        session.add(InstanceAccess(discord_user_id="42"))
        session.add(Guild(discord_id="100", name="Connected", owner_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": "0"}],
            roles_by_guild={"100": ["555"]},
        )
        from database.models.guild import GuildSetting

        session.add(
            GuildSetting(
                guild_id="100",
                key="dashboard_moderator_roles",
                value='["555"]',
            )
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
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "viewer"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        response = await client.get("/dashboard")

    assert response.status_code == 200
    assert "<p>Ready to manage</p>" in response.text
    assert "Ready to manage" in response.text


@pytest.mark.asyncio
async def test_roles_api_flags_administrator_roles(db, monkeypatch):
    """The guild roles API marks roles with the ADMINISTRATOR permission so
    the Dashboard Access card can list admin roles by name."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="moderator"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": str(0x20), "owner": True}],
        )

    def role(role_id, name, permissions):
        return type(
            "Role",
            (),
            {"id": role_id, "name": name, "color": None, "permissions": permissions},
        )()

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Connected"
    bot_guild.icon = None
    bot_guild.roles = [
        role(100, "@everyone", 0),
        role(555, "Pleb", 0),
        role(556, "Big Admin", 0x8),
        role(557, "Admin+Manage", 0x8 | 0x20),
    ]
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda guild_id: bot_guild if guild_id == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "moderator"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
    ) as client:
        response = await client.get("/api/v1/guilds/100/roles")

    assert response.status_code == 200
    roles = response.json()["data"]["roles"]
    flags = {entry["name"]: entry["administrator"] for entry in roles}
    assert flags == {"Pleb": False, "Big Admin": True, "Admin+Manage": True}


@pytest.mark.asyncio
async def test_settings_redacts_staff_roles_for_moderator(db, monkeypatch):
    """The staff-role security config (who can moderate/admin Bark here) must
    be redacted from the settings dump for moderators and below — only admins
    and owners see role IDs."""
    import config
    from database.models.guild import Guild, GuildSetting

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    async with session_scope() as session:
        session.add(Guild(discord_id="100", name="Connected"))
        session.add(GuildSetting(guild_id="100", key="dashboard_moderator_roles", value='["555"]'))
        session.add(GuildSetting(guild_id="100", key="dashboard_admin_role", value="777"))
        session.add(GuildSetting(guild_id="100", key="prefix", value="!"))
        session.add(DashboardUser(discord_id="42", username="Cody", role="moderator"))
        session.add(InstanceAccess(discord_user_id="42"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Connected", "permissions": str(0x20), "owner": False}],
        )

    bot_guild = MagicMock()
    bot_guild.id = 100
    bot_guild.name = "Connected"
    bot_guild.icon = None
    bot = MagicMock()
    bot.guilds = [bot_guild]
    bot.get_guild.side_effect = lambda gid: bot_guild if gid == 100 else None
    app = _dashboard_app(bot)
    cookie = _session_cookie({"user": {"id": "42", "username": "Cody"}, "role": "moderator"})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies=dict(session=cookie),
        follow_redirects=False,
    ) as client:
        response = await client.get("/api/v1/guilds/100/settings")

    assert response.status_code == 200
    settings = response.json()["data"]["settings"]
    assert settings.get("prefix") == "!"  # benign settings still visible
    assert "dashboard_moderator_roles" not in settings  # staff-role IDs redacted
    assert "dashboard_admin_role" not in settings


@pytest.mark.asyncio
async def test_csrf_rejects_untrusted_origin_and_allows_trusted(db, monkeypatch):
    """State-changing /api requests with an untrusted Origin must be rejected;
    a trusted Origin passes the CSRF gate."""
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    bot = MagicMock()
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    app = _dashboard_app(bot)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Untrusted Origin (an attacker's site) -> CSRF gate rejects.
        evil = await client.post(
            "/api/v1/guilds/100/notes", json={}, headers={"Origin": "http://evil.example"}
        )
        assert evil.status_code == 403
        assert "Cross-origin" in evil.json()["error"]
        # Trusted Origin (the Bark dashboard host) -> passes the CSRF gate.
        trusted = await client.post(
            "/api/v1/guilds/100/notes",
            json={},
            headers={"Origin": "http://10.0.0.227:8091"},
        )
        assert "Cross-origin" not in (trusted.text or "")


@pytest.mark.asyncio
async def test_revoke_user_guild_access_deletes_only_that_user_guild_pair(db):
    """A user removed from a guild must lose dashboard access to it immediately."""
    from services.dashboard_access import revoke_user_guild_access

    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))

    login = [
        {"id": "100", "name": "Alpha", "icon": None, "owner": True, "permissions": "0"},
        {"id": "200", "name": "Beta", "icon": None, "owner": False, "permissions": str(0x20)},
    ]
    async with session_scope() as session:
        await replace_user_guild_access(session, "42", login)

    # Revoke only user 42's access to guild 100; guild 200 must remain.
    async with session_scope() as session:
        revoked = await revoke_user_guild_access(session, "42", 100)
        assert revoked is True

    async with session_scope() as session:
        rows = await get_user_guild_access(session, "42")
        assert [row.guild_id for row in rows] == ["200"]

    # Second call (row already gone) reports no change.
    async with session_scope() as session:
        assert await revoke_user_guild_access(session, "42", 100) is False

    # Other users' rows for the same guild are untouched.
    async with session_scope() as session:
        session.add(DashboardUser(discord_id="99", username="Other", role="viewer"))
    async with session_scope() as session:
        await replace_user_guild_access(
            session,
            "99",
            [{"id": "100", "name": "Alpha", "icon": None, "owner": False, "permissions": "0"}],
        )
    async with session_scope() as session:
        rows = await get_user_guild_access(session, "99")
        assert [row.guild_id for row in rows] == ["100"]
