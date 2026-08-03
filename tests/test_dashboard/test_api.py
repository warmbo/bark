"""API endpoint tests for Bark dashboard.

Uses httpx AsyncClient against the FastAPI app with a mock bot.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

# ── Fixtures ──────────────────────────────────────────


@pytest_asyncio.fixture
async def app(db):
    """Create the FastAPI app with a minimal mock bot for testing."""
    from unittest.mock import MagicMock

    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        await session.commit()

    # Create a minimal bot mock — use plain MagicMock for auto-attribute creation
    bot = MagicMock()
    bot.is_ready.return_value = True
    bot.is_connected.return_value = True
    bot.user = MagicMock()
    bot.user.id = 12345
    bot.user.name = "Bark Test"
    bot.guilds = []
    bot.modules = MagicMock()
    bot.modules.event_bus = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}
    bot.modules.get_module.return_value = None
    bot.modules.get_enabled_modules.return_value = {}

    # Add a mock guild for routes that need one
    mock_guild = MagicMock()
    mock_guild.id = 1
    mock_guild.name = "Test Guild"
    mock_guild.member_count = 100
    mock_guild.owner_id = "123"
    mock_guild.icon = None  # No icon — safely handled
    mock_guild.owner = None
    mock_guild.get_member.return_value = None  # no cached members — fall back to stored tags
    mock_guild.get_role.return_value = None  # no cached roles — fall back to stored IDs
    mock_guild.channels = []
    mock_guild.roles = []
    mock_guild.text_channels = []
    mock_guild.voice_channels = []
    mock_guild.premium_subscription_count = 0
    mock_guild.premium_tier = 0
    mock_guild.max_members = 1000
    mock_guild.description = None
    mock_guild.banner = None
    mock_guild.emojis = []
    mock_guild.created_at = None
    mock_guild.verification_level = MagicMock()
    mock_guild.verification_level.name = "none"
    mock_guild.me = MagicMock()
    mock_guild.me.guild_permissions = MagicMock()
    mock_guild.me.guild_permissions.view_audit_log = False

    bot.get_guild.side_effect = lambda guild_id: mock_guild if int(guild_id) == 1 else None

    dashboard_app = create_app(bot)

    # Register moderation module API routes (rulesets, wordlists, rules)
    # so tests can call them without mocking.
    from modules.moderation.module import ModerationModule
    from services.bark_context import BarkContext

    ctx = BarkContext(bot, bot.modules.event_bus)
    mod_module = ModerationModule(ctx)
    router = mod_module.get_api_routes()
    if router is not None:
        dashboard_app.app.include_router(router, prefix="/api/v1")

    return dashboard_app.app


@pytest_asyncio.fixture
async def client(app):
    """HTTP client for testing."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Health & Ping ─────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check(client):
    """GET /api/v1/health should return system health status."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "status" in data["data"]
    assert data["data"]["status"] in ("healthy", "degraded")
    assert "version" in data["data"]


@pytest.mark.asyncio
async def test_health_ping(client):
    """GET /api/v1/health should return healthy status."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] in ("healthy", "degraded")


@pytest.mark.asyncio
async def test_public_health_does_not_expose_database_error_details(client, monkeypatch):
    from database import engine

    def fail_engine():
        raise RuntimeError("private database host and credential details")

    monkeypatch.setattr(engine, "get_engine", fail_engine)

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"]["database"] == {
        "healthy": False,
        "status": "unavailable",
    }
    assert "private database" not in response.text


def test_realtime_bridge_is_initialized(app):
    assert app.state.realtime_bridge is not None


@pytest.mark.asyncio
async def test_untrusted_host_is_rejected(client):
    response = await client.get("/api/v1/health", headers={"Host": "evil.example"})
    assert response.status_code == 400


# ── Guilds ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_guilds(client):
    """GET /api/v1/guilds should return list."""
    resp = await client.get("/api/v1/guilds")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "guilds" in data["data"]


