"""
Permission service — role-based access control for dashboard and bot.

See docs/permissions-model.md for full permission system documentation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("bark.services.permission_service")


class PermissionService:
    """
    Role-based permission service.

    Maps Discord users to dashboard roles:
    - admin: Full access to everything
    - moderator: Mod actions, case management, limited settings
    - viewer: Read-only dashboard access

    Modules register actions via module.get_permissions().
    The service discovers all module permissions automatically.
    """

    ROLE_HIERARCHY = {
        "viewer": 0,
        "moderator": 1,
        "admin": 2,
        "owner": 3,
    }

    # Core actions (not tied to any module)
    CORE_ACTIONS = {
        "dashboard.access": "viewer",
        "guild.manage": "admin",
        "settings.general": "admin",
        "settings.logging": "moderator",
        "settings.automod": "admin",
        "modules.manage": "admin",
        "modules.configure": "admin",
        "dashboard.users": "admin",
        # Moderation work is available to moderators; destructive case removal
        # and all configuration remain administrator-only.
        "moderation.warn": "moderator",
        "moderation.timeout": "moderator",
        "moderation.kick": "moderator",
        "moderation.ban": "moderator",
        "moderation.unban": "moderator",
        "moderation.vc_kick": "moderator",
        "moderation.vc_move": "moderator",
        "moderation.vc_mute": "moderator",
        "moderation.vc_unmute": "moderator",
        "moderation.cases.create": "moderator",
        "moderation.cases.delete": "admin",
        "moderation.warnings.delete": "moderator",
        "moderation.notes.create": "moderator",
        "moderation.notes.view": "moderator",
        "moderation.notes.delete": "moderator",
        "logging.configure": "moderator",
        "roles.manage": "admin",
    }

    def __init__(self, session=None):
        self.session = session
        self._module_actions: dict[str, str] = {}

    def register_module_permissions(self, module_name: str, permission_defs: list) -> None:
        """Register permissions from a module. Called during module discovery."""
        for perm in permission_defs:
            action_name = perm.name if hasattr(perm, "name") else perm.get("name", "")
            # Preserve centrally defined role levels; unknown module mutations
            # remain administrator-only unless a future definition says otherwise.
            self._module_actions[action_name] = self.CORE_ACTIONS.get(action_name, "admin")

    def discover_module_permissions(self, modules: dict) -> None:
        """Scan all modules and register their permissions."""
        for name, module in modules.items():
            try:
                perms = module.get_permissions()
                self.register_module_permissions(name, perms)
            except Exception:
                pass

    def get_all_actions(self) -> dict[str, str]:
        """Return all known actions with their required role level."""
        all_actions = dict(self.CORE_ACTIONS)
        all_actions.update(self._module_actions)
        return all_actions

    def role_has_access(self, user_role: str, required_role: str) -> bool:
        """Check if a user's role meets the required access level."""
        user_level = self.ROLE_HIERARCHY.get(user_role, -1)
        required_level = self.ROLE_HIERARCHY.get(required_role, 99)
        return user_level >= required_level

    def get_required_role_for_action(self, action: str) -> str:
        """
        Return the minimum role needed for a given action.

        Checks module-registered permissions first, then falls back to core actions.
        """
        # Check module permissions first
        if action in self._module_actions:
            return self._module_actions[action]
        # Fall back to core actions
        return self.CORE_ACTIONS.get(action, "admin")

    def capabilities_for_role(self, role: str) -> dict[str, bool]:
        """Return the complete, stable action manifest for a dashboard role."""
        return {
            action: self.role_has_access(role, required)
            for action, required in sorted(self.get_all_actions().items())
        }
