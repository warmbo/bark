"""API endpoint tests for Bark dashboard.

Uses httpx AsyncClient against the FastAPI app with a mock bot.
"""

from __future__ import annotations

from pathlib import Path

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
    # Public health endpoint must NOT fingerprint the deployment: no version,
    # no started_at timestamp.
    assert "version" not in data["data"]
    assert "started_at" not in data["data"]["uptime"]


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


@pytest.mark.asyncio
async def test_moderation_actions_redact_unexpected_discord_errors(monkeypatch):
    """Unexpected Discord exceptions are logged server-side and returned generically."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value="moderator"))

    member = MagicMock(bot=False, id=42)
    guild = MagicMock(id=1)
    guild.me.guild_permissions.moderate_members = True
    guild.get_member.return_value = member
    bot = MagicMock()
    bot.get_guild.return_value = guild
    bot.fetch_user = AsyncMock(side_effect=RuntimeError("private upstream credential details"))
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={},
        json=AsyncMock(return_value={"target_id": "42", "reason": "test"}),
    )

    async def fail_executor(*args):
        raise RuntimeError("private moderation backend details")

    action_response = await actions._mod_action(request, "1", "warn", fail_executor)
    unban_response = await actions.action_unban(request, "1")

    assert action_response.status_code == 502
    assert unban_response.status_code == 502
    assert b"private" not in action_response.body
    assert b"private" not in unban_response.body


@pytest.mark.asyncio
async def test_member_detail_does_not_disclose_moderation_data_without_permission(monkeypatch):
    """Member profiles must not bypass private moderation read permissions."""
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    member = MagicMock()
    member.id = 42
    member.display_name = "Member"
    member.display_avatar = None
    member.joined_at = None
    member.created_at = None
    member.roles = []
    member.top_role = None
    member.bot = False
    member.is_timed_out.return_value = False
    member.voice = None
    guild = MagicMock()
    guild.get_member.return_value = member
    request = SimpleNamespace(
        state=SimpleNamespace(bot=SimpleNamespace(get_guild=lambda _gid: guild)),
        session={"role": "viewer"},
    )

    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value=None))
    monkeypatch.setattr(actions, "check_api_permission", lambda *_args, **_kwargs: False)
    private_notes = AsyncMock(return_value=[{"content": "private note"}])
    private_cases = AsyncMock(return_value=[{"target_id": "42", "reason": "private"}])
    private_warnings = AsyncMock(return_value=[{"reason": "private"}])
    private_voice = AsyncMock(return_value=[{"channel_name": "private"}])
    monkeypatch.setattr(actions, "_get_user_notes", private_notes)
    monkeypatch.setattr(actions.SERVICE, "get_cases", private_cases)
    monkeypatch.setattr(actions.SERVICE, "get_warnings", private_warnings)
    monkeypatch.setattr(actions.SERVICE, "get_voice_sessions", private_voice)

    response = await actions.get_member_detail(request, "1", "42")
    data = json.loads(response.body)["data"]

    assert data["can_view_notes"] is False
    assert data["can_view_moderation"] is False
    assert data["cases"] == []
    assert data["warnings"] == []
    assert data["voice_sessions"] == []
    assert data["notes"] == []
    private_cases.assert_not_awaited()
    private_warnings.assert_not_awaited()
    private_voice.assert_not_awaited()
    private_notes.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_routes_reject_non_numeric_member_ids(client):
    api_response = await client.get("/api/v1/guilds/1/members/not-a-number")
    web_response = await client.get("/guild/1/members/not-a-number")

    assert api_response.status_code == 404
    assert web_response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("target_id", ["not-a-number", None])
async def test_unban_rejects_invalid_target_as_client_error(monkeypatch, target_id):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from dashboard.routes.api import actions

    bot = MagicMock()
    bot.fetch_user = AsyncMock()
    bot.get_guild.return_value = MagicMock()
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={"role": "admin"},
        json=AsyncMock(return_value={"target_id": target_id, "reason": "test"}),
    )
    monkeypatch.setattr(actions, "get_module_min_role", AsyncMock(return_value="admin"))
    monkeypatch.setattr(actions, "check_api_permission", lambda *_args, **_kwargs: True)

    response = await actions.action_unban(request, "1")

    assert response.status_code == 400
    bot.fetch_user.assert_not_awaited()


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
async def test_module_toggle_failure_does_not_persist(client, app):
    """If the runtime enable/disable transition fails, the DB row must NOT be
    written and the API returns 409 — persisted and live state can't diverge."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.module import ModuleConfig

    module = MagicMock()
    module.save_dashboard_config = AsyncMock()
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.set_guild_enabled = AsyncMock(return_value=False)

    resp = await client.post("/api/v1/guilds/1/modules/logging/toggle", json={"enabled": True})

    assert resp.status_code == 409
    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "logging",
                )
            )
        ).scalar_one_or_none()
    assert row is None, "ModuleConfig must not be written when the transition fails"


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


@pytest.mark.asyncio
async def test_guild_capabilities_match_module_role_enforcement(client, app, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import config
    from modules.base import PermissionDefinition
    from services.response import get_guild_capabilities

    module = MagicMock()
    module.get_permissions.return_value = [
        PermissionDefinition(name="moderation.warn", label="Warn Members"),
        PermissionDefinition(name="automod.configure", label="Configure AutoMod"),
    ]
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}

    request = SimpleNamespace(
        session={"role": "moderator"},
        state=SimpleNamespace(bot=app.state.bot),
        url=SimpleNamespace(path="/api/v1/guilds/1/manifest"),
    )
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    default_capabilities = await get_guild_capabilities(request, 1)
    assert default_capabilities["moderation.warn"] is False
    assert default_capabilities["automod.configure"] is False

    monkeypatch.setattr(config.config.oauth2, "client_id", "")
    response = await client.patch(
        "/api/v1/guilds/1/modules/moderation/role-access",
        json={"min_role": "moderator"},
    )
    assert response.status_code == 200
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")

    overridden_capabilities = await get_guild_capabilities(request, 1)
    assert overridden_capabilities["moderation.warn"] is True
    assert overridden_capabilities["automod.configure"] is True


@pytest.mark.asyncio
async def test_private_moderation_reads_require_module_access(app, monkeypatch):
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds, moderation
    from modules.moderation.module import ModerationModule
    from services.bark_context import BarkContext
    from services.response import set_cached_module_min_role

    module = ModerationModule(BarkContext(app.state.bot, app.state.bot.modules.event_bus))
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}
    set_cached_module_min_role("moderation", 1, None)
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    request = SimpleNamespace(
        session={"role": "viewer"},
        state=SimpleNamespace(bot=app.state.bot),
        url=SimpleNamespace(path="/api/v1/guilds/1/moderation/cases"),
    )

    cases_response = await moderation.list_cases(request, "1", page=0, limit=50)
    stats_response = await guilds.get_guild_stats(request, 1)
    activity_response = await guilds.get_guild_activity(request, 1)
    ruleset_route = next(
        route for route in module.get_api_routes().routes if route.path.endswith("/rulesets")
    )
    request.url.path = "/api/v1/guilds/1/rulesets"
    rulesets_response = await ruleset_route.endpoint(request, "1")

    assert cases_response.status_code == 403
    # Statistics are intentionally viewable by most users (like the Dashboard) —
    # they no longer require moderation.view.
    assert stats_response.status_code == 200
    assert activity_response.status_code == 403
    assert rulesets_response.status_code == 403


