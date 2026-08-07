"""Authorization and validation tests for reputation dashboard routes."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.guild import Guild
from database.models.permissions import DashboardUser
from modules.reputation.module import ReputationModule
from services.bark_context import BarkContext
from services.dashboard_access import replace_user_guild_access


def _session_cookie(role: str) -> str:
    session = {
        "user": {"id": "42", "username": "Auditor"},
        "role": role,
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


@pytest.mark.asyncio
async def test_reputation_read_routes_enforce_module_view_permission(db, monkeypatch):
    """A viewer must not bypass a module's configured read permission."""
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Auditor", role="viewer"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x20)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"reputation": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("viewer")),
    ) as client:
        response = await client.get("/api/v1/guilds/1/modules/reputation/leaderboard")

    assert response.status_code == 403
    assert response.json()["error"] == "Insufficient permissions"


def _manager_bot():
    """A MagicMock bot whose guild exposes a controllable role resolver."""
    from types import SimpleNamespace

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"reputation": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    guild = SimpleNamespace(id=1, get_role=lambda rid: SimpleNamespace(id=rid))
    bot.get_guild.return_value = guild
    return bot


def test_reputation_module_declares_tiers_tab():
    """The Tiers tab must be part of the module's dashboard tabs."""
    from modules.reputation.module import ReputationModule

    bot = MagicMock()
    bot.guilds = []
    bot.modules = MagicMock()
    bot.modules.event_bus = MagicMock()
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    tabs = [t["id"] for t in module.get_extra_tabs()]
    assert "tiers" in tabs
    assert tabs.index("tiers") == 0  # primary tab for role linking


@pytest.fixture
async def _seeded_tiers(db):
    from database.models.reputation import ReputationTier

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Auditor", role="admin"))
        await session.flush()
        # Administrator-tier access row so the persisted per-guild snapshot
        # matches the admin session role the tests assert with.
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x8)}],
        )
        session.add(
            ReputationTier(
                guild_id="1",
                name="Recruit",
                symbol="⬜",
                min_level=0,
                color_hex="#99aab5",
                sort_order=0,
            )
        )
        session.add(
            ReputationTier(
                guild_id="1",
                name="Scout",
                symbol="🥉",
                min_level=10,
                color_hex="#cd7f32",
                sort_order=1,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_tiers_list_returns_ladder_sorted_by_sort_order(
    db, _seeded_tiers, monkeypatch
):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.get("/api/v1/guilds/1/modules/reputation/tiers")

    assert response.status_code == 200
    tiers = response.json()["data"]["tiers"]
    assert [t["name"] for t in tiers] == ["Recruit", "Scout"]
    assert all("role_id" in t and "assign_role" in t for t in tiers)


@pytest.mark.asyncio
async def test_tier_update_links_role(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"role_id": "777", "assign_role": True, "min_level": 12},
        )

    assert response.status_code == 200
    tier = response.json()["data"]["tier"]
    assert tier["role_id"] == "777"
    assert tier["assign_role"] is True
    assert tier["min_level"] == 12


@pytest.mark.asyncio
async def test_tier_update_rejects_role_not_in_guild(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    bot.get_guild.return_value.get_role = lambda rid: None  # no such role

    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"role_id": "999999"},
        )

    assert response.status_code == 400
    assert "not found" in response.json()["error"]


@pytest.mark.asyncio
async def test_tier_create_appends_to_ladder(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers",
            json={"name": "Overlord", "min_level": 50, "assign_role": True},
        )

    assert response.status_code == 200
    tier = response.json()["data"]["tier"]
    assert tier["name"] == "Overlord"
    assert tier["sort_order"] == 2  # appended after Recruit(0) + Scout(1)
    assert tier["min_level"] == 50

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        listing = await client.get("/api/v1/guilds/1/modules/reputation/tiers")
    names = [t["name"] for t in listing.json()["data"]["tiers"]]
    assert names == ["Recruit", "Scout", "Overlord"]


@pytest.mark.asyncio
async def test_tier_create_rejects_duplicate_name(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers", json={"name": "Scout"}
        )

    assert response.status_code == 400
    assert "already exists" in response.json()["error"]


@pytest.mark.asyncio
async def test_tier_delete_removes_and_re_tiers_profiles(
    db, _seeded_tiers, monkeypatch
):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from datetime import date

    from database.models.reputation import ReputationProfile

    async with session_scope() as session:
        session.add(
            ReputationProfile(
                guild_id="1",
                user_id="77",
                total_score=31250.0,  # level 25, current tier Scout
                current_tier="Scout",
                week_start=date.today(),
                month_start=date.today().replace(day=1),
            )
        )
        await session.commit()

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.delete(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout"
        )

    assert response.status_code == 200

    async with session_scope() as session:
        from sqlalchemy import select

        prof = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "77",
                )
            )
        ).scalar_one()
        # Re-tiered from remaining ladder: level 25 → highest remaining is Recruit
        assert prof.current_tier == "Recruit"