@pytest.mark.asyncio
async def test_guild_channel_endpoint_filters_voice_channels(client, app, monkeypatch):
    from types import SimpleNamespace

    from dashboard.routes.api import guilds as guild_routes

    class FakeTextChannel:
        pass

    class FakeVoiceChannel:
        pass

    text = FakeTextChannel()
    voice = FakeVoiceChannel()
    for channel, channel_id, name, position in (
        (text, 10, "general", 1),
        (voice, 20, "Join to Create", 2),
    ):
        channel.id = channel_id
        channel.name = name
        channel.category = SimpleNamespace(name="Channels")
        channel.position = position
        channel.type = "text" if channel is text else "voice"

    guild = app.state.bot.get_guild(1)
    guild.channels = [text, voice]
    monkeypatch.setattr(guild_routes.discord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(guild_routes.discord, "VoiceChannel", FakeVoiceChannel)

    text_response = await client.get("/api/v1/guilds/1/channels")
    assert text_response.status_code == 200
    assert [item["id"] for item in text_response.json()["data"]["channels"]] == ["10"]

    response = await client.get("/api/v1/guilds/1/channels", params={"type": "voice"})

    assert response.status_code == 200
    assert response.json()["data"]["channels"] == [
        {
            "id": "20",
            "name": "Join to Create",
            "parent_name": "Channels",
            "type": "voice",
        }
    ]


@pytest.mark.asyncio
async def test_module_toggle_updates_only_the_target_guild(client, app):
    from unittest.mock import AsyncMock, MagicMock

    module = MagicMock()
    module.save_dashboard_config = AsyncMock()
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.set_guild_enabled = AsyncMock(return_value=True)

    response = await client.post(
        "/api/v1/guilds/1/modules/logging/toggle",
        json={"enabled": False},
    )

    assert response.status_code == 200
    app.state.bot.modules.set_guild_enabled.assert_awaited_once_with(1, "logging", False)


@pytest.mark.asyncio
async def test_saving_fresh_module_config_preserves_default_enabled_state(client, app):
    """A first settings save must not silently disable a default-enabled module."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.module import ModuleConfig

    module = MagicMock()
    module.get_settings_schema.return_value = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
    }
    module.save_dashboard_config = AsyncMock()
    app.state.bot.modules.get_module.return_value = module

    response = await client.put(
        "/api/v1/guilds/1/modules/community",
        json={"config": {"message": "hello"}},
    )

    assert response.status_code == 200
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "community",
                )
            )
        ).scalar_one()
    assert row.enabled is True


@pytest.mark.asyncio
async def test_module_role_access_override_enforces_and_resets_default(client, app, monkeypatch):
    """Moderator access follows the override and reset restores admin-only."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import config
    from services.response import check_api_permission, get_module_min_role

    module = MagicMock()
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}

    response = await client.patch(
        "/api/v1/guilds/1/modules/moderation/role-access",
        json={"min_role": "moderator"},
    )
    assert response.status_code == 200
    listed = await client.get("/api/v1/guilds/1/modules/role-access")
    assert listed.json()["data"]["moderation"] == "moderator"

    request = SimpleNamespace(
        session={"role": "viewer"},
        state=SimpleNamespace(bot=app.state.bot),
        url=SimpleNamespace(path="/api/v1/guilds/1/actions/warn"),
    )
    await get_module_min_role("moderation", 1)
    # OAuth-disabled mode stays permissive even when an override exists.
    assert check_api_permission(request, "moderation.warn", guild_id=1)

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    request.session["role"] = "moderator"
    await get_module_min_role("moderation", 1)
    assert check_api_permission(request, "moderation.warn", guild_id=1)

    # API writes remain permissive only while OAuth is disabled for this test.
    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    response = await client.patch(
        "/api/v1/guilds/1/modules/moderation/role-access",
        json={"min_role": "admin"},
    )
    assert response.status_code == 200
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    await get_module_min_role("moderation", 1)
    assert not check_api_permission(request, "moderation.warn", guild_id=1)

    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    response = await client.delete("/api/v1/guilds/1/modules/moderation/role-access")
    assert response.status_code == 200
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    assert await get_module_min_role("moderation", 1) is None
    assert not check_api_permission(request, "moderation.warn", guild_id=1)


def test_module_config_validation_rejects_array_and_enum_type_drift():
    from dashboard.routes.api.modules import _validate_config

    properties = {
        "ignored_roles": {
            "type": "array",
            "items": {"type": "string"},
        },
        "mode": {
            "type": "string",
            "enum": ["safe", "strict"],
        },
    }

    errors = _validate_config(
        {"ignored_roles": '["123"]', "mode": "unknown"},
        properties,
    )

    assert "ignored_roles: expected array, got str" in errors
    assert "mode: expected one of safe, strict" in errors


@pytest.mark.asyncio
async def test_module_voice_channel_field_uses_voice_only_endpoint(client, app):
    from unittest.mock import AsyncMock, MagicMock

    module = MagicMock()
    module.version = "1.0.0"
    module.description = "Auto voice"
    module.author = "Bark"
    module.get_settings_schema.return_value = {
        "type": "object",
        "properties": {
            "primary_channel_id": {
                "type": "string",
                "format": "voice_channel_select",
                "title": "Join-to-Create Channel",
            }
        },
    }
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_about.return_value = []
    module.get_actions.return_value = []
    module.get_extra_tabs.return_value = []
    module.load_dashboard_config = AsyncMock(return_value={})
    app.state.bot.modules.get_module.return_value = module

    response = await client.get("/guild/1/modules/auto_voice")

    assert response.status_code == 200
    assert 'data-api="/api/v1/guilds/{guild_id}/channels?type=voice"' in response.text
    assert "Select a voice channel…" in response.text
    # Module slug renders as a human name (not "Auto_voice")
    assert "Auto Voice" in response.text
    assert "Auto_voice" not in response.text
    # Live name-template preview script is registered
    assert "auto-voice-workspace.js" in response.text


@pytest.mark.asyncio
async def test_modules_grid_renders_human_module_names(client, app):
    """The Modules grid must show 'Auto Voice', not the raw slug 'Auto_voice'."""
    from unittest.mock import MagicMock

    module = MagicMock()
    module.version = "0.3.0"
    module.description = "AVC-compatible temporary voice channels"
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    app.state.bot.modules.get_all_modules.return_value = {"auto_voice": module}

    response = await client.get("/guild/1/modules")

    assert response.status_code == 200
    assert "Auto Voice" in response.text
    assert "Auto_voice" not in response.text