@pytest.mark.asyncio
async def test_moderation_export_returns_json_archive(app, monkeypatch):
    """GET .../moderation/export streams cases + warnings as a JSON file."""
    from types import SimpleNamespace

    import config
    from modules.moderation.module import ModerationModule
    from services.bark_context import BarkContext
    from services.response import set_cached_module_min_role

    module = ModerationModule(BarkContext(app.state.bot, app.state.bot.modules.event_bus))
    app.state.bot.modules.get_all_modules.return_value = {"moderation": module}
    set_cached_module_min_role("moderation", 1, None)
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")
    request = SimpleNamespace(
        session={"role": "admin"},
        state=SimpleNamespace(bot=app.state.bot),
        url=SimpleNamespace(path="/api/v1/guilds/1/modules/moderation/export"),
    )
    export_route = next(
        r for r in module.get_api_routes().routes if r.path.endswith("/export")
    )
    resp = await export_route.endpoint(request, "1")
    import json as _json

    data = _json.loads(resp.body)
    assert data["guild_id"] == 1
    assert "cases" in data and "warnings" in data
    hdrs = {k.lower(): v for k, v in dict(resp.headers).items()}
    assert "content-disposition" in hdrs
    assert "attachment" in hdrs["content-disposition"]


@pytest.mark.asyncio
async def test_list_members_includes_role_colors_and_join_date(app, monkeypatch):
    """Members list returns each role's Discord color and the join date."""
    from types import SimpleNamespace

    import discord

    import config
    from dashboard.routes.api import actions

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    admin_role = SimpleNamespace(id=555, name="Admin", color=discord.Colour(0x5865F2))
    everyone = SimpleNamespace(id=0, name="@everyone", color=discord.Colour(0))
    member = SimpleNamespace(
        id=1,
        display_name="Alice",
        tag="Alice#1",
        display_avatar=None,
        roles=[everyone, admin_role],
        top_role=admin_role,
        created_at=None,
        joined_at=None,
        bot=False,
        voice=None,
        is_timed_out=lambda: False,
        __str__=lambda s: "Alice#1",
    )
    guild = SimpleNamespace(members=[member])
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot),
        session={"role": "admin"},
        url=SimpleNamespace(path="/api/v1/guilds/1/members"),
    )

    resp = await actions.list_members(
        request, "1", search="", page=0, limit=10, role_id="",
        sort="name", order="asc", min_age_days=0, max_age_days=0,
    )
    assert resp.status_code == 200
    import json
    data = json.loads(resp.body)
    m = data["data"]["members"][0]
    assert m["roles"][0]["name"] == "Admin"
    assert m["roles"][0]["color"] == "#5865f2"  # @everyone (value 0) excluded
    assert m["top_role_color"] == "#5865f2"
    assert m["joined_at"] is None


