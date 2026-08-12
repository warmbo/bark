"""Regression tests: module pages render the bot's dynamic slash-command group.

The /bark group name follows the bot (BARK_COMMAND_GROUP override > bot
username > "bark"), so every module page that lists commands must use the
runtime-derived name instead of a hardcoded "/bark". This applies to core
modules AND add-on plugins (they share the same routes/templates/helper).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from modules.base import BarkModule

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "dashboard" / "templates"


def _source(rel: str) -> str:
    return (TEMPLATES / rel).read_text(encoding="utf-8")


# ── BarkModule.command_group_name() helper ─────────────────────


class _ConcreteModule(BarkModule):
    """Minimal concrete BarkModule for helper tests."""

    name = "concrete"

    async def enable(self) -> None:  # pragma: no cover - stub
        return None

    async def disable(self) -> None:  # pragma: no cover - stub
        return None


def _module_with_ctx(ctx) -> _ConcreteModule:
    return _ConcreteModule(ctx)


def test_module_command_group_name_uses_manager():
    module = _module_with_ctx(MagicMock())
    module.ctx.bot.modules.command_group_name.return_value = "bob"
    assert module.command_group_name() == "bob"


def test_module_command_group_name_falls_back_to_bark():
    module = _module_with_ctx(MagicMock())
    module.ctx.bot = None
    import config as config_module

    config_module.config.bot.command_group = ""
    assert module.command_group_name() == "bark"


def test_module_command_group_name_respects_config_override():
    module = _module_with_ctx(MagicMock())
    module.ctx.bot = None
    import config as config_module

    config_module.config.bot.command_group = "fido"
    assert module.command_group_name() == "fido"
    config_module.config.bot.command_group = ""


# ── Module pages render the dynamic prefix (not hardcoded /bark) ─


def test_module_detail_command_list_uses_dynamic_prefix():
    html = _source("pages/module_detail.html")
    # The command list must interpolate the runtime group name.
    assert "/{{ command_group_name }} {{ cmd.name }}" in html
    # And must NOT hardcode a /bark prefix on command names.
    assert "/bark {{ cmd.name }}" not in html


def test_modules_list_command_badge_uses_dynamic_prefix():
    html = _source("pages/modules.html")
    assert "/{{ command_group_name }} {{ cmd.name }}" in html
    assert "/bark {{ cmd.name }}" not in html


def test_dashboard_help_text_uses_dynamic_prefix():
    html = _source("pages/dashboard.html")
    assert "/{{ command_group_name }}" in html
    assert "code>/bark</code>" not in html


def test_speak_phrases_tab_uses_dynamic_prefix():
    html = _source("components/speak_phrases.html")
    assert "/{{ command_group_name }} speak" in html
    assert "/bark speak" not in html


# ── Routes inject command_group_name into the template context ──


def test_module_routes_pass_command_group_name():
    src = (ROOT / "dashboard" / "routes" / "web" / "modules.py").read_text(
        encoding="utf-8"
    )
    # Both the list page and the detail page must feed the name to the template.
    assert '"command_group_name": bot.modules.command_group_name()' in src
    assert src.count("command_group_name") >= 3  # both routes


def test_dashboard_route_passes_command_group_name():
    src = (ROOT / "dashboard" / "__init__.py").read_text(encoding="utf-8")
    assert '"command_group_name": bot.modules.command_group_name()' in src
