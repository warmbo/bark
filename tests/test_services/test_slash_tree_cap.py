"""Regression: the /bark native subcommand tree must stay under Discord's
25-child cap so the tree sync succeeds.

Live incident (2026-09-01): the moderation subcommand-group held 30 children
(16 canonical + 14 aliases). `tree.sync()` failed with 50035
"In ...options: Must be 25 or fewer in length", the new /bark signature never
reached Discord, and every /bark interaction was rejected with
CommandSignatureMismatch ("Couldn't run that command — check the arguments").
"""
import importlib

from modules.base import BarkModule
from services.slash_dispatcher import SlashDispatcher

CORE = [
    "announcements",
    "auto_voice",
    "help",
    "logging",
    "moderation",
    "reputation",
    "role_manager",
    "speak",
    "welcome",
]
PLUGINS = ["birthdays"]


class FakeManager:
    def is_plugin(self, name):
        return name in PLUGINS

    def _command_enabled_check(self, name):
        return lambda _i: True


class FakeBot:
    pass


def _module_class(module_name):
    if module_name in PLUGINS:
        mod = importlib.import_module(f"data.plugins.{module_name}")
    else:
        mod = importlib.import_module(f"modules.{module_name}.module")
    return next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, BarkModule)
        and v is not BarkModule
        and hasattr(v, "get_commands")
    )


def _build_tree():
    d = SlashDispatcher(FakeBot(), FakeManager())
    for name in CORE + PLUGINS:
        d.register_module(name, _module_class(name).__new__(_module_class(name)))
    return d.build_group("bark")


def test_every_subcommand_group_respects_discord_cap():
    """No subgroup may exceed 25 children (canonical + aliases)."""
    group = _build_tree()
    bad = []
    for child in group.commands:
        if getattr(child, "commands", None) and len(child.commands) > 25:
            bad.append((child.name, len(child.commands)))
    assert not bad, f"subgroups over Discord's 25-child cap: {bad}"


def test_canonical_commands_present_before_cap():
    """Capping aliases must not silently drop canonical commands — every
    module's primary commands stay in the tree."""
    group = _build_tree()
    names = {c.name: getattr(c, "commands", None) for c in group.commands}
    # The birthday group (module plugin) keeps all 4 subcommands.
    bday = names.get("birthdays")
    assert bday is not None and {c.name for c in bday} >= {"set", "remove", "list", "channel"}