@pytest.mark.asyncio
async def test_guild_profile_includes_motd_scheduled_events_and_message_stats(app, monkeypatch):
    """get_guild returns the server profile (MOTD + Discord events) and the
    stats endpoint surfaces today's message/emoji activity."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from database.engine import session_scope
    from database.models.guild import Guild, GuildSetting

    async with session_scope() as s:
        from sqlalchemy import select

        if not (await s.execute(select(Guild).where(Guild.discord_id == "123456"))).scalars().first():
            s.add(Guild(discord_id="123456", name="Profile Guild"))
        s.add(GuildSetting(guild_id="123456", key="motd", value="Welcome everyone!"))
        await s.commit()

    ev = SimpleNamespace(
        id=1, name="Movie Night", description="Watch a movie",
        start_time=None, end_time=None, status=SimpleNamespace(name="scheduled"),
        entity_type=SimpleNamespace(name="external"), url="https://discord.gg/x",
        user_count=12, channel=None,
    )
    guild = SimpleNamespace(
        id=123456, name="Profile Guild", member_count=42, owner_id=1,
        owner=None, banner=None, icon=None, description="A nice server",
        premium_tier=1, premium_subscription_count=3, premium_subscriber_count=3, max_members=100,
        channels=[], roles=[], emojis=[], created_at=None,
        verification_level=SimpleNamespace(name="moderate"), features=["ANIMATED_ICON"],
        scheduled_events=[ev], members=[], text_channels=[], voice_channels=[],
    )
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild
    # Seed the daily stats tables — the source of truth the stats endpoint reads.
    from datetime import date, timedelta

    from database.engine import session_scope
    from database.models.analytics import DailyChannelStat, DailyEmojiStat

    async with session_scope() as s:
        s.add(DailyChannelStat(guild_id="123456", stat_date=date.today(), channel_id="100", channel_name="general", message_count=3))
        s.add(DailyChannelStat(guild_id="123456", stat_date=date.today(), channel_id="200", channel_name="memes", message_count=2))
        s.add(DailyChannelStat(guild_id="123456", stat_date=date.today() - timedelta(days=1), channel_id="100", channel_name="general", message_count=8))
        s.add(DailyEmojiStat(guild_id="123456", stat_date=date.today(), emoji_name="laugh", count=4))
        s.add(DailyEmojiStat(guild_id="123456", stat_date=date.today() - timedelta(days=1), emoji_name="laugh", count=40))
        await s.commit()
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot), session={"role": "admin"},
        url=SimpleNamespace(path="/api/v1/guilds/123456"),
    )

    import json
    profile = await guilds.get_guild(request, 123456)
    assert profile.status_code == 200
    data = json.loads(profile.body)["data"]
    assert data["name"] == "Profile Guild"
    assert data["motd"] == "Welcome everyone!"
    assert data["verification_level"] == "moderate"
    assert data["scheduled_events"][0]["name"] == "Movie Night"
    assert data["scheduled_events"][0]["user_count"] == 12

    stats = await guilds.get_guild_stats(request, 123456)
    assert stats.status_code == 200
    sdata = json.loads(stats.body)["data"]
    # DB-sourced stats.
    assert sdata["messages_today"] == 5
    assert sdata["top_channels_today"][0]["name"] == "general"
    assert sdata["top_channels_today"][0]["count"] == 3
    assert sdata["top_emojis_today"][0] == {"name": "laugh", "count": 4}
    # Trailing-window + all-time stats (aggregated from the daily tables).
    assert sdata["top_channels_7d"][0]["name"] == "general"
    assert sdata["top_channels_7d"][0]["count"] == 11
    assert sdata["top_channels_30d"][0]["name"] == "general"
    assert sdata["top_emojis_all_time"][0] == {"name": "laugh", "count": 44}


@pytest.mark.asyncio
async def test_stats_surfaces_persisted_channel_emoji_after_restart(app, monkeypatch):
    """The Statistics page reads entirely from the persisted daily stats tables
    (source of truth) — even with no in-memory live counters (a fresh restart),
    top channels / emojis still show data from the DB (item 5)."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from datetime import date, timedelta

    from database.engine import session_scope
    from database.models.analytics import ActivitySnapshot, DailyChannelStat, DailyEmojiStat
    from database.models.guild import Guild

    async with session_scope() as s:
        from sqlalchemy import select

        if not (await s.execute(select(Guild).where(Guild.discord_id == "999"))).scalars().first():
            s.add(Guild(discord_id="999", name="Persist Guild"))
            await s.flush()
        # Today + yesterday member snapshots (for growth).
        s.add(ActivitySnapshot(guild_id="999", snapshot_date=date.today() - timedelta(days=1), total_members=10))
        s.add(ActivitySnapshot(guild_id="999", snapshot_date=date.today(), total_members=11))
        # Per-day channel/emoji stats — the source of truth the page reads.
        s.add(DailyChannelStat(guild_id="999", stat_date=date.today() - timedelta(days=1), channel_id="100", channel_name="general", message_count=5))
        s.add(DailyChannelStat(guild_id="999", stat_date=date.today() - timedelta(days=1), channel_id="200", channel_name="memes", message_count=2))
        s.add(DailyChannelStat(guild_id="999", stat_date=date.today(), channel_id="100", channel_name="general", message_count=5))
        s.add(DailyChannelStat(guild_id="999", stat_date=date.today(), channel_id="200", channel_name="memes", message_count=2))
        s.add(DailyEmojiStat(guild_id="999", stat_date=date.today() - timedelta(days=1), emoji_name="laugh", count=4))
        s.add(DailyEmojiStat(guild_id="999", stat_date=date.today() - timedelta(days=1), emoji_name="wow", count=1))
        s.add(DailyEmojiStat(guild_id="999", stat_date=date.today(), emoji_name="laugh", count=4))
        s.add(DailyEmojiStat(guild_id="999", stat_date=date.today(), emoji_name="wow", count=1))
        # Reputation / voice / game data backing the newer charts.
        from datetime import datetime, timezone

        from database.models.analytics import VoiceGameStat
        from database.models.reputation import ReputationEvent
        from database.models.voice import VoiceSession

        s.add(ReputationEvent(
            guild_id="999", actor_id="42", target_id="90001", event_type="message", points=1,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        s.add(ReputationEvent(
            guild_id="999", actor_id="42", target_id="90001", event_type="thanks", points=3,
            created_at=datetime.now(timezone.utc),
        ))
        s.add(VoiceSession(
            guild_id="999", user_id="90001", user_tag="User0#0000", channel_id="1000",
            channel_name="Gaming", joined_at=datetime.now(timezone.utc) - timedelta(days=1),
            left_at=datetime.now(timezone.utc), duration_seconds=3600,
        ))
        s.add(VoiceGameStat(
            guild_id="999", game_name="Valorant",
            recorded_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        from database.models.reputation import ReputationProfile

        s.add(ReputationProfile(
            guild_id="999", user_id="90001", total_score=42.0, level=5,
            week_start=date.today(), month_start=date.today(),
        ))
        await s.commit()

    guild = SimpleNamespace(
        id=999, name="Persist Guild", member_count=11, owner_id=1, owner=None,
        banner=None, icon=None, description=None, premium_tier=0,
        premium_subscription_count=0, premium_subscriber_count=0, max_members=100,
        channels=[], roles=[], emojis=[], created_at=None, verification_level=None,
        features=[], scheduled_events=[], members=[], text_channels=[], voice_channels=[],
    )
    # A member with a display name + avatar for Top Reputation resolution.
    member = SimpleNamespace(
        id=90001, display_name="CoolUser", name="cooluser",
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatars/90001/hash.png"),
    )
    guild.get_member = lambda uid: member if uid == 90001 else None
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot), session={"role": "admin"},
        url=SimpleNamespace(path="/api/v1/guilds/999"),
    )

    import json
    stats = await guilds.get_guild_stats(request, 999)
    assert stats.status_code == 200
    data = json.loads(stats.body)["data"]
    # The page reads from the DB, so top channels / emojis always show.
    assert data["messages_today"] == 7
    assert data["top_channels_today"] == [{"name": "general", "count": 5}, {"name": "memes", "count": 2}]
    assert data["top_channels_7d"][0]["name"] == "general"
    assert data["top_channels_7d"][0]["count"] == 10
    assert data["top_channels_30d"][0]["name"] == "general"
    assert data["top_emojis_today"][0] == {"name": "laugh", "count": 4}
    assert data["top_emojis_all_time"][0] == {"name": "laugh", "count": 8}
    # Newer charts backed by accumulating data.
    assert len(data["reputation_series"]) == 30
    assert sum(p["count"] for p in data["reputation_series"]) == 2
    assert data["reputation_by_type"] and {"name": "Messages", "count": 1} in data["reputation_by_type"]
    assert data["voice_series"] and sum(p["count"] for p in data["voice_series"]) == 1
    assert data["top_voice_users"][0]["name"] == "CoolUser"
    assert data["top_voice_users"][0]["count"] == 60  # 3600s = 60 min
    assert data["popular_games"] == [{"name": "Valorant", "count": 1}]
    assert len(data["new_members_series"]) == 30
    assert len(data["audit_series"]) == 30
    # Top Reputation resolves the display name + avatar from the live guild.
    assert data["top_reputation"] == [{
        "name": "CoolUser", "id": "90001",
        "avatar_url": "https://cdn.discordapp.com/avatars/90001/hash.png",
        "count": 42,
    }]
    # Top Voice Users resolves the display name + avatar too (covered above).


@pytest.mark.asyncio
async def test_set_guild_banner_persists_and_clears(app, monkeypatch):
    """PUT /guilds/{id}/banner stores a custom banner URL (and clears it)."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as s:
        from sqlalchemy import select

        if not (await s.execute(select(Guild).where(Guild.discord_id == "222222"))).scalars().first():
            s.add(Guild(discord_id="222222", name="Banner Guild"))
            await s.commit()

    guild = SimpleNamespace(
        id=222222, name="Banner Guild", member_count=10, owner_id=1, owner=None,
        banner=None, icon=None, description=None, premium_tier=0,
        premium_subscription_count=0, premium_subscriber_count=0, max_members=100,
        channels=[], roles=[], emojis=[], created_at=None,
        verification_level=None, features=[], scheduled_events=[], members=[],
        text_channels=[], voice_channels=[],
    )
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild
    request = SimpleNamespace(
        state=SimpleNamespace(bot=bot), session={"role": "admin"},
        url=SimpleNamespace(path="/api/v1/guilds/222222/banner"),
    )

    import json

    class _Req(SimpleNamespace):
        _body = {}

        async def json(self):
            return self._body

    # Set a custom banner.
    set_req = _Req(state=SimpleNamespace(bot=bot), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    set_req._body = {"banner_url": "https://example.com/banner.png"}
    set_req.state.guild_viewer = False
    resp = await guilds.set_guild_banner(set_req, 222222)
    assert resp.status_code == 200
    # Reading it back.
    profile = await guilds.get_guild(request, 222222)
    data = json.loads(profile.body)["data"]
    assert data["custom_banner_url"] == "https://example.com/banner.png"

    # Clear it.
    req = _Req(state=SimpleNamespace(bot=bot), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    req._body = {"banner_url": ""}
    req.state.guild_viewer = False
    await guilds.set_guild_banner(req, 222222)
    profile2 = await guilds.get_guild(req, 222222)
    assert json.loads(profile2.body)["data"]["custom_banner_url"] == ""


@pytest.mark.asyncio
async def test_guild_dashboard_cards_collect_module_widgets(app, monkeypatch):
    """GET /guilds/{id}/dashboard is a single aggregate: profile + viewer + cards."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    guild = SimpleNamespace(
        id=333333, name="Cards Guild", member_count=42, owner_id=1, owner=None,
        banner=None, icon=None, description=None, premium_tier=0,
        premium_subscription_count=0, premium_subscriber_count=0, max_members=100,
        channels=[], roles=[], emojis=[], created_at=None,
        verification_level=None, features=[], scheduled_events=[], members=[],
        text_channels=[], voice_channels=[],
    )
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild

    async def fake_cards(_gid):
        return [{"id": "reputation_top", "module": "reputation", "title": "Top Members", "type": "list", "items": [], "link": "/guild/333333/modules/reputation"}]

    bot.modules.get_dashboard_cards = fake_cards
    bot.modules.get_all_modules = lambda: {
        "reputation": SimpleNamespace(
            name="reputation", title="Reputation", description="Levels", link="",
            get_commands=lambda: [SimpleNamespace(name="rank", description="Check rank", slash=True)],
        ),
    }
    bot.modules.is_enabled_for_guild = lambda _gid, mname: mname == "reputation"
    request = SimpleNamespace(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))

    import json
    resp = await guilds.get_guild_dashboard(request, 333333)
    assert resp.status_code == 200
    data = json.loads(resp.body)["data"]
    assert data["viewer"] is False
    assert data["guild"]["name"] == "Cards Guild"
    assert data["cards"][0]["id"] == "reputation_top"
    assert data["cards"][0]["module"] == "reputation"
    assert data["cards"][0]["link"] == "/guild/333333/modules/reputation"
    assert any(m["name"] == "reputation" and m["link"] for m in data["modules"])
    rep = next(m for m in data["modules"] if m["name"] == "reputation")
    assert rep["commands"][0]["name"] == "rank"
    assert rep["commands"][0]["slash"] is True


