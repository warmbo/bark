"""Regression: moderation read actions must be reachable by moderators.

Live audit (2026-08-29): the moderation module declares ``moderation.view``
("View Moderation Records") but it was not registered in CORE_ACTIONS, so it
fell back to the admin default. A moderator who could *create* a warning or
case (``moderation.warn`` / ``moderation.cases.create`` = moderator) could not
*view* the case list or live event stream (``moderation.view`` = admin) — an
inverted read/write permission. Reading records must be at least as permissive
as creating them.
"""

import importlib

from modules.base import BarkModule
from services.permission_service import PermissionService


def _moderation_module():
    mod = importlib.import_module("modules.moderation.module")
    cls = next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, BarkModule)
        and v is not BarkModule
        and hasattr(v, "get_permissions")
    )
    return cls.__new__(cls)


def test_moderation_view_is_moderator_gated():
    svc = PermissionService()
    svc.discover_module_permissions({"moderation": _moderation_module()})

    # Reads are at least as permissive as writes.
    assert svc.get_required_role_for_action("moderation.view") == "moderator"
    assert svc.get_required_role_for_action("moderation.warn") == "moderator"
    # Moderators can view; viewers cannot.
    assert svc.role_has_access("moderator", "moderator")
    assert not svc.role_has_access("viewer", "moderator")
    # Destructive actions stay admin.
    assert svc.get_required_role_for_action("moderation.cases.delete") == "admin"