@pytest.mark.asyncio
async def test_tier_delete_rejects_last_tier(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        first = await client.delete(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout"
        )
        assert first.status_code == 200
        last = await client.delete(
            "/api/v1/guilds/1/modules/reputation/tiers/Recruit"
        )

    assert last.status_code == 400
    assert "last tier" in last.json()["error"]


@pytest.mark.asyncio
async def test_generate_roles_creates_and_links_missing_roles(
    db, _seeded_tiers, monkeypatch
):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from types import SimpleNamespace

    async with session_scope() as session:
        from sqlalchemy import select

        from database.models.reputation import ReputationTier

        scout = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1",
                    ReputationTier.name == "Scout",
                )
            )
        ).scalar_one()
        scout.role_id = "777"  # already linked — generation must skip it
        await session.commit()

    created_roles = []

    class FakeGuild:
        id = 1

        async def create_role(self, **kwargs):
            created_roles.append(kwargs)
            return SimpleNamespace(id=555 + len(created_roles))

        def get_role(self, rid):
            return None

    bot = _manager_bot()
    bot.get_guild.return_value = FakeGuild()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers/generate-roles"
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [c["name"] for c in data["created"]] == ["Recruit"]  # Scout already linked
    assert [s["name"] for s in data["skipped"]] == ["Scout"]
    assert created_roles[0]["name"] == "Recruit"

    async with session_scope() as session:
        from sqlalchemy import select

        from database.models.reputation import ReputationTier

        recruit = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1",
                    ReputationTier.name == "Recruit",
                )
            )
        ).scalar_one()
        assert recruit.role_id == "556"
        assert recruit.assign_role is True


@pytest.mark.asyncio
async def test_generate_roles_reports_missing_permission(
    db, _seeded_tiers, monkeypatch
):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    from unittest.mock import MagicMock

    import discord

    class NoPermGuild:
        id = 1

        async def create_role(self, **kwargs):
            raise discord.Forbidden(
                response=MagicMock(status=403), message="no perms"
            )

        def get_role(self, rid):
            return None

    bot = _manager_bot()
    bot.get_guild.return_value = NoPermGuild()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers/generate-roles"
        )

    assert response.status_code == 403
    assert "Manage Roles" in response.json()["error"]


@pytest.mark.asyncio
async def test_leaderboard_admin_set_score_updates_profile(
    db, _seeded_tiers, monkeypatch
):
    from datetime import date, timedelta

    from sqlalchemy import select

    import config
    from database.models.reputation import ReputationEvent, ReputationProfile

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    today = date.today()
    async with session_scope() as session:
        session.add(
            ReputationProfile(
                guild_id="1",
                user_id="43",
                total_score=60000.0,
                level=34,
                current_tier="Scout",
                week_start=today - timedelta(days=today.weekday()),
                month_start=today.replace(day=1),
            )
        )
        await session.commit()

    from dashboard import create_app

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/leaderboard/43/score",
            json={"score": 120000, "reason": "manual correction"},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_score"] == 120000
    assert data["level"] == 48  # isqrt(120000 / 50)
    assert data["delta"] == 60000

    async with session_scope() as session:
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "43",
                )
            )
        ).scalar_one()
        assert profile.total_score == 120000.0
        assert profile.level == 48
        events = list(
            (
                await session.execute(
                    select(ReputationEvent).where(
                        ReputationEvent.guild_id == "1",
                        ReputationEvent.event_type == "admin_adjust",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].points == 60000.0
        assert events[0].target_id == "43"


@pytest.mark.asyncio
async def test_leaderboard_set_score_requires_manage_permission(db, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Auditor", role="viewer"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": str(0x20)}],
        )

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("viewer")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/leaderboard/43/score",
            json={"score": 100},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_leaderboard_set_score_rejects_bad_values(db, _seeded_tiers, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        negative = await client.post(
            "/api/v1/guilds/1/modules/reputation/leaderboard/43/score",
            json={"score": -5},
        )
        non_numeric = await client.post(
            "/api/v1/guilds/1/modules/reputation/leaderboard/43/score",
            json={"score": "abc"},
        )
        missing = await client.post(
            "/api/v1/guilds/1/modules/reputation/leaderboard/43/score",
            json={},
        )

    assert negative.status_code == 400
    assert non_numeric.status_code == 400
    assert missing.status_code == 400
