"""
Bark services layer.

Contains shared business logic:
- ModuleManager: module lifecycle management
- PermissionService: role-based access control
"""

from services.module_manager import ModuleManager
from services.permission_service import PermissionService

__all__ = ["ModuleManager", "PermissionService"]