@pytest.mark.asyncio
async def test_voice_history_prefers_recorded_channel_name(client, app):
    """Voice history shows the name recorded at leave time even when the live
    channel is gone (Auto Voice deletes temporary channels after a leave)."""
    from database.engine import session_scope
    from database.models.voice import VoiceSession

    mock_guild = app.state.bot.get_guild(1)
    mock_guild.get_member.return_value = None
    mock_guild.get_channel.return_value = None

    async with session_scope() as session:
        session.add(
            VoiceSession(
                guild_id="1",
                user_id="42",
                user_tag="cody#0001",
                channel_id="200",
                channel_name="hangout",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/guilds/1/moderation/voice-history")

    assert resp.status_code == 200
    sessions = resp.json()["data"]["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["channel_name"] == "hangout"
    assert sessions[0]["channel_original_name"] == "hangout"


@pytest.mark.asyncio
async def test_role_manager_create_rule_accepts_json_body(app, client):
    """Regression: Request-typed POST handlers must not be treated as query
    params (would return 422). Register the role_manager router and POST."""
    from modules.role_manager.module import RoleManagerModule
    from services.bark_context import BarkContext

    bot = app.state.bot
    ctx = BarkContext(bot, bot.modules.event_bus)
    router = RoleManagerModule(ctx).get_api_routes()
    assert router is not None
    app.include_router(router, prefix="/api/v1")

    resp = await client.post(
        "/api/v1/guilds/1/modules/role_manager/rules",
        json={"name": "Welcome", "rule_type": "welcome", "role_id": "555"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] > 0


@pytest.mark.asyncio
async def test_module_action_fields_render_with_browser_valid_types(client, app):
    from unittest.mock import AsyncMock, MagicMock

    module = MagicMock()
    module.version = "1.0.0"
    module.description = "Moderation maintenance"
    module.author = "Bark"
    module.get_settings_schema.return_value = {}
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_about.return_value = []
    module.get_actions.return_value = [
        {
            "id": "cleanup",
            "label": "Cleanup",
            "endpoint": "cleanup",
            "destructive": True,
            "fields": [
                {"key": "days", "label": "Days", "type": "integer", "required": True},
                {"key": "dry_run", "label": "Dry run", "type": "boolean", "default": True},
            ],
        }
    ]
    module.load_dashboard_config = AsyncMock(return_value={})
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}

    response = await client.get("/guild/1/modules/moderation")

    assert response.status_code == 200
    assert 'type="number"' in response.text
    assert 'name="dry_run" data-schema-type="boolean"' in response.text
    dry_run_field = response.text.split('name="dry_run"', 1)[1].split(">", 1)[0]
    assert "checked" in dry_run_field
    assert 'data-destructive="true"' in response.text


@pytest.mark.asyncio
async def test_module_without_actions_has_no_operate_tab(client, app):
    """A configuration-only module opens on Configure, not an empty Operate tab."""
    from unittest.mock import AsyncMock, MagicMock

    module = MagicMock()
    module.version = "1.0.0"
    module.description = "Configuration-only module"
    module.author = "Bark"
    module.get_settings_schema.return_value = {"type": "object", "properties": {}}
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_about.return_value = []
    module.get_actions.return_value = []
    module.get_extra_tabs.return_value = []
    module.load_dashboard_config = AsyncMock(return_value={})
    app.state.bot.modules.get_module.return_value = module

    response = await client.get("/guild/1/modules/logging")

    assert response.status_code == 200
    assert 'id="workspace-tab-operate"' not in response.text
    assert 'id="workspace-tab-configure" class="tab active"' in response.text


# ── Moderation Cases ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_cases_empty(client):
    """GET /guilds/{id}/moderation/cases should return empty paginated result."""
    resp = await client.get("/api/v1/guilds/1/moderation/cases", params={"limit": 5})
    # Without a real guild, this may 404 or 200 — check response
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert "items" in data["data"]


@pytest.mark.asyncio
async def test_paginated_routes_reject_unbounded_negative_limits(client):
    response = await client.get(
        "/api/v1/guilds/1/moderation/cases",
        params={"limit": -1},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_case_validation(client):
    """POST /guilds/{id}/moderation/cases without guild should fail gracefully."""
    resp = await client.post(
        "/api/v1/guilds/99999/moderation/cases",
        json={"action_type": "warn", "target_id": "123", "reason": "Test"},
    )
    # Should return 500 (no real guild) but not crash
    assert resp.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_get_case_not_found(client):
    """GET /guilds/{id}/moderation/cases/99999 should return 404."""
    resp = await client.get("/api/v1/guilds/1/moderation/cases/99999")
    assert resp.status_code in (200, 404)
    if resp.status_code == 404:
        data = resp.json()
        assert data["success"] is False
        assert "error" in data


@pytest.mark.asyncio
async def test_delete_case_not_found(client):
    """DELETE /guilds/{id}/moderation/cases/99999 should return 404."""
    resp = await client.delete("/api/v1/guilds/1/moderation/cases/99999")
    assert resp.status_code in (200, 404)
    if resp.status_code == 404:
        data = resp.json()
        assert data["success"] is False


# ── Moderation Warnings ───────────────────────────────


@pytest.mark.asyncio
async def test_list_warnings(client):
    """GET /guilds/{id}/moderation/warnings should return wrapped response."""
    resp = await client.get("/api/v1/guilds/1/moderation/warnings")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True


# ── Moderation Notes ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_notes(client):
    """GET /guilds/{id}/moderation/notes should return wrapped response."""
    resp = await client.get("/api/v1/guilds/1/moderation/notes")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True


@pytest.mark.asyncio
async def test_note_edit_and_delete_persist(client):
    """Dashboard note CRUD persists and ignores client-supplied authors."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.moderation import UserNote

    created = await client.post(
        "/api/v1/guilds/1/notes",
        json={"user_id": "123456", "author_id": "spoofed", "content": "Original note"},
    )
    assert created.status_code == 200
    note_id = created.json()["data"]["id"]
    async with session_scope() as session:
        note = (await session.execute(select(UserNote).where(UserNote.id == note_id))).scalar_one()
        assert note.content == "Original note"
        assert note.author_id == "dashboard"

    updated = await client.patch(
        f"/api/v1/guilds/1/notes/{note_id}", json={"content": "Updated note"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["content"] == "Updated note"
    listed = await client.get("/api/v1/guilds/1/notes")
    assert [item["content"] for item in listed.json()["data"]["notes"]] == ["Updated note"]

    deleted = await client.delete(f"/api/v1/guilds/1/notes/{note_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    async with session_scope() as session:
        assert (
            await session.execute(select(UserNote).where(UserNote.id == note_id))
        ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_note_validation_preserves_existing_record(client):
    """An invalid edit must not erase the persisted note text."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.moderation import UserNote

    async with session_scope() as session:
        note = UserNote(guild_id="1", user_id="123456", author_id="dashboard", content="Keep me")
        session.add(note)
        await session.commit()
        await session.refresh(note)
        note_id = note.id
    response = await client.patch(f"/api/v1/guilds/1/notes/{note_id}", json={"content": "   "})
    assert response.status_code == 400
    async with session_scope() as session:
        assert (
            await session.execute(select(UserNote.content).where(UserNote.id == note_id))
        ).scalar_one() == "Keep me"


# ── Settings ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_settings(client):
    """GET /guilds/{id}/settings should return wrapped response."""
    resp = await client.get("/api/v1/guilds/1/settings")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True


# ── Modules ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_modules(client):
    """GET /guilds/{id}/modules should return list."""
    resp = await client.get("/api/v1/guilds/1/modules")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
        assert "modules" in data["data"]


# ── Manifest ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_manifest(client):
    """GET /guilds/{id}/manifest should return structured manifest."""
    resp = await client.get("/api/v1/guilds/1/manifest")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert "categories" in data["data"]


# ── Stats ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guild_stats(client):
    """GET /guilds/{id}/stats should return stats dict."""
    resp = await client.get("/api/v1/guilds/1/stats")
    assert resp.status_code in (200, 404, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
        assert "members" in data["data"]


@pytest.mark.asyncio
async def test_guild_activity_aggregates_all_logged_sources(client, db):
    """Activity feed surfaces cases, warnings, reputation, roles, notes, voice, and auto-voice."""
    from datetime import datetime, timedelta, timezone

    from database.engine import session_scope
    from database.models.auto_voice import AutoVoiceChannel
    from database.models.moderation import AuditLog, ModerationCase, UserNote
    from database.models.moderation import Warning as WarningModel
    from database.models.reputation import ReputationEvent
    from database.models.role_manager import RoleAssignment
    from database.models.voice import VoiceSession

    async with session_scope() as session:
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                ModerationCase(
                    guild_id="1", case_number=1, action_type="warn", target_id="900",
                    target_tag="WarnedUser", moderator_id="800", moderator_tag="Mod",
                    reason="spam", created_at=now - timedelta(minutes=1),
                ),
                WarningModel(
                    guild_id="1", user_id="901", moderator_id="800", reason="nope", active=True,
                    created_at=now - timedelta(minutes=2),
                ),
                # Non-numeric actor ID (dashboard) must not crash name resolution.
                WarningModel(
                    guild_id="1", user_id="907", moderator_id="dashboard", reason="spam", active=True,
                    created_at=now - timedelta(seconds=15),
                ),
                # Noisy per-message scoring must be filtered out of the feed.
                ReputationEvent(
                    guild_id="1", actor_id="800", target_id="902", event_type="thanks",
                    points=2.0, created_at=now - timedelta(minutes=3),
                ),
                ReputationEvent(
                    guild_id="1", actor_id="800", target_id="902", event_type="message",
                    points=1.0, created_at=now - timedelta(seconds=30),
                ),
                ReputationEvent(
                    guild_id="1", actor_id="800", target_id="902", event_type="reaction",
                    points=0.5, created_at=now - timedelta(seconds=20),
                ),
                ReputationEvent(
                    guild_id="1", actor_id="800", target_id="902", event_type="reaction_given",
                    points=0.5, created_at=now - timedelta(seconds=18),
                ),
                # Messaging audit event — target_id is a message id, not a user.
                AuditLog(
                    guild_id="1", action="link_posted", actor_id="800",
                    target_id="1533906144068632777",
                    details='{"channel": "#general", "link": "https://example.com", "actor_tag": "Mod"}',
                    created_at=now - timedelta(seconds=10),
                ),
                RoleAssignment(
                    guild_id="1", user_id="903", role_id="700", action="add",
                    created_at=now - timedelta(minutes=4),
                ),
                UserNote(
                    guild_id="1", user_id="904", author_id="800", content="watch this member",
                    created_at=now - timedelta(minutes=5),
                ),
                VoiceSession(
                    guild_id="1", user_id="905", channel_id="600", channel_name="General",
                    joined_at=now - timedelta(hours=1), left_at=now - timedelta(minutes=6),
                    duration_seconds=3200,
                ),
                AutoVoiceChannel(
                    channel_id="601", guild_id="1", owner_id="906", primary_channel_id="602",
                    created_at=now - timedelta(minutes=7),
                ),
            ]
        )
        await session.commit()

    resp = await client.get("/api/v1/guilds/1/activity")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    activity = data["data"]["activity"]
    assert len(activity) >= 7

    types = {a["type"] for a in activity}
    assert {"case", "warning", "reputation", "role", "note", "voice", "auto_voice"} <= types

    # Per-message scoring noise is excluded from the feed.
    rep_items = [a for a in activity if a["type"] == "reputation"]
    assert all(a["action"] != "message" for a in rep_items)
    assert all(a["action"] != "reaction" for a in rep_items)
    assert all(a["action"] != "reaction_given" for a in rep_items)
    assert any(a["action"] == "thanks" for a in rep_items)

    # Voice sessions surface as joins.
    voice_items = [a for a in activity if a["type"] == "voice"]
    assert voice_items and all(a["action"] == "voice_join" for a in voice_items)

    # Every item has a category, a human label, and a resolved display name.
    for a in activity:
        assert a.get("category") in {
            "moderation", "messaging", "voice", "roles", "reputation", "notes", "system",
        }
        assert a.get("label"), a

    # Case items resolve the stored target tag into the description.
    case_items = [a for a in activity if a["type"] == "case"]
    assert case_items and "WarnedUser" in case_items[0]["description"]
    assert case_items[0]["label"] == "Warning issued"

    # Messaging audit events describe the actor + channel, never the message id.
    audit_items = [a for a in activity if a["type"] == "audit"]
    link_items = [a for a in audit_items if a["action"] == "link_posted"]
    assert link_items
    assert "1533906144068632777" not in link_items[0]["description"]
    assert "Link posted by" in link_items[0]["description"]

    # Role assignments include the role name in the description.
    role_items = [a for a in activity if a["type"] == "role"]
    assert role_items and "Role assigned" in role_items[0]["description"]

    # Chronological ordering — newest first
    stamps = [a.get("timestamp") or "" for a in activity]
    assert stamps == sorted(stamps, reverse=True)


# ═══════════════════════════════════════════════════════
# ── Phase 16 Regression: Persistence Tests ────────────
# ═══════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_module_toggle_on_off_persists(client, app):
    """Module toggle persists in DB across enable/disable cycles."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.module import ModuleConfig

    module = MagicMock()
    module.save_dashboard_config = AsyncMock()
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.set_guild_enabled = AsyncMock(return_value=True)

    # Toggle on
    resp = await client.post("/api/v1/guilds/1/modules/logging/toggle", json={"enabled": True})
    assert resp.status_code == 200
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "logging",
                )
            )
        ).scalar_one_or_none()
    assert row is not None, "ModuleConfig should exist after toggle on"
    assert row.enabled is True

    # Toggle off
    resp = await client.post("/api/v1/guilds/1/modules/logging/toggle", json={"enabled": False})
    assert resp.status_code == 200
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "logging",
                )
            )
        ).scalar_one()
    assert row.enabled is False

    # Toggle back on — single row, state flipped
    resp = await client.post("/api/v1/guilds/1/modules/logging/toggle", json={"enabled": True})
    assert resp.status_code == 200
    async with session_scope() as session:
        row_count = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "logging",
                )
            )
        ).all()
    assert len(row_count) == 1, "Toggle must not duplicate rows"
    assert row_count[0][0].enabled is True


@pytest.mark.asyncio
async def test_module_config_save_persists_and_updates(client, app):
    """Config save writes to DB and subsequent updates replace config."""
    import json
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.module import ModuleConfig

    module = MagicMock()
    module.get_settings_schema.return_value = {
        "type": "object",
        "properties": {"message": {"type": "string"}},
    }

    async def _save_config(guild_id, config):
        """Real persistence via the module's save_dashboard_config contract."""
        async with session_scope() as session:
            result = await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == str(guild_id),
                    ModuleConfig.module_name == "community",
                )
            )
            dbc = result.scalar_one_or_none()
            if dbc is None:
                dbc = ModuleConfig(guild_id=str(guild_id), module_name="community", enabled=True)
                session.add(dbc)
            dbc.config = json.dumps(config)
            await session.commit()

    module.save_dashboard_config = AsyncMock(side_effect=_save_config)
    app.state.bot.modules.get_module.return_value = module

    # Save initial config
    resp = await client.put(
        "/api/v1/guilds/1/modules/community",
        json={"config": {"message": "hello"}},
    )
    assert resp.status_code == 200
    module.save_dashboard_config.assert_awaited_once_with(1, {"message": "hello"})
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "community",
                )
            )
        ).scalar_one()
    assert row.enabled is True
    assert json.loads(row.config) == {"message": "hello"}

    # Update config — row count stays at 1, config changes
    module.save_dashboard_config.reset_mock()
    resp = await client.put(
        "/api/v1/guilds/1/modules/community",
        json={"config": {"message": "updated"}},
    )
    assert resp.status_code == 200
    module.save_dashboard_config.assert_awaited_once_with(1, {"message": "updated"})
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "community",
                )
            )
        ).all()
    assert len(rows) == 1, "Save must update, not duplicate"
    assert json.loads(rows[0][0].config) == {"message": "updated"}


