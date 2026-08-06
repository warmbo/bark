"""Self-update support: pull the latest build from the git remote.

The instance is expected to be a git checkout (production and dev both are).
``apply_update`` resets the working tree to ``origin/<branch>``, installs any
new dependencies, then exits the process — the systemd unit has
``Restart=always``, so the service comes back up on the new build.

Security: updates are gated behind instance-owner auth in the API layer, and
git only ever fetches from the configured ``origin`` remote — no arbitrary
URLs are accepted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from config import config

logger = logging.getLogger("bark.update")


def repo_root() -> Path:
    """The instance's git checkout root (config override or auto-detected)."""
    if config.instance.repo_dir:
        return Path(config.instance.repo_dir).expanduser().resolve()
    # This file lives at <repo>/services/update_service.py
    return Path(__file__).resolve().parents[1]


def _run(
    cmd: list[str], *, timeout: int = 60, check: bool = False
) -> subprocess.CompletedProcess[str]:
    logger.debug("git: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=repo_root(),
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr[-500:]}"
        )
    return result


def current_commit() -> str:
    result = _run(["git", "rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def current_branch() -> str:
    result = _run(["git", "branch", "--show-current"])
    return result.stdout.strip() if result.returncode == 0 else ""


def _origin_commit(branch: str) -> str:
    result = _run(["git", "rev-parse", f"origin/{branch}"])
    return result.stdout.strip() if result.returncode == 0 else ""


def check_update(branch: str | None = None) -> dict:
    """Fetch the branch and compare with the running build."""
    branch = branch or config.instance.update_branch
    current = current_commit()
    available = ""
    error = ""
    try:
        _run(["git", "fetch", "origin", branch], timeout=120, check=True)
        available = _origin_commit(branch)
    except Exception as exc:  # network down / not a checkout
        logger.warning("Update check failed: %s", exc)
        error = str(exc)
    return {
        "branch": branch,
        "current_commit": current,
        "current_branch": current_branch(),
        "available_commit": available,
        "update_available": bool(available) and available != current,
        "repo_dir": str(repo_root()),
        "error": error,
    }


def _requirements_changed(old_commit: str) -> bool:
    result = _run(["git", "diff", "--name-only", old_commit, "HEAD"])
    changed = set(result.stdout.splitlines())
    return bool(changed & {"requirements.txt", "pyproject.toml"})


def apply_update(branch: str) -> dict:
    """Pull ``origin/<branch>`` into the checkout.

    Returns before the caller exits the process; systemd restarts the unit.
    """
    old_commit = current_commit()
    try:
        _run(["git", "fetch", "origin", branch], timeout=120, check=True)
        available = _origin_commit(branch)
    except Exception as exc:
        logger.exception("Update fetch failed")
        return {"ok": False, "error": f"fetch failed: {exc}"}
    if not available:
        return {"ok": False, "error": f"could not resolve origin/{branch}"}
    if available == old_commit:
        return {"ok": True, "restarted": False, "message": "already up to date"}

    try:
        _run(["git", "reset", "--hard", f"origin/{branch}"], timeout=120, check=True)
    except Exception as exc:
        logger.exception("Update reset failed")
        return {"ok": False, "error": f"reset failed: {exc}"}

    new_commit = current_commit()

    # Install any new dependencies before restarting.
    if _requirements_changed(old_commit):
        pip = str(repo_root() / ".venv" / "bin" / "pip")
        if Path(pip).exists():
            try:
                _run([pip, "install", "-r", "requirements.txt"], timeout=600, check=True)
            except Exception as exc:
                logger.warning("pip install failed after update: %s", exc)

    logger.info("Update applied: %s -> %s (%s)", old_commit, new_commit, branch)
    return {
        "ok": True,
        "restarted": True,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "branch": branch,
    }


async def apply_update_async(branch: str) -> dict:
    """Run the update in a worker thread, then exit so systemd restarts us."""
    await asyncio.sleep(1.5)  # let the HTTP response flush first
    result = await asyncio.to_thread(apply_update, branch)
    if result.get("restarted"):
        logger.info("Exiting process for restart (pid %s)", os.getpid())
        os._exit(0)
    if not result.get("ok"):
        logger.error("Update did not apply; staying on current build: %s", result)
    return result
