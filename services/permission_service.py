"""
Permission service — role-based access control for dashboard and bot.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database.engine import AsyncSession

logger = logging.getLogger("bark.services.permission_service")


class PermissionService:
    """
    Role-based permission service.

    Maps Discord users to dashboard roles:
    - admin: Full access to everything
    - moderator: Mod actions, case management, limited settings
    - viewer: Read-only dashboard access
    """

    ROLE_HIERARCHY = {
        "viewer": 0,
        "moderator": 1,
        "admin": 2,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def role_has_access(self, user_role: str, required_role: str) -> bool:
        """Check if a user's role meets the required access level."""
        user_level = self.ROLE_HIERARCHY.get(user_role, -1)
        required_level = self.ROLE_HIERARCHY.get(required_role, 99)
        return user_level >= required_level

    @staticmethod
    def get_required_role_for_action(action: str) -> str:
        """
        Return the minimum role needed for a given action.

        'admin' actions: module management, guild settings, user role assignment
        'moderator' actions: warn, timeout, kick, ban, case management
        'viewer' actions: read-only dashboard access
        """
        admin_actions = {
            "modules.manage", "modules.configure",
            "settings.general", "settings.automod",
            "dashboard.users", "guild.manage",
        }
        moderator_actions = {
            "moderation.warn", "moderation.timeout", "moderation.kick",
            "moderation.ban", "moderation.unban", "moderation.cases",
            "moderation.notes", "moderation.warnings",
            "settings.logging",
        }

        if action in admin_actions:
            return "admin"
        if action in moderator_actions:
            return "moderator"
        return "viewer"