@pytest.mark.asyncio
async def test_set_guild_slug_validates_persists_and_clears(app, monkeypatch):
    """PUT /guilds/{id}/slug sets a validated, unique slug; invalid -> 400."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as s:
        from sqlalchemy import select

        if not (await s.execute(select(Guild).where(Guild.discord_id == "555555"))).scalars().first():
            s.add(Guild(discord_id="555555", name="Slug Guild"))
            await s.commit()

    guild = SimpleNamespace(
        id=555555, name="Slug Guild", member_count=10, owner_id=1, owner=None,
        banner=None, icon=None, description=None, premium_tier=0,
        premium_subscription_count=0, premium_subscriber_count=0, max_members=100,
        channels=[], roles=[], emojis=[], created_at=None,
        verification_level=None, features=[], scheduled_events=[], members=[],
        text_channels=[], voice_channels=[],
    )
    bot = app.state.bot
    bot.get_guild = lambda _gid: guild
    request = SimpleNamespace(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))

    import json

    class _Req(SimpleNamespace):
        _body = {}

        async def json(self):
            return self._body

    # Valid slug.
    r = _Req(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    r._body = {"slug": "my-server"}
    resp = await guilds.set_guild_slug(r, 555555)
    assert resp.status_code == 200
    assert json.loads(resp.body)["data"]["slug"] == "my-server"
    # get_guild returns it.
    profile = await guilds.get_guild(request, 555555)
    assert json.loads(profile.body)["data"]["slug"] == "my-server"

    # Invalid slug -> 400.
    bad = _Req(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    bad._body = {"slug": "bad slug!!"}
    resp_bad = await guilds.set_guild_slug(bad, 555555)
    assert resp_bad.status_code == 400

    # Empty clears it.
    clear = _Req(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    clear._body = {"slug": ""}
    await guilds.set_guild_slug(clear, 555555)
    profile2 = await guilds.get_guild(request, 555555)
    assert json.loads(profile2.body)["data"]["slug"] == ""


@pytest.mark.asyncio
async def test_guild_slug_redirect_resolves_to_numeric_guild(app, monkeypatch):
    """GET /g/{slug} redirects to the numeric guild page; unknown -> 404."""
    from types import SimpleNamespace

    import config
    from dashboard.routes.api import guilds
    from dashboard.routes.web.home import guild_slug_redirect

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as s:
        from sqlalchemy import select

        if not (await s.execute(select(Guild).where(Guild.discord_id == "555555"))).scalars().first():
            s.add(Guild(discord_id="555555", name="Slug Guild"))
            await s.commit()

    bot = app.state.bot
    request = SimpleNamespace(state=SimpleNamespace(bot=bot), session={"role": "admin"}, url=SimpleNamespace(path="/x"))

    class _Req(SimpleNamespace):
        _body = {}

        async def json(self):
            return self._body

    set_req = _Req(state=SimpleNamespace(bot=bot, guild_viewer=False), session={"role": "admin"}, url=SimpleNamespace(path="/x"))
    set_req._body = {"slug": "my-server"}
    await guilds.set_guild_slug(set_req, 555555)

    # Known slug -> 302 redirect to /guild/{id}.
    resp = await guild_slug_redirect(request, "my-server")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/guild/555555"

    # Slug matching is case-insensitive.
    resp2 = await guild_slug_redirect(request, "MY-SERVER")
    assert resp2.status_code == 302

    # Unknown slug -> 404.
    resp3 = await guild_slug_redirect(request, "does-not-exist")
    assert resp3.status_code == 404


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


def test_auto_voice_flat_config_validates_against_grouped_schema():
    """Legacy flat auto_voice configs must validate cleanly against the
    grouped dashboard schema — no 'unknown setting' false positives.

    The module normalizes flat keys into their schema groups before the
    validator sees them; a config that only exists in the flat shape must
    not be reported unhealthy."""
    from modules.auto_voice.module import CONFIG_GROUPS, AutoVoiceModule, normalize_config

    schema = AutoVoiceModule.__new__(AutoVoiceModule).get_settings_schema()
    properties = schema.get("properties", {})

    # Flat legacy shape as stored by older versions.
    flat = {
        "primary_channel_id": "111",
        "channel_name_template": "## [@@game@@]",
        "fallback_name": "Temp",
        "name_uppercase": False,
        "name_lowercase": True,
        "name_titlecase": False,
        "user_limit": 5,
        "bitrate_kbps": 64,
        "inherit_permissions": True,
        "private_by_default": False,
        "empty_delete_delay_seconds": 30,
        "owner_can_rename": True,
        "owner_can_limit": True,
        "owner_can_lock": False,
        "required_role_id": "",
    }
    normalized = normalize_config(flat)

    # Every flat key lands in exactly one declared group.
    all_group_keys = {k for keys in CONFIG_GROUPS.values() for k in keys}
    for key in flat:
        assert key in all_group_keys, key

    from dashboard.routes.api.modules import _validate_config

    errors = _validate_config(normalized, properties)
    assert errors == [], f"flat auto_voice config must validate clean, got {errors}"

    # The grouped shape itself also validates (casing now under "channel").
    grouped_errors = _validate_config(
        {"channel": {"primary_channel_id": "222", "name_uppercase": True}},
        properties,
    )
    assert grouped_errors == [], f"grouped auto_voice config must validate clean, got {grouped_errors}"

    # A legacy config still carrying the pre-consolidation "naming" group must
    # normalize into the "channel" group and validate clean (no orphan key).
    legacy = normalize_config({"channel": {"primary_channel_id": "222"}, "naming": {"name_uppercase": True}})
    assert "naming" not in legacy
    assert legacy["channel"]["name_uppercase"] is True
    legacy_errors = _validate_config(legacy, properties)
    assert legacy_errors == [], f"legacy 'naming' auto_voice config must validate clean, got {legacy_errors}"


def test_speak_config_with_module_managed_phrases_validates_clean():
    """The speak module stores a module-managed ``phrases`` dict alongside its
    form settings; config health must not flag it as an unknown setting."""
    from dashboard.routes.api.modules import _validate_config
    from modules.speak.module import SpeakModule

    schema = SpeakModule.__new__(SpeakModule).get_settings_schema()
    properties = schema.get("properties", {})

    # ``phrases`` is declared in the schema (as a free-form object with no
    # sub-properties — module-managed data, not a form control).
    assert "phrases" in properties
    assert properties["phrases"]["type"] == "object"
    assert "properties" not in properties["phrases"]

    stored = {
        "delete_delay_seconds": 5,
        "phrases": {"word1": "hello", "word2": "world"},
    }
    errors = _validate_config(stored, properties)
    assert errors == [], f"speak config with phrases must validate clean, got {errors}"

    # The generic form renderer must not try to draw a control for the
    # free-form ``phrases`` object (it has no renderable sub-fields).
    module_detail = (Path(__file__).resolve().parents[2] / "dashboard" / "templates" / "pages" / "module_detail.html").read_text()
    assert (
        "prop.type != 'object' or prop.properties" in module_detail
    ), "form renderer must skip free-form object props (module-managed data)"


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
async def test_modules_plugin_manager_links_plugins_repo(client, app):
    """The Plugin Manager must link to the plugins repository so owners can
    find ready-made single-file modules to upload."""
    from unittest.mock import MagicMock

    module = MagicMock()
    module.version = "1.0.0"
    module.description = "plugin"
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    app.state.bot.modules.get_all_modules.return_value = {"auto_voice": module}

    response = await client.get("/guild/1/modules")
    assert response.status_code == 200
    assert (
        'href="https://github.com/warmbo/bark-plugins" target="_blank" rel="noopener"'
        in response.text
    )


@pytest.mark.asyncio
async def test_modules_grid_addons_default_off(client, app):
    """Add-on plugins with no persisted per-guild row render OFF (not ON).

    Regression for 2026-08-10: the card template defaulted missing rows to
    enabled, so freshly installed plugins showed as on while the runtime
    treated them as off.
    """
    from unittest.mock import MagicMock

    def make_module(name):
        m = MagicMock()
        m.version = "1.0.0"
        m.description = f"{name} plugin"
        m.get_commands.return_value = []
        m.get_events.return_value = []
        m.get_dashboard_pages.return_value = []
        return m

    app.state.bot.modules.get_all_modules.return_value = {
        "logging": make_module("logging"),
        "dice_roller": make_module("dice_roller"),
        "fun_facts": make_module("fun_facts"),
    }
    app.state.bot.modules.plugin_names.return_value = {"dice_roller", "fun_facts"}
    # No persisted rows: core modules default enabled, plugins default disabled.
    app.state.bot.modules.is_enabled_for_guild.side_effect = (
        lambda gid, name: name not in {"dice_roller", "fun_facts"}
    )

    response = await client.get("/guild/1/modules")
    assert response.status_code == 200

    # Core module card renders enabled (is-enabled + On)
    assert 'data-module="logging"' in response.text
    assert "module-card is-enabled" in response.text
    assert ">On<" in response.text

    # Add-on cards render disabled (is-disabled + Off + unchecked)
    for name in ("dice_roller", "fun_facts"):
        assert f'data-module="{name}"' in response.text
    assert "module-card is-disabled" in response.text
    assert ">Off<" in response.text
    # No add-on checkbox may carry the checked attribute
    import re

    addon_block = response.text[response.text.index("Add-on Modules") :]
    assert re.search(r'module-toggle-(dice_roller|fun_facts)".*?checked', addon_block) is None


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
async def test_role_manager_assignments_resolve_names(app, client, db):
    """Assignments endpoint returns resolved user/role names when the guild
    cache knows them, with the triggering rule name."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from modules.role_manager.module import RoleManagerModule
    from services.bark_context import BarkContext

    # Register the role_manager router for this test.
    bot = app.state.bot
    ctx = BarkContext(bot, bot.modules.event_bus)
    router = RoleManagerModule(ctx).get_api_routes()
    assert router is not None
    app.include_router(router, prefix="/api/v1")

    # Seed a rule + assignment.

    from database.engine import session_scope
    from database.models.role_manager import RoleAssignment, RoleRule

    async with session_scope() as session:
        rule = RoleRule(
            guild_id="1",
            name="Counter-Strike role",
            rule_type="reaction",
            role_id="555",
            trigger_key="reaction:123:🎮",
            trigger_config='{"channel_id": "123", "emoji": "🎮"}',
        )
        session.add(rule)
        await session.flush()
        session.add(
            RoleAssignment(
                guild_id="1",
                user_id="903",
                role_id="555",
                rule_id=rule.id,
                action="add",
                reason="",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    # Give the mock guild a member and a role with real names.
    guild = bot.get_guild(1)
    guild.get_member.return_value = SimpleNamespace(display_name="Jenny Ruiz")
    guild.get_role.return_value = SimpleNamespace(name="Member")

    resp = await client.get("/api/v1/guilds/1/modules/role_manager/assignments")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assignments = data["data"]["assignments"]
    assert assignments
    a = assignments[0]
    assert a["user_name"] == "Jenny Ruiz"
    assert a["role_name"] == "Member"
    assert a["rule_name"] == "Counter-Strike role"
    # Raw ids still present for reference.
    assert a["user_id"] == "903"
    assert a["role_id"] == "555"


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
async def test_note_reads_require_moderation_permission(client, monkeypatch):
    """Viewer-level sessions must not read private moderation notes."""
    from unittest.mock import AsyncMock

    from dashboard.routes.api import notes

    monkeypatch.setattr(notes, "_can_view_notes", AsyncMock(return_value=False))

    all_notes = await client.get("/api/v1/guilds/1/notes")
    user_notes = await client.get("/api/v1/guilds/1/notes/user/123456")

    assert all_notes.status_code == 403
    assert user_notes.status_code == 403
    assert all_notes.json()["error"] == "Insufficient permissions to view notes"


@pytest.mark.asyncio
async def test_discord_audit_log_requires_admin_permission(client, monkeypatch):
    """Discord's native audit history is administrator-only data."""
    from dashboard.routes.api import audit_log

    monkeypatch.setattr(audit_log, "_can_view_audit_log", lambda request, guild_id: False)

    entries = await client.get("/api/v1/guilds/1/audit-log")
    summary = await client.get("/api/v1/guilds/1/audit-log/summary")

    assert entries.status_code == 403
    assert summary.status_code == 403


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


@pytest.mark.asyncio
async def test_list_modules_reports_true_guild_state(client, app):
    """The modules API must report the authoritative per-guild state.

    Regression for 2026-08-10: missing ModuleConfig rows defaulted to
    enabled, so add-on plugins with no row reported enabled while the
    runtime defaulted them to disabled.
    """
    from unittest.mock import MagicMock

    def make_module(name):
        m = MagicMock()
        m.version = "1.0.0"
        m.description = f"{name} plugin"
        m.get_commands.return_value = []
        m.get_events.return_value = []
        m.get_settings_schema.return_value = {}
        return m

    app.state.bot.modules.get_all_modules.return_value = {
        "logging": make_module("logging"),
        "fun_facts": make_module("fun_facts"),
    }
    app.state.bot.modules.plugin_names.return_value = {"fun_facts"}
    # No persisted rows: core defaults enabled, plugin defaults disabled.
    app.state.bot.modules.is_enabled_for_guild.side_effect = (
        lambda gid, name: name not in {"fun_facts"}
    )

    resp = await client.get("/api/v1/guilds/1/modules")
    assert resp.status_code == 200
    by_name = {m["name"]: m["enabled"] for m in resp.json()["data"]["modules"]}
    assert by_name["logging"] is True
    assert by_name["fun_facts"] is False


@pytest.mark.asyncio
async def test_get_module_reports_true_guild_state(client, app):
    """Single-module API must agree with the runtime per-guild state."""
    from unittest.mock import MagicMock

    module = MagicMock()
    module.name = "fun_facts"
    module.version = "1.0.0"
    module.description = "fun facts plugin"
    module.author = "test"
    module.get_commands.return_value = []
    module.get_events.return_value = []
    module.get_dashboard_pages.return_value = []
    module.get_settings_schema.return_value = {}
    app.state.bot.modules.get_module.return_value = module
    app.state.bot.modules.is_enabled_for_guild.return_value = False

    resp = await client.get("/api/v1/guilds/1/modules/fun_facts")
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False


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


@pytest.mark.asyncio
async def test_manifest_groups_plugins_under_addon_modules(client, app):
    """Plugin modules land in the 'Add-on Modules' nav category, defaults in 'Modules'."""
    from types import SimpleNamespace

    def make_module(name: str, label: str) -> SimpleNamespace:
        return SimpleNamespace(
            version="1.0.0",
            description=f"{label} module",
            get_dashboard_pages=lambda: [
                SimpleNamespace(
                    route=f"/guild/{{guild_id}}/modules/{name}",
                    label=label,
                    icon="zap",
                    category="",
                )
            ],
            get_actions=lambda: [],
            get_commands=lambda: [],
            get_settings_schema=lambda: {},
        )

    core = make_module("alpha", "Alpha")
    plugin = make_module("beta", "Beta")
    bot = app.state.bot
    bot.modules.get_all_modules.return_value = {"alpha": core, "beta": plugin}
    bot.modules.is_plugin.side_effect = lambda name: name == "beta"

    resp = await client.get("/api/v1/guilds/1/manifest")
    assert resp.status_code == 200
    categories = resp.json()["data"]["categories"]

    assert categories["_modules"]["label"] == "Modules"
    core_pages = categories["_modules"]["pages"]
    assert [p["module"] for p in core_pages] == ["alpha"]
    assert all(p["is_plugin"] is False for p in core_pages)

    # The unlabeled core section must never duplicate plugin entries.
    assert "beta" not in [
        p.get("module") for p in categories.get("_core", {}).get("pages", [])
    ]

    assert categories["_plugins"]["label"] == "Add-on Modules"
    plugin_pages = categories["_plugins"]["pages"]
    assert [p["module"] for p in plugin_pages] == ["beta"]
    assert all(p["is_plugin"] is True for p in plugin_pages)


@pytest.mark.asyncio
async def test_manifest_lists_pageless_plugins_in_addon_nav(client, app):
    """Plugins without dashboard pages still get an 'Add-on Modules' nav entry."""
    from types import SimpleNamespace

    def make_module(name: str, has_pages: bool) -> SimpleNamespace:
        return SimpleNamespace(
            version="1.0.0",
            description=f"{name} module",
            get_dashboard_pages=lambda: (
                [
                    SimpleNamespace(
                        route=f"/guild/{{guild_id}}/modules/{name}",
                        label=name.title(),
                        icon="zap",
                        category="",
                    )
                ]
                if has_pages
                else []
            ),
            get_actions=lambda: [],
            get_commands=lambda: [],
            get_settings_schema=lambda: {},
        )

    bot = app.state.bot
    bot.modules.get_all_modules.return_value = {
        "dice": make_module("dice", has_pages=False),
        "trivia": make_module("trivia", has_pages=True),
    }
    bot.modules.is_plugin.side_effect = lambda name: True

    resp = await client.get("/api/v1/guilds/1/manifest")
    assert resp.status_code == 200
    categories = resp.json()["data"]["categories"]
    plugin_pages = categories["_plugins"]["pages"]
    modules = [p["module"] for p in plugin_pages]
    assert "dice" in modules and "trivia" in modules
    dice_entry = next(p for p in plugin_pages if p["module"] == "dice")
    assert dice_entry["route"] == "/guild/1/modules/dice"
    assert dice_entry["is_plugin"] is True
    assert dice_entry["enabled"] is True


@pytest.mark.asyncio
async def test_manifest_hides_disabled_addons_from_sidebar(client, app):
    """An add-on that's uploaded but not enabled for the guild stays out of
    the left-pane nav, but is still listed (disabled) in the Modules surface.
    """
    from types import SimpleNamespace

    def make_module(name: str, has_pages: bool) -> SimpleNamespace:
        return SimpleNamespace(
            version="1.0.0",
            description=f"{name} module",
            get_dashboard_pages=lambda: (
                [
                    SimpleNamespace(
                        route=f"/guild/{{guild_id}}/modules/{name}",
                        label=name.title(),
                        icon="zap",
                        category="",
                    )
                ]
                if has_pages
                else []
            ),
            get_actions=lambda: [],
            get_commands=lambda: [],
            get_settings_schema=lambda: {},
        )

    bot = app.state.bot
    bot.modules.get_all_modules.return_value = {
        "alpha": make_module("alpha", has_pages=True),
        "beta": make_module("beta", has_pages=False),
    }
    bot.modules.is_plugin.side_effect = lambda name: name == "beta"
    # alpha is enabled for the guild; the beta add-on is disabled.
    bot.modules.is_enabled_for_guild.side_effect = (
        lambda guild_id, name: name != "beta"
    )

    resp = await client.get("/api/v1/guilds/1/manifest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    categories = data["categories"]

    # Enabled core module appears in the left-pane Modules nav.
    assert categories["_modules"]["pages"][0]["module"] == "alpha"

    # Disabled add-on is NOT in the sidebar (no "Add-on Modules" category).
    assert "_plugins" not in categories

    # But it is still listed in the Modules management surface, marked off.
    beta = next(m for m in data["modules"] if m["name"] == "beta")
    assert beta["enabled"] is False

    # Stats reflect the authoritative count.
    assert data["stats"]["modules_total"] == 2
    assert data["stats"]["modules_enabled"] == 1


def test_repo_plugin_catalog_only_lists_installable_plugins(monkeypatch):
    """The plugin catalog parses the bark-plugins README and must surface
    ONLY rows whose File cell links to a real plugins/*.py file — planned
    (not-yet-built) entries and header rows are skipped, and the file path is
    extracted from the markdown link so download/install works.
    """
    from dashboard.routes.api import manifest

    readme = """\
## Available plugins

| Plugin | File | What it adds |
|---|---|---|
| Fun | [`plugins/fun.py`](plugins/fun.py) | rolls dice |
| Trivia | [`plugins/trivia.py`](plugins/trivia.py) | multiplayer trivia |
| Minimal Example | [`plugins/minimal_example.py`](plugins/minimal_example.py) | hello |

## Plugin ideas (not yet built)

| Idea | File (planned) | What it would add | Deps |
|---|---|---|---|
| Slots | `plugins/slots.py` | slot machine | none |
| Wordle | `plugins/wordle.py` | daily word | none |
"""

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return readme.encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())

    rows = manifest._repo_plugin_entries()
    names = [r["name"] for r in rows]
    # Real plugins only, in order; no planned/idea rows.
    assert names == ["Fun", "Trivia", "Minimal Example"]
    for r in rows:
        # file is a clean plugins/*.py path (not the markdown cell), and the
        # URL points at that same file.
        file = str(r["file"])
        assert file.startswith("plugins/") and file.endswith(".py")
        assert "[" not in file and "]" not in file
        assert str(r["url"]).endswith(file)


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
                    guild_id="1",
                    case_number=1,
                    action_type="warn",
                    target_id="900",
                    target_tag="WarnedUser",
                    moderator_id="800",
                    moderator_tag="Mod",
                    reason="spam",
                    created_at=now - timedelta(minutes=1),
                ),
                WarningModel(
                    guild_id="1",
                    user_id="901",
                    moderator_id="800",
                    reason="nope",
                    active=True,
                    created_at=now - timedelta(minutes=2),
                ),
                # Non-numeric actor ID (dashboard) must not crash name resolution.
                WarningModel(
                    guild_id="1",
                    user_id="907",
                    moderator_id="dashboard",
                    reason="spam",
                    active=True,
                    created_at=now - timedelta(seconds=15),
                ),
                # Noisy per-message scoring must be filtered out of the feed.
                ReputationEvent(
                    guild_id="1",
                    actor_id="800",
                    target_id="902",
                    event_type="thanks",
                    points=2.0,
                    created_at=now - timedelta(minutes=3),
                ),
                ReputationEvent(
                    guild_id="1",
                    actor_id="800",
                    target_id="902",
                    event_type="message",
                    points=1.0,
                    created_at=now - timedelta(seconds=30),
                ),
                ReputationEvent(
                    guild_id="1",
                    actor_id="800",
                    target_id="902",
                    event_type="reaction",
                    points=0.5,
                    created_at=now - timedelta(seconds=20),
                ),
                ReputationEvent(
                    guild_id="1",
                    actor_id="800",
                    target_id="902",
                    event_type="reaction_given",
                    points=0.5,
                    created_at=now - timedelta(seconds=18),
                ),
                # Messaging audit event — target_id is a message id, not a user.
                AuditLog(
                    guild_id="1",
                    action="link_posted",
                    actor_id="800",
                    target_id="1533906144068632777",
                    details='{"channel": "#general", "link": "https://example.com", "actor_tag": "Mod"}',
                    created_at=now - timedelta(seconds=10),
                ),
                RoleAssignment(
                    guild_id="1",
                    user_id="903",
                    role_id="700",
                    action="add",
                    created_at=now - timedelta(minutes=4),
                ),
                UserNote(
                    guild_id="1",
                    user_id="904",
                    author_id="800",
                    content="watch this member",
                    created_at=now - timedelta(minutes=5),
                ),
                VoiceSession(
                    guild_id="1",
                    user_id="905",
                    channel_id="600",
                    channel_name="General",
                    joined_at=now - timedelta(hours=3),
                    left_at=now - timedelta(minutes=6),
                    duration_seconds=3200,
                ),
                AutoVoiceChannel(
                    channel_id="601",
                    guild_id="1",
                    owner_id="906",
                    primary_channel_id="602",
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
    voice_timestamp = datetime.fromisoformat(voice_items[0]["timestamp"])
    assert now - voice_timestamp >= timedelta(hours=2, minutes=59)

    # Every persisted timestamp is serialized as explicit UTC, never as a
    # browser-local naive datetime.
    for item in activity:
        if item["timestamp"]:
            timestamp = datetime.fromisoformat(item["timestamp"])
            assert timestamp.utcoffset() == timedelta(0)

    # Every item has a category, a human label, and a resolved display name.
    for a in activity:
        assert a.get("category") in {
            "moderation",
            "messaging",
            "voice",
            "roles",
            "reputation",
            "notes",
            "system",
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


@pytest.mark.asyncio
async def test_activity_reputation_feed_filters_noise_in_sql(client, db):
    """When the 50 most recent reputation events are all noisy (message /
    reaction), older notable events must still surface — the filter must run
    in SQL, not after fetching the newest 50 rows."""
    from datetime import datetime, timedelta, timezone

    from database.engine import session_scope
    from database.models.reputation import ReputationEvent

    async with session_scope() as session:
        now = datetime.now(timezone.utc)
        # 60 noisy events all newer than the single notable one.
        session.add_all(
            ReputationEvent(
                guild_id="1",
                actor_id="800",
                target_id="902",
                event_type="message" if i % 2 else "reaction",
                points=1.0,
                created_at=now - timedelta(seconds=i + 1),
            )
            for i in range(60)
        )
        session.add(
            ReputationEvent(
                guild_id="1",
                actor_id="800",
                target_id="902",
                event_type="thanks",
                points=2.0,
                created_at=now - timedelta(minutes=5),
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/guilds/1/activity")
    assert resp.status_code == 200
    rep_items = [a for a in resp.json()["data"]["activity"] if a["type"] == "reputation"]
    assert rep_items, "notable reputation events must not be hidden by noisy ones"
    assert any(a["action"] == "thanks" for a in rep_items)


@pytest.mark.asyncio
async def test_upload_image_requires_permission_and_returns_public_url(client, app, monkeypatch):
    """Image uploads gate on content permissions, validate input, and serve back."""
    import dashboard.routes.api.uploads as uploads_route

    # Denied without a content-editing permission.
    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: False)
    denied = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert denied.status_code == 403

    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: True)

    # Reject disallowed content type.
    bad_type = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert bad_type.status_code == 400

    # Reject empty uploads.
    empty = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.png", b"", "image/png")},
    )
    assert empty.status_code == 400

    # Reject oversized uploads.
    oversized = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 413

    # Valid PNG upload returns a public URL, persists the file, and serves it.
    valid = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert valid.status_code == 200
    url = valid.json()["data"]["url"]
    assert url.startswith("http://127.0.0.1:8090/media/uploads/1/")
    name = url.rsplit("/", 1)[1]
    saved = uploads_route._guild_uploads_dir("1") / name
    assert saved.read_bytes() == b"\x89PNG\r\n\x1a\n"

    served = await client.get(f"/media/uploads/1/{name}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_upload_image_write_failure_returns_clean_500(client, app, monkeypatch):
    """A disk write failure must return a JSON error, not an unhandled traceback."""
    import dashboard.routes.api.uploads as uploads_route

    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: True)

    def boom_directory(guild_id: str):
        class Unwritable:
            def mkdir(self, *a, **k):
                raise OSError("permission denied")

            def iterdir(self):
                raise OSError("permission denied")

            def exists(self):
                return False

        return Unwritable()

    monkeypatch.setattr(uploads_route, "_guild_uploads_dir", boom_directory)

    resp = await client.post(
        "/api/v1/guilds/1/uploads",
        files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body.get("success") is False
    assert "error" in body


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
        {"id": "logs", "label": "Logs", "template": "modules/logging/templates/logging_logs.html"}
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


@pytest.mark.asyncio
async def test_upload_library_lists_previous_uploads(client, app, monkeypatch, tmp_path):
    """Library endpoint returns previously uploaded images newest-first, gated by permission."""
    import dashboard.routes.api.uploads as uploads_route

    directory = tmp_path / "uploads"
    guild_dir = directory / "1"
    guild_dir.mkdir(parents=True, exist_ok=True)
    (guild_dir / "alpha.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (guild_dir / "beta.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (guild_dir / "note.txt").write_bytes(b"skip me")
    # Another guild's uploads must never appear in this guild's library.
    other_dir = directory / "2"
    other_dir.mkdir(parents=True, exist_ok=True)
    (other_dir / "other.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(uploads_route, "uploads_directory", lambda: directory)

    # Denied without a content-editing permission.
    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: False)
    denied = await client.get("/api/v1/guilds/1/uploads")
    assert denied.status_code == 403

    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: True)
    ok = await client.get("/api/v1/guilds/1/uploads")
    assert ok.status_code == 200
    items = ok.json()["data"]["items"]
    names = [i["name"] for i in items]
    # Only this guild's image files, no .txt, and never another guild's files.
    assert set(names) == {"alpha.png", "beta.jpg"}
    assert all(i["url"].startswith("http://127.0.0.1:8090/media/uploads/1/") for i in items)


@pytest.mark.asyncio
async def test_upload_delete_removes_file_and_guards_paths(client, app, monkeypatch, tmp_path):
    """DELETE upload removes the file and rejects traversal/type attacks."""
    import dashboard.routes.api.uploads as uploads_route

    directory = tmp_path / "uploads"
    guild_dir = directory / "1"
    guild_dir.mkdir(parents=True, exist_ok=True)
    victim = guild_dir / "victim.png"
    victim.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(uploads_route, "uploads_directory", lambda: directory)
    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: True)

    # Path traversal is rejected (FastAPI may 404 before the handler runs; either way no delete).
    bad = await client.delete("/api/v1/guilds/1/uploads/..%2Fsecret.png")
    assert bad.status_code in (400, 404)
    assert victim.exists()

    # Wrong extension is rejected.
    wrong = await client.delete("/api/v1/guilds/1/uploads/secret.txt")
    assert wrong.status_code == 400

    # Missing file yields 404.
    missing = await client.delete("/api/v1/guilds/1/uploads/nope.png")
    assert missing.status_code == 404

    # Valid delete removes the file.
    ok = await client.delete("/api/v1/guilds/1/uploads/victim.png")
    assert ok.status_code == 200
    assert not victim.exists()

    # Deletion gated on permission.
    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: False)
    (guild_dir / "locked.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    denied = await client.delete("/api/v1/guilds/1/uploads/locked.png")
    assert denied.status_code == 403
    assert (guild_dir / "locked.png").exists()


@pytest.mark.asyncio
async def test_upload_delete_cannot_touch_another_guilds_file(client, app, monkeypatch, tmp_path):
    """A guild can only delete files from its own uploads directory."""
    import dashboard.routes.api.uploads as uploads_route

    directory = tmp_path / "uploads"
    other_dir = directory / "2"
    other_dir.mkdir(parents=True, exist_ok=True)
    (other_dir / "sneaky.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(uploads_route, "uploads_directory", lambda: directory)
    monkeypatch.setattr(uploads_route, "check_api_permission", lambda *_args, **_kwargs: True)

    # Guild 1 cannot delete guild 2's file (resolves to a missing path -> 404).
    denied = await client.delete("/api/v1/guilds/1/uploads/sneaky.png")
    assert denied.status_code == 404
    assert (other_dir / "sneaky.png").exists()


@pytest.mark.asyncio
async def test_media_uploads_are_public_without_session(client, app, monkeypatch, tmp_path):
    """/media/uploads must be reachable without auth so Discord can fetch images."""
    import dashboard.routes.api.uploads as uploads_route

    directory = tmp_path / "uploads"
    guild_dir = directory / "1"
    guild_dir.mkdir(parents=True, exist_ok=True)
    (guild_dir / "public.gif").write_bytes(b"GIF89a")
    monkeypatch.setattr(uploads_route, "uploads_directory", lambda: directory)

    response = await client.get("/media/uploads/1/public.gif")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/gif")


# ── Backup & Restore (export/import) ─────────────────


@pytest.mark.asyncio
async def test_settings_export_returns_backup_with_settings_and_modules(client, app, db):
    """Export bundles guild settings + module configs/stats as editable JSON."""
    from database.engine import session_scope
    from database.models.guild import GuildSetting
    from database.models.module import ModuleConfig

    async with session_scope() as session:
        session.add(GuildSetting(guild_id="1", key="prefix", value="!"))
        session.add(
            ModuleConfig(
                guild_id="1",
                module_name="trivia",
                enabled=True,
                config='{"difficulty": "medium"}',
            )
        )
        await session.commit()

    class FakeModule:
        name = "trivia"

        async def export_stats(self, guild_id):
            return {"scores": [{"user_id": "9", "points": 5}]}

        async def import_stats(self, guild_id, stats):
            return [f"trivia: restored {len(stats.get('scores', []))} row(s)"]

        async def save_dashboard_config(self, guild_id, config):
            return True

    fake = FakeModule()
    app.state.bot.modules.get_all_modules.return_value = {"trivia": fake}

    response = await client.get("/api/v1/guilds/1/settings/export")
    assert response.status_code == 200
    backup = response.json()["data"]["backup"]
    assert backup["format"] == "bark-backup"
    assert backup["guild_id"] == "1"
    assert backup["settings"] == {"prefix": "!"}
    assert backup["modules"]["trivia"]["enabled"] is True
    assert backup["modules"]["trivia"]["config"] == {"difficulty": "medium"}
    assert backup["modules"]["trivia"]["stats"] == {
        "scores": [{"user_id": "9", "points": 5}]
    }


@pytest.mark.asyncio
async def test_settings_import_applies_settings_configs_and_stats(client, app, db):
    """Import writes settings + module configs and reports stats restore."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.guild import GuildSetting

    fake_module = MagicMock()
    fake_module.save_dashboard_config = AsyncMock()
    fake_module.import_stats = AsyncMock(return_value=["trivia: restored 2 row(s)"])
    fake_module.export_stats = AsyncMock(return_value={})
    app.state.bot.modules.get_all_modules.return_value = {"trivia": fake_module}

    backup = {
        "format": "bark-backup",
        "version": 1,
        "exported_at": "2026-08-06T00:00:00Z",
        "guild_id": "1",
        "settings": {"prefix": "?", "language": "en"},
        "modules": {
            "trivia": {
                "enabled": True,
                "priority": 100,
                "config": {"difficulty": "hard"},
                "stats": {"scores": [{"user_id": "9", "points": 5}]},
            }
        },
    }
    response = await client.post(
        "/api/v1/guilds/1/settings/import", json={"backup": backup}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["imported"] is True
    assert any("settings: restored 2" in line for line in data["report"])
    fake_module.save_dashboard_config.assert_awaited_once_with(1, {"difficulty": "hard"})
    fake_module.import_stats.assert_awaited_once()

    async with session_scope() as session:
        settings = (
            await session.execute(
                select(GuildSetting).where(GuildSetting.guild_id == "1")
            )
        ).scalars().all()
        assert {s.key: s.value for s in settings} == {"prefix": "?", "language": "en"}


@pytest.mark.asyncio
async def test_settings_import_rejects_non_backup_files(client, app, db):
    response = await client.post(
        "/api/v1/guilds/1/settings/import",
        json={"backup": {"format": "other", "version": 1}},
    )
    assert response.status_code == 400

    response = await client.post(
        "/api/v1/guilds/1/settings/import",
        json={"backup": {"format": "bark-backup", "version": None}},
    )
    assert response.status_code == 400
    assert "Unsupported backup version" in response.json()["error"]


@pytest.mark.asyncio
async def test_settings_import_persists_config_for_missing_module(client, app, db):
    """Config rows for not-yet-installed modules still persist for later installs."""
    from sqlalchemy import select

    from database.engine import session_scope
    from database.models.module import ModuleConfig

    app.state.bot.modules.get_all_modules.return_value = {}

    backup = {
        "format": "bark-backup",
        "version": 1,
        "guild_id": "1",
        "settings": {},
        "modules": {
            "dice_roller": {
                "enabled": True,
                "priority": 100,
                "config": {"max": 20},
                "stats": {},
            }
        },
    }
    response = await client.post(
        "/api/v1/guilds/1/settings/import", json={"backup": backup}
    )
    assert response.status_code == 200

    async with session_scope() as session:
        row = (
            await session.execute(
                select(ModuleConfig).where(
                    ModuleConfig.guild_id == "1",
                    ModuleConfig.module_name == "dice_roller",
                )
            )
        ).scalar_one()
    assert row.enabled is True
    assert '"max": 20' in row.config
