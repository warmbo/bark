from config import Config, _get_or_generate_secret_key


def test_public_url_drives_default_oauth_callback(monkeypatch, tmp_path):
    monkeypatch.setenv("BARK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BARK_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BARK_OAUTH2_REDIRECT_URI", raising=False)

    loaded = Config.load()

    assert loaded.dashboard.public_url == "https://bark.warx.org"
    assert loaded.dashboard.secure_cookies is True
    assert loaded.oauth2.redirect_uri == "https://bark.warx.org/auth/callback"


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
