"""Unit tests for the single-file plugin system (services/plugin_manager.py
and the ModuleManager plugin lifecycle)."""

from __future__ import annotations

import discord
import pytest

from services.plugin_manager import (
    MAX_PLUGIN_BYTES,
    PluginValidationError,
    is_core_module,
    load_plugin_class,
    plugins_directory,
    validate_plugin_name,
)

VALID_PLUGIN = '''
from modules.base import BarkModule, CommandRegistration, EventRegistration

class PingPlugin(BarkModule):
    name = "ping_plugin"
    version = "1.0.0"
    description = "A tiny test plugin"

    def get_commands(self):
        return [CommandRegistration(name="ping", description="Ping!")]

    def get_events(self):
        return [EventRegistration("discord_message", handler="_on_message")]

    async def _on_message(self, event_type: str, **data):
        return None

    async def enable(self):
        pass

    async def disable(self):
        pass
'''

NO_SUBCLASS_PLUGIN = """
# This file has no BarkModule subclass.
ANSWER = 42
"""

TWO_CLASSES_PLUGIN = '''
from modules.base import BarkModule

class FirstPlugin(BarkModule):
    name = "first_plugin"
    async def enable(self): pass
    async def disable(self): pass

class SecondPlugin(BarkModule):
    name = "second_plugin"
    async def enable(self): pass
    async def disable(self): pass
'''

BROKEN_PLUGIN = """
this is not valid python !!!
"""


class FakeBot:
    """Minimal bot stand-in with a real ModuleManager and no FastAPI app."""

    def __init__(self):
        from services.event_bus import EventBus
        from services.module_manager import ModuleManager

        self._event_bus = EventBus()
        self._module_manager = ModuleManager(self)
        self.app = None
        self.guilds = []
        self.tree = None
        self.user = None

    @property
    def modules(self):
        return self._module_manager

    def is_ready(self):
        return False


@pytest.fixture
def manager():
    bot = FakeBot()
    return bot.modules


# ── Validation helpers ───────────────────────────────


def test_validate_plugin_name_accepts_snake_case():
    assert validate_plugin_name("my_plugin") == "my_plugin"


@pytest.mark.parametrize(
    "bad",
    ["MyPlugin", "my-plugin", "1plugin", "my plugin", "", "a", "toolong_" + "x" * 40],
)
def test_validate_plugin_name_rejects_invalid(bad):
    with pytest.raises(PluginValidationError):
        validate_plugin_name(bad)


def test_validate_plugin_name_rejects_core_and_reserved():
    assert is_core_module("reputation")
    for name in ("reputation", "base", "__init__", "plugins", "modules"):
        with pytest.raises(PluginValidationError):
            validate_plugin_name(name)


def test_load_plugin_class_returns_single_class(tmp_path):
    path = tmp_path / "ping_plugin.py"
    path.write_text(VALID_PLUGIN)
    cls = load_plugin_class(path)
    assert cls.name == "ping_plugin"


def test_load_plugin_class_rejects_files_without_subclass(tmp_path):
    path = tmp_path / "noop.py"
    path.write_text(NO_SUBCLASS_PLUGIN)
    with pytest.raises(PluginValidationError, match="No BarkModule subclass"):
        load_plugin_class(path)


def test_load_plugin_class_rejects_multiple_subclasses(tmp_path):
    path = tmp_path / "double.py"
    path.write_text(TWO_CLASSES_PLUGIN)
    with pytest.raises(PluginValidationError, match="exactly one"):
        load_plugin_class(path)


