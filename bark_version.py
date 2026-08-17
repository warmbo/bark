"""Runtime access to Bark's version.

The displayed version is X.X.X style, derived from the base version in
pyproject.toml plus the git commit count as the patch component — so every
change to the repo produces a distinct, monotonic version on the web UI
(e.g. ``0.3.0`` -> ``0.3.1`` -> ``0.3.2`` ...). When git is
unavailable (e.g. an sdist without VCS metadata), it falls back to the
installed package version from importlib.metadata.
"""

from __future__ import annotations

import subprocess
from importlib.metadata import version as _installed_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


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
    """X.X.X version: base from installed metadata, patch = commit count."""
    base = _installed_version("bark")
    commit_count = _git_commit_count()
    if commit_count is None:
        return base
    parts = base.split(".")
    major_minor = ".".join(parts[:2]) if len(parts) >= 2 else base
    return f"{major_minor}.{commit_count}"


__version__ = _derive_version()
