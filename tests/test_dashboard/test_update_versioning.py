"""Unit tests for version-based update comparison (VERSION file contract)."""

from __future__ import annotations

import services.update_service as update_service


def test_version_key_parses_semver():
    assert update_service._version_key("0.2.158") == (0, 2, 158)
    assert update_service._version_key("v1.2.3") == (1, 2, 3)
    assert update_service._version_key("0.2.158-dev") == (0, 2, 158)
    assert update_service._version_key("0.2") == (0, 2, 0)
    assert update_service._version_key("garbage") == (0, 0, 0)


def test_version_comparison_orders_releases():
    assert update_service._version_key("0.2.160") > update_service._version_key("0.2.158")
    assert update_service._version_key("1.0.0") > update_service._version_key("0.9.999")
    assert update_service._version_key("0.2.158") == update_service._version_key("0.2.158")


def test_remote_version_reads_version_file_without_checkout(monkeypatch):
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "0.2.160\n"})()

    monkeypatch.setattr(update_service, "_run", fake_run)
    assert update_service.remote_version("github", "main") == "0.2.160"
    assert captured == [["git", "show", "github/main:VERSION"]]


def test_remote_version_missing_file_returns_empty(monkeypatch):
    def fake_run(cmd, **kwargs):
        return type("R", (), {"returncode": 128, "stdout": ""})()

    monkeypatch.setattr(update_service, "_run", fake_run)
    assert update_service.remote_version("github", "main") == ""


def test_check_update_offers_by_version_not_commit(monkeypatch):
    """A remote with a NEWER VERSION but the SAME commit shape still offers an
    update — availability is decided by version number, not build identity."""
    state = {"current": "abc123"}

    def fake_run(cmd, **kwargs):
        name = " ".join(cmd)
        if name == "git rev-parse HEAD":
            return type("R", (), {"returncode": 0, "stdout": state["current"]})()
        if name.startswith("git fetch"):
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name.startswith("git rev-parse --verify"):
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name == "git rev-parse github/main":
            return type("R", (), {"returncode": 0, "stdout": state["current"]})()
        if name == "git show github/main:VERSION":
            return type("R", (), {"returncode": 0, "stdout": "0.2.160\n"})()
        if name == "git merge-base --is-ancestor github/main abc123":
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name.startswith("git remote get-url"):
            return type("R", (), {"returncode": 0, "stdout": "https://github.com/warmbo/bark.git"})()
        if name == "git branch --show-current":
            return type("R", (), {"returncode": 0, "stdout": "main"})()
        if name == "git config --get bark.update.channel":
            return type("R", (), {"returncode": 1, "stdout": ""})()
        return type("R", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr(update_service, "_run", fake_run)
    monkeypatch.setattr(update_service, "local_version", lambda: "0.2.158")

    result = update_service.check_update("main")
    assert result["update_available"] is True
    assert result["current_version"] == "0.2.158"
    assert result["available_version"] == "0.2.160"
    assert result["repo_url"] == "https://github.com/warmbo/bark"


def test_check_update_no_downgrade_by_version(monkeypatch):
    """A remote with an OLDER version never offers an update."""
    def fake_run(cmd, **kwargs):
        name = " ".join(cmd)
        if name == "git rev-parse HEAD":
            return type("R", (), {"returncode": 0, "stdout": "def456"})()
        if name.startswith("git fetch"):
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name.startswith("git rev-parse --verify"):
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name == "git rev-parse github/main":
            return type("R", (), {"returncode": 0, "stdout": "old789"})()
        if name == "git show github/main:VERSION":
            return type("R", (), {"returncode": 0, "stdout": "0.2.100\n"})()
        if name == "git merge-base --is-ancestor old789 def456":
            return type("R", (), {"returncode": 0, "stdout": ""})()
        if name.startswith("git remote get-url"):
            return type("R", (), {"returncode": 0, "stdout": "https://github.com/warmbo/bark.git"})()
        if name == "git branch --show-current":
            return type("R", (), {"returncode": 0, "stdout": "main"})()
        if name == "git config --get bark.update.channel":
            return type("R", (), {"returncode": 1, "stdout": ""})()
        return type("R", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr(update_service, "_run", fake_run)
    monkeypatch.setattr(update_service, "local_version", lambda: "0.2.158")

    result = update_service.check_update("main")
    assert result["update_available"] is False
