"""Application version contract tests."""

import re

import bark_version


def test_runtime_version_is_non_empty():
    """Version is always present (VERSION file, or installed metadata)."""
    assert bark_version.__version__


def test_version_is_xxx_style():
    """Version is X.X.X style, optionally with a +build suffix (e.g. 0.2.158+162)."""
    version = bark_version._derive_version()
    assert version is not None
    assert re.match(r"^\d+\.\d+\.\d+(\+\d+)?$", version), version


def test_version_grows_with_commit_count(monkeypatch):
    """In a git checkout the version carries a +commit-count suffix so it
    changes with every commit, even between releases."""
    monkeypatch.setattr(bark_version, "_read_version_file", lambda: "0.2.158")
    monkeypatch.setattr(bark_version, "_git_commit_count", lambda: 162)
    assert bark_version._derive_version() == "0.2.158+162"


def test_version_fallback_when_version_file_missing(monkeypatch):
    """Without a VERSION file or git, the version falls back to installed metadata."""
    from importlib.metadata import version as installed_version

    monkeypatch.setattr(bark_version, "_read_version_file", lambda: None)
    monkeypatch.setattr(bark_version, "_git_commit_count", lambda: None)
    assert bark_version._derive_version() == installed_version("bark")
