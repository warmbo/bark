"""Announcements scheduling API integration tests."""

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner


async def _schedule_client(db, monkeypatch):
    """App + admin session for a guild with one channel, shared by the tests here."""
    import config
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.permissions import DashboardUser
    from modules.announcements.module import AnnouncementsModule
    from services.bark_context import BarkContext
    from services.dashboard_access import replace_user_guild_access

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Moderator", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": "0", "owner": True}],
        )

    channel = MagicMock()
    channel.send = AsyncMock()
    guild = MagicMock()
    guild.get_channel.return_value = channel
    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.get_guild.return_value = guild
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"announcements": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    app = create_app(bot)
    module = AnnouncementsModule(BarkContext(bot, bot.modules.event_bus))
    app.app.include_router(module.get_api_routes(), prefix="/api/v1")

    session_data = {"user": {"id": "42", "username": "Moderator"}, "role": "admin"}
    payload = base64.b64encode(json.dumps(session_data).encode("utf-8"))
    cookie = TimestampSigner("test_secret_key").sign(payload).decode("utf-8")
    return (
        AsyncClient(
            transport=ASGITransport(app=app.app),
            base_url="http://test",
            cookies={"session": cookie},
        ),
        channel,
    )


@pytest.mark.asyncio
async def test_edit_endpoint_replaces_content_and_time_without_sending(db, monkeypatch):
    """Viewing a schedule already worked; editing it must not need delete+recreate."""
    client, channel = await _schedule_client(db, monkeypatch)
    first_run = datetime.now(timezone.utc) + timedelta(days=1)
    moved_to = datetime.now(timezone.utc) + timedelta(days=9)

    created = await client.post(
        "/api/v1/guilds/1/modules/announcements/post",
        json={
            "channel_id": "55",
            "message": "Original text",
            "as_embed": True,
            "delivery_mode": "schedule",
            "scheduled_for": first_run.isoformat(),
            "timezone_name": "America/Chicago",
            "recurrence_unit": "day",
            "recurrence_interval": 1,
        },
    )
    schedule_id = created.json()["data"]["id"]

    edited = await client.post(
        f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}",
        json={
            "channel_id": "55",
            "title": "Edited title",
            "message": "Edited text",
            "as_embed": False,
            "delivery_mode": "schedule",
            "scheduled_for": moved_to.isoformat(),
            "timezone_name": "America/Chicago",
            "recurrence_unit": "week",
            "recurrence_interval": 2,
        },
    )
    listed = await client.get("/api/v1/guilds/1/modules/announcements/schedules")

    assert edited.status_code == 200, edited.text
    assert edited.json()["data"] == {"updated": True, "id": schedule_id}
    job = listed.json()["data"]["schedules"][0]
    assert job["message"] == "Edited text"
    assert job["title"] == "Edited title"
    assert job["recurrence_unit"] == "week" and job["recurrence_interval"] == 2
    assert job["next_run_at"].startswith(moved_to.strftime("%Y-%m-%dT"))
    assert job["status"] == "queued"
    channel.send.assert_not_awaited()

    # A past time is rejected by the same validation as creating one.
    stale = await client.post(
        f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}",
        json={
            "channel_id": "55",
            "message": "Too late",
            "delivery_mode": "schedule",
            "scheduled_for": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    )
    assert stale.status_code == 400
    assert "future" in stale.json()["error"]

    missing = await client.post(
        "/api/v1/guilds/1/modules/announcements/schedules/424242",
        json={
            "channel_id": "55",
            "message": "Nobody's job",
            "delivery_mode": "schedule",
            "scheduled_for": moved_to.isoformat(),
        },
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_edit_refuses_a_schedule_a_worker_is_sending(db, monkeypatch):
    """'sending' is the worker's ownership boundary — an edit must not race it."""
    from services.announcement_schedules import update_schedule

    client, _ = await _schedule_client(db, monkeypatch)
    created = await client.post(
        "/api/v1/guilds/1/modules/announcements/post",
        json={
            "channel_id": "55",
            "message": "In flight",
            "delivery_mode": "schedule",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        },
    )
    schedule_id = created.json()["data"]["id"]

    claimed = await client.post(
        f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}",
        json={
            "channel_id": "55",
            "message": "Rewrite",
            "delivery_mode": "schedule",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
        },
    )
    assert claimed.status_code == 200

    from sqlalchemy import update

    from database.engine import session_scope
    from database.models.announcements import AnnouncementSchedule

    async with session_scope() as session:
        await session.execute(
            update(AnnouncementSchedule)
            .where(AnnouncementSchedule.id == schedule_id)
            .values(status="sending")
        )

    refused = await update_schedule(
        guild_id="1",
        schedule_id=schedule_id,
        channel_id="55",
        title="",
        message="While sending",
        as_embed=False,
        embed_color="",
        image_url="",
        video_url="",
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=4),
        timezone_name="UTC",
        recurrence_unit=None,
        recurrence_interval=1,
    )
    assert refused is False


@pytest.mark.asyncio
async def test_schedule_api_queues_without_sending_and_lists_job(db, monkeypatch):
    client, channel = await _schedule_client(db, monkeypatch)

    created = await client.post(
        "/api/v1/guilds/1/modules/announcements/post",
        json={
            "channel_id": "55",
            "message": "Daily update",
            "as_embed": True,
            "delivery_mode": "schedule",
            "scheduled_for": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "timezone_name": "America/Chicago",
            "recurrence_unit": "day",
            "recurrence_interval": 1,
        },
    )
    listed = await client.get("/api/v1/guilds/1/modules/announcements/schedules")

    assert created.status_code == 200, created.text
    schedule_id = created.json()["data"]["id"]
    paused = await client.patch(
        f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}",
        json={"paused": True},
    )
    paused_list = await client.get("/api/v1/guilds/1/modules/announcements/schedules")
    deleted = await client.delete(f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}")

    assert created.status_code == 200
    assert created.json()["data"]["scheduled"] is True
    channel.send.assert_not_awaited()
    assert listed.status_code == 200
    jobs = listed.json()["data"]["schedules"]
    assert len(jobs) == 1
    assert jobs[0]["message"] == "Daily update"
    assert jobs[0]["recurrence_unit"] == "day"
    assert jobs[0]["status"] == "queued"
    assert paused.status_code == 200
    assert paused_list.json()["data"]["schedules"][0]["status"] == "paused"
    assert deleted.status_code == 200
