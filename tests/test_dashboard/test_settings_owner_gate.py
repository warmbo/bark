"""Owner-only Settings sections are hidden for non-owners.

Backups, Updates, Diagnostics, Bot Customization, and Hosted Instance Access
must render only for the instance owner. The APIs behind them are already
owner-gated; this guards the UI so a non-owner admin doesn't see controls they
can't use (and aren't supposed to know are there).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Each owner-only card is identified by a string that appears ONLY in that
# gated card's markup (not in the page's shared JS, where words like "Backups"
# and "Updates" legitimately appear in comments/strings).
OWNER_CARD_MARKERS = [
    "Snapshot the full database",  # Backups
    "Change the bot's name, avatar, banner",  # Bot Customization
    "Pull the latest release from GitHub",  # Updates
    "Download a redacted report",  # Diagnostics
    "Create one-time share links",  # Hosted Instance Access
]


def _make_bot() -> MagicMock:
    bot = MagicMock()
    guild = MagicMock()
    guild.id = 1
    guild.name = "Test Guild"
    bot.get_guild.return_value = guild
    bot.modules.get_all_modules.return_value = {}
    return bot


async def _render_settings(monkeypatch, user_id: str | None, view: str = "instance") -> str:
    import config as cfg
    from dashboard.routes.web.settings import settings_page

    # Enable OAuth so can_manage_instance actually checks the owner list.
    monkeypatch.setattr(cfg.config.oauth2, "client_id", "123")
    monkeypatch.setattr(cfg.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(cfg.config.oauth2, "redirect_uri", "http://test/callback")
    monkeypatch.setattr(cfg.config.oauth2, "owner_discord_ids", {"42"})

    request = SimpleNamespace(
        state=SimpleNamespace(bot=_make_bot()),
        session=({"user": {"id": user_id, "username": "Test"}} if user_id else {}),
        url=SimpleNamespace(path=f"/guild/1/settings/{'instance' if view == 'instance' else ''}"),
        app=SimpleNamespace(state=SimpleNamespace(version="test")),
    )
    # The owner-only cards (Backups, Updates, Diagnostics, Bot Customization,
    # Hosted Instance Access) live on the Instance page, so render that view.
    from dashboard.routes.web import settings as settings_mod

    handler = settings_mod.settings_instance_page if view == "instance" else settings_page
    response = await handler(request, 1)
    return response.body.decode()


@pytest.mark.asyncio
async def test_owner_sections_hidden_for_non_owner(monkeypatch):
    html = await _render_settings(monkeypatch, user_id="43")
    for marker in OWNER_CARD_MARKERS:
        assert marker not in html, f"owner card should be hidden for a non-owner: {marker}"


@pytest.mark.asyncio
async def test_owner_sections_shown_for_owner(monkeypatch):
    html = await _render_settings(monkeypatch, user_id="42")
    for marker in OWNER_CARD_MARKERS:
        assert marker in html, f"owner card should be visible to the owner: {marker}"


@pytest.mark.asyncio
async def test_owner_sections_hidden_when_unauthenticated(monkeypatch):
    html = await _render_settings(monkeypatch, user_id=None)
    for marker in OWNER_CARD_MARKERS:
        assert marker not in html, f"owner card should be hidden when signed out: {marker}"


def test_settings_route_passes_is_owner():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent.parent / "dashboard" / "routes" / "web" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert '"is_owner"' in src
    assert "can_manage_instance(request)" in src
