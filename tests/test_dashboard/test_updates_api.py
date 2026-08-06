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
            "branch": branch or "main",
            "current_commit": "aaaaaaa",
            "current_branch": "main",
            "available_commit": "bbbbbbb",
            "update_available": True,
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