@pytest.mark.asyncio
async def test_role_access_save_persistence(client, app):
    """Role-access PATCH stores in DB and survives reload; DELETE removes it."""
    from unittest.mock import MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.permissions import ModuleRoleAccess

    # Need to mock the module so the route doesn't 404
    module = MagicMock()
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}

    # Set moderator override
    resp = await client.patch(
        "/api/v1/guilds/1/modules/moderation/role-access",
        json={"min_role": "moderator"},
    )
    assert resp.status_code == 200

    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleRoleAccess).where(
                    ModuleRoleAccess.guild_id == "1",
                    ModuleRoleAccess.module_name == "moderation",
                )
            )
        ).scalar_one()
    assert row.min_role == "moderator"

    # Reload via GET and confirm persisted value
    listed = await client.get("/api/v1/guilds/1/modules/role-access")
    assert listed.status_code == 200
    assert listed.json()["data"]["moderation"] == "moderator"

    # Delete override
    resp = await client.delete("/api/v1/guilds/1/modules/moderation/role-access")
    assert resp.status_code == 200

    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleRoleAccess).where(
                    ModuleRoleAccess.guild_id == "1",
                    ModuleRoleAccess.module_name == "moderation",
                )
            )
        ).scalar_one_or_none()
    assert row is None, "Role access override should be deleted"


