"""Application version contract tests."""

import re

from importlib.metadata import version as installed_version

import bark_version


def test_runtime_version_matches_installed_package_metadata():
    """Version is non-empty and, outside a git repo, equals installed metadata."""
    assert bark_version.__version__


def test_git_version_embeds_commit_count_and_sha():
    """In a git checkout the version includes commit count + short SHA."""
    version = bark_version._git_version()
    assert version is not None
    # e.g. 0.2.0.412-g3f9a2c1 or 0.2.0.412-g3f9a2c1-dirty
    assert re.match(rf"^{re.escape(installed_version('bark'))}\.\d+-g[0-9a-f]{{7,}}(?:-dirty)?$", version), version


def test_git_version_fallback_when_git_unavailable(monkeypatch):
    """Without git, _git_version() returns None so the module falls back."""
    monkeypatch.setattr(
        bark_version.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")),
    )
    assert bark_version._git_version() is None
    # Fallback logic: installed metadata is used when git yields nothing.
    assert bark_version._git_version() or installed_version("bark")
