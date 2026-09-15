"""Milestone A reputation fixes.

Covers: partial tier updates preserving role_id, robust numeric tier field
validation (bool / non-finite / wrong type => 400), ignored_roles enforcement
across all earning paths (fail-safe on unresolved members), and no points for
self-reactions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner
from sqlalchemy import select

from database.engine import session_scope
from database.models.guild import Guild
from database.models.permissions import DashboardUser
from database.models.reputation import ReputationEvent, ReputationProfile, ReputationTier
from modules.reputation.module import ReputationModule
from services.bark_context import BarkContext
from services.dashboard_access import replace_user_guild_access


# ── API-level helpers (tier endpoints) ──────────────────────────────────


def _session_cookie(role: str) -> str:
    session = {
        "user": {"id": "42", "username": "Auditor"},
        "role": role,
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


def _manager_bot():
    """A MagicMock bot whose guild exposes a controllable role resolver."""
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


async def _seed_guild_and_tiers():
    async with session_scope() as session:
        if (
            await session.execute(select(Guild).where(Guild.discord_id == "1"))
        ).scalar_one_or_none() is None:
            session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Auditor", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": "0", "owner": True}],
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


def _app_with_module(monkeypatch, bot=None):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    bot = bot or _manager_bot()
    dashboard = create_app(bot)
    module = ReputationModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")
    return dashboard


# ── Handler-level helpers ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def _guild_row(db):
    """Handler tests write Reputation* rows with a guild FK — ensure guild 1 exists."""
    async with session_scope() as session:
        existing = (
            await session.execute(select(Guild).where(Guild.discord_id == "1"))
        ).scalar_one_or_none()
        if existing is None:
            session.add(Guild(discord_id="1", name="Test Guild"))
            await session.commit()


def _role(rid: int):
    return SimpleNamespace(id=rid, name=f"role-{rid}")


def _member(uid: int, roles=(), bot=False):
    return SimpleNamespace(
        id=uid,
        bot=bot,
        guild=SimpleNamespace(id=1),
        roles=list(roles),
        mention=f"<@{uid}>",
        display_name=f"user-{uid}",
    )


class _FakeGuild:
    def __init__(self, members=(), channels=()):
        self.id = 1
        self._members = {m.id: m for m in members}
        self._channels = {c.id: c for c in channels}

    def get_member(self, user_id):
        return self._members.get(user_id)

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)


class _FakeCtx:
    """Minimal module context: controllable config + guild member resolution."""

    def __init__(self, config, guild):
        self.bot = SimpleNamespace(user=SimpleNamespace(id="1", name="bark"))
        self.config = config
        self.guilds = [guild]
        self._guild = guild

    async def get_module_config(self, name, guild_id):
        return dict(self.config)

    async def save_module_config(self, name, guild_id, cfg):
        self.config = cfg

    def get_guild(self, guild_id):
        return self._guild

    def get_member(self, guild_id, user_id):
        return self._guild.get_member(user_id) if self._guild else None


def _config(**overrides) -> dict:
    cfg = {
        "enabled_sources": {
            "messages": True,
            "reactions": True,
            "thanks": True,
            "voice": True,
        },
        "ignored_roles": "",
    }
    cfg.update(overrides)
    return cfg


def _reaction_channel(message) -> AsyncMock:
    channel = AsyncMock(spec=__import__("discord").TextChannel)
    channel.fetch_message.return_value = message
    return channel


async def _events_for(user_id: int, event_type: str | None = None) -> list:
    async with session_scope() as session:
        q = select(ReputationEvent).where(ReputationEvent.guild_id == "1")
        if user_id is not None:
            q = q.where(ReputationEvent.target_id == str(user_id))
        if event_type is not None:
            q = q.where(ReputationEvent.event_type == event_type)
        return list((await session.execute(q)).scalars().all())


# ── 1. Partial tier updates preserve role_id ────────────────────────────


@pytest.mark.asyncio
async def test_tier_update_without_role_id_preserves_linked_role(
    db, monkeypatch
):
    await _seed_guild_and_tiers()
    async with session_scope() as session:
        tier = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1", ReputationTier.name == "Scout"
                )
            )
        ).scalar_one()
        tier.role_id = "777"
        tier.assign_role = True
        await session.commit()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"min_level": 12},  # role_id omitted: must not clear it
        )

    assert response.status_code == 200
    assert response.json()["data"]["tier"]["role_id"] == "777"


@pytest.mark.asyncio
async def test_tier_update_with_explicit_null_role_id_clears_it(db, monkeypatch):
    await _seed_guild_and_tiers()
    async with session_scope() as session:
        tier = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1", ReputationTier.name == "Scout"
                )
            )
        ).scalar_one()
        tier.role_id = "777"
        await session.commit()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"role_id": None},
        )

    assert response.status_code == 200
    assert response.json()["data"]["tier"]["role_id"] is None


# ── 2. Robust numeric tier field validation (bool/non-finite/invalid) ───


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"min_level": True},
        {"min_level": "abc"},
        {"min_level": [1]},
        {"min_level": float("nan")},
        {"min_score": False},
        {"min_score": float("inf")},
        {"sort_order": "x"},
    ],
)
async def test_tier_update_rejects_invalid_numeric_fields(db, monkeypatch, payload):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    # Raw body: httpx's json= rejects NaN, but the server's JSON parser
    # accepts it — which is exactly the value this validation must reject.
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "Overlord", "min_level": True},
        {"name": "Overlord", "min_score": float("nan")},
        {"name": "Overlord", "min_level": "abc"},
    ],
)
async def test_tier_create_rejects_invalid_numeric_fields(db, monkeypatch, payload):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    # Raw body: httpx's json= rejects NaN, but the server's JSON parser
    # accepts it — which is exactly the value this validation must reject.
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_tier_create_still_defaults_omitted_numeric_fields(db, monkeypatch):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers", json={"name": "Overlord"}
        )

    assert response.status_code == 200
    tier = response.json()["data"]["tier"]
    assert tier["min_level"] == 0
    assert tier["min_score"] == 0


# ── 2b. No partial commit on malformed update; huge/infinite values 400 ─


@pytest.mark.asyncio
async def test_tier_update_invalid_numeric_does_not_partial_commit(db, monkeypatch):
    """A 400 for a bad numeric field must not save sibling edits (symbol)."""
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"symbol": "ZZ", "min_level": "abc"},
        )

    assert response.status_code == 400
    async with session_scope() as session:
        tier = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1", ReputationTier.name == "Scout"
                )
            )
        ).scalar_one()
        assert tier.symbol == "🥉"  # untouched by the rejected update


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"min_level": float("inf")},  # int(inf) would OverflowError → must 400
        {"min_level": float("nan")},
        {"min_level": 10**19},  # beyond sqlite's signed 64-bit INTEGER bound
        {"min_level": -(10**19)},
        {"sort_order": 10**19},
        {"min_score": 10**400},  # float(10**400) would OverflowError → must 400
        {"min_score": float("inf")},
    ],
)
async def test_tier_update_huge_or_infinite_values_400(db, monkeypatch, payload):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_tier_update_huge_value_leaves_row_unchanged(db, monkeypatch):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            content=json.dumps({"min_level": 10**19}),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    async with session_scope() as session:
        tier = (
            await session.execute(
                select(ReputationTier).where(
                    ReputationTier.guild_id == "1", ReputationTier.name == "Scout"
                )
            )
        ).scalar_one()
        assert tier.min_level == 10  # seed value untouched


# ── 2c. sort_order contract: create appends at bottom; update honors value ─


@pytest.mark.asyncio
async def test_tier_create_ignores_client_sort_order_appends_bottom(db, monkeypatch):
    """Documented behavior: 'Create a new tier at the bottom of the ladder' —
    a client-supplied sort_order is ignored, the tier lands at max+1."""
    await _seed_guild_and_tiers()  # Recruit=0, Scout=1

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.post(
            "/api/v1/guilds/1/modules/reputation/tiers",
            json={"name": "Overlord", "sort_order": 999},
        )

    assert response.status_code == 200
    assert response.json()["data"]["tier"]["sort_order"] == 2  # bottom, not 999


@pytest.mark.asyncio
async def test_tier_update_honors_explicit_sort_order(db, monkeypatch):
    await _seed_guild_and_tiers()

    dashboard = _app_with_module(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/1/modules/reputation/tiers/Scout",
            json={"sort_order": 5},
        )

    assert response.status_code == 200
    assert response.json()["data"]["tier"]["sort_order"] == 5


# ── 3. ignored_roles enforced on every earning path ─────────────────────


@pytest.mark.asyncio
async def test_message_from_ignored_role_earns_no_points(db):
    guild = _FakeGuild(members=[_member(99, roles=[_role(888)])])
    module = ReputationModule(
        _FakeCtx(_config(ignored_roles="888"), guild)
    )
    msg = SimpleNamespace(
        id=1001, guild=guild, author=_member(99, roles=[_role(888)]),
        channel=SimpleNamespace(id=10), content="hello there",
    )

    await module._on_message("discord_message", message=msg)

    assert await _events_for(99) == []


@pytest.mark.asyncio
async def test_message_from_non_ignored_member_still_earns(db):
    guild = _FakeGuild(members=[_member(99, roles=[_role(999)])])
    module = ReputationModule(
        _FakeCtx(_config(ignored_roles="888"), guild)
    )
    msg = SimpleNamespace(
        id=1002, guild=guild, author=_member(99, roles=[_role(999)]),
        channel=SimpleNamespace(id=10), content="hello there",
    )

    await module._on_message("discord_message", message=msg)

    assert len(await _events_for(99, "message")) == 1


@pytest.mark.asyncio
async def test_reaction_ignored_actor_skips_giver_points_only(db):
    author = _member(99)
    actor = _member(98, roles=[_role(888)])
    guild = _FakeGuild(members=[author, actor])
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    channel = _reaction_channel(SimpleNamespace(author=author))
    guild._channels[10] = channel
    payload = SimpleNamespace(
        guild_id=1, channel_id=10, message_id=2001, user_id=98, emoji="⭐"
    )

    await module._on_reaction_add("raw_reaction_add", payload=payload)

    assert await _events_for(98) == []  # ignored giver earns nothing
    assert len(await _events_for(99, "reaction")) == 1  # author still earns


@pytest.mark.asyncio
async def test_reaction_unresolved_actor_skips_giver_points_only(db):
    author = _member(99)
    guild = _FakeGuild(members=[author])  # actor 98 not in member cache
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    channel = _reaction_channel(SimpleNamespace(author=author))
    guild._channels[10] = channel
    payload = SimpleNamespace(
        guild_id=1, channel_id=10, message_id=2002, user_id=98, emoji="⭐"
    )

    await module._on_reaction_add("raw_reaction_add", payload=payload)

    assert await _events_for(98) == []  # fail safe: unresolved giver earns nothing
    assert len(await _events_for(99, "reaction")) == 1


@pytest.mark.asyncio
async def test_reaction_unresolved_author_awards_nothing_to_author(db):
    actor = _member(98)
    guild = _FakeGuild(members=[actor])  # message author not in member cache
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    author = _member(99)
    channel = _reaction_channel(SimpleNamespace(author=author))
    guild._channels[10] = channel
    payload = SimpleNamespace(
        guild_id=1, channel_id=10, message_id=2003, user_id=98, emoji="⭐"
    )

    await module._on_reaction_add("raw_reaction_add", payload=payload)

    assert await _events_for(99) == []  # fail safe: unresolved target earns nothing
    assert len(await _events_for(98, "reaction_given")) == 1


@pytest.mark.asyncio
async def test_voice_leave_from_ignored_member_earns_nothing(db):
    member = _member(99, roles=[_role(888)])
    guild = _FakeGuild(members=[member])
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    module._voice_activity[1][99] = time.time() - 600  # 10 minutes in voice

    await module._on_voice_state(
        "discord_voice_state", member=member, after_channel=None
    )

    assert await _events_for(99) == []


@pytest.mark.asyncio
async def test_voice_leave_from_non_ignored_member_earns(db):
    member = _member(99)
    guild = _FakeGuild(members=[member])
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    module._voice_activity[1][99] = time.time() - 600

    await module._on_voice_state(
        "discord_voice_state", member=member, after_channel=None
    )

    assert len(await _events_for(99, "voice_minute")) == 1


@pytest.mark.asyncio
async def test_voice_tick_skips_unresolved_member(db):
    guild = _FakeGuild(members=[])  # nobody resolves
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    module._voice_activity[1][555] = time.time() - 600

    await module._credit_voice_tick(time.time())

    assert await _events_for(555) == []


@pytest.mark.asyncio
async def test_thanks_ignored_receiver_earns_nothing_but_giver_does(db):
    giver = _member(98)
    receiver = _member(99, roles=[_role(888)])
    guild = _FakeGuild(members=[giver, receiver])
    module = ReputationModule(_FakeCtx(_config(ignored_roles="888"), guild))
    thanks_cmd = module._make_thanks_command().callback  # decorator returns a Command

    interaction = SimpleNamespace(
        guild=guild,
        user=giver,
        response=SimpleNamespace(
            send_message=AsyncMock(), defer=AsyncMock()
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    await thanks_cmd(interaction, receiver, reason="for the help")

    assert await _events_for(99) == []  # ignored receiver earns nothing
    assert len(await _events_for(98, "thanks_given")) == 1  # giver still earns


# ── 4. Self-reactions earn no points ────────────────────────────────────


@pytest.mark.asyncio
async def test_self_reaction_earns_no_points(db):
    author = _member(99)
    guild = _FakeGuild(members=[author])
    module = ReputationModule(_FakeCtx(_config(), guild))
    channel = _reaction_channel(SimpleNamespace(author=author))
    guild._channels[10] = channel
    payload = SimpleNamespace(
        guild_id=1, channel_id=10, message_id=3001, user_id=99, emoji="⭐"
    )

    await module._on_reaction_add("raw_reaction_add", payload=payload)

    assert await _events_for(99) == []
    async with session_scope() as session:
        profile = (
            await session.execute(
                select(ReputationProfile).where(
                    ReputationProfile.guild_id == "1",
                    ReputationProfile.user_id == "99",
                )
            )
        ).scalar_one_or_none()
    assert profile is None
