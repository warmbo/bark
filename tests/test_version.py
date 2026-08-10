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