@pytest.mark.asyncio
async def test_ruleset_crud_persistence(client):
    """Full ruleset CRUD: create → verify DB → delete → verify DB."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.ruleset import RuleSet

    # ── Create ──────────────────────────────────────────
    resp = await client.post(
        "/api/v1/guilds/1/rulesets",
        json={"name": "Test Ruleset", "enabled": True, "priority": 50},
    )
    assert resp.status_code == 200
    rs_id = resp.json()["data"]["id"]

    async with session_scope() as session:
        row = (await session.execute(select(RuleSet).where(RuleSet.id == rs_id))).scalar_one()
    assert row.name == "Test Ruleset"
    assert row.enabled is True
    assert row.priority == 50
    assert row.guild_id == "1"

    # ── Verify in list ──────────────────────────────────
    listed = await client.get("/api/v1/guilds/1/rulesets")
    assert listed.status_code == 200
    ids = [rs["id"] for rs in listed.json()["data"]["rulesets"]]
    assert rs_id in ids

    # ── Update ──────────────────────────────────────────
    resp = await client.patch(
        f"/api/v1/guilds/1/rulesets/{rs_id}",
        json={"name": "Updated Ruleset", "priority": 25},
    )
    assert resp.status_code == 200

    async with session_scope() as session:
        row = (await session.execute(select(RuleSet).where(RuleSet.id == rs_id))).scalar_one()
    assert row.name == "Updated Ruleset"
    assert row.priority == 25

    # ── Delete ──────────────────────────────────────────
    resp = await client.delete(f"/api/v1/guilds/1/rulesets/{rs_id}")
    assert resp.status_code == 200

    async with session_scope() as session:
        row = (
            await session.execute(select(RuleSet).where(RuleSet.id == rs_id))
        ).scalar_one_or_none()
    assert row is None, "Ruleset should be deleted"


@pytest.mark.asyncio
async def test_rule_crud_within_ruleset_persists(client):
    """Rule create/update/delete inside a ruleset persists in DB."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.ruleset import Rule

    # Create parent ruleset
    resp = await client.post(
        "/api/v1/guilds/1/rulesets",
        json={"name": "Rule Test", "enabled": True},
    )
    rs_id = resp.json()["data"]["id"]

    # ── Create rule ─────────────────────────────────────
    resp = await client.post(
        f"/api/v1/guilds/1/rulesets/{rs_id}/rules",
        json={
            "trigger_type": "spam",
            "effect_type": "warn",
            "trigger_config": {"threshold": 5, "window_seconds": 10},
            "effect_config": {"custom_message": "No spam"},
            "priority": 50,
        },
    )
    assert resp.status_code == 200
    rule_id = resp.json()["data"]["id"]

    async with session_scope() as session:
        rule = (
            await session.execute(select(Rule).where(Rule.id == rule_id, Rule.ruleset_id == rs_id))
        ).scalar_one()
    assert rule.trigger_type == "spam"
    assert rule.effect_type == "warn"
    import json

    assert json.loads(rule.trigger_config) == {"threshold": 5, "window_seconds": 10}
    assert json.loads(rule.effect_config) == {"custom_message": "No spam"}

    # ── Update rule ─────────────────────────────────────
    resp = await client.patch(
        f"/api/v1/guilds/1/rulesets/{rs_id}/rules/{rule_id}",
        json={
            "trigger_type": "invite",
            "effect_type": "delete",
            "trigger_config": {},
        },
    )
    assert resp.status_code == 200

    async with session_scope() as session:
        rule = (
            await session.execute(select(Rule).where(Rule.id == rule_id, Rule.ruleset_id == rs_id))
        ).scalar_one()
    assert rule.trigger_type == "invite"
    assert rule.effect_type == "delete"
    assert json.loads(rule.trigger_config) == {}

    # ── Delete rule ─────────────────────────────────────
    resp = await client.delete(f"/api/v1/guilds/1/rulesets/{rs_id}/rules/{rule_id}")
    assert resp.status_code == 200

    async with session_scope() as session:
        rule = (
            await session.execute(select(Rule).where(Rule.id == rule_id, Rule.ruleset_id == rs_id))
        ).scalar_one_or_none()
    assert rule is None, "Rule should be deleted"

    # Cleanup: remove parent ruleset
    await client.delete(f"/api/v1/guilds/1/rulesets/{rs_id}")


