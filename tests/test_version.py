"""Application version contract tests."""

import re

import bark_version


def test_runtime_version_is_non_empty():
    """Version is always present (derived, or installed metadata)."""
    assert bark_version.__version__


def test_version_is_xxx_style():
    """Version is X.X.X style (e.g. 0.2.166)."""
    version = bark_version._derive_version()
    assert version is not None
    assert re.match(r"^\d+\.\d+\.\d+$", version), version


def test_version_grows_with_commit_count(monkeypatch):
    """In a git checkout the patch component is the commit count, so the
    version changes with every commit (0.2.0 -> 0.2.1 -> ... -> 0.2.166)."""
    monkeypatch.setattr(bark_version, "_installed_version", lambda name: "0.2.0")
    monkeypatch.setattr(bark_version, "_git_commit_count", lambda: 166)
    assert bark_version._derive_version() == "0.2.166"


def test_version_fallback_when_git_unavailable(monkeypatch):
    """Without git, the derived version falls back to installed metadata."""
    from importlib.metadata import version as installed_version

    monkeypatch.setattr(bark_version, "_git_commit_count", lambda: None)
    assert bark_version._derive_version() == installed_version("bark")


def test_git_commit_count_retries_a_transient_failure(monkeypatch):
    """The first git call after a container boot can fail transiently. One
    failure must not silently degrade the version to the pyproject base."""
    from types import SimpleNamespace

    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(returncode=128, stdout="", stderr="fatal: boom")
        return SimpleNamespace(returncode=0, stdout="443\n", stderr="")

    monkeypatch.setattr(bark_version.subprocess, "run", flaky)
    monkeypatch.setattr(bark_version.time, "sleep", lambda _seconds: None)

    assert bark_version._git_commit_count() == 443
    assert len(calls) == 2


def test_git_commit_count_gives_up_and_reports_after_retries(monkeypatch, caplog):
    """Persistent failure still falls back — but loudly, so a wrong version in
    the UI is diagnosable instead of silent."""
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        raise OSError("Resource temporarily unavailable")

    monkeypatch.setattr(bark_version.subprocess, "run", always_fail)
    monkeypatch.setattr(bark_version.time, "sleep", lambda _seconds: None)

    with caplog.at_level("WARNING", logger="bark.version"):
        assert bark_version._git_commit_count() is None

    assert len(calls) == bark_version._GIT_ATTEMPTS
    assert "git commit count" in caplog.text