def test_load_plugin_class_rejects_broken_syntax(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text(BROKEN_PLUGIN)
    with pytest.raises(PluginValidationError, match="failed to import"):
        load_plugin_class(path)


# ── Install ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_plugin_registers_and_enables(manager):
    metadata = await manager.install_plugin(VALID_PLUGIN.encode(), "whatever.py")
    assert metadata["name"] == "ping_plugin"
    assert metadata["loaded"] is True
    assert metadata["file"] == "ping_plugin.py"

    assert manager.is_plugin("ping_plugin")
    assert "ping_plugin" in manager.get_all_modules()
    module = manager.get_module("ping_plugin")
    assert module.enabled is True
    assert [c.name for c in module.get_commands()] == ["ping"]

    # The file is written under the module name, not the upload filename.
    assert (plugins_directory() / "ping_plugin.py").is_file()
    assert not (plugins_directory() / "whatever.py").exists()


@pytest.mark.asyncio
async def test_plugin_defaults_off_per_guild(manager):
    """Installing a plugin makes it AVAILABLE, not enabled — fresh guilds
    opt in explicitly (core modules stay default-on)."""
    # Core modules (not in _plugin_files) default to enabled.
    assert manager.is_enabled_for_guild(999, "logging") is True

    await manager.install_plugin(VALID_PLUGIN.encode(), "whatever.py")
    # No persisted state: the add-on is OFF for a fresh guild...
    assert manager.is_enabled_for_guild(999, "ping_plugin") is False
    # ...while the instance still reports it as available.
    assert manager.is_plugin("ping_plugin")

    # Explicit opt-in flips it on for exactly that guild.
    assert await manager.set_guild_enabled(999, "ping_plugin", True) is True
    assert manager.is_enabled_for_guild(999, "ping_plugin") is True
    # A different guild that never opted in stays off.
    assert manager.is_enabled_for_guild(888, "ping_plugin") is False
    # Turning it off again for the only enabled guild unloads it.
    assert await manager.set_guild_enabled(999, "ping_plugin", False) is True
    assert manager.is_enabled_for_guild(999, "ping_plugin") is False
    assert manager.get_module("ping_plugin").enabled is False


@pytest.mark.asyncio
async def test_set_guild_enabled_syncs_on_first_enable(manager, monkeypatch):
    """Enabling a plugin for the first time re-syncs the command tree so
    Discord learns about ``/bark <cmd>`` (a runtime-only register is never
    pushed to Discord otherwise). Re-enabling an already-synced module must
    not re-sync.
    """
    from unittest.mock import AsyncMock

    sync = AsyncMock()
    monkeypatch.setattr(manager, "_sync_commands", sync)

    # Install registers the plugin's commands but does NOT sync (install
    # happens after the startup sync), so the module is queued as unsynced.
    await manager.install_plugin(VALID_PLUGIN.encode(), "whatever.py")
    assert "ping_plugin" in manager._unsynced_commands
    sync.reset_mock()

    # First per-guild enable drains the queue -> sync exactly once.
    assert await manager.set_guild_enabled(999, "ping_plugin", True) is True
    assert sync.await_count == 1
    assert "ping_plugin" not in manager._unsynced_commands

    # A second guild opts in while the module is already registered+synced ->
    # no re-sync (nothing changed in the command tree).
    assert await manager.set_guild_enabled(888, "ping_plugin", True) is True
    assert sync.await_count == 1


@pytest.mark.asyncio
async def test_install_rejects_non_py(manager):
    with pytest.raises(PluginValidationError, match=r"\.py file"):
        await manager.install_plugin(b"x", "plugin.txt")


@pytest.mark.asyncio
async def test_install_rejects_empty_and_oversized(manager):
    with pytest.raises(PluginValidationError, match="empty"):
        await manager.install_plugin(b"", "p.py")
    with pytest.raises(PluginValidationError, match="size limit"):
        await manager.install_plugin(b"x" * (MAX_PLUGIN_BYTES + 1), "p.py")


@pytest.mark.asyncio
async def test_install_rejects_bad_module_name(manager):
    bad = VALID_PLUGIN.replace('name = "ping_plugin"', 'name = "My-Plugin!"')
    with pytest.raises(PluginValidationError, match="Module name"):
        await manager.install_plugin(bad.encode(), "p.py")
    # Nothing left behind.
    assert list(plugins_directory().glob("*.py")) == []


@pytest.mark.asyncio
async def test_install_rejects_core_module_collision(manager):
    bad = VALID_PLUGIN.replace('name = "ping_plugin"', 'name = "reputation"')
    with pytest.raises(PluginValidationError, match="built-in"):
        await manager.install_plugin(bad.encode(), "p.py")


@pytest.mark.asyncio
async def test_reinstall_replaces_existing_plugin(db, manager):
    v1 = VALID_PLUGIN.replace('version = "1.0.0"', 'version = "2.0.0"')
    first = await manager.install_plugin(VALID_PLUGIN.encode(), "a.py")
    assert first["version"] == "1.0.0"
    second = await manager.install_plugin(v1.encode(), "b.py")
    assert second["version"] == "2.0.0"
    assert manager.get_module("ping_plugin").version == "2.0.0"
    assert len(list(plugins_directory().glob("*.py"))) == 1


# ── Uninstall ────────────────────────────────────────


@pytest.mark.asyncio
async def test_uninstall_plugin_cleans_everything(db, manager):
    from database.engine import session_scope
    from database.models.guild import Guild
    from database.models.module import ModuleConfig
    from database.models.permissions import ModuleRoleAccess

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(ModuleConfig(guild_id="1", module_name="ping_plugin", enabled=True))
        session.add(
            ModuleRoleAccess(guild_id="1", module_name="ping_plugin", min_role="viewer")
        )
        await session.commit()

    await manager.install_plugin(VALID_PLUGIN.encode(), "p.py")
    assert manager.is_plugin("ping_plugin")

    assert await manager.uninstall_plugin("ping_plugin") is True
    assert not manager.is_plugin("ping_plugin")
    assert "ping_plugin" not in manager.get_all_modules()
    assert not (plugins_directory() / "ping_plugin.py").exists()

    from sqlalchemy import select

    async with session_scope() as session:
        configs = (
            (
                await session.execute(
                    select(ModuleConfig).where(ModuleConfig.module_name == "ping_plugin")
                )
            )
            .scalars()
            .all()
        )
        roles = (
            (
                await session.execute(
                    select(ModuleRoleAccess).where(
                        ModuleRoleAccess.module_name == "ping_plugin"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert configs == []
    assert roles == []


@pytest.mark.asyncio
async def test_uninstall_refuses_unknown_and_core(manager):
    assert await manager.uninstall_plugin("reputation") is False
    assert await manager.uninstall_plugin("nope") is False


# ── Discovery ────────────────────────────────────────


def test_discover_plugins_loads_files_on_disk(manager, tmp_path):
    (plugins_directory() / "ping_plugin.py").write_text(VALID_PLUGIN)
    manager.discover_plugins()
    assert manager.is_plugin("ping_plugin")
    assert manager.get_module("ping_plugin") is not None


def test_discover_plugins_skips_invalid_files(manager, tmp_path):
    (plugins_directory() / "broken.py").write_text(BROKEN_PLUGIN)
    (plugins_directory() / "ping_plugin.py").write_text(VALID_PLUGIN)
    manager.discover_plugins()
    assert manager.is_plugin("ping_plugin")
    assert not manager.is_plugin("broken")


# ── Reload ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_reload_plugin_reloads_code(manager):
    await manager.install_plugin(VALID_PLUGIN.encode(), "p.py")
    new_version = VALID_PLUGIN.replace('version = "1.0.0"', 'version = "3.1.4"')
    (plugins_directory() / "ping_plugin.py").write_text(new_version)
    assert await manager.reload_module("ping_plugin") is True
    assert manager.get_module("ping_plugin").version == "3.1.4"
    assert manager.get_module("ping_plugin").enabled is True


# ── /bark command namespace ──────────────────────────


@pytest.mark.asyncio
async def test_module_commands_nest_under_single_bark_group(tmp_path):
    """All module slash commands register as subcommands of one /bark group."""
    import discord.app_commands as ac
    from discord.app_commands import CommandTree

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()
    from unittest.mock import MagicMock

    bot.http = MagicMock()
    bot._connection = MagicMock()
    bot._connection._command_tree = None
    bot.tree = CommandTree(bot)  # real tree so nesting is observable

    class FakeModule:
        name = "fake"
        version = "1.0.0"
        enabled = False
        description = "fake module"

        def __init__(self, ctx):
            self.ctx = ctx

        async def enable(self):
            return True

        async def disable(self):
            return True

        def get_commands(self):
            from modules.base import CommandRegistration

            return [CommandRegistration(name="roll", description="Roll dice", slash=True)]

        def get_events(self):
            return []

        def _make_roll_command(self):
            @ac.command(name="roll", description="Roll dice")
            async def roll(interaction: discord.Interaction):
                return None

            return roll

        def get_dashboard_pages(self):
            return []

        def get_actions(self):
            return []

    manager = ModuleManager(bot)
    manager._modules["fake"] = FakeModule(BarkContext(bot, bot._event_bus))
    assert await manager.enable_module("fake") is True

    bark = manager._get_bark_group()
    assert bark.name == "bark"
    # Single-command modules hang directly off /bark: /bark roll
    assert [c.name for c in bark.commands] == ["roll"]
    # The group itself is on the tree (global registration), not the subcommand.
    assert "bark" in bot.tree._global_commands
    assert "roll" not in bot.tree._global_commands

    # Disabling the module removes its subcommand but keeps the bark group.
    assert await manager.disable_module("fake") is True
    assert [c.name for c in bark.commands] == []
    assert "bark" in bot.tree._global_commands


@pytest.mark.asyncio
async def test_multi_command_module_gets_subgroup(tmp_path):
    """Multi-command modules nest under a per-module subgroup (/bark mod a)."""
    import discord.app_commands as ac
    from discord.app_commands import CommandTree

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()
    from unittest.mock import MagicMock

    bot.http = MagicMock()
    bot._connection = MagicMock()
    bot._connection._command_tree = None
    bot.tree = CommandTree(bot)

    class MultiModule:
        name = "mod"
        version = "1.0.0"
        enabled = False
        description = "multi module"

        def __init__(self, ctx):
            self.ctx = ctx

        async def enable(self):
            return True

        async def disable(self):
            return True

        def get_commands(self):
            from modules.base import CommandRegistration

            return [
                CommandRegistration(name="alpha", description="Alpha", slash=True),
                CommandRegistration(name="beta", description="Beta", slash=True),
            ]

        def get_events(self):
            return []

        def _make_alpha_command(self):
            @ac.command(name="alpha", description="Alpha")
            async def alpha(interaction: discord.Interaction):
                return None

            return alpha

        def _make_beta_command(self):
            @ac.command(name="beta", description="Beta")
            async def beta(interaction: discord.Interaction):
                return None

            return beta

        def get_dashboard_pages(self):
            return []

        def get_actions(self):
            return []

    manager = ModuleManager(bot)
    manager._modules["mod"] = MultiModule(BarkContext(bot, bot._event_bus))
    assert await manager.enable_module("mod") is True

    bark = manager._get_bark_group()
    assert [c.name for c in bark.commands] == ["mod"]
    subgroup = bark.commands[0]
    assert [c.name for c in subgroup.commands] == ["alpha", "beta"]

    assert await manager.disable_module("mod") is True
    # Empty subgroups are dropped so the /bark group never syncs empty groups.
    assert [c.name for c in bark.commands] == []


@pytest.mark.asyncio
async def test_namespaced_group_command_hangs_directly_off_bark(tmp_path):
    """A module exposing a namespaced group (e.g. /bark trivia start) is a
    direct child of /bark rather than wrapped in another subgroup."""
    from discord.app_commands import CommandTree, Group

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()
    from unittest.mock import MagicMock

    bot.http = MagicMock()
    bot._connection = MagicMock()
    bot._connection._command_tree = None
    bot.tree = CommandTree(bot)

    class GroupModule:
        name = "trivia"
        version = "1.0.0"
        enabled = False
        description = "Trivia game"

        def __init__(self, ctx):
            self.ctx = ctx

        async def enable(self):
            return True

        async def disable(self):
            return True

        def get_commands(self):
            from modules.base import CommandRegistration

            return [
                CommandRegistration(name="trivia", description="Trivia game", slash=True)
            ]

        def get_events(self):
            return []

        def _make_trivia_command(self):
            group = Group(name="trivia", description="Trivia game")
            for sub in ("start", "stop"):

                async def cb(interaction: discord.Interaction, _name: str = sub):
                    return None

                cb.__name__ = f"trivia_{sub}"
                group.command(name=sub, description=sub)(cb)
            return group

        def get_dashboard_pages(self):
            return []

        def get_actions(self):
            return []

    manager = ModuleManager(bot)
    manager._modules["trivia"] = GroupModule(BarkContext(bot, bot._event_bus))
    assert await manager.enable_module("trivia") is True

    bark = manager._get_bark_group()
    assert [c.name for c in bark.commands] == ["trivia"]
    trivia_group = bark.commands[0]
    assert [c.name for c in trivia_group.commands] == ["start", "stop"]

    assert await manager.disable_module("trivia") is True
    assert [c.name for c in bark.commands] == []
