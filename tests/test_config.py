import pytest

from config import Config, ConfigurationError, _get_or_generate_secret_key


def test_public_url_drives_default_oauth_callback(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BARK_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BARK_OAUTH2_REDIRECT_URI", raising=False)

    loaded = Config.load()

    assert loaded.dashboard.host == "127.0.0.1"
    assert loaded.dashboard.public_url == "http://127.0.0.1:8090"
    assert loaded.dashboard.secure_cookies is False
    assert loaded.oauth2.redirect_uri == "http://127.0.0.1:8090/auth/callback"


def test_public_url_is_normalized_and_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_PUBLIC_URL", "https://staging.example.test/")
    monkeypatch.delenv("BARK_OAUTH2_REDIRECT_URI", raising=False)

    loaded = Config.load()

    assert loaded.dashboard.public_url == "https://staging.example.test"
    assert loaded.oauth2.redirect_uri == "https://staging.example.test/auth/callback"


def test_owner_discord_ids_are_parsed_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_OWNER_DISCORD_IDS", "123, 456,123")

    loaded = Config.load()

    assert loaded.oauth2.owner_discord_ids == {"123", "456"}


def test_secret_key_file_is_private(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("existing-key")
    key_file.chmod(0o664)

    assert _get_or_generate_secret_key(tmp_path) == "existing-key"
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_invalid_dashboard_port_fails_with_setting_name(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_DASHBOARD_PORT", "not-a-port")

    with pytest.raises(ConfigurationError, match="BARK_DASHBOARD_PORT"):
        Config.load()


def test_startup_validation_requires_bot_token(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_BOT_TOKEN", "")
    monkeypatch.chdir(tmp_path)

    loaded = Config.load()

    with pytest.raises(ConfigurationError, match="BARK_BOT_TOKEN"):
        loaded.validate_startup()


def test_startup_validation_allows_oauth_to_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_BOT_TOKEN", "configured-token")
    monkeypatch.delenv("BARK_OAUTH2_CLIENT_ID", raising=False)
    monkeypatch.delenv("BARK_OAUTH2_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BARK_OAUTH2_REDIRECT_URI", raising=False)

    loaded = Config.load()

    loaded.validate_startup()


def test_startup_validation_rejects_public_dashboard_without_oauth(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BARK_BOT_TOKEN", "configured-token")
    monkeypatch.setenv("BARK_DASHBOARD_HOST", "0.0.0.0")
    monkeypatch.delenv("BARK_OAUTH2_CLIENT_ID", raising=False)
    monkeypatch.delenv("BARK_OAUTH2_CLIENT_SECRET", raising=False)

    loaded = Config.load()

    with pytest.raises(ConfigurationError, match="OAuth"):
        loaded.validate_startup()
