"""Announcements scheduling API integration tests."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner


@pytest.mark.asyncio
async def test_schedule_api_queues_without_sending_and_lists_job(db, monkeypatch):
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

    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies={"session": cookie},
    ) as client:
        created = await client.post(
            "/api/v1/guilds/1/modules/announcements/post",
            json={
                "channel_id": "55",
                "message": "Daily update",
                "as_embed": True,
                "delivery_mode": "schedule",
                "scheduled_for": "2026-09-01T15:30:00Z",
                "timezone_name": "America/Chicago",
                "recurrence_unit": "day",
                "recurrence_interval": 1,
            },
        )
        listed = await client.get("/api/v1/guilds/1/modules/announcements/schedules")

        schedule_id = created.json()["data"]["id"]
        paused = await client.patch(
            f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}",
            json={"paused": True},
        )
        paused_list = await client.get(
            "/api/v1/guilds/1/modules/announcements/schedules"
        )
        deleted = await client.delete(
            f"/api/v1/guilds/1/modules/announcements/schedules/{schedule_id}"
        )

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
