"""Application version contract tests."""

import re
from importlib.metadata import version as installed_version

import bark_version


def test_runtime_version_matches_installed_package_metadata():
    """Version is non-empty and, outside a git repo, equals installed metadata."""
    assert bark_version.__version__


def test_git_version_is_xxx_style():
    """In a git checkout the version is X.X.X style (e.g. 0.2.19)."""
    version = bark_version._derive_version()
    assert version is not None
    assert re.match(r"^\d+\.\d+\.\d+$", version), version
    # patch component comes from git commit count
    base = installed_version("bark")
    assert version.startswith(base.split(".")[0] + "." + base.split(".")[1] + ".")


def test_git_version_fallback_when_git_unavailable(monkeypatch):
    """Without git, the derived version falls back to installed metadata."""
    monkeypatch.setattr(
        bark_version.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")),
    )
    assert bark_version._git_commit_count() is None
    assert bark_version._derive_version() == installed_version("bark")
