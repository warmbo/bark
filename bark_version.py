"""Runtime access to Bark's version.

The displayed version is derived from git (commit count + short SHA) so that
every change to the repo produces a distinct version on the web UI. When git
is unavailable (e.g. an sdist without VCS metadata), it falls back to the
installed package version from importlib.metadata.
"""

from __future__ import annotations

import subprocess
from importlib.metadata import version as _installed_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


def _git_version() -> str | None:
    """Return a build-version string from the git repo, or None.

    Format: ``<base>.<commit-count>-g<short-sha>`` where base is the
    pyproject.toml version — e.g. ``0.2.0.412-g3f9a2c1``. Appends ``-dirty``
    when the working tree has uncommitted changes.
    """
    try:
        count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if count.returncode == 0 and sha.returncode == 0 and count.stdout.strip():
            suffix = "-dirty" if dirty.returncode == 0 and dirty.stdout.strip() else ""
            return (
                f"{_installed_version('bark')}."
                f"{count.stdout.strip()}-g{sha.stdout.strip()}{suffix}"
            )
    except (OSError, subprocess.SubprocessError):
        pass
    return None


__version__ = _git_version() or _installed_version("bark")
