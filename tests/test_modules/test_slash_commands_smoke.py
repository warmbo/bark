"""Smoke-test every registered /bark slash command.

Bots cannot trigger slash commands on Discord — only users can — so this
harness exercises the real command tree the same way the gateway does:
every module is discovered and enabled under the /bark group, then each
leaf command's callback is invoked with realistic option values and a fake
interaction whose response is recorded. Any handler crash or missing
response fails the test for that command.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = Path(__file__).resolve().parents[2].parent / "bark-plugins" / "plugins"


# ── Rich fakes ─────────────────────────────────────────


class FakeRole:
    def __init__(self, id: int, name: str = "role", position: int = 1):
        self.id = id
        self.name = name
        self.position = position
        self.mention = f"<@&{id}>"
        self.color = discord.Color.default()
        self.colour = self.color
        self.hoist = False
        self.managed = False


class FakeMessage:
    def __init__(self, id: int = 900, content=None):
        self.id = id
        self.content = content

    async def add_reaction(self, reaction):
        return None

    async def edit(self, **kwargs):
        self.content = kwargs.get("content", self.content)
        return None

    async def delete(self):
        return None


class FakeChannel:
    def __init__(self, id: int, name: str = "general", kind: str = "text"):
        self.id = id
        self.name = name
        self.type = discord.ChannelType.voice if kind == "voice" else discord.ChannelType.text
        self.mention = f"<#{id}>"
        self.guild = None
        self.members = []

    async def send(self, content=None, **kwargs):
        return FakeMessage(id=900, content=content)

    async def create_thread(self, **kwargs):
        return SimpleNamespace(id=910, send=async_noop)

    def permissions_for(self, member=None):
        return discord.Permissions(0x20)


async def async_noop(*a, **k):
    return None


class FakeMember:
    def __init__(self, id: int, name: str = "TestUser", guild=None, bot: bool = False):
        self.id = id
        self.name = name
        self.display_name = name
        self.mention = f"<@{id}>"
        self.bot = bot
        self.guild = guild
        self.roles = [FakeRole(1, "@everyone", 0), FakeRole(2, "Member", 1)]
        self.top_role = self.roles[-1]
        self.joined_at = datetime(2024, 1, 1)
        self.created_at = datetime(2023, 1, 1)
        self.status = discord.Status.online
        self.voice = None
        self.premium_since = None
        self.avatar = SimpleNamespace(url="https://example.com/avatar.png")
        self.display_avatar = SimpleNamespace(url="https://example.com/avatar.png")
        self.display = SimpleNamespace(avatar=None)
        self.raw_status = "online"
        self.mobile_status = "offline"
        self.desktop_status = "offline"
        self.web_status = "offline"

    def __str__(self):
        return self.name

    @property
    def guild_permissions(self):
        return discord.Permissions(0x20)  # MANAGE_GUILD

    @property
    def permissions(self):
        return self.guild_permissions

    async def timeout(self, **kwargs):
        return None

    async def ban(self, **kwargs):
        return None

    async def kick(self, **kwargs):
        return None

    async def unban(self, **kwargs):
        return None

    async def move_to(self, **kwargs):
        return None

    async def edit(self, **kwargs):
        return None

    async def send(self, content=None, **kwargs):
        return SimpleNamespace(id=920, content=content)


class FakeGuild:
    def __init__(self, id: int = 1, name: str = "War Lab"):
        self.id = id
        self.name = name
        self.member_count = 5
        self.owner = FakeMember(10, "Owner", self)
        self.me = FakeMember(1, "Bark", self, bot=True)
        self.created_at = datetime(2023, 1, 1)
        self.icon = None
        self.premium_subscription_count = 1
        self.channels = [
            FakeChannel(100, "general", "text"),
            FakeChannel(101, "voice-chat", "voice"),
        ]
        self.roles = [FakeRole(1, "@everyone", 0), FakeRole(2, "Member", 1)]
        self.members = [self.owner, FakeMember(11, "Alice", self), FakeMember(12, "Bob", self)]

    def get_member(self, user_id):
        for member in self.members:
            if member.id == user_id:
                return member
        return None

    def get_channel(self, channel_id):
        for channel in self.channels:
            if channel.id == channel_id:
                return channel
        return None

    def get_role(self, role_id):
        for role in self.roles:
            if role.id == role_id:
                return role
        return None

    async def fetch_member(self, user_id):
        return self.get_member(user_id) or FakeMember(user_id, "Fetched", self)

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    async def unban(self, user, **kwargs):
        return None


class FakeResponse:
    def __init__(self):
        self.sent = []
        self._done = False

    def is_done(self):
        return self._done

    async def defer(self, **kwargs):
        self._done = True

    async def send_message(self, content=None, embed=None, ephemeral=False, **kwargs):
        self.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})
        self._done = True
        return SimpleNamespace(id=900)

    async def edit_message(self, **kwargs):
        self._done = True

    async def followup(self, content=None, **kwargs):
        self.sent.append({"content": content, "embed": kwargs.get("embed"), "ephemeral": False})
        return SimpleNamespace(id=901)


class _Followup:
    """Mimics discord.py's Interaction.followup — a Webhook-like object."""

    def __init__(self, response):
        self._response = response

    async def send(self, content=None, embed=None, ephemeral=False, **kwargs):
        self._response.sent.append({"content": content, "embed": embed, "ephemeral": ephemeral})
        return SimpleNamespace(id=901)


