"""Diagnostics report tests: content, secret redaction, and the text render."""

from __future__ import annotations

from services.diagnostics import build_diagnostics_report, render_report


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