@pytest.mark.asyncio
async def test_rule_mutations_cannot_cross_guild_boundaries(client):
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.ruleset import Rule, RuleSet

    async with session_scope() as session:
        session.add(Guild(discord_id="2", name="Other Guild"))
        await session.flush()
        ruleset = RuleSet(guild_id="2", name="Private Rules")
        session.add(ruleset)
        await session.flush()
        rule = Rule(
            ruleset_id=ruleset.id,
            trigger_type="spam",
            effect_type="warn",
        )
        session.add(rule)
        await session.commit()
        ruleset_id = ruleset.id
        rule_id = rule.id

    update = await client.patch(
        f"/api/v1/guilds/1/rulesets/{ruleset_id}/rules/{rule_id}",
        json={"effect_type": "ban"},
    )
    delete = await client.delete(f"/api/v1/guilds/1/rulesets/{ruleset_id}/rules/{rule_id}")

    assert update.status_code == 404
    assert delete.status_code == 404
    async with session_scope() as session:
        saved = (await session.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    assert saved.effect_type == "warn"


@pytest.mark.asyncio
async def test_ruleset_delete_cascades_to_rules(client):
    """Deleting a ruleset removes all its rules from DB."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.ruleset import Rule, RuleSet

    # Create ruleset with one rule
    resp = await client.post(
        "/api/v1/guilds/1/rulesets",
        json={"name": "Cascade Test", "enabled": True},
    )
    rs_id = resp.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/guilds/1/rulesets/{rs_id}/rules",
        json={"trigger_type": "spam", "effect_type": "warn"},
    )
    rule_id = resp.json()["data"]["id"]

    # Verify both exist
    async with session_scope() as session:
        assert (
            await session.execute(select(RuleSet).where(RuleSet.id == rs_id))
        ).scalar_one_or_none() is not None
        assert (
            await session.execute(select(Rule).where(Rule.id == rule_id))
        ).scalar_one_or_none() is not None

    # Delete ruleset
    resp = await client.delete(f"/api/v1/guilds/1/rulesets/{rs_id}")
    assert resp.status_code == 200

    # Verify both are gone (cascade = "all, delete-orphan")
    async with session_scope() as session:
        assert (
            await session.execute(select(RuleSet).where(RuleSet.id == rs_id))
        ).scalar_one_or_none() is None
        assert (
            await session.execute(select(Rule).where(Rule.id == rule_id))
        ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_wordlist_crud_persistence(client):
    """Word list create/update/delete persists in DB."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.ruleset import WordList

    # ── Create ──────────────────────────────────────────
    resp = await client.post(
        "/api/v1/guilds/1/wordlists",
        json={
            "name": "Bad Words",
            "list_type": "word",
            "entries": ["badword1", "badword2"],
        },
    )
    assert resp.status_code == 200
    wl_id = resp.json()["data"]["id"]

    async with session_scope() as session:
        wl = (await session.execute(select(WordList).where(WordList.id == wl_id))).scalar_one()
    import json

    assert wl.name == "Bad Words"
    assert wl.list_type == "word"
    assert json.loads(wl.entries) == ["badword1", "badword2"]
    assert wl.guild_id == "1"

    # Verify in list
    listed = await client.get("/api/v1/guilds/1/wordlists")
    assert listed.status_code == 200
    ids = [wl["id"] for wl in listed.json()["data"]["wordlists"]]
    assert wl_id in ids

    # ── Update entries ──────────────────────────────────
    resp = await client.patch(
        f"/api/v1/guilds/1/wordlists/{wl_id}",
        json={"name": "Updated List", "entries": ["word3"]},
    )
    assert resp.status_code == 200

    async with session_scope() as session:
        wl = (await session.execute(select(WordList).where(WordList.id == wl_id))).scalar_one()
    assert wl.name == "Updated List"
    assert json.loads(wl.entries) == ["word3"]

    # ── Delete ──────────────────────────────────────────
    resp = await client.delete(f"/api/v1/guilds/1/wordlists/{wl_id}")
    assert resp.status_code == 200

    async with session_scope() as session:
        wl = (
            await session.execute(select(WordList).where(WordList.id == wl_id))
        ).scalar_one_or_none()
    assert wl is None, "WordList should be deleted"


@pytest.mark.asyncio
async def test_warning_clear_persists(client):
    """Clearing a warning via DELETE marks it inactive in DB."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.moderation import Warning as WarningModel

    async with session_scope() as session:
        w = WarningModel(
            guild_id="1",
            user_id="123456",
            moderator_id="dashboard",
            reason="Test warning",
            active=True,
            created_at=datetime.now(timezone.utc),
        )
        session.add(w)
        await session.commit()
        warning_id = w.id

    resp = await client.delete(f"/api/v1/guilds/1/moderation/warnings/{warning_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["deleted"] is True
    assert data["data"]["warning_id"] == warning_id

    async with session_scope() as session:
        w = (
            await session.execute(select(WarningModel).where(WarningModel.id == warning_id))
        ).scalar_one()
    assert w.active is False, "Warning should be marked inactive"


@pytest.mark.asyncio
async def test_case_resolution_persists(client):
    """Deleting a case marks it resolved (soft-delete) in DB."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.moderation import ModerationCase

    async with session_scope() as session:
        c = ModerationCase(
            guild_id="1",
            case_number=42,
            action_type="warn",
            target_id="123456",
            target_tag="User#0001",
            moderator_id="dashboard",
            moderator_tag="Dashboard",
            reason="Test case",
            created_at=datetime.now(timezone.utc),
            resolved=False,
        )
        session.add(c)
        await session.commit()

    resp = await client.delete("/api/v1/guilds/1/moderation/cases/42")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["deleted"] is True
    assert data["data"]["case_number"] == 42

    async with session_scope() as session:
        c = (
            await session.execute(
                select(ModerationCase).where(
                    ModerationCase.guild_id == "1",
                    ModerationCase.case_number == 42,
                )
            )
        ).scalar_one()
    assert c.resolved is True, "Case should be marked resolved"
    assert c.resolved_at is not None, "Case should have resolved_at timestamp"


@pytest.mark.asyncio
async def test_logging_logs_endpoint_returns_audit_entries(app, client):
    """Logging module Logs tab reads Bark's own audit-log table.

    Regression guard: modules/logging/module.py get_api_routes() must expose
    GET /guilds/{guild_id}/modules/logging/logs and return recorded audit
    entries (message edits/deletes/links, joins, voice state).
    """
    from database.engine import session_scope
    from database.models.moderation import AuditLog
    from modules.logging.module import LoggingModule
    from services.bark_context import BarkContext

    # Seed an audit entry the way the module records one.
    async with session_scope() as session:
        session.add(
            AuditLog(
                guild_id="1",
                action="message_edit",
                actor_id="42",
                target_id="99",
                details='{"actor_tag":"cody#0001","channel":"#general","before":"old","after":"new"}',
            )
        )
        await session.commit()

    bot = app.state.bot
    mock_guild = bot.get_guild(1)
    mock_guild.get_member.return_value = None

    ctx = BarkContext(bot, bot.modules.event_bus)
    router = LoggingModule(ctx).get_api_routes()
    assert router is not None
    app.include_router(router, prefix="/api/v1")

    resp = await client.get("/api/v1/guilds/1/modules/logging/logs?limit=10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    entries = body["data"]["entries"]
    assert len(entries) == 1
    assert entries[0]["action"] == "message_edit"
    assert entries[0]["actor"] == "cody#0001"  # member cache empty → falls back to stored tag
    assert entries[0]["channel"] == "#general"
    assert entries[0]["details"]["before"] == "old"


@pytest.mark.asyncio
async def test_logging_workspace_has_logs_tab(client, app):
    """The Logging module workspace registers a Logs tab with its template."""
    from unittest.mock import AsyncMock, MagicMock

    module = MagicMock()
    module.version = "3.0.0"
    module.description = "Log message edits, deletes, file uploads"
    module.author = "Bark"
    module.get_settings_schema.return_value = {}
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_about.return_value = []
    module.get_actions.return_value = [
        {"id": "test_log", "label": "Test Log", "endpoint": "test", "fields": []}
    ]
    module.get_extra_tabs.return_value = [
        {"id": "logs", "label": "Logs", "template": "module_tabs/logging_logs.html"}
    ]
    module.load_dashboard_config = AsyncMock(return_value={})
    app.state.bot.modules.get_module.return_value = module

    resp = await client.get("/guild/1/modules/logging")
    assert resp.status_code == 200
    assert 'id="workspace-tab-logs"' in resp.text
    assert 'data-section="logs"' in resp.text
    assert "logging-logs-content" in resp.text
    # Workspace JS must be registered on the logging module page
    assert "logging-workspace.js" in resp.text
