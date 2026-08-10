"""Runtime access to Bark's version.

The version is read from the ``VERSION`` file at the repository root — a
release version number (e.g. ``0.2.158``) that updates compare and display
instead of raw git build identifiers. When the file is missing (e.g. an sdist
without VCS metadata), fall back to the installed package version.
"""

from __future__ import annotations

from importlib.metadata import version as _installed_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


def _read_version_file() -> str | None:
    try:
        value = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return value or None
    except (OSError, UnicodeDecodeError):
        return None


def _derive_version() -> str:
    """VERSION file first; installed package metadata as the fallback."""
    return _read_version_file() or _installed_version("bark")


__version__ = _derive_version()
