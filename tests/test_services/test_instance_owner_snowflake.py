"""Regression: an instance owner must not be gated by a snowflake type mismatch.

Live report (2026-08-27): Richard, the owner of a Bark instance
(``bark.richard.works``), had his Discord ID correctly set in
``BARK_OWNER_DISCORD_IDS`` but clicking "Update & Restart" returned 403
("You do not have permission to perform this action"). Discord snowflakes
are large integers that some session/proxy layers deserialize as ``int``,
while ``owner_discord_ids`` is parsed from the env as a set of ``str``.
``can_manage_instance`` compared ``user["id"]`` (int) directly to the str set,
so a real owner failed the gate. The fix normalizes both sides to str.
"""

from types import SimpleNamespace

from services.instance_auth import can_manage_instance


def test_can_manage_instance_owner_with_int_session_id(monkeypatch):
    """An owner id stored as int in the session is still recognized as owner."""
    import config

    # Owner ids are parsed from env as strings.
    monkeypatch.setattr(
        config.config.oauth2, "owner_discord_ids", {"234383655651377153", "140283014562214336"}
    )
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    # Session user id arrives as an int (snowflake coerced by a proxy/session layer).
    request = SimpleNamespace(session={"user": {"id": 234383655651377153}})
    assert can_manage_instance(request) is True


def test_can_manage_instance_owner_with_string_session_id(monkeypatch):
    """A string owner id (the normal case) still matches."""
    import config

    monkeypatch.setattr(
        config.config.oauth2, "owner_discord_ids", {"234383655651377153", "140283014562214336"}
    )
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    request = SimpleNamespace(session={"user": {"id": "234383655651377153"}})
    assert can_manage_instance(request) is True


def test_can_manage_instance_denies_non_owner(monkeypatch):
    """A user not in owner ids is denied regardless of type."""
    import config

    monkeypatch.setattr(config.config.oauth2, "owner_discord_ids", {"234383655651377153"})
    monkeypatch.setattr(config.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(config.config.oauth2, "redirect_uri", "http://test/auth/callback")

    request = SimpleNamespace(session={"user": {"id": "999999"}})
    assert can_manage_instance(request) is False


def test_resolve_dashboard_role_owner_with_int_id(monkeypatch):
    """resolve_dashboard_role recognizes an int snowflake as owner too."""
    from services.dashboard_access import resolve_dashboard_role

    assert (
        resolve_dashboard_role(
            234383655651377153,
            {"234383655651377153", "140283014562214336"},
            "admin",
            None,
        )
        == "owner"
    )
