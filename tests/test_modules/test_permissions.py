"""
Tests for permission service.
"""

import pytest
from services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_role_hierarchy():
    """Test permission role hierarchy."""
    svc = PermissionService.__new__(PermissionService)

    assert svc.role_has_access("admin", "viewer") == True
    assert svc.role_has_access("admin", "moderator") == True
    assert svc.role_has_access("admin", "admin") == True

    assert svc.role_has_access("moderator", "viewer") == True
    assert svc.role_has_access("moderator", "moderator") == True
    assert svc.role_has_access("moderator", "admin") == False

    assert svc.role_has_access("viewer", "viewer") == True
    assert svc.role_has_access("viewer", "moderator") == False
    assert svc.role_has_access("viewer", "admin") == False


def test_required_role_for_action():
    """Test action-to-role mapping."""
    assert PermissionService.get_required_role_for_action("modules.manage") == "admin"
    assert PermissionService.get_required_role_for_action("moderation.warn") == "moderator"
    assert PermissionService.get_required_role_for_action("moderation.cases") == "moderator"
    assert PermissionService.get_required_role_for_action("viewing.dashboard") == "viewer"
