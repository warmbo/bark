"""Regression: dashboard moderators/admins can control the Reputation module.

Live report (2026-08-27): only the server owner could run the Reputation
module — a server admin (e.g. a Discord MANAGE_GUILD holder or configured
staff role, which maps to the dashboard "moderator" tier) got 403 enabling,
configuring, or even viewing reputation. The actions ``reputation.manage`` /
``reputation.configure`` / ``reputation.view`` were undeclared in
CORE_ACTIONS, so they fell back to ``admin`` — locking out every non-owner
elevated user. The fix registers them explicitly so any server manager can
control the module.
"""

import importlib

from modules.base import BarkModule
from services.permission_service import PermissionService


def _reputation_module():
    mod = importlib.import_module("modules.reputation.module")
    cls = next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, BarkModule)
        and v is not BarkModule
        and hasattr(v, "get_permissions")
    )
    return cls.__new__(cls)


def test_reputation_manage_is_moderator_gated():
    svc = PermissionService()
    svc.discover_module_permissions({"reputation": _reputation_module()})

    assert "reputation.manage" in svc.get_all_actions()
    # Any server manager (admin or moderator tier) can enable/disable reputation.
    assert svc.get_required_role_for_action("reputation.manage") == "moderator"
    assert svc.get_required_role_for_action("reputation.configure") == "moderator"
    # Viewing reputation data is open to every member.
    assert svc.get_required_role_for_action("reputation.view") == "viewer"
    # Tier checks: moderator+ passes manage, viewer does not.
    assert svc.role_has_access("moderator", "moderator")
    assert svc.role_has_access("admin", "moderator")
    assert not svc.role_has_access("viewer", "moderator")


def test_check_api_permission_reputation_manage_allows_moderator(monkeypatch):
    """A moderator (elevated admin) can toggle/configure reputation with no
    per-guild ModuleRoleAccess override — the reported incident."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import config

    from services.response import check_api_permission, get_permission_service

    svc = get_permission_service()
    svc.discover_module_permissions({"reputation": _reputation_module()})

    # Force OAuth-enabled so the gate is actually evaluated. monkeypatch
    # restores the config after the test so later tests aren't polluted.
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    request = SimpleNamespace(
        session={"role": "moderator"},
        state=SimpleNamespace(bot=MagicMock()),
        url=SimpleNamespace(path="/api/v1/guilds/8/modules/reputation"),
    )
    # No override seeded -> declared moderator role lets a manager through.
    assert check_api_permission(request, "reputation.manage", guild_id=8)
    assert check_api_permission(request, "reputation.configure", guild_id=8)

    # A viewer must still be denied.
    request.session["role"] = "viewer"
    assert not check_api_permission(request, "reputation.manage", guild_id=8)
    assert not check_api_permission(request, "reputation.configure", guild_id=8)
