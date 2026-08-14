"""Authorization and validation tests for role-manager dashboard routes."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from database.engine import session_scope
from database.models.guild import Guild
from database.models.permissions import DashboardUser
from modules.role_manager.module import RoleManagerModule
from services.bark_context import BarkContext
from services.dashboard_access import replace_user_guild_access


def _session_cookie(role: str) -> str:
    session = {
        "user": {"id": "42", "username": "Auditor"},
        "role": role,
    }
    payload = base64.b64encode(json.dumps(session).encode("utf-8"))
    return TimestampSigner("test_secret_key").sign(payload).decode("utf-8")


@pytest.mark.asyncio
async def test_role_manager_read_routes_enforce_module_view_permission(db, monkeypatch):
    """A viewer must not bypass the module's configured read permission."""
    import config
    from dashboard import create_app

    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        session.add(DashboardUser(discord_id="42", username="Auditor", role="viewer"))
        await session.flush()
        await replace_user_guild_access(
            session,
            "42",
            [{"id": "1", "name": "Test Guild", "permissions": "0", "owner": False}],
        )

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {"role_manager": MagicMock()}
    bot.modules.is_enabled_for_guild.return_value = True

    dashboard = create_app(bot)
    module = RoleManagerModule(BarkContext(bot, bot.modules.event_bus))
    dashboard.app.include_router(module.get_api_routes(), prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=dashboard.app),
        base_url="http://test",
        cookies={"session": _session_cookie("viewer")},
    ) as client:
        rules = await client.get("/api/v1/guilds/1/modules/role_manager/rules")
        assignments = await client.get("/api/v1/guilds/1/modules/role_manager/assignments")
        invalid_limit = await client.get(
            "/api/v1/guilds/1/modules/role_manager/assignments",
            params={"limit": -1},
        )

    assert rules.status_code == 403
    assert assignments.status_code == 403
    # A viewer is blocked at the middleware before validation can run.
    assert invalid_limit.status_code == 403
