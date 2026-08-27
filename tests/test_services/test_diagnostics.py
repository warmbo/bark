"""Diagnostics report tests: content, secret redaction, and the text render."""

from __future__ import annotations

from services.diagnostics import (
    _bot_app_id,
    _database_path,
    build_diagnostics_report,
    render_report,
)


def test_report_contains_expected_sections():
    report = build_diagnostics_report()
    assert set(report.keys()) >= {
        "bark",
        "environment",
        "config",
        "git",
        "intents",
        "update",
        "logs",
    }
    assert report["bark"]["version"]
    assert report["bark"]["commit"]
    assert report["environment"]["install_dir"]
    assert report["environment"]["install_method"]
    assert isinstance(report["environment"]["tmp_writable"], bool)
    # Bark requests the three privileged intents whose absence causes 4014.
    assert report["intents"]["message_content"] is True
    assert report["intents"]["server_members"] is True
    assert report["intents"]["presence"] is True
    # The resolved log path is surfaced (was previously hardcoded to bark.log).
    assert report["logs"]["log_path"]


def test_bot_app_id_decodes_from_token(monkeypatch):
    import base64

    import config as config_module

    app_id = 987654321
    first = base64.urlsafe_b64encode(str(app_id).encode()).decode().rstrip("=")
    monkeypatch.setattr(config_module.config.bot, "token", f"{first}.timestamp.sig")
    assert _bot_app_id() == str(app_id)


def test_bot_app_id_no_token(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "token", "")
    assert _bot_app_id() == "(no token set)"


def test_database_path_resolves_relative_sqlite(monkeypatch, tmp_path):
    import config as config_module

    monkeypatch.setattr(config_module.config.database, "url", "sqlite+aiosqlite:///bark.db")
    monkeypatch.setattr(config_module.config, "data_dir", tmp_path)
    assert _database_path() == str(tmp_path / "bark.db")


def test_report_never_leaks_secrets(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "token", "SUPERSECRETTOKEN")
    monkeypatch.setattr(config_module.config.oauth2, "client_secret", "SUPERSECRETCLIENT")
    monkeypatch.setattr(config_module.config.dashboard, "secret_key", "SUPERSECRETKEY")

    text = render_report(build_diagnostics_report())
    for secret in ("SUPERSECRETTOKEN", "SUPERSECRETCLIENT", "SUPERSECRETKEY"):
        assert secret not in text, f"secret leaked into the report: {secret}"


def test_render_report_plaintext_shape():
    report = {
        "bark": {
            "version": "0.2.1",
            "commit": "abc",
            "branch": "main",
            "update_channel": "stable",
        },
        "environment": {
            "platform": "Linux-5.15-x86_64",
            "machine": "x86_64",
            "python_version": "3.13",
            "hostname": "host",
            "install_dir": "/x",
            "install_method": "manual (python app.py)",
            "systemd_active": False,
            "tmp_writable": True,
            "disk_free_bytes": 1024,
            "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "False"},
        "intents": {"message_content": True},
        "git": {
            "update_remote": "github",
            "stable_branch": "main",
            "remotes": [],
            "refs": {"github/main": False, "origin/main": True},
        },
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"bark_log_tail": []},
    }
    text = render_report(report)
    assert "Bark diagnostic report" in text
    assert "[Config (redacted)]" in text
    assert "[Git remotes]" in text
    assert "[Environment / hardware]" in text
    # Missing refs are flagged loudly (the "can't find branch on remote" case).
    assert "github/main      ABSENT" in text
    assert "origin/main      present" in text


def test_report_builds_when_git_and_systemctl_are_unavailable(monkeypatch):
    """Termux / minimal installs without systemctl (or git off PATH) must not
    crash the diagnostic report — helpers degrade to '' instead of raising."""
    import services.diagnostics as d
    import services.update_service as us

    def _missing_binary(cmd, *args, **kwargs):
        raise FileNotFoundError(cmd[0] if cmd else "binary")

    monkeypatch.setattr(us, "_run", _missing_binary)

    # These helpers must not raise when the binary is absent.
    assert d._git("rev-parse", "HEAD") == ""
    assert d._systemctl(["is-active", "bark.service"]) == ""
    assert d._systemd_active() is False
    assert d._running_unit()  # falls back to a non-empty service name

    # The full report still builds and renders.
    report = build_diagnostics_report()
    assert report["bark"]["commit"]  # falls back to "unknown" or similar
    text = render_report(report)
    assert "Bark diagnostic report" in text


def test_config_warnings_flags_http_oauth_redirect(monkeypatch):
    """A report must flag an http:// OAuth redirect so login failures on a
    Termux box (http config behind an https site) are obvious."""
    import config as config_module

    import services.diagnostics as d

    monkeypatch.setattr(config_module.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config_module.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(
        config_module.config.oauth2, "redirect_uri", "http://bark.richard.works/auth/callback"
    )
    monkeypatch.setattr(
        config_module.config.dashboard, "public_url", "http://bark.richard.works"
    )
    monkeypatch.setattr(config_module.config.oauth2, "owner_discord_ids", {"1"})

    warnings = d._config_warnings()
    assert any("http://" in w and "redirect_uri" in w for w in warnings)

    report = {
        "bark": {"version": "0.2.1", "commit": "abc", "branch": "main", "update_channel": "stable"},
        "environment": {
            "platform": "Linux", "machine": "x86_64", "python_version": "3.13",
            "hostname": "host", "install_dir": "/x", "install_method": "manual",
            "systemd_active": False, "tmp_writable": True,
            "disk_free_bytes": 1024, "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "True"},
        "config_warnings": warnings,
        "intents": {"message_content": True},
        "git": {"update_remote": "github", "stable_branch": "main", "remotes": [], "refs": {}},
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"log_path": "", "bark_log_tail": []},
    }
    text = d.render_report(report)
    assert "[Config warnings]" in text
    assert "⚠" in text


