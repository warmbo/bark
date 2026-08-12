"""Tests for the dynamic slash-command group name.

The /bark group should follow the bot's name: rename the bot to "Bob" and
users type /bob. Covered here: the sanitizer and the resolver precedence.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config import sanitize_command_group
from services.module_manager import ModuleManager

# ── sanitize_command_group ─────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bark", "bark"),
        ("Bob", "bob"),
        ("Bark Dev", "bark_dev"),
        ("bark-dev", "bark-dev"),
        ("  Spaces  ", "spaces"),
        ("UPPER CASE", "upper_case"),
        ("###", "bark"),  # no valid chars -> fallback
        ("", "bark"),
        ("a" * 50, "a" * 32),  # capped at 32
        ("MiXeD-Case_Name", "mixed-case_name"),  # hyphens/underscores preserved
    ],
)
def test_sanitize_command_group(raw: str, expected: str):
    assert sanitize_command_group(raw) == expected


# ── ModuleManager.command_group_name ───────────────────


def _manager_with_bot(bot) -> ModuleManager:
    return ModuleManager(bot)


def test_defaults_to_bark_when_no_user():
    bot = MagicMock()
    bot.user = None
    manager = _manager_with_bot(bot)
    assert manager.command_group_name() == "bark"


def test_derives_from_bot_name():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.name = "Bob"
    manager = _manager_with_bot(bot)
    assert manager.command_group_name() == "bob"


def test_derives_and_sanitizes_bot_name():
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.name = "Bark Dev!"
    manager = _manager_with_bot(bot)
    assert manager.command_group_name() == "bark_dev"


def test_explicit_config_override_wins(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "command_group", "fido")
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.name = "Bob"
    manager = _manager_with_bot(bot)
    assert manager.command_group_name() == "fido"


def test_config_override_is_sanitized(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "command_group", "  Good Boy  ")
    manager = _manager_with_bot(MagicMock())
    assert manager.command_group_name() == "good_boy"


def test_group_is_created_with_dynamic_name(monkeypatch):
    """The registered Group name follows the bot name, not a hardcoded 'bark'."""
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "command_group", "")
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.name = "Bob"
    bot.tree = MagicMock()
    manager = _manager_with_bot(bot)
    group = manager._get_bark_group()
    assert group.name == "bob"
    bot.tree.add_command.assert_called_once()
