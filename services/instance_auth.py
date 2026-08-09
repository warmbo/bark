"""Instance-owner authorization shared by owner-gated API routes.

Gate rule (fail-closed): when OAuth is enabled, only users whose Discord ID is
in ``config.oauth2.owner_discord_ids`` may manage the instance (backups,
plugins, updates, bot appearance). When OAuth is disabled (mock/dev harnesses),
everyone is permitted — there is no other notion of identity.

Callers must NOT duplicate this logic; import ``can_manage_instance``.
"""

from __future__ import annotations

from fastapi import Request

from config import config


def can_manage_instance(request: Request) -> bool:
    """Owner-only when OAuth is configured; permissive otherwise.

    Deliberately fail-closed: with OAuth enabled but no owner IDs configured,
    nobody passes (avoids exposing backups/plugins/updates to every
    authenticated user in custom launchers that skip validate_startup).
    """
    if config.oauth2.enabled:
        ids = config.oauth2.owner_discord_ids
        if not ids:
            return False
        user = request.session.get("user") or {}
        return user.get("id") in ids
    return True
