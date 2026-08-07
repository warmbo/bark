"""Self-update support: pull the latest build from the git remote.

The instance is expected to be a git checkout (production and dev both are).
``apply_update`` resets the working tree to ``origin/<branch>``, installs any
new dependencies, then exits the process — the systemd unit has
``Restart=always``, so the service comes back up on the new build.

Security: updates are gated behind instance-owner auth in the API layer, and
git only ever fetches from the configured remotes — no arbitrary URLs are
accepted. The branch is resolved across remotes (e.g. GitHub's ``main`` when
the primary remote only tracks ``master``/``dev``).
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


def _git_remotes() -> list[str]:
    """Return configured git remote names (empty when not a checkout)."""
    result = _run(["git", "remote"])
    return result.stdout.split() if result.returncode == 0 else []


def _remote_has_branch(remote: str, branch: str) -> bool:
    """Return whether ``remote/<branch>`` exists locally (after a fetch)."""
    result = _run(["git", "rev-parse", "--verify", "--quiet", f"{remote}/{branch}"])
    return result.returncode == 0


def _fetch_remote_branch(remote: str, branch: str) -> bool:
    """Fetch ``<remote> <branch>``; return True on success."""
    result = _run(["git", "fetch", remote, branch], timeout=120)
    return result.returncode == 0


def _resolve_remote(branch: str) -> str | None:
    """Pick the remote that carries ``branch``.

    Prefers the configured ``update_remote`` (default ``origin``), then falls
    back to other remotes (e.g. GitHub's ``main`` when Forgejo only has
    ``master``/``dev``). Returns the first remote where the fetch succeeded
    and the branch ref exists, or ``None``.
    """
    remotes = _git_remotes()
    if not remotes:
        return None
    preferred = config.instance.update_remote
    ordered = [preferred] + [r for r in remotes if r != preferred]
    for remote in ordered:
        if _fetch_remote_branch(remote, branch) and _remote_has_branch(remote, branch):
            return remote
    return None


def _remote_commit(remote: str, branch: str) -> str:
    result = _run(["git", "rev-parse", f"{remote}/{branch}"])
    return result.stdout.strip() if result.returncode == 0 else ""


def check_update(branch: str | None = None) -> dict:
    """Fetch the branch and compare with the running build."""
    branch = branch or config.instance.update_branch
    current = current_commit()
    available = ""
    error = ""
    try:
        remote = _resolve_remote(branch)
        if remote is not None:
            available = _remote_commit(remote, branch)
        else:
            error = f"could not find branch '{branch}' on any git remote"
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
    """Pull ``<remote>/<branch>`` into the checkout.

    Returns before the caller exits the process; systemd restarts the unit.
    """
    old_commit = current_commit()
    try:
        remote = _resolve_remote(branch)
        if remote is None:
            return {"ok": False, "error": f"could not find branch '{branch}' on any git remote"}
        available = _remote_commit(remote, branch)
    except Exception as exc:
        logger.exception("Update fetch failed")
        return {"ok": False, "error": f"fetch failed: {exc}"}
    if not available:
        return {"ok": False, "error": f"could not resolve {remote}/{branch}"}
    if available == old_commit:
        return {"ok": True, "restarted": False, "message": "already up to date"}

    try:
        _run(["git", "reset", "--hard", f"{remote}/{branch}"], timeout=120, check=True)
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
