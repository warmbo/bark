"""End-to-end tests for the public documentation wiki (/docs).

Builds a real ModuleManager with all core modules enabled (so the wiki reflects
actual commands/settings/permissions) and asserts the wiki pages render,
link correctly, and are publicly reachable without authentication.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[2]


class _FakeChannel:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name
        self.type = 0


class _FakeRole:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name


class _FakeMember:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name
        self.display_name = name
        self.bot = False


class _FakeGuild:
    def __init__(self, id_=1):
        self.id = id_
        self.name = "War Lab"
        self.members = [_FakeMember(11, "Alice"), _FakeMember(12, "Bob")]
        self.get_member = lambda uid: next(
            (m for m in self.members if m.id == uid), None
        )
        self.get_channel = lambda cid: _FakeChannel(100, "general")


def _build_bot(manager):
    import discord.app_commands as ac

    class FakeBot:
        def __init__(self):
            self.http = MagicMock()
            self._connection = MagicMock()
            self._connection._command_tree = None
            self.tree = ac.CommandTree(self)
            self._event_bus = MagicMock()
            self.guilds = []
            self.user = SimpleNamespace(name="Bark")
            self._commands = {}
            self.modules = manager

        def get_guild(self, guild_id):
            return _FakeGuild(guild_id or 1)

        async def fetch_user(self, user_id):
            return _FakeMember(user_id, "Fetched")

    return FakeBot()


@pytest.fixture
def wiki_app(db):
    """A real ModuleManager (core modules enabled) behind a create_app dashboard."""
    from services.module_manager import ModuleManager

    from database.engine import session_scope
    from database.models.guild import Guild

    async def _seed():
        async with session_scope() as session:
            session.add(Guild(discord_id="1", name="War Lab"))
            await session.commit()

    asyncio.run(_seed())

    bot_factory_bot = MagicMock()
    manager = ModuleManager(bot_factory_bot)
    manager.discover()
    for name in list(manager.get_all_modules()):
        asyncio.run(manager.enable_module(name))

    bot = _build_bot(manager)

    from dashboard import create_app

    dash = create_app(bot)
    return dash.app


@pytest.fixture
async def client(wiki_app):
    async with AsyncClient(
        transport=ASGITransport(app=wiki_app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_docs_index_is_public_and_lists_sections(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Bark Documentation" in body
    assert "/docs/modules" in body
    assert "/docs/commands" in body
    assert "/docs/settings" in body


@pytest.mark.asyncio
async def test_docs_is_not_redirected_to_login(client):
    """Wiki pages must be reachable with no session (not 302 to /auth/login)."""
    resp = await client.get("/docs", follow_redirects=False)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_docs_modules_page_lists_core_modules(client):
    resp = await client.get("/docs/modules")
    assert resp.status_code == 200
    body = resp.text
    for module in ("Moderation", "Reputation", "Announcements", "Help", "Logging"):
        assert module in body


@pytest.mark.asyncio
async def test_docs_module_page_lists_commands_and_settings(client):
    resp = await client.get("/docs/modules/moderation")
    assert resp.status_code == 200
    body = resp.text
    assert "warn" in body
    assert "ban" in body
    assert "Moderator" in body or "Admin" in body


@pytest.mark.asyncio
async def test_docs_module_unknown_returns_not_found(client):
    resp = await client.get("/docs/modules/nonexistent")
    assert resp.status_code == 200
    assert "doesn't exist" in resp.text


@pytest.mark.asyncio
async def test_docs_commands_page_lists_all_commands(client):
    resp = await client.get("/docs/commands")
    assert resp.status_code == 200
    body = resp.text
    assert "leaderboard" in body
    assert "help" in body
    # Info commands carry the Anyone badge; mutators carry a role badge.
    assert "Anyone" in body


@pytest.mark.asyncio
async def test_docs_command_page_shows_arguments_and_role(client):
    # Dispatcher paths are flattened leaf names (e.g. "warn", not "moderation warn").
    resp = await client.get("/docs/commands/warn")
    assert resp.status_code == 200
    body = resp.text
    assert "warn" in body
    assert "member" in body  # argument
    assert "Moderator" in body  # required role
    # Mutating commands must not advertise the "info command" public note.
    assert "changes server state" in body


@pytest.mark.asyncio
async def test_docs_command_info_command_advertises_public_visibility(client):
    resp = await client.get("/docs/commands/leaderboard")
    assert resp.status_code == 200
    body = resp.text
    assert "info command" in body
    assert "public" in body  # the "post for everyone" hint


@pytest.mark.asyncio
async def test_docs_command_moderation_records_are_always_private(client):
    """Cases/warnings expose other members' records and must be documented as
    always-private (never advertise a public-broadcast toggle)."""
    resp = await client.get("/docs/commands/cases")
    assert resp.status_code == 200
    body = resp.text
    assert "always private" in body
    # Must not advertise the public-toggle syntax.
    assert "post it in the channel for everyone" not in body


@pytest.mark.asyncio
async def test_docs_settings_page_lists_settings_by_module(client):
    resp = await client.get("/docs/settings")
    assert resp.status_code == 200
    assert "/docs/settings/" in resp.text


@pytest.mark.asyncio
async def test_docs_settings_module_page_shows_schema(client):
    resp = await client.get("/docs/settings/reputation")
    assert resp.status_code == 200
    body = resp.text
    assert "Reputation" in body
    assert "Type" in body  # table header


@pytest.mark.asyncio
async def test_docs_permissions_page_lists_actions(client):
    resp = await client.get("/docs/permissions")
    assert resp.status_code == 200
    body = resp.text
    assert "guild.manage" in body
    assert "moderation.view" in body
    assert "Admin" in body


@pytest.mark.asyncio
async def test_docs_command_not_found(client):
    resp = await client.get("/docs/commands/doesnotexist")
    assert resp.status_code == 200
    assert "doesn't exist" in resp.text
