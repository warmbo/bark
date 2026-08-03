from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.security import (
    AuthMiddleware,
    RateLimiter,
    SecurityMiddleware,
    _module_action_from_path,
    mutation_capability,
    rate_limit_identity,
)


def test_module_action_path_only_matches_runtime_actions():
    assert _module_action_from_path("/api/v1/guilds/123/modules/logging/test") == (
        123,
        "logging",
        "test",
    )
    assert _module_action_from_path("/api/v1/guilds/123/modules/logging/toggle") is None
    assert _module_action_from_path("/api/v1/guilds/123/modules/logging") is None


@pytest.mark.asyncio
async def test_disabled_module_runtime_action_is_rejected():
    app = FastAPI()
    bot = MagicMock()
    bot.modules.is_enabled_for_guild.return_value = False
    app.state.bot = bot
    app.add_middleware(SecurityMiddleware)

    @app.post("/api/v1/guilds/{guild_id}/modules/{module_name}/test")
    async def action(guild_id: int, module_name: str):
        return {"executed": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/guilds/123/modules/logging/test")

    assert response.status_code == 409
    assert response.json()["error"] == "Module 'logging' is disabled for this server"


@pytest.mark.asyncio
async def test_cross_origin_api_write_is_rejected():
    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.post("/api/v1/save")
    async def save():
        return {"saved": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://bark.warx.org"
    ) as client:
        response = await client.post("/api/v1/save", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert response.json()["error"] == "Cross-origin write rejected"


@pytest.mark.asyncio
async def test_public_https_configuration_emits_hsts(monkeypatch):
    import config

    monkeypatch.setattr(config.config.dashboard, "force_https", True)

    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.get("/")
    async def index():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://bark.warx.org"
    ) as client:
        response = await client.get("/")

    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_mutation_capabilities_cover_every_route_family_and_gets_remain_readable():
    assert mutation_capability("GET", "/api/v1/guilds/1/settings/general") is None
    assert mutation_capability("POST", "/api/v1/guilds/1/actions/warn") == "moderation.warn"
    assert mutation_capability("PUT", "/api/v1/guilds/1/settings/logging") == "logging.configure"
    assert (
        mutation_capability("POST", "/api/v1/guilds/1/modules/roles/create_role_menu")
        == "roles.manage"
    )
    assert mutation_capability("POST", "/api/v1/guilds/1/modules/post/compose") == "post.manage"
    assert mutation_capability("POST", "/api/v1/guilds/1/notes") == "moderation.notes.create"
    assert mutation_capability("PATCH", "/api/v1/guilds/1/notes/42") == "moderation.notes.create"
    assert mutation_capability("DELETE", "/api/v1/guilds/1/notes/42") == "moderation.notes.create"
    assert mutation_capability("DELETE", "/api/v1/guilds/1/unknown/new-route") == "guild.manage"


def test_rate_limiter_bounds_and_prunes_inactive_buckets(monkeypatch):
    import services.security as security

    limiter = RateLimiter(capacity=10, max_keys=3)
    monkeypatch.setattr(security.time, "monotonic", lambda: 0.0)
    for key in ("one", "two", "three", "four"):
        assert limiter.check(key)
    assert len(limiter.tokens) == 3
    assert "one" not in limiter.tokens

    monkeypatch.setattr(security.time, "monotonic", lambda: 61.0)
    assert limiter.check("five")
    assert set(limiter.tokens) == {"five"}


def test_rate_limit_identity_prefers_authenticated_user_over_proxy_ip():
    request = MagicMock()
    request.scope = {"session": {"user": {"id": "42"}}}
    request.client.host = "10.0.0.1"

    assert rate_limit_identity(request) == "user:42"


def test_dashboard_middleware_exposes_session_to_security_layer():
    from starlette.middleware.sessions import SessionMiddleware

    from dashboard import create_app

    dashboard = create_app(MagicMock())
    middleware = [entry.cls.__name__ for entry in dashboard.app.user_middleware]

    assert middleware.index(SessionMiddleware.__name__) < middleware.index(
        SecurityMiddleware.__name__
    )
    assert middleware.index(SecurityMiddleware.__name__) < middleware.index(AuthMiddleware.__name__)


@pytest.mark.asyncio
async def test_oauth_mutation_rbac_denies_viewer_and_allows_admin(monkeypatch):
    import base64
    import json

    from itsdangerous import TimestampSigner
    from starlette.middleware.sessions import SessionMiddleware

    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "client")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/callback")

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    @app.api_route("/api/v1/save", methods=["GET", "POST"])
    async def save():
        return {"saved": True}

    def cookie(role):
        data = {"user": {"id": "42"}, "role": role}
        payload = base64.b64encode(json.dumps(data).encode())
        return TimestampSigner("test-secret").sign(payload).decode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", cookie("viewer"))
        viewer_write = await client.post("/api/v1/save")
        viewer_read = await client.get("/api/v1/save")
        client.cookies.set("session", cookie("admin"))
        admin_write = await client.post("/api/v1/save")

    assert viewer_write.status_code == 403
    assert viewer_write.json()["required_capability"] == "guild.manage"
    assert viewer_read.status_code == 200
    assert admin_write.status_code == 200


@pytest.mark.asyncio
async def test_oauth_disabled_mutation_mode_remains_permissive(monkeypatch):
    import config

    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.post("/api/v1/save")
    async def save():
        return {"saved": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/save")

    assert response.status_code == 200
