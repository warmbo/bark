"""First-time setup: config flag, .env writer, and wizard API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from services import setup_service
from services.setup_service import SetupError


@pytest.fixture
def fresh_env(tmp_path, monkeypatch):
    """Point the .env writer at a temp dir and mark the instance unconfigured."""
    monkeypatch.setattr(setup_service, "_REPO_ROOT", tmp_path)
    return tmp_path


def test_needs_setup_true_without_token(monkeypatch):
    from config import config

    monkeypatch.setattr(config.bot, "token", "")
    assert config.needs_setup is True
    config.bot.token = "test_token_12345"
    assert config.needs_setup is False


def test_write_env_creates_dotenv(fresh_env):
    payload = {
        "token": "MTEz.abc.def",
        "public_url": "https://bark.example.com",
        "client_id": "123",
        "client_secret": "s3cret",
        "redirect_uri": "https://bark.example.com/auth/callback",
        "owner_ids": "111, 222",
    }
    path = setup_service.write_env(payload)
    content = path.read_text()
    assert "BARK_BOT_TOKEN=MTEz.abc.def" in content
    assert "BARK_OAUTH2_CLIENT_ID=123" in content
    assert "BARK_OAUTH2_CLIENT_SECRET=s3cret" in content
    assert 'BARK_OAUTH2_REDIRECT_URI=https://bark.example.com/auth/callback' in content
    assert 'BARK_OWNER_DISCORD_IDS="111, 222"' in content  # quoted (has space)
    assert "BARK_PUBLIC_URL=https://bark.example.com" in content
    # No prefix setting: commands are global slash commands under /bark.
    assert "BARK_COMMAND_PREFIX" not in content
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_write_env_skips_oauth_when_all_empty(fresh_env):
    payload = {"token": "MTEz.abc.def", "public_url": "https://bark.example.com"}
    content = setup_service.write_env(payload).read_text()
    assert "BARK_OAUTH2" not in content
    assert "BARK_OWNER_DISCORD_IDS" not in content


def test_write_env_refuses_when_dotenv_exists(fresh_env):
    (fresh_env / ".env").write_text("BARK_BOT_TOKEN=existing")
    with pytest.raises(SetupError, match="already exists"):
        setup_service.write_env({"token": "MTEz.abc.def", "public_url": "https://x.example"})
    assert "existing" in (fresh_env / ".env").read_text()  # untouched


def test_validate_rejects_bad_inputs(fresh_env):
    with pytest.raises(SetupError, match="token is required"):
        setup_service.write_env({"public_url": "https://x.example"})
    with pytest.raises(SetupError, match="doesn't look like"):
        setup_service.write_env({"token": "not-a-token", "public_url": "https://x.example"})
    with pytest.raises(SetupError, match="dashboard URL"):
        setup_service.write_env({"token": "MTEz.abc.def", "public_url": ""})
    with pytest.raises(SetupError, match="client ID and client secret"):
        setup_service.write_env(
            {"token": "MTEz.abc.def", "public_url": "https://x.example", "client_id": "123"}
        )
    with pytest.raises(SetupError, match="BARK_OWNER_DISCORD_IDS"):
        setup_service.write_env(
            {
                "token": "MTEz.abc.def",
                "public_url": "https://x.example",
                "client_id": "123",
                "client_secret": "s3cret",
            }
        )


# ── Wizard API ────────────────────────────────────────


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    from config import config
    from dashboard.routes import setup as setup_routes
    from dashboard.setup_app import create_setup_app

    monkeypatch.setattr(setup_service, "_REPO_ROOT", tmp_path)
    # conftest sets BARK_BOT_TOKEN for every test — force the unconfigured
    # state the setup wizard requires.
    monkeypatch.setattr(config.bot, "token", "")
    # The test host runs under systemd (PID 1) — don't actually schedule a
    # process exit during tests.
    monkeypatch.setattr(setup_routes, "_schedule_restart", lambda: False)
    return create_setup_app()


@pytest.mark.asyncio
async def test_setup_page_renders_when_unconfigured(setup_app):
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test"
    ) as client:
        response = await client.get("/setup")
    assert response.status_code == 200
    assert "Welcome to Bark" in response.text
    assert "Discord bot token" in response.text
    # Branding: the Bark logo image sits in the header (not just the title).
    assert 'class="setup-logo-img"' in response.text
    assert "/static/img/bark-avatar.png" in response.text


@pytest.mark.asyncio
async def test_root_redirects_to_setup(setup_app):
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test", follow_redirects=False
    ) as client:
        response = await client.get("/")
    assert response.status_code in (302, 303)
    assert "/setup" in response.headers["location"]


@pytest.mark.asyncio
async def test_setup_post_writes_dotenv(setup_app, tmp_path):
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup",
            json={
                "token": "MTEz.abc.def",
                "public_url": "https://bark.example.com",
                "client_id": "123",
                "client_secret": "s3cret",
                "redirect_uri": "",
                "owner_ids": "999",
            },
        )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["restarting"] is False
    assert (tmp_path / ".env").read_text().startswith("BARK_BOT_TOKEN=")


@pytest.mark.asyncio
async def test_setup_post_validation_error(setup_app, tmp_path):
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test"
    ) as client:
        response = await client.post("/api/setup", json={"token": "nope", "public_url": "https://x.example"})
    assert response.status_code == 400
    assert "doesn't look like" in response.json()["error"]
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_setup_post_refuses_when_already_configured(setup_app, tmp_path):
    (tmp_path / ".env").write_text("BARK_BOT_TOKEN=existing")
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/setup", json={"token": "MTEz.abc.def", "public_url": "https://x.example"}
        )
    assert response.status_code == 409
    assert "already exists" in response.json()["error"]


# ── Setup-token gate ──────────────────────────────


@pytest.mark.asyncio
async def test_setup_post_requires_token_when_configured(setup_app, tmp_path, monkeypatch):
    from config import config

    monkeypatch.setattr(config.dashboard, "setup_token", "s3cr3t-t0ken")
    async with AsyncClient(
        transport=ASGITransport(app=setup_app), base_url="http://test"
    ) as client:
        # Missing token → 403, no .env written.
        denied = await client.post(
            "/api/setup", json={"token": "MTEz.abc.def", "public_url": "https://x.example"}
        )
        assert denied.status_code == 403
        assert not (tmp_path / ".env").exists()
        # Correct token → accepted.
        ok = await client.post(
            "/api/setup",
            json={"token": "MTEz.abc.def", "public_url": "https://x.example"},
            headers={"X-Setup-Token": "s3cr3t-t0ken"},
        )
        assert ok.status_code == 200
        assert (tmp_path / ".env").read_text().startswith("BARK_BOT_TOKEN=")


def test_resolve_setup_host_forces_loopback_without_token():
    from dashboard.setup_app import resolve_setup_host

    assert resolve_setup_host("0.0.0.0", "") == "127.0.0.1"
    assert resolve_setup_host("10.0.0.227", "") == "127.0.0.1"
    assert resolve_setup_host("127.0.0.1", "") == "127.0.0.1"
    # A configured token permits a non-loopback bind (remote, token-gated setup).
    assert resolve_setup_host("0.0.0.0", "s3cr3t-t0ken") == "0.0.0.0"
