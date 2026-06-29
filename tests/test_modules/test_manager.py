"""
Tests for the module manager.
"""

import pytest
from services.module_manager import ModuleManager


@pytest.mark.asyncio
async def test_module_manager_discovery(monkeypatch):
    """Test that module manager initializes without errors."""
    from modules.base import BarkModule

    bot = type('MockBot', (), {'user': None, 'tree': None})()

    # Mock the discovery to avoid importing real modules during testing
    manager = ModuleManager(bot)

    # Should start with empty modules dict
    assert len(manager.get_all_modules()) == 0

    # Enable/disable on empty manager should be safe
    assert not await manager.enable_module("nonexistent")
    assert not await manager.disable_module("nonexistent")
    assert not await manager.reload_module("nonexistent")


def test_module_manager_queries():
    """Test query methods on empty module manager."""
    bot = type('MockBot', (), {'user': None, 'tree': None})()
    manager = ModuleManager(bot)

    assert manager.get_all_modules() == {}
    assert manager.get_enabled_modules() == {}
    assert manager.get_dashboard_pages() == {}
    assert manager.get_all_commands() == []
    assert manager.get_all_events() == []
    assert manager.get_module("anything") is None
