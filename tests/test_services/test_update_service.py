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
    # Test repos use `origin` as the update remote with `main` as the
    # stable branch (mirrors the production GitHub layout).
    monkeypatch.setattr(update_service.config.instance, "update_remote", "origin")
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "main")
    # These are git-only fixtures — no database. Neutralize the pre-update
    # backup so apply tests exercise the git mechanics; dedicated tests
    # override it to assert backup behavior.
    monkeypatch.setattr(
        update_service,
        "_pre_update_backup",
        lambda: {"filename": "bark-backup-test.db", "size": 0, "created_at": "now"},
    )
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
    # Release date = the remote HEAD's committer date (ISO-8601), non-empty.
    assert status["available_date"] != ""
    expected_date = _git(work, "log", "-1", "--format=%cI", "origin/main").stdout.strip()
    assert status["available_date"] == expected_date


def test_check_update_no_update_when_in_sync(repo):
    work, _ = repo
    status = update_service.check_update("main")
    assert status["update_available"] is False


def test_resolve_remote_falls_back_to_origin(repo, monkeypatch):
    """A fresh one-line install clones GitHub as `origin`, not `github`. The
    configured update_remote ('github') doesn't exist, so updates must fall
    back to origin instead of failing with 'could not find branch'."""
    monkeypatch.setattr(update_service.config.instance, "update_remote", "github")
    # 'github' remote does not exist in the test repo — _resolve_remote must
    # fall through to origin and find main there.
    resolved = update_service._resolve_remote("main")
    assert resolved == "origin"

    # A branch that exists nowhere still resolves to None (keeps the
    # "could not find branch ... on remote" error path working).
    assert update_service._resolve_remote("nonexistent-branch") is None


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


def test_stable_channel_resolves_github_main(tmp_path, monkeypatch):
    """The stable channel resolves ``main`` on the GitHub remote (default
    update remote), which is the source of truth for updates."""
    github = tmp_path / "github.git"
    _git(tmp_path, "init", "--bare", str(github))

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@bark")
    _git(work, "config", "user.name", "Test")
    (work / "version.txt").write_text("one")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v1")
    _git(work, "remote", "add", "github", str(github))
    _git(work, "push", "github", "HEAD:main")
    _git(work, "push", "github", "HEAD:dev")

    monkeypatch.setattr(update_service.config.instance, "repo_dir", str(work))
    monkeypatch.setattr(update_service.config.instance, "update_remote", "github")
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "main")

    status = update_service.check_update("main")
    assert status["error"] == ""
    assert status["branch"] == "main"
    assert status["available_commit"] == _git(work, "rev-parse", "HEAD").stdout.strip()
    assert status["update_available"] is False  # in sync with github/main

    dev_status = update_service.check_update("dev")
    assert dev_status["branch"] == "dev"
    assert dev_status["update_available"] is False


def test_apply_update_refuses_dev_channel_crossing_to_stable(repo):
    """A Dev-channel instance must NOT update from main/stable — even when
    that branch carries a higher version number (the reported bug)."""
    work, _ = repo
    _git(work, "config", "bark.update.channel", "dev")
    head_before = _git(work, "rev-parse", "HEAD").stdout.strip()

    result = update_service.apply_update("main")

    assert result["ok"] is False
    assert "not allowed" in result["error"]
    # The checkout must be untouched.
    assert _git(work, "rev-parse", "HEAD").stdout.strip() == head_before
    # The persisted channel is still dev.
    assert update_service.get_channel() == "dev"


