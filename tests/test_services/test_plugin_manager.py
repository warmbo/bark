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

VALID_PLUGIN = """
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
"""

NO_SUBCLASS_PLUGIN = """
# This file has no BarkModule subclass.
ANSWER = 42
"""

TWO_CLASSES_PLUGIN = """
from modules.base import BarkModule

class FirstPlugin(BarkModule):
    name = "first_plugin"
    async def enable(self): pass
    async def disable(self): pass

class SecondPlugin(BarkModule):
    name = "second_plugin"
    async def enable(self): pass
    async def disable(self): pass
"""

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
        self._commands: dict[str, object] = {}

    @property
    def modules(self):
        return self._module_manager

    def is_ready(self):
        return False

    # discord.ext.commands.Bot command-table surface (prefix commands).
    def add_command(self, cmd):
        self._commands[cmd.name] = cmd

    def get_command(self, name):
        return self._commands.get(name)

    def remove_command(self, name):
        self._commands.pop(name, None)


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
    # Turning it off again for the only enabled guild gates it — the module
    # stays registered (commands remain globally available) so a re-enable is
    # instant, with no command re-registration or Discord re-sync.
    assert await manager.set_guild_enabled(999, "ping_plugin", False) is True
    assert manager.is_enabled_for_guild(999, "ping_plugin") is False
    assert manager.get_module("ping_plugin").enabled is True


@pytest.mark.asyncio
async def test_set_guild_enabled_flips_gate_instantly(manager, monkeypatch):
    """Toggling a module per-server must be instant: it only flips the
    execution gate. Commands are registered globally at install/startup, so
    the toggle must NOT call enable_module/disable_module or re-sync the
    command tree.
    """
    from unittest.mock import AsyncMock

    await manager.install_plugin(VALID_PLUGIN.encode(), "whatever.py")

    enable = AsyncMock()
    disable = AsyncMock()
    monkeypatch.setattr(manager, "enable_module", enable)
    monkeypatch.setattr(manager, "disable_module", disable)

    # Enabling just flips the gate for that guild — no lifecycle churn.
    assert await manager.set_guild_enabled(999, "ping_plugin", True) is True
    assert manager.is_enabled_for_guild(999, "ping_plugin") is True
    enable.assert_not_called()
    disable.assert_not_called()

    # Disabling just flips the gate; the module stays registered.
    assert await manager.set_guild_enabled(999, "ping_plugin", False) is True
    assert manager.is_enabled_for_guild(999, "ping_plugin") is False
    enable.assert_not_called()
    disable.assert_not_called()


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
        session.add(ModuleRoleAccess(guild_id="1", module_name="ping_plugin", min_role="viewer"))
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
                    select(ModuleRoleAccess).where(ModuleRoleAccess.module_name == "ping_plugin")
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


@pytest.mark.asyncio
async def test_uninstall_syncs_command_tree(db, manager, monkeypatch):
    """Uninstalling a plugin re-syncs the command tree so its /bark commands
    stop appearing in Discord (mirrors the install-side sync)."""
    from unittest.mock import AsyncMock, MagicMock

    tree = MagicMock()
    tree.sync = AsyncMock()
    fake_bot = MagicMock()
    fake_bot.tree = tree
    fake_bot.is_ready.return_value = True
    monkeypatch.setattr(manager, "bot", fake_bot)

    await manager.install_plugin(VALID_PLUGIN.encode(), "p.py")
    tree.sync.reset_mock()

    assert await manager.uninstall_plugin("ping_plugin") is True
    tree.sync.assert_awaited_once()


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
    """A module's slash handler is registered as a prefix command (bark!roll)."""
    import discord.app_commands as ac

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()

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
    manager._register_module(FakeModule(BarkContext(bot, bot._event_bus)))
    assert await manager.enable_module("fake") is True

    # The prefix command is registered on the bot's text-command table.
    cmd = bot.get_command("roll")
    assert cmd is not None
    assert cmd.name == "roll"

    # Disabling the module removes the prefix command.
    assert await manager.disable_module("fake") is True
    assert bot.get_command("roll") is None


@pytest.mark.asyncio
async def test_multi_command_module_gets_subgroup(tmp_path):
    """Each of a module's commands registers as a flat prefix command."""
    import discord.app_commands as ac

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()

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
    manager._register_module(MultiModule(BarkContext(bot, bot._event_bus)))
    assert await manager.enable_module("mod") is True

    # Multi-command modules register as a bark!<module> group (bark!mod alpha).
    from discord.ext import commands

    mod = bot.get_command("mod")
    assert isinstance(mod, commands.Group)
    assert {c.name for c in mod.commands} == {"alpha", "beta"}

    assert await manager.disable_module("mod") is True
    assert bot.get_command("mod") is None


@pytest.mark.asyncio
async def test_namespaced_group_command_hangs_directly_off_bark(tmp_path):
    """A group-returning module becomes a text-command group (bark!trivia start)."""
    from discord.app_commands import Group

    from services.bark_context import BarkContext
    from services.module_manager import ModuleManager

    bot = FakeBot()

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

            return [CommandRegistration(name="trivia", description="Trivia game", slash=True)]

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
    manager._register_module(GroupModule(BarkContext(bot, bot._event_bus)))
    assert await manager.enable_module("trivia") is True

    # The group factory registers as a commands.Group (bark!trivia start).
    from discord.ext import commands

    trivia = bot.get_command("trivia")
    assert isinstance(trivia, commands.Group)
    assert {c.name for c in trivia.commands} == {"start", "stop"}

    assert await manager.disable_module("trivia") is True
    assert bot.get_command("trivia") is None
