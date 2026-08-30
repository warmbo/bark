"""Public documentation / wiki data model, generated from the live module registry.

The wiki pages are built from the running bot's modules so the documentation
never drifts from code: command paths and arguments come from the slash
dispatcher registry, settings from ``get_settings_schema()``, permissions from
``get_permissions()``, and module metadata from the ``BarkModule``
declarations. Everything returned here is plain, serializable data suitable for
a Jinja template.

When the bot/module registry is unavailable (e.g. dashboard booted before
modules enabled, or a bare import in tests) the collectors degrade to empty
lists rather than raising, so the wiki stays up.
"""

from __future__ import annotations

from typing import Any

from discord import AppCommandOptionType
from discord import Permissions as DiscordPermissions

# AppCommandOptionType -> human-readable argument type.
_OPTION_LABELS: dict[AppCommandOptionType, str] = {
    AppCommandOptionType.string: "text",
    AppCommandOptionType.integer: "whole number",
    AppCommandOptionType.number: "number",
    AppCommandOptionType.boolean: "yes/no",
    AppCommandOptionType.user: "member",
    AppCommandOptionType.mentionable: "member or role",
    AppCommandOptionType.role: "role",
    AppCommandOptionType.channel: "channel",
    AppCommandOptionType.attachment: "attachment",
}

# Moderation-record commands that expose *other members'* disciplinary history
# (warning reasons, moderator IDs, case targets). These stay member-readable
# but must never be broadcast publicly — they have no hide/public toggle.
_ALWAYS_PRIVATE_PATHS = {"cases", "warnings"}


# A Discord Permissions bitfield -> the role tier that can run the command.
_MODERATOR_BITS = (
    "moderate_members",
    "kick_members",
    "ban_members",
    "mute_members",
    "move_members",
    "deafen_members",
    "manage_messages",
)


def _option_label(option_type: int | None) -> str:
    if option_type is None:
        return "value"
    try:
        return _OPTION_LABELS.get(AppCommandOptionType(option_type), "value")
    except (TypeError, ValueError):
        return "value"


def _required_role(perms: Any) -> str:
    """Map a leaf command's ``default_permissions`` to a human role tier.

    ``None`` means any member may run it. Discord bitfields are mapped to the
    documented tiers: any moderation permission -> moderator, Manage Server ->
    admin.
    """
    if perms is None:
        return "Anyone"
    if isinstance(perms, bool):
        return "Anyone"  # degenerate; treat as un-gated
    p = perms if isinstance(perms, DiscordPermissions) else DiscordPermissions(int(perms) if isinstance(perms, int) else 0)
    if any(getattr(p, bit, False) for bit in _MODERATOR_BITS):
        return "Moderator"
    if getattr(p, "manage_guild", False) or getattr(p, "administrator", False):
        return "Admin"
    return "Anyone"


def _parameter_dict(param: Any) -> dict[str, Any]:
    return {
        "name": getattr(param, "name", ""),
        "type": _option_label(getattr(param, "type", None)),
        "required": bool(getattr(param, "required", False)),
        "description": getattr(param, "description", "") or "",
    }


def _command_dict(leaf: Any) -> dict[str, Any]:
    cmd = getattr(leaf, "command", None)
    params = getattr(cmd, "parameters", []) if cmd else []
    default_permissions = getattr(cmd, "default_permissions", None) if cmd else None
    return {
        "path": getattr(leaf, "path", ""),
        "module": getattr(leaf, "module_name", ""),
        "name": getattr(cmd, "name", "") if cmd else "",
        "description": getattr(cmd, "description", "") if cmd else "",
        "parameters": [_parameter_dict(p) for p in params],
        "required_role": _required_role(default_permissions),
        "always_private": getattr(leaf, "path", "") in _ALWAYS_PRIVATE_PATHS,
    }


def _schema_properties(module) -> list[dict[str, Any]]:
    try:
        schema = module.get_settings_schema() or {}
    except Exception:
        return []
    props = schema.get("properties", {})
    out: list[dict[str, Any]] = []
    for key, spec in (props or {}).items():
        if not isinstance(spec, dict):
            continue
        out.append(
            {
                "key": key,
                "title": spec.get("title") or key,
                "type": spec.get("type", ""),
                "description": spec.get("description", ""),
                "default": spec.get("default"),
                "enum": spec.get("enum"),
            }
        )
    return out


