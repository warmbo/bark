"""Self-update service tests against real temporary git repos."""

from __future__ import annotations

import subprocess

import pytest

from services import update_service


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )


def _make_repo(tmp_path):
    """A bare origin + a working clone on branch main, both at commit 'v1'."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "checkout", "-b", "main")  # ensure branch name regardless of git default
    _git(work, "config", "user.email", "test@bark")
    _git(work, "config", "user.name", "Test")
    (work / "version.txt").write_text("one")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v1")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-u", "origin", "main")
    return work, origin


@pytest.fixture
def repo(tmp_path, monkeypatch):
    work, origin = _make_repo(tmp_path)
    monkeypatch.setattr(update_service.config.instance, "repo_dir", str(work))
    return work, origin


def test_current_commit_and_branch(repo):
    work, _ = repo
    assert update_service.current_commit() == _git(work, "rev-parse", "HEAD").stdout.strip()
    assert update_service.current_branch() == "main"


def test_check_update_reports_available_when_remote_ahead(repo):
    work, _ = repo
    # advance the remote
    (work / "version.txt").write_text("two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v2")
    _git(work, "push", "origin", "main")
    # rewind the checkout to v1 (simulate the running instance behind origin)
    _git(work, "reset", "--hard", "HEAD~1")

    status = update_service.check_update("main")
    assert status["current_commit"] == _git(work, "rev-parse", "HEAD").stdout.strip()
    assert status["available_commit"] == _git(work, "rev-parse", "origin/main").stdout.strip()
    assert status["update_available"] is True
    assert status["error"] == ""


def test_check_update_no_update_when_in_sync(repo):
    work, _ = repo
    status = update_service.check_update("main")
    assert status["update_available"] is False


def test_apply_update_resets_to_origin(repo):
    work, _ = repo
    old = _git(work, "rev-parse", "HEAD").stdout.strip()

    (work / "version.txt").write_text("two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v2")
    _git(work, "push", "origin", "main")
    _git(work, "reset", "--hard", "HEAD~1")  # checkout falls behind

    result = update_service.apply_update("main")
    assert result["ok"] is True
    assert result["old_commit"] == old
    new_head = _git(work, "rev-parse", "HEAD").stdout.strip()
    assert result["new_commit"] == new_head
    assert new_head == _git(work, "rev-parse", "origin/main").stdout.strip()
    assert (work / "version.txt").read_text() == "two"


def test_apply_update_already_up_to_date(repo):
    work, _ = repo
    result = update_service.apply_update("main")
    assert result["ok"] is True
    assert result["restarted"] is False