def test_apply_update_same_channel_dev_allowed(repo):
    """A Dev-channel instance can still update from the dev branch."""
    work, _ = repo
    _git(work, "config", "bark.update.channel", "dev")
    # create a dev branch on origin that is ahead of the checkout
    _git(work, "checkout", "-b", "dev")
    (work / "version.txt").write_text("dev-two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "dev v2")
    _git(work, "push", "-u", "origin", "dev")
    _git(work, "reset", "--hard", "HEAD~1")

    result = update_service.apply_update("dev")
    assert result["ok"] is True
    assert (work / "version.txt").read_text() == "dev-two"


def test_apply_update_stable_can_switch_to_dev(repo):
    """Stable → Dev remains an explicit one-way switch (not blocked)."""
    work, _ = repo
    _git(work, "config", "bark.update.channel", "stable")
    result = update_service.apply_update("dev")
    # There is no origin/dev in this fixture, so the failure must be a
    # fetch/branch error — NOT the channel-enforcement error.
    assert result["ok"] is False
    assert "not allowed" not in result["error"]


def test_apply_update_creates_pre_update_backup(repo, monkeypatch):
    """Every real update snapshots the database first and reports it."""
    work, _ = repo
    calls = []
    monkeypatch.setattr(
        update_service,
        "_pre_update_backup",
        lambda: calls.append(1) or {"filename": "bark-backup-20260810-000000-000000.db", "size": 42, "created_at": "now"},
    )

    (work / "version.txt").write_text("two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v2")
    _git(work, "push", "origin", "main")
    _git(work, "reset", "--hard", "HEAD~1")

    result = update_service.apply_update("main")
    assert result["ok"] is True
    assert len(calls) == 1
    assert result["backup"]["filename"] == "bark-backup-20260810-000000-000000.db"


def test_apply_update_blocks_when_pre_update_backup_fails(repo, monkeypatch):
    """A failed pre-update backup aborts the update — no partial state."""
    work, _ = repo
    monkeypatch.setattr(
        update_service, "_pre_update_backup", lambda: (_ for _ in ()).throw(RuntimeError("disk full"))
    )
    head_before = _git(work, "rev-parse", "HEAD").stdout.strip()

    (work / "version.txt").write_text("two")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "v2")
    _git(work, "push", "origin", "main")
    _git(work, "reset", "--hard", "HEAD~1")

    result = update_service.apply_update("main")
    assert result["ok"] is False
    assert "backup failed" in result["error"]
    assert _git(work, "rev-parse", "HEAD").stdout.strip() == head_before


def test_check_update_defaults_to_persisted_channel(repo, monkeypatch):
    """With no branch argument the check tracks the instance's own channel."""
    monkeypatch.setattr(update_service, "get_channel", lambda: "dev")
    status = update_service.check_update()
    assert status["branch"] == "dev"
    assert status["channel"] == "dev"


def test_apply_update_streams_terminal_log(repo):
    """apply_update mirrors its commands + outcome into the live log."""
    update_service.clear_update_log()
    result = update_service.apply_update("main")  # in-sync fixture
    assert result["ok"] is True

    log = update_service.get_update_log(0)
    lines = [e["line"] for e in log["entries"]]
    assert any(line.startswith("Updating Bark from the 'stable' channel") for line in lines)
    assert any(line.startswith("$ git fetch") for line in lines)
    assert any("Already up to date" in line for line in lines)
    assert log["last"] == len(log["entries"])
    # Progress phases exposed for the modal
    assert log["phases"] == ["fetch", "backup", "reset", "deps", "restart"]
    assert log["phase"] == "fetch"  # fetch ran before the already-up-to-date exit

    # after=<last> returns nothing new; clearing empties the log.
    assert update_service.get_update_log(log["last"])["entries"] == []
    update_service.clear_update_log()
    assert update_service.get_update_log(0)["entries"] == []


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


def test_channel_to_branch_falls_back_to_main_when_no_default(repo, monkeypatch):
    work, _ = repo
    monkeypatch.setattr(update_service.config.instance, "stable_branch", "")
    _git(work, "remote", "set-head", "origin", "--delete")
    assert update_service.channel_to_branch("main") == "main"


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


def test_check_update_no_update_when_remote_behind(repo):
    """A remote that has fallen behind the checkout (stale mirror) must not
    be reported as an available update — no downgrades."""
    work, _ = repo
    # Advance the local checkout WITHOUT pushing (simulates the instance
    # being ahead of a stale remote).
    (work / "version.txt").write_text("newer")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "local ahead of remote")
    current = _git(work, "rev-parse", "HEAD").stdout.strip()

    status = update_service.check_update("main")
    assert status["current_commit"] == current
    assert status["available_commit"] != current  # remote is stale/behind
    assert status["update_available"] is False  # guard suppressed it
    assert status["error"] == ""


def test_apply_update_refuses_downgrade_when_remote_behind(repo):
    """apply_update must refuse to reset backwards to a stale remote."""
    work, _ = repo
    (work / "version.txt").write_text("newer")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "local ahead of remote")
    current = _git(work, "rev-parse", "HEAD").stdout.strip()

    result = update_service.apply_update("main")
    assert result["ok"] is False
    assert "behind this instance" in result["error"]
    # Working tree untouched.
    assert _git(work, "rev-parse", "HEAD").stdout.strip() == current
    assert (work / "version.txt").read_text() == "newer"
