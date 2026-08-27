"""Authorization and behavior tests for the instance self-update endpoints."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from dashboard.routes.api import updates as updates_api


def _session_cookie(user_id: str) -> str:
    session = {"user": {"id": user_id, "username": "Auditor"}, "role": "admin"}
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

    dashboard = create_app(bot)
    # Deterministic channel state for API tests (real git config is not
    # consulted); the one-way rule is exercised by dedicated tests below.
    monkeypatch.setattr(updates_api, "get_channel", lambda: "stable")
    return dashboard


@pytest.mark.asyncio
async def test_update_status_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),  # not the owner
    ) as client:
        response = await client.get("/api/v1/instance/update/status?branch=main")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_status_returns_build_info(app, monkeypatch):
    monkeypatch.setattr(
        updates_api,
        "check_update",
        lambda branch=None: {
            "channel": "stable",
            "branch": "master",
            "current_commit": "aaaaaaa",
            "current_branch": "main",
            "available_commit": "bbbbbbb",
            "update_available": True,
            "available_version": "0.2.190",
            "available_date": "2026-08-11T13:00:00+00:00",
            "repo_dir": "/tmp/repo",
            "error": "",
        },
    )
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.get("/api/v1/instance/update/status?branch=main")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["current_commit"] == "aaaaaaa"
    assert data["update_available"] is True
    assert data["channel"] == "stable"
    assert data["branch"] == "master"
    # The release date of the available version is surfaced to the UI.
    assert data["available_date"] == "2026-08-11T13:00:00+00:00"


@pytest.mark.asyncio
async def test_perform_update_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "main"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_perform_update_rejects_unknown_branch(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "hack/branch"}
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_perform_update_accepts_and_reports_restart(app, monkeypatch):
    started = []

    async def fake_apply(branch):
        started.append(branch)

    monkeypatch.setattr(updates_api, "apply_update_async", fake_apply)
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "dev"}
        )
    assert response.status_code == 200
    assert "restart" in response.json()["data"]["message"].lower()
    assert started == ["dev"]


@pytest.mark.asyncio
async def test_perform_update_rejects_stable_when_on_dev_channel(app, monkeypatch):
    """The Dev channel is one-way: once an instance is on Dev, updating to
    Stable (main) must be rejected."""
    monkeypatch.setattr(updates_api, "get_channel", lambda: "dev")
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "main"}
        )
    assert response.status_code == 403
    assert "switching back to Stable" in response.json()["error"]


@pytest.mark.asyncio
async def test_perform_update_allows_stable_when_on_stable_channel(app, monkeypatch):
    started = []

    async def fake_apply(branch):
        started.append(branch)

    monkeypatch.setattr(updates_api, "apply_update_async", fake_apply)
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "main"}
        )
    assert response.status_code == 200
    assert started == ["main"]


@pytest.mark.asyncio
async def test_perform_update_allows_dev_when_on_dev_channel(app, monkeypatch):
    started = []

    async def fake_apply(branch):
        started.append(branch)

    monkeypatch.setattr(updates_api, "get_channel", lambda: "dev")
    monkeypatch.setattr(updates_api, "apply_update_async", fake_apply)
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "dev"}
        )
    assert response.status_code == 200
    assert started == ["dev"]


# ── Live terminal log ─────────────────────────────────


@pytest.mark.asyncio
async def test_update_log_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),  # not the owner
    ) as client:
        response = await client.get("/api/v1/instance/update/log")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_log_streams_entries_and_after_cursor(app, monkeypatch):
    from services import update_service

    update_service.clear_update_log()
    update_service.set_update_phase("", done=False)
    update_service.log_line("$ git fetch github main", "cmd")
    update_service.log_line("✓ Already up to date", "ok")
    update_service.set_update_active(True)

    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        first = await client.get("/api/v1/instance/update/log")
        body = first.json()["data"]
        assert body["active"] is True
        assert len(body["entries"]) == 2
        assert body["entries"][0]["line"] == "$ git fetch github main"
        assert body["entries"][0]["level"] == "cmd"
        last = body["last"]
        assert last == 2

        # after=<last> returns only newer entries
        second = await client.get(f"/api/v1/instance/update/log?after={last}")
        assert second.json()["data"]["entries"] == []

        # progress state is exposed for the modal's progress bar
        update_service.set_update_phase("backup")
        third = await client.get("/api/v1/instance/update/log")
        assert third.json()["data"]["phase"] == "backup"
        assert third.json()["data"]["phases"] == ["fetch", "backup", "reset", "deps", "restart"]

        # active flag flips when the flow finishes
        update_service.set_update_active(False)
        update_service.set_update_phase("", done=True)
        fourth = await client.get("/api/v1/instance/update/log")
        assert fourth.json()["data"]["active"] is False
        assert fourth.json()["data"]["done"] is True

    update_service.clear_update_log()
    update_service.set_update_active(False)
    update_service.set_update_phase("", done=False)


@pytest.mark.asyncio
async def test_diagnostics_endpoint_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),  # not the owner
    ) as client:
        response = await client.get("/api/v1/instance/diagnostics")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_diagnostics_endpoint_downloads_plaintext_report(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),  # the owner
    ) as client:
        response = await client.get("/api/v1/instance/diagnostics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="bark-diagnostics-' in response.headers.get("content-disposition", "")
    assert "Bark diagnostic report" in response.text
    assert "[Config (redacted)]" in response.text


def _session_cookie_with_role(user_id: str, role: str) -> str:
    session = {"user": {"id": user_id, "username": "Auditor"}, "role": role}
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


@pytest.mark.asyncio
async def test_instance_owner_with_non_admin_session_can_update(app, monkeypatch):
    """Regression: an instance owner who isn't a Discord server admin (session
    role below admin) must still be able to update — the guild mutation
    middleware used to 403 instance routes because it mapped them to
    ``guild.manage`` (admin) instead of letting the route's owner check decide.

    Live report: Richard, owner of bark.richard.works, got 'You do not have
    permission to perform this action' on Update & Restart despite being the
    configured owner.
    """
    started = []

    async def fake_apply(branch):
        started.append(branch)

    monkeypatch.setattr(updates_api, "apply_update_async", fake_apply)
    # Owner is user "42"; session role is "viewer" (not a guild admin).
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie_with_role("42", "viewer")),
    ) as client:
        response = await client.post(
            "/api/v1/instance/update", json={"branch": "main"}
        )
    assert response.status_code == 200, response.text
    assert started == ["main"]