class FakeInteraction:
    def __init__(self, guild: FakeGuild, user: FakeMember, command: str = "bark"):
        self.guild = guild
        self.user = user
        self.guild_id = guild.id
        self.channel = guild.channels[0]
        self.response = FakeResponse()
        self.followup = _Followup(self.response)
        self.data = {"name": command, "id": "1", "type": 1}
        self.type = discord.InteractionType.application_command
        self.id = 1
        self.command = None
        self.command_failed = False

    async def original_response(self):
        return SimpleNamespace(id=900, add_reaction=async_noop)

    async def edit_original_response(self, **kwargs):
        return None


# ── Command walking ────────────────────────────────────


def _load_plugin_module(name: str):
    spec = importlib.util.spec_from_file_location(name, PLUGINS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sample_for_param(param):
    """A realistic value for each AppCommandParameter type."""
    from discord.app_commands.commands import AppCommandOptionType

    t = param.type
    if t is AppCommandOptionType.string:
        return "123"  # numeric string — several handlers int() their args
    if t is AppCommandOptionType.integer:
        return 3
    if t is AppCommandOptionType.number:
        return 1.5
    if t is AppCommandOptionType.boolean:
        return True
    if t is AppCommandOptionType.channel:
        return FakeChannel(100, "general", "text")
    if t in (AppCommandOptionType.user, AppCommandOptionType.mentionable):
        return FakeMember(11, "Alice")
    if t is AppCommandOptionType.role:
        return FakeRole(2, "Member", 1)
    return "test"


def _all_leaf_commands(tree, command=None, path=()):
    """Yield (path, Command) for every leaf under the /bark group."""
    if command is None:
        for cmd in tree.get_commands():
            if cmd.name == "bark":
                yield from _all_leaf_commands(tree, cmd, ("bark",))
        return
    if getattr(command, "commands", None):
        for sub in command.commands:
            yield from _all_leaf_commands(tree, sub, path + (sub.name,))
    else:
        yield path, command


@pytest.fixture
async def tree(db, tmp_path):
    """A real ModuleManager with every module (core + plugins) enabled."""
    import shutil
    from unittest.mock import MagicMock

    import discord.app_commands as ac

    from services.module_manager import ModuleManager

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    for plugin_file in PLUGINS_DIR.glob("*.py"):
        if plugin_file.name == "minimal_example.py":  # template, not deployed
            continue
        shutil.copy(plugin_file, plugins_dir / plugin_file.name)

    from database.engine import session_scope
    from database.models.guild import Guild

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="War Lab"))
        await session.commit()

    class FakeBot:
        def __init__(self):
            self.http = MagicMock()
            self._connection = MagicMock()
            self._connection._command_tree = None
            self.tree = ac.CommandTree(self)
            self._event_bus = MagicMock()
            self.guilds = []
            self.user = None

        def get_guild(self, guild_id):
            return FakeGuild(id=guild_id or 1)

        async def fetch_user(self, user_id):
            return FakeMember(user_id, "Fetched", None)

        async def fetch_channel(self, channel_id):
            return None

    bot = FakeBot()
    manager = ModuleManager(bot)
    manager.discover()
    for name in list(manager._modules):
        assert await manager.enable_module(name), f"failed to enable {name}"
    return bot, manager


@pytest.mark.asyncio
async def test_every_bark_slash_command_responds(tree):
    bot, manager = tree
    guild = FakeGuild()
    user = FakeMember(11, "Alice", guild)

    failures = []
    tested = []
    for path, command in _all_leaf_commands(bot.tree):
        interaction = FakeInteraction(guild, user, command="bark")
        kwargs = {}
        for param in getattr(command, "parameters", []):
            kwargs[param.name] = _sample_for_param(param)
        try:
            await command.callback(interaction, **kwargs)
            tested.append("/" + " ".join(path))
        except Exception as exc:  # noqa: BLE001 — report every failing command
            failures.append(f"/{' '.join(path)}: {type(exc).__name__}: {exc}")

    assert not failures, "failing commands:\n" + "\n".join(failures)
    assert len(tested) >= 20, f"expected a full command tree, got {len(tested)}: {tested}"
    # Core module commands must always be deployed. The plugin commands
    # (serverinfo, fact, poll, dice_roller, trivia) only exist when the
    # bark-plugins sibling repo is present on the machine — a fresh checkout
    # has no plugins, so those are asserted conditionally below.
    for required in (
        "/bark help",
        "/bark moderation warn",
        "/bark reputation leaderboard",
    ):
        assert required in tested, f"missing command from tree: {required} in {tested}"
    if PLUGINS_DIR.exists():
        for plugin_cmd in (
            "/bark serverinfo",
            "/bark fact",
            "/bark poll",
            "/bark dice_roller roll",
            "/bark trivia start",
        ):
            assert plugin_cmd in tested, f"missing plugin command from tree: {plugin_cmd} in {tested}"
