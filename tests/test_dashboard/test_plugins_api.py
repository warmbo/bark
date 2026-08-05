"""API tests for single-file plugin install/remove (dashboard/routes/api/plugins.py).

Uses a real ModuleManager (not a MagicMock) so uploads genuinely install and
removing a plugin genuinely unloads it, including the guarded API routes.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

VALID_PLUGIN = '''
from modules.base import BarkModule, CommandRegistration

class PingPlugin(BarkModule):
    name = "ping_plugin"
    version = "1.0.0"
    description = "A tiny test plugin"

    def get_commands(self):
        return [CommandRegistration(name="ping", description="Ping!")]

    async def enable(self):
        pass

    async def disable(self):
        pass
'''

ROUTED_PLUGIN = '''
from modules.base import BarkModule
from fastapi import APIRouter

class RoutedPlugin(BarkModule):
    name = "routed_plugin"
    version = "1.0.0"
    description = "Plugin with an API route"

    def get_api_routes(self):
        router = APIRouter(tags=["plugin-routed"])

        @router.get("/guilds/{guild_id}/modules/routed_plugin/ping")
        async def ping(guild_id: str):
            return {"success": True, "data": {"pong": "ok"}}

        return router

    async def enable(self):
        pass

    async def disable(self):
        pass
'''


class FakeBot:
    """Bot stand-in backed by a REAL ModuleManager."""

    def __init__(self):
        from services.event_bus import EventBus
        from services.module_manager import ModuleManager

        self._event_bus = EventBus()
        self._module_manager = ModuleManager(self)
        self.app = None
        self.guilds = []
        self.tree = None
        self.user = None

    @property
    def modules(self):
        return self._module_manager

    def is_ready(self):
        return False

    def get_guild(self, guild_id):
        return None


@pytest_asyncio.fixture
async def app(db):
    """Full dashboard app with a real module manager (permissive OAuth mode)."""
    from dashboard import create_app

    bot = FakeBot()
    dashboard_app = create_app(bot)
    return dashboard_app.app


@pytest_asyncio.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── List ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_plugins_empty(client):
    resp = await client.get("/api/v1/instance/plugins")
    assert resp.status_code == 200
    assert resp.json()["data"]["plugins"] == []


@pytest.mark.asyncio
async def test_list_plugins_after_install(client):
    await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("ping.py", VALID_PLUGIN.encode(), "text/x-python")},
    )
    resp = await client.get("/api/v1/instance/plugins")
    data = resp.json()["data"]["plugins"]
    assert len(data) == 1
    assert data[0]["name"] == "ping_plugin"
    assert data[0]["enabled"] is True
    assert data[0]["file"] == "ping_plugin.py"


# ── Install ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_plugin_returns_metadata(client):
    resp = await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("ping.py", VALID_PLUGIN.encode(), "text/x-python")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["name"] == "ping_plugin"


@pytest.mark.asyncio
async def test_install_rejects_invalid_file(client):
    resp = await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("notes.txt", b"not a plugin", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_install_rejects_broken_plugin(client):
    resp = await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("broken.py", b"def not valid( !!!", "text/x-python")},
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False


# ── Remove ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_plugin_unloads_and_guards_routes(client):
    # Install a plugin that contributes an API route.
    resp = await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("routed.py", ROUTED_PLUGIN.encode(), "text/x-python")},
    )
    assert resp.status_code == 200

    # Its route is live while installed.
    live = await client.get("/api/v1/guilds/1/modules/routed_plugin/ping")
    assert live.status_code == 200
    assert live.json()["data"]["pong"] == "ok"

    # Removing it works and the route becomes inert (404 via the guard).
    removed = await client.delete("/api/v1/instance/plugins/routed_plugin")
    assert removed.status_code == 200
    assert removed.json()["success"] is True

    gone = await client.get("/api/v1/guilds/1/modules/routed_plugin/ping")
    assert gone.status_code == 404

    # File is deleted from the plugin directory.
    from services.plugin_manager import plugins_directory

    assert not (plugins_directory() / "routed_plugin.py").exists()


@pytest.mark.asyncio
async def test_remove_core_module_is_404(client):
    resp = await client.delete("/api/v1/instance/plugins/reputation")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_missing_plugin_is_404(client):
    resp = await client.delete("/api/v1/instance/plugins/does_not_exist")
    assert resp.status_code == 404


# ── Owner gating ─────────────────────────────────────


@pytest.mark.asyncio
async def test_plugins_api_requires_owner_when_oauth_configured(app, client, monkeypatch):
    """With OAuth configured, unauthenticated calls are rejected by middleware
    and the owner gate denies non-owner sessions."""
    import config as cfg

    # oauth2.enabled is a read-only property; enable it via its inputs.
    monkeypatch.setattr(cfg.config.oauth2, "client_id", "test-client")
    monkeypatch.setattr(cfg.config.oauth2, "client_secret", "test-secret")
    monkeypatch.setattr(cfg.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(cfg.config.oauth2, "owner_discord_ids", {"111"})
    assert cfg.config.oauth2.enabled is True

    # No session user → middleware rejects before the owner gate.
    resp = await client.get("/api/v1/instance/plugins")
    assert resp.status_code in (401, 403)
    resp = await client.post(
        "/api/v1/instance/plugins",
        files={"file": ("ping.py", VALID_PLUGIN.encode(), "text/x-python")},
    )
    assert resp.status_code in (401, 403)
    resp = await client.delete("/api/v1/instance/plugins/ping_plugin")
    assert resp.status_code in (401, 403)


def test_can_manage_plugins_owner_gate(monkeypatch):
    """The owner gate itself: allowlist owners pass, everyone else is denied."""
    import config as cfg
    from dashboard.routes.api.plugins import _can_manage_plugins

    monkeypatch.setattr(cfg.config.oauth2, "client_id", "test-client")
    monkeypatch.setattr(cfg.config.oauth2, "client_secret", "test-secret")
    monkeypatch.setattr(cfg.config.oauth2, "redirect_uri", "http://test/auth/callback")
    monkeypatch.setattr(cfg.config.oauth2, "owner_discord_ids", {"111"})

    class FakeRequest:
        def __init__(self, user_id):
            self.session = {"user": {"id": user_id}} if user_id else {}

    assert _can_manage_plugins(FakeRequest("111")) is True
    assert _can_manage_plugins(FakeRequest("222")) is False
    assert _can_manage_plugins(FakeRequest(None)) is False

    # Permissive mode (no OAuth): everything is allowed.
    monkeypatch.setattr(cfg.config.oauth2, "client_id", "")
    monkeypatch.setattr(cfg.config.oauth2, "client_secret", "")
    monkeypatch.setattr(cfg.config.oauth2, "redirect_uri", "")
    monkeypatch.setattr(cfg.config.oauth2, "owner_discord_ids", set())
    assert _can_manage_plugins(FakeRequest(None)) is True
