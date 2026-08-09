"""Authorization and behavior tests for the instance database backup endpoints."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner


def _session_cookie(user_id: str) -> str:
    session = {"user": {"id": user_id, "username": "BackupTester"}, "role": "admin"}
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
    return create_app(bot)


@pytest.mark.asyncio
async def test_list_backups_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),  # not the owner
    ) as client:
        response = await client.get("/api/v1/instance/backups")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_backup_requires_owner(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("43")),
    ) as client:
        response = await client.post("/api/v1/instance/backup")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_gate_fails_closed_when_no_owner_ids_configured(app, monkeypatch):
    """With OAuth enabled but owner_discord_ids empty, NOBODY may manage the
    instance (backups are full DB downloads — fail closed)."""
    import config

    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", set())
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.get("/api/v1/instance/backups")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_backup_lifecycle_create_list_download(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        created = await client.post("/api/v1/instance/backup")
        assert created.status_code == 200
        entry = created.json()["data"]
        filename = entry["filename"]
        assert filename.startswith("bark-backup-")
        assert entry["size"] > 0

        listed = await client.get("/api/v1/instance/backups")
        assert listed.status_code == 200
        backups = listed.json()["data"]["backups"]
        assert backups[0]["filename"] == filename

        downloaded = await client.get(f"/api/v1/instance/backup/{filename}")
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("application/octet-stream")
        # Snapshot must be a valid SQLite file.
        assert downloaded.content[:16] == b"SQLite format 3\x00"


@pytest.mark.asyncio
async def test_download_rejects_invalid_filenames(app):
    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("42")),
    ) as client:
        response = await client.get("/api/v1/instance/backup/passwd")
        assert response.status_code == 400

        traversal = await client.get(
            "/api/v1/instance/backup/..%2F..%2Fetc%2Fpasswd"
        )
        # Encoded slashes are normalized by the router before the handler — a
        # 404 there is still a safe rejection (never a 200).
        assert traversal.status_code in (400, 404)

        missing = await client.get(
            "/api/v1/instance/backup/bark-backup-20200101-000000-000000.db"
        )
        assert missing.status_code == 404
