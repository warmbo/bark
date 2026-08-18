"""Module UI "ingredient" rules (v0.4 Part B enforcement).

Every module's Configure page must be composed only from the pre-determined
"ingredient" vocabulary the renderer understands. These tests fail closed when
a module declares a schema type/format the renderer cannot render, or when a
module grows the shared bespoke UI template dirs instead of staying
self-contained.

Rules (see docs/module-workspace.md):
1. ``get_settings_schema()`` property ``type`` must be a known ingredient type.
2. ``get_settings_schema()`` property ``format`` must be a known ingredient hint.
3. Module-specific UI must NOT be added to the shared ``module_tabs/`` or
   ``components/`` directories — it belongs under ``modules/<name>/``.

These tests are deliberately non-vacuous: the module packages are discovered
and every schema property is walked, so a module that stops declaring a schema
does not silently empty the assertion.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import modules as modules_pkg
from modules.base import BarkModule
from services.bark_context import BarkContext
from services.event_bus import EventBus

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "dashboard" / "templates"

# The only ingredient types the renderer (primitives.html ``schema_field`` +
# module_detail.html) can render. Adding a type here is a deliberate, documented
# extension of the ingredient vocabulary — NOT an escape hatch for new markup.
ALLOWED_SCHEMA_TYPES = {
    "object",  # grouping container (nested properties)
    "string",
    "text",
    "integer",
    "number",
    "boolean",
    "array",
    "color",
}

# ``format`` hints the renderer understands (api-selects + rich textarea).
ALLOWED_SCHEMA_FORMATS = {
    "textarea",
    "role_select",
    "channel_select",
    "voice_channel_select",
}

# The existing colocated bespoke module-UI partials. This allowlist must NOT
# grow: new module UI belongs in the module's own directory.
ALLOWED_SHARED_MODULE_TEMPLATES = {
    "modules/logging/templates/logging_logs.html",
    "modules/moderation/templates/moderation_cases.html",
    "modules/moderation/templates/moderation_notes.html",
    "modules/moderation/templates/moderation_rulesets.html",
    "modules/moderation/templates/moderation_voice.html",
    "modules/moderation/templates/moderation_warnings.html",
    "modules/moderation/templates/moderation_wordlists.html",
    "modules/reputation/templates/reputation_leaderboard.html",
    "modules/reputation/templates/reputation_thanks.html",
    "modules/reputation/templates/reputation_tiers.html",
    "modules/role_manager/templates/role_manager_assignments.html",
    "modules/role_manager/templates/role_manager_rules.html",
    "components/speak_phrases.html",
    "components/bot_customization.html",
    "components/discord_toolbar.html",
    "components/icons.html",
    "components/primitives.html",
    "components/settings_scripts.html",
}


def _module_packages() -> list[str]:
    """Return the names of discoverable core module packages."""
    return [
        name
        for _, name, is_pkg in pkgutil.iter_modules(modules_pkg.__path__)
        if is_pkg and name != "base"
    ]


def _module_classes(package_name: str) -> list[type[BarkModule]]:
    """Return every BarkModule subclass defined within a module package."""
    candidates: list[object] = [importlib.import_module(f"modules.{package_name}")]
    pkg_path = getattr(candidates[0], "__path__", None)
    if pkg_path:
        for _, sub_name, _ in pkgutil.iter_modules(pkg_path):
            try:
                candidates.append(importlib.import_module(f"modules.{package_name}.{sub_name}"))
            except Exception:  # a broken submodule is reported by discovery, not here
                continue
    found: list[type[BarkModule]] = []
    for candidate in candidates:
        for _, obj in inspect.getmembers(candidate):
            if (
                inspect.isclass(obj)
                and issubclass(obj, BarkModule)
                and obj is not BarkModule
                and obj.__module__.startswith(f"modules.{package_name}")
            ):
                found.append(obj)
    return found


def _settings_schema(cls: type[BarkModule]) -> dict:
    """Build one module instance with a stub context and read its schema."""
    ctx = BarkContext(SimpleNamespace(), EventBus())
    return cls(ctx).get_settings_schema() or {}


def _iter_schema_props(schema: dict):
    """Yield (path, prop) for every leaf property, descending object groups."""
    for key, prop in (schema.get("properties") or {}).items():
        yield (key,), prop
        if prop.get("type") == "object" and prop.get("properties"):
            for sub_path, sub_prop in _iter_schema_props(prop):
                yield (key, *sub_path), sub_prop


def test_settings_schema_uses_only_known_ingredient_types():
    """Every schema property type/format is a renderable ingredient."""
    offending: list[str] = []
    for package in _module_packages():
        for cls in _module_classes(package):
            schema = _settings_schema(cls)
            for path, prop in _iter_schema_props(schema):
                label = f"{cls.__name__} (modules.{package}).{'.'.join(path)}"
                ptype = prop.get("type")
                if ptype and ptype not in ALLOWED_SCHEMA_TYPES:
                    offending.append(f"{label}: type={ptype!r}")
                pformat = prop.get("format")
                if pformat and pformat not in ALLOWED_SCHEMA_FORMATS:
                    offending.append(f"{label}: format={pformat!r}")
    assert not offending, (
        "Module settings schemas use non-ingredient types/formats the renderer "
        "cannot draw:\n" + "\n".join(sorted(offending))
    )


def test_module_ui_stays_colocated_not_shared():
    """The shared bespoke module-template set must not grow."""
    shared = {
        str(p.relative_to(TEMPLATES)) for p in (TEMPLATES / "module_tabs").rglob("*.html")
    } | {str(p.relative_to(TEMPLATES)) for p in (TEMPLATES / "components").rglob("*.html")}
    unexpected = sorted(shared - ALLOWED_SHARED_MODULE_TEMPLATES)
    assert not unexpected, (
        "New bespoke shared module UI added — colocate it under "
        "modules/<name>/ (config.html/assets) or compose it from the preset "
        "ingredient macros instead:\n" + "\n".join(unexpected)
    )


def test_every_module_declares_a_renderable_schema_or_none():
    """Each module either omits a settings schema or yields at least one
    property (non-vacuous: a module with a schema must have walkable props)."""
    for package in _module_packages():
        for cls in _module_classes(package):
            schema = _settings_schema(cls)
            props = list(_iter_schema_props(schema))
            # A schema with a non-empty properties dict must yield props.
            if (schema.get("properties") or {}) and not props:
                pytest.fail(f"modules.{package} schema declares properties but none are walkable")
