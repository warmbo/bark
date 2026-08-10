"""Application version contract tests."""

import re

import bark_version


def test_runtime_version_is_non_empty():
    """Version is always present (VERSION file, or installed metadata)."""
    assert bark_version.__version__


def test_version_is_xxx_style():
    """Version is X.X.X style (e.g. 0.2.158) from the VERSION file."""
    version = bark_version._derive_version()
    assert version is not None
    assert re.match(r"^\d+\.\d+\.\d+$", version), version


def test_version_fallback_when_version_file_missing(monkeypatch):
    """Without a VERSION file, the version falls back to installed metadata."""
    monkeypatch.setattr(
        bark_version,
        "_read_version_file",
        lambda: None,
    )
    from importlib.metadata import version as installed_version

    assert bark_version._derive_version() == installed_version("bark")
