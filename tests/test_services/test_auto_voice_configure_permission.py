"""Regression: dashboard moderators can save Auto Voice configuration.

Live incident (2026-08-24): an admin (Discord staff role -> dashboard
"moderator") in Bennny's Love Shack got 403 saving the Auto Voice module —
the config route checks ``auto_voice.configure`` but the module only declared
``auto_voice.manage``, so the unknown action fell through to the admin
default and every moderator save was denied.
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
