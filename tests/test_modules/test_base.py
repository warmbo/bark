"""
Tests for the module system.
"""

import pytest
from modules.base import BarkModule, CommandRegistration, EventRegistration, PageRegistration


class MockBot:
    """Minimal mock bot for testing modules."""
    def __init__(self):
        self.user = None
        self.tree = None

    def get_guild(self, guild_id):
        return None

    def listen(self, name):
        def decorator(func):
            return func
        return decorator


class MockTestModule(BarkModule):
    """Test module implementation."""
    name = "test_module"
    version = "2.0.0"
    description = "A test module"

    async def enable(self):
        self.enabled = True

    async def disable(self):
        self.enabled = False

    def get_commands(self):
        return [CommandRegistration(name="test", description="Test command")]

    def get_events(self):
        return [EventRegistration(event_name="on_message")]

    def get_dashboard_pages(self):
        return [PageRegistration(route="/test", label="Test")]

    def get_permissions(self):
        from modules.base import PermissionDefinition
        return [PermissionDefinition(name="test.perm", label="Test Perm")]


@pytest.mark.asyncio
async def test_module_lifecycle():
    """Test enable/disable/reload lifecycle."""
    bot = MockBot()
    module = MockTestModule(bot)

    assert module.name == "test_module"
    assert module.version == "2.0.0"
    assert not module.enabled

    await module.enable()
    assert module.enabled

    await module.disable()
    assert not module.enabled


@pytest.mark.asyncio
async def test_module_reload():
    """Test module reload."""
    bot = MockBot()
    module = MockTestModule(bot)

    await module.enable()
    assert module.enabled

    await module.reload()
    assert module.enabled


def test_module_registrations():
    """Test module registration methods."""
    bot = MockBot()
    module = MockTestModule(bot)

    commands = module.get_commands()
    assert len(commands) == 1
    assert commands[0].name == "test"

    events = module.get_events()
    assert len(events) == 1
    assert events[0].event_name == "on_message"

    pages = module.get_dashboard_pages()
    assert len(pages) == 1
    assert pages[0].route == "/test"

    perms = module.get_permissions()
    assert len(perms) == 1
    assert perms[0].name == "test.perm"


def test_module_settings_schema():
    """Test settings schema."""
    bot = MockBot()
    module = MockTestModule(bot)
    assert module.get_settings_schema() == {}
