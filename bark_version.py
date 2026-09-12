"""Runtime access to Bark's version.

The displayed version is X.X.X style, derived from the base version in
pyproject.toml plus the git commit count as the patch component — so every
change to the repo produces a distinct, monotonic version on the web UI
(e.g. ``0.3.0`` -> ``0.3.1`` -> ``0.3.2`` ...). When git is
unavailable (e.g. an sdist without VCS metadata), it falls back to the
installed package version from importlib.metadata.
"""

from __future__ import annotations

import logging
import subprocess
import time
from importlib.metadata import version as _installed_version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

# The git lookup is retried: the first call after a container boot can fail
# transiently, and a failure silently degrades the version to the pyproject base
# (0.3.0) — which is what showed up in the dashboard and the startup log on the
# 2026-09-03 and 2026-09-04 boots.
_GIT_TIMEOUT_SECONDS = 5.0
_GIT_ATTEMPTS = 3

_logger = logging.getLogger("bark.version")


def _git_commit_count() -> int | None:
    """Return the number of commits on the current branch, or None."""
    last_error = ""
    for attempt in range(_GIT_ATTEMPTS):
        try:
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            if count.returncode == 0 and count.stdout.strip():
                return int(count.stdout.strip())
            last_error = (count.stderr or "").strip() or f"exit code {count.returncode}"
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < _GIT_ATTEMPTS - 1:
            time.sleep(0.5 * (attempt + 1))

    # Never fail silently: a fallback here means the UI is about to show the
    # wrong version, so say so.
    _logger.warning(
        "Could not read the git commit count from %s after %d attempt(s) (%s) — "
        "falling back to the installed package version.",
        _REPO_ROOT,
        _GIT_ATTEMPTS,
        last_error,
    )
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
