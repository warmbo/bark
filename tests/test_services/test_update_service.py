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
    # The test repos use `main` as their stable branch (the real repos use
    # `master`); pin it so channel mapping is deterministic in tests.
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "main")
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


def test_check_update_falls_back_to_other_remote_when_branch_missing(tmp_path, monkeypatch):
    """A stable branch like GitHub's ``main`` must resolve even when the
    primary remote (Forgejo) only tracks ``master``/``dev``."""
    # Two bare remotes: origin has only master; github has main.
    origin = tmp_path / "origin.git"
    github = tmp_path / "github.git"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(tmp_path, "init", "--bare", str(github))

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@bark")
    _git(work, "config", "user.name", "Test")
    (work / "version.txt").write_text("one")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v1")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "remote", "add", "github", str(github))
    _git(work, "push", "origin", "HEAD:master")
    _git(work, "push", "github", "HEAD:main")

    monkeypatch.setattr(update_service.config.instance, "repo_dir", str(work))

    status = update_service.check_update("main")
    assert status["error"] == ""
    assert status["available_commit"] == _git(work, "rev-parse", "HEAD").stdout.strip()
    assert status["update_available"] is False  # in sync with github/main


def test_check_update_reports_error_when_branch_on_no_remote(repo, monkeypatch):
    work, _ = repo
    monkeypatch.setattr(update_service.config.instance, "repo_dir", str(work))
    # The stable channel maps to a branch that does not exist on the remote.
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "nonexistent-branch")
    status = update_service.check_update("main")
    assert status["update_available"] is False
    assert "could not find branch 'nonexistent-branch'" in status["error"]


def test_channel_to_branch_maps_stable_to_configured_stable_branch(repo):
    work, _ = repo
    assert update_service.channel_to_branch("main") == "main"
    update_service.config.instance.stable_branch = "master"
    assert update_service.channel_to_branch("main") == "master"
    assert update_service.channel_to_branch("dev") == "dev"


def test_channel_to_branch_resolves_remote_default_when_unset(repo, monkeypatch):
    work, _ = repo
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "")
    _git(work, "remote", "set-head", "origin", "main")  # origin/HEAD -> main
    assert update_service.channel_to_branch("main") == "main"


def test_channel_to_branch_falls_back_to_master_when_no_default(repo, monkeypatch):
    work, _ = repo
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "")
    _git(work, "remote", "set-head", "origin", "--delete")
    assert update_service.channel_to_branch("main") == "master"


def test_channel_persistence_roundtrip(repo):
    work, _ = repo
    assert update_service.get_channel() == "stable"  # checkout is on main
    update_service.set_channel("dev")
    assert update_service.get_channel() == "dev"
    update_service.set_channel("stable")
    assert update_service.get_channel() == "stable"


def test_get_channel_defaults_from_branch(repo):
    work, _ = repo
    assert update_service.get_channel() == "stable"  # branch main -> stable
    _git(work, "checkout", "-b", "dev")
    assert update_service.get_channel() == "dev"  # branch dev -> dev


def test_no_fallback_to_other_remotes(repo):
    """A stale branch on a secondary remote (e.g. GitHub mirror) must never
    be used when the update remote lacks the branch."""
    work, origin = repo
    # Add a 'github' remote with a stale 'main', and delete 'main' from
    # origin so the update remote has no such branch.
    github = work / "github.git"
    _git(work, "init", "--bare", str(github))
    _git(work, "remote", "add", "github", str(github))
    _git(work, "push", "github", "main")
    _git(work, "push", "origin", "--delete", "main")

    # Advance the github remote, then record the local ref — a (forbidden)
    # fetch during the update check would move it and be detectable.
    (work / "version.txt").write_text("stale-update")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "stale github main")
    _git(work, "push", "github", "main")
    stale = _git(work, "rev-parse", "refs/remotes/github/main").stdout.strip()

    status = update_service.check_update("main")
    assert status["error"] != ""
    assert status["available_commit"] == ""
    after = _git(work, "rev-parse", "refs/remotes/github/main").stdout.strip()
    assert after == stale, "github/main was fetched — fallback must not happen"


def test_apply_update_persists_channel(repo):
    work, _ = repo
    (work / "version.txt").write_text("two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v2")
    _git(work, "push", "origin", "main")
    _git(work, "reset", "--hard", "HEAD~1")

    result = update_service.apply_update("main")
    assert result["ok"] is True
    assert result["channel"] == "stable"
    assert update_service.get_channel() == "stable"
