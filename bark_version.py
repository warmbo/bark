"""Runtime access to Bark's version.

The version is read from the ``VERSION`` file at the repository root — a
release version number (e.g. ``0.2.158``) that the update system compares
and displays. When the repository is a git checkout, the displayed version
carries a PEP 440 local suffix with the commit count (e.g.
``0.2.158+162``) so the version visibly changes with every commit, even
between releases. When git is unavailable (e.g. an sdist without VCS
metadata), it falls back to the installed package version.
"""

from __future__ import annotations

import subprocess
from importlib.metadata import version as _installed_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


def _read_version_file() -> str | None:
    try:
        value = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return value or None
    except (OSError, UnicodeDecodeError):
        return None


def _git_commit_count() -> int | None:
    """Return the number of commits on the current branch, or None."""
    try:
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if count.returncode == 0 and count.stdout.strip():
            return int(count.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _derive_version() -> str:
    """Release version (VERSION file), plus a per-commit build suffix."""
    base = _read_version_file() or _installed_version("bark")
    commit_count = _git_commit_count()
    if commit_count is None:
        return base
    return f"{base}+{commit_count}"


__version__ = _derive_version()
