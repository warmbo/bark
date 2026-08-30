from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.security import (
    AuthMiddleware,
    RateLimiter,
    SecurityMiddleware,
    _apply_security_headers,
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
async def test_lan_origin_api_write_is_allowed(monkeypatch):
    """Direct LAN access (http://10.0.0.227:8091) is a supported dashboard
    path, so state-changing requests from that origin must not be treated
    as cross-origin — when the operator lists it in BARK_TRUSTED_ORIGINS."""
    import config

    monkeypatch.setattr(
        config.config.dashboard, "trusted_origins", ["http://10.0.0.227:8091"]
    )

    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.post("/api/v1/save")
    async def save():
        return {"saved": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://10.0.0.227:8091"
    ) as client:
        response = await client.post(
            "/api/v1/save", headers={"Origin": "http://10.0.0.227:8091"}
        )

    assert response.status_code == 200
    assert response.json() == {"saved": True}


@pytest.mark.asyncio
async def test_same_host_different_port_origin_is_rejected(monkeypatch):
    """A second service on the same host (different port) must NOT pass CSRF —
    SameSite=Lax treats same-host/different-port as same-site, so the origin
    check is the only remaining defense."""
    import config

    monkeypatch.setattr(
        config.config.dashboard, "trusted_origins", ["http://10.0.0.227:8091"]
    )

    app = FastAPI()
    app.add_middleware(SecurityMiddleware)

    @app.post("/api/v1/save")
    async def save():
        return {"saved": True}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://10.0.0.227:8091"
    ) as client:
        response = await client.post(
            "/api/v1/save", headers={"Origin": "http://10.0.0.227:8080"}
        )

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
    assert (
        mutation_capability("POST", "/api/v1/guilds/1/modules/announcements/post")
        == "announcements.post"
    )
    assert (
        mutation_capability(
            "PATCH", "/api/v1/guilds/1/modules/announcements/schedules/42"
        )
        == "announcements.post"
    )
    assert (
        mutation_capability(
            "DELETE", "/api/v1/guilds/1/modules/announcements/schedules/42"
        )
        == "announcements.post"
    )
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
        # Send cookies explicitly per-request. Sliding renewal re-emits
        # Set-Cookie on every authenticated response, which makes manual
        # client.cookies.set() calls collide in httpx's jar — real browsers
        # replace the cookie, httpx does not.
        viewer_write = await client.post(
            "/api/v1/save", headers={"cookie": f"session={cookie('viewer')}"}
        )
        viewer_read = await client.get(
            "/api/v1/save", headers={"cookie": f"session={cookie('viewer')}"}
        )
        admin_write = await client.post(
            "/api/v1/save", headers={"cookie": f"session={cookie('admin')}"}
        )

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


@pytest.mark.asyncio
async def test_authenticated_request_renews_sliding_session(monkeypatch):
    """Every authenticated request re-signs the cookie (fresh Max-Age) so an
    active user never hits the session_ttl wall — inactivity is what expires
    the login, not elapsed time."""
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
    app.add_middleware(SessionMiddleware, secret_key="test-secret", max_age=3600)

    @app.get("/api/v1/private")
    async def private():
        return {"ok": True}

    data = {"user": {"id": "42"}, "role": "admin"}
    payload = base64.b64encode(json.dumps(data).encode())
    cookie = TimestampSigner("test-secret").sign(payload).decode()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/private", headers={"cookie": f"session={cookie}"}
        )

    assert response.status_code == 200
    # The middleware must have written _renewed back into the session, which
    # causes Starlette to re-emit a Set-Cookie with a fresh Max-Age.
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "Max-Age=3600" in set_cookie
    # Verify the re-signed payload actually contains the renewal marker.
    raw = set_cookie.split("session=", 1)[1].split(";", 1)[0]
    unsigned = TimestampSigner("test-secret").unsign(raw, max_age=3600)
    decoded = json.loads(base64.b64decode(unsigned))
    assert "_renewed" in decoded


def test_csp_allows_no_unused_external_cdns():
    """The CSP must not allow unused external script/style/font CDNs (unpkg,
    googleapis, fonts). Removing them eliminates a supply-chain / XSS-via-CDN
    class of risk since no page loads from them."""
    from types import SimpleNamespace

    from fastapi.responses import Response

    resp = Response()
    cfg = SimpleNamespace(dashboard=SimpleNamespace(secure_cookies=False))
    _apply_security_headers(resp, cfg)
    csp = resp.headers["Content-Security-Policy"]

    # Must NOT allow the stale external CDNs.
    for forbidden in ("unpkg.com", "googleapis.com", "fonts.gstatic.com", "fonts.googleapis.com"):
        assert forbidden not in csp, f"CSP still allows unused CDN: {forbidden}"

    # Must keep self + discord CDN (avatars/banners/emojis) + realtime ws.
    assert "default-src 'self'" in csp
    assert "https://cdn.discordapp.com" in csp
    assert "ws:" in csp and "wss:" in csp
    assert "frame-ancestors 'none'" in csp
    # Related hardening headers.
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"

