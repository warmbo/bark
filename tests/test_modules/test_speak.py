"""Tests for the Speak module: /bark speak command + phrases API."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.permissions import DashboardUser
from modules.speak.module import SpeakModule, validate_phrases
from services.bark_context import BarkContext
from services.dashboard_access import replace_user_guild_access


def _make_module(phrases: dict | None = None) -> SpeakModule:
    ctx = MagicMock(spec=BarkContext)
    ctx.get_module_config = AsyncMock(return_value={"phrases": phrases or {}})
    ctx.save_module_config = AsyncMock()
    return SpeakModule(ctx)


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append({"content": content, "ephemeral": kwargs.get("ephemeral")})


class _Interaction:
    def __init__(self, guild_id=100, phrases=None):
        self.guild_id = guild_id
        self.response = _Response()
        self._phrases = phrases

    @property
    def data(self):
        return MagicMock()

    async def _handler(self, module):
        # Build the command and pull out the wrapped coroutine to call directly.
        cmd = module._make_speak_command()
        # discord.app_commands.command returns a Command; the underlying
        # function is the callback. Call it with self as the interaction.
        await cmd.callback(self, key="word1")
        return self.response.messages


def test_module_registration():
    module = _make_module()
    assert module.name == "speak"
    assert module.version == "1.0.0"
    assert module.get_commands()[0].name == "speak"
    perms = module.get_permissions()
    assert any(p.name == "speak.manage" for p in perms)
    # Nav entry (single page) + phrases editor lives in the Configure tab,
    # not as an extra tab.
    pages = module.get_dashboard_pages()
    assert pages[0].label == "Speak"
    assert pages[0].route == "/guild/{guild_id}/modules/speak"
    assert module.get_extra_tabs() == []
    # Single-command module -> command hangs directly off /bark
    assert len(module.get_commands()) == 1


@pytest.mark.asyncio
async def test_speak_sends_phrase_publicly():
    module = _make_module({"word1": "hello there"})
    interaction = _Interaction(guild_id=100)
    cmd = module._make_speak_command()
    await cmd.callback(interaction, key="word1")
    assert interaction.response.messages == [
        {"content": "hello there", "ephemeral": None}
    ]


@pytest.mark.asyncio
async def test_speak_unknown_key_lists_available():
    module = _make_module({"word1": "hello", "phrase2": "world"})
    interaction = _Interaction(guild_id=100)
    cmd = module._make_speak_command()
    await cmd.callback(interaction, key="nope")
    assert interaction.response.messages
    message = interaction.response.messages[0]
    assert message["ephemeral"] is True
    assert "Unknown phrase" in message["content"]
    assert "`word1`" in message["content"]
    assert "`phrase2`" in message["content"]


@pytest.mark.asyncio
async def test_speak_no_phrases_hint():
    module = _make_module({})
    interaction = _Interaction(guild_id=100)
    cmd = module._make_speak_command()
    await cmd.callback(interaction, key="word1")
    message = interaction.response.messages[0]
    assert message["ephemeral"] is True
    assert "No phrases configured yet" in message["content"]


@pytest.mark.asyncio
async def test_speak_requires_guild():
    module = _make_module({"word1": "hello"})
    interaction = _Interaction(guild_id=None)
    cmd = module._make_speak_command()
    await cmd.callback(interaction, key="word1")
    message = interaction.response.messages[0]
    assert message["ephemeral"] is True
    assert "only works inside a server" in message["content"]


def test_validate_phrases_accepts_valid():
    phrases, error = validate_phrases({"word1": "hello", "phrase2": "world"})
    assert error is None
    assert phrases == {"word1": "hello", "phrase2": "world"}


def test_validate_phrases_strips_values_and_keys():
    phrases, error = validate_phrases({" word1 ": "  hello  "})
    assert error is None
    assert phrases == {"word1": "hello"}


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-dict",
        {"bad key": "text"},  # space in key
        {"": "text"},  # empty key
        {"a" * 65: "text"},  # key too long
        {"héllo": "text"},  # non-token chars
        {"word1": ""},  # empty text
        {"word1": "   "},  # whitespace-only text
        {"word1": "x" * 1901},  # too long
    ],
)
def test_validate_phrases_rejects_bad_input(raw):
    phrases, error = validate_phrases(raw)
    assert phrases is None
    assert error is not None


def _session_cookie(role: str) -> str:
    session = {"user": {"id": "42", "username": "Auditor"}, "role": role}
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


@pytest.mark.asyncio
async def test_speak_api_enforces_manage_permission(db, monkeypatch):
    """A viewer cannot read or write phrases."""
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="viewer"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Guild", "permissions": str(0)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"speak": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True
    app = create_app(bot)

    # Module API routes register when the module is enabled at runtime; in
    # tests the mock bot never enables it, so mount the router directly
    # (same pattern as test_reputation_api.py).
    from services.bark_context import BarkContext

    module = SpeakModule(BarkContext(bot, bot.modules.event_bus))
    app.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("viewer")),
    ) as client:
        get_resp = await client.get("/api/v1/guilds/100/modules/speak/phrases")
        put_resp = await client.put(
            "/api/v1/guilds/100/modules/speak/phrases",
            json={"phrases": {"word1": "hello"}},
        )
    assert get_resp.status_code == 403
    assert put_resp.status_code == 403


@pytest.mark.asyncio
async def test_speak_api_validation_rejects_bad_payload(db, monkeypatch):
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(DashboardUser(discord_id="42", username="Cody", role="admin"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "100", "name": "Guild", "permissions": str(2147483647)}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"speak": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True
    app = create_app(bot)

    from services.bark_context import BarkContext

    module = SpeakModule(BarkContext(bot, bot.modules.event_bus))
    app.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=app.app),
        base_url="http://test",
        cookies=dict(session=_session_cookie("admin")),
    ) as client:
        response = await client.put(
            "/api/v1/guilds/100/modules/speak/phrases",
            json={"phrases": {"bad key": "text"}},
        )
    assert response.status_code == 400
    assert "Invalid phrase key" in response.json()["error"]