def _module_dict(module: Any, commands: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": getattr(module, "name", ""),
        "version": getattr(module, "version", ""),
        "description": getattr(module, "description", "") or "",
        "author": getattr(module, "author", "") or "",
        "commands": [c for c in commands if c["module"] == getattr(module, "name", "")],
        "settings": _schema_properties(module),
        "permissions": _permission_dicts(module),
        "about": _about_stories(module),
    }


def _permission_dicts(module) -> list[dict[str, str]]:
    try:
        perms = module.get_permissions() or []
    except Exception:
        return []
    return [
        {
            "name": getattr(p, "name", ""),
            "label": getattr(p, "label", "") or getattr(p, "name", ""),
            "description": getattr(p, "description", "") or "",
        }
        for p in perms
    ]


def _about_stories(module) -> list[dict[str, Any]]:
    try:
        about = module.get_about() or []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for item in about:
        if not isinstance(item, dict):
            continue
        if "stories" in item and isinstance(item["stories"], list):
            out.append({"title": item.get("title", ""), "stories": item["stories"]})
        else:
            out.append(
                {
                    "title": item.get("title", ""),
                    "stories": [{"prefix": "", "text": item.get("description", "")}],
                }
            )
    return out


def _module_names(manager: Any) -> list[str]:
    if manager is None:
        return []
    try:
        all_modules = manager.get_all_modules()
    except Exception:
        return []
    return list(all_modules.keys()) if isinstance(all_modules, dict) else []


def _dispatcher_registry(manager: Any) -> dict[str, Any]:
    if manager is None:
        return {}
    dispatcher = getattr(manager, "_dispatcher", None)
    if dispatcher is None:
        return {}
    try:
        return getattr(dispatcher, "_registry", {}) or {}
    except Exception:
        return {}


def collect_modules(manager: Any) -> list[dict[str, Any]]:
    """Every module with its commands, settings, permissions, and about text."""
    registry = _dispatcher_registry(manager)
    commands = [_command_dict(leaf) for leaf in registry.values()]
    modules: list[dict[str, Any]] = []
    if manager is None:
        return modules
    try:
        all_modules = manager.get_all_modules()
    except Exception:
        return modules
    for name in (all_modules.keys() if isinstance(all_modules, dict) else []):
        module = all_modules.get(name) if isinstance(all_modules, dict) else None
        if module is None:
            continue
        modules.append(_module_dict(module, commands))
    modules.sort(key=lambda m: m["name"])
    return modules


def collect_commands(manager: Any) -> list[dict[str, Any]]:
    """Every command path with args and required role, sorted by module then path."""
    commands = [_command_dict(leaf) for leaf in _dispatcher_registry(manager).values()]
    commands.sort(key=lambda c: (c["module"], c["path"]))
    return commands


def collect_settings(manager: Any) -> list[dict[str, Any]]:
    """Every module's settings (from its JSON schema)."""
    out: list[dict[str, Any]] = []
    if manager is None:
        return out
    try:
        all_modules = manager.get_all_modules()
    except Exception:
        return out
    for name in (all_modules.keys() if isinstance(all_modules, dict) else []):
        module = all_modules.get(name) if isinstance(all_modules, dict) else None
        if module is None:
            continue
        props = _schema_properties(module)
        if props:
            out.append(
                {
                    "module": getattr(module, "name", name),
                    "module_description": getattr(module, "description", "") or "",
                    "settings": props,
                }
            )
    out.sort(key=lambda m: m["module"])
    return out


def collect_permissions() -> list[dict[str, str]]:
    """Every known action mapped to its required role tier (core + modules)."""
    from services.permission_service import PermissionService

    try:
        actions = PermissionService().get_all_actions()
    except Exception:
        return []
    out = [
        {"action": action, "role": (role or "admin")}
        for action, role in (actions or {}).items()
    ]
    out.sort(key=lambda p: p["action"])
    return out


def command_group_name(manager: Any) -> str:
    if manager is None:
        return "bark"
    try:
        return manager.command_group_name()
    except Exception:
        return "bark"


def public_url(config: Any) -> str:
    try:
        return getattr(config.dashboard, "public_url", "") or ""
    except Exception:
        return ""
