"""
Bark services layer — the backbone of the system.

All business logic lives here. Services coordinate between
the API layer, modules, database, and bot runtime.
"""

from services.bark_context import BarkContext
from services.event_bus import EventBus
from services.module_manager import ModuleManager
from services.moderation_service import ModerationService
from services.permission_service import PermissionService
from services.response import api_success, api_error, api_created, api_not_found, api_forbidden, api_paginated
from services.realtime_bridge import RealtimeBridge

__all__ = [
    "BarkContext",
    "EventBus",
    "ModuleManager",
    "ModerationService",
    "PermissionService",
    "RealtimeBridge",
    "api_success",
    "api_error",
    "api_created",
    "api_not_found",
    "api_forbidden",
    "api_paginated",
]
