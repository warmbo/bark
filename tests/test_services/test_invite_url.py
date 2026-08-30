"""Regression: the generic /invite link must not send contradictory params.

Live report (2026-08-29): Viru (a phone-verified Discord account, server owner)
could not install Bark via the invite link. Root cause: build_bot_invite_url()
always added ``guild_id=<empty>`` AND ``disable_guild_select=true`` for the
generic /invite link. Discord interprets disable_guild_select as "skip the
server picker" but with no guild_id to target, so the install had no way to
choose a server and failed. The generic link must omit disable_guild_select so
Discord shows the server picker.
"""

from services.dashboard_access import build_bot_invite_url


def test_generic_invite_omits_guild_select_disable():
    url = build_bot_invite_url("123", "")
    assert "guild_id=" not in url
    assert "disable_guild_select" not in url
    assert "client_id=123" in url
    assert "scope=bot+applications.commands" in url
    assert "permissions=8" in url


def test_guild_targeted_invite_keeps_guildelect_disable():
    url = build_bot_invite_url("123", "456")
    assert "guild_id=456" in url
    assert "disable_guild_select=true" in url


def test_no_client_id_returns_empty():
    assert build_bot_invite_url("", "456") == ""
