"""Regression: dashboard moderators can save Auto Voice configuration.

Live incident (2026-08-24): an admin (Discord staff role -> dashboard
"moderator") in Bennny's Love Shack got 403 saving the Auto Voice module.
The config route checks ``auto_voice.configure``; that action is declared
moderator (CORE_ACTIONS + the module's get_permissions()), but
``check_api_permission``'s module branch ignored the declared role and
defaulted unset module actions to admin-only — so moderators were locked out
until an admin manually added a ModuleRoleAccess override row (which the UI
offered no way to do). The fix: an unset module action falls back to its
declared role instead of admin.
"""
import importlib

from modules.base import BarkModule
from services.permission_service import PermissionService


def _auto_voice_module():
    mod = importlib.import_module("modules.auto_voice.module")
    cls = next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, BarkModule)
        and v is not BarkModule
        and hasattr(v, "get_permissions")
    )
    return cls.__new__(cls)


def test_auto_voice_configure_is_registered_and_moderator_gated():
    svc = PermissionService()
    svc.discover_module_permissions({"auto_voice": _auto_voice_module()})

    assert "auto_voice.configure" in svc.get_all_actions()
    required = svc.get_required_role_for_action("auto_voice.configure")
    assert required == "moderator"
    # The route resolves the action to a role, then compares tiers.
    assert svc.role_has_access("moderator", required)
    assert svc.role_has_access("admin", required)
    assert not svc.role_has_access("viewer", required)
    # Lifecycle stays admin-only.
    assert svc.get_required_role_for_action("auto_voice.manage") == "admin"


def test_check_api_permission_module_action_defaults_to_declared_role(monkeypatch):
    """Unset module actions fall back to the declared role, not admin-only.

    Reproduces the incident: a moderator (no per-guild ModuleRoleAccess
    override) must be able to save auto_voice.configure, which is declared
    moderator, without an admin first creating an override row.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import config

    from services.response import check_api_permission, get_permission_service

    # Discover so _module_actions carries the module-declared roles.
    svc = get_permission_service()
    svc.discover_module_permissions({"auto_voice": _auto_voice_module()})

    # Force OAuth-enabled so the gate is actually evaluated. monkeypatch
    # restores the config so a later auth-dependent test isn't polluted.
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    request = SimpleNamespace(
        session={"role": "moderator"},
        state=SimpleNamespace(bot=MagicMock()),
        url=SimpleNamespace(path="/api/v1/guilds/8/modules/auto_voice"),
    )
    # No override seeded -> declared moderator role is the default.
    assert check_api_permission(request, "auto_voice.configure", guild_id=8)

    # A viewer must still be denied (declared role is moderator, not viewer).
    request.session["role"] = "viewer"
    assert not check_api_permission(request, "auto_voice.configure", guild_id=8)
