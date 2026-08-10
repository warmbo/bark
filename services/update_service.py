"""Self-update support: pull the latest build from the git remote.

The instance is expected to be a git checkout (production and dev both are).
``apply_update`` resets the working tree to ``<update_remote>/<branch>``,
installs any new dependencies, then exits the process — the systemd unit has
``Restart=always``, so the service comes back up on the new build.

Security: updates are gated behind instance-owner auth in the API layer, and
git only ever fetches from the configured ``update_remote`` (default
``github`` — GitHub's ``main`` and ``dev`` branches) — no other remotes and
no arbitrary URLs are consulted. The stable channel maps to
``config.instance.stable_branch`` (default ``main``); ``dev`` maps to
``dev``. A no-downgrade guard refuses any update whose target commit is an
ancestor of the running build, so a stale/unsynced remote can never pull an
instance backwards.

Channel rules: an instance may move from the stable channel to the dev
channel, but not back (enforced in the API layer). The current channel is
persisted in the local git config (``bark.update.channel``) so it survives
``reset --hard``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from config import config

logger = logging.getLogger("bark.update")

CHANNEL_CONFIG_KEY = "bark.update.channel"


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


def _remote_has_branch(remote: str, branch: str) -> bool:
    """Return whether ``remote/<branch>`` exists locally (after a fetch)."""
    result = _run(["git", "rev-parse", "--verify", "--quiet", f"{remote}/{branch}"])
    return result.returncode == 0


def _fetch_remote_branch(remote: str, branch: str) -> bool:
    """Fetch ``<remote> <branch>``; return True on success."""
    result = _run(["git", "fetch", remote, branch], timeout=120)
    return result.returncode == 0


def _resolve_remote(branch: str) -> str | None:
    """Fetch ``branch`` from the configured update remote.

    Only ``config.instance.update_remote`` (default ``origin``) is ever
    consulted — other remotes (e.g. a GitHub mirror with a stale ``main``)
    are never used for updates. Returns the remote name on success, else
    ``None``.
    """
    remote = config.instance.update_remote
    if not remote:
        return None
    if _fetch_remote_branch(remote, branch) and _remote_has_branch(remote, branch):
        return remote
    return None


def channel_to_branch(channel: str) -> str:
    """Map a UI channel name to the actual git branch to track.

    ``dev`` maps to the ``dev`` branch. The stable channel maps to
    ``config.instance.stable_branch`` (default ``main`` — GitHub's stable
    branch), else the remote's default branch, else ``main``.
    """
    if channel == "dev":
        return "dev"
    if config.instance.stable_branch:
        return config.instance.stable_branch
    result = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if result.returncode == 0 and result.stdout.strip():
        ref = result.stdout.strip()
        for prefix in ("origin/", "refs/remotes/"):
            if ref.startswith(prefix):
                return ref[len(prefix):]
        return ref
    return "main"


def get_channel() -> str:
    """The instance's update channel: persisted value, else a sensible default.

    ``"stable"`` or ``"dev"``. The default derives from the checked-out
    branch so a dev-branch checkout is treated as the dev channel even
    before the first update persists the value.
    """
    result = _run(["git", "config", "--get", CHANNEL_CONFIG_KEY])
    if result.returncode == 0 and result.stdout.strip() in ("stable", "dev"):
        return result.stdout.strip()
    return "dev" if current_branch() == "dev" else "stable"


def set_channel(channel: str) -> None:
    """Persist the channel in the local git config (survives resets)."""
    if channel not in ("stable", "dev"):
        raise ValueError(f"invalid channel: {channel}")
    _run(["git", "config", "--local", CHANNEL_CONFIG_KEY, channel])


def _remote_commit(remote: str, branch: str) -> str:
    result = _run(["git", "rev-parse", f"{remote}/{branch}"])
    return result.stdout.strip() if result.returncode == 0 else ""


def _version_file() -> Path:
    return repo_root() / "VERSION"


def local_version() -> str:
    """The running instance's release version (VERSION file)."""
    try:
        value = _version_file().read_text(encoding="utf-8").strip()
        return value or "0.0.0"
    except (OSError, UnicodeDecodeError):
        return "0.0.0"


def remote_version(remote: str, branch: str) -> str:
    """The remote branch's release version, read without a checkout."""
    result = _run(["git", "show", f"{remote}/{branch}:VERSION"])
    if result.returncode != 0:
        return ""
    return result.stdout.strip() or ""


def _version_key(value: str) -> tuple[int, ...]:
    """Parse X.Y.Z (with optional -suffix) into a comparable tuple."""
    core = value.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in core.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def remote_repo_url() -> str:
    """Human-facing GitHub URL for the update source."""
    result = _run(["git", "remote", "get-url", config.instance.update_remote])
    if result.returncode == 0:
        url = result.stdout.strip()
        if url.startswith("git@"):
            url = "https://" + url.replace(":", "/").lstrip("https://")[4:]
        return url.rstrip(".git")
    return "https://github.com"


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """Return True when ``ancestor`` is an ancestor of (or equal to) ``descendant``.

    Used as a no-downgrade guard: a remote that has fallen behind the local
    checkout (e.g. an unsynced mirror) must never pull the instance
    backwards.
    """
    result = _run(["git", "merge-base", "--is-ancestor", ancestor, descendant])
    return result.returncode == 0


def check_update(channel: str | None = None) -> dict:
    """Fetch the channel's branch and compare with the running build.

    ``channel`` is a UI channel name (``main``/``stable`` or ``dev``); it is
    mapped to the actual git branch via :func:`channel_to_branch`.

    Availability is decided by RELEASE VERSION (the ``VERSION`` file on the
    remote branch) rather than commit identity — an update is offered when
    the remote's version is newer than the running instance's, regardless of
    how many commits sit between them.
    """
    channel = channel or config.instance.update_branch
    branch = channel_to_branch(channel)
    current = current_commit()
    available = ""
    current_version = local_version()
    available_version = ""
    error = ""
    try:
        remote = _resolve_remote(branch)
        if remote is not None:
            available = _remote_commit(remote, branch)
            available_version = remote_version(remote, branch)
        else:
            error = f"could not find branch '{branch}' on remote '{config.instance.update_remote}'"
    except Exception as exc:  # network down / not a checkout
        logger.warning("Update check failed: %s", exc)
        error = str(exc)
    # Version comparison (the authoritative signal) with the commit-ancestor
    # check as a belt-and-braces no-downgrade guard.
    update_available = False
    if available_version and _version_key(available_version) > _version_key(current_version):
        update_available = True
    elif available and available != current and not (
        available and _is_ancestor(available, current)
    ):
        # Remote has no VERSION file yet (older build) — fall back to commit
        # comparison so pre-version releases still offer updates.
        update_available = True
    if available and available == current and available_version == current_version:
        update_available = False
    if update_available and available and _is_ancestor(available, current):
        logger.info(
            "Remote %s/%s is behind this checkout (%s); no update offered",
            config.instance.update_remote,
            branch,
            available,
        )
        update_available = False
    return {
        "channel": get_channel(),
        "branch": branch,
        "current_version": current_version,
        "available_version": available_version,
        "current_commit": current,
        "current_branch": current_branch(),
        "available_commit": available,
        "update_available": update_available,
        "repo_url": remote_repo_url(),
        "repo_dir": str(repo_root()),
        "error": error,
    }


def _requirements_changed(old_commit: str) -> bool:
    result = _run(["git", "diff", "--name-only", old_commit, "HEAD"])
    changed = set(result.stdout.splitlines())
    return bool(changed & {"requirements.txt", "pyproject.toml"})


def apply_update(channel: str) -> dict:
    """Pull the channel's branch into the checkout.

    ``channel`` is a UI channel name (``main``/``stable`` or ``dev``). The
    channel is persisted after a successful pull so the one-way
    stable → dev rule survives restarts. Returns before the caller exits
    the process; systemd restarts the unit.
    """
    old_commit = current_commit()
    branch = channel_to_branch(channel)
    channel_label = "stable" if channel != "dev" else "dev"
    try:
        remote = _resolve_remote(branch)
        if remote is None:
            return {
                "ok": False,
                "error": f"could not find branch '{branch}' on remote '{config.instance.update_remote}'",
            }
        available = _remote_commit(remote, branch)
    except Exception as exc:
        logger.exception("Update fetch failed")
        return {"ok": False, "error": f"fetch failed: {exc}"}
    if not available:
        return {"ok": False, "error": f"could not resolve {remote}/{branch}"}
    if available == old_commit:
        set_channel(channel_label)
        return {"ok": True, "restarted": False, "message": "already up to date"}
    # No-downgrade guard: refuse to reset backwards to a stale remote.
    if _is_ancestor(available, old_commit):
        logger.warning(
            "Refusing update: %s/%s (%s) is behind current build (%s)",
            remote,
            branch,
            available,
            old_commit,
        )
        return {
            "ok": False,
            "error": (
                f"remote {remote}/{branch} is behind this instance "
                f"({available[:10]} vs {old_commit[:10]}) — no downgrade applied"
            ),
        }

    try:
        _run(["git", "reset", "--hard", f"{remote}/{branch}"], timeout=120, check=True)
    except Exception as exc:
        logger.exception("Update reset failed")
        return {"ok": False, "error": f"reset failed: {exc}"}

    new_commit = current_commit()
    set_channel(channel_label)

    # Install any new dependencies before restarting.
    if _requirements_changed(old_commit):
        pip = str(repo_root() / ".venv" / "bin" / "pip")
        if Path(pip).exists():
            try:
                _run([pip, "install", "-r", "requirements.txt"], timeout=600, check=True)
            except Exception as exc:
                logger.warning("pip install failed after update: %s", exc)

    logger.info("Update applied: %s -> %s (%s/%s)", old_commit, new_commit, channel, branch)
    return {
        "ok": True,
        "restarted": True,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "branch": branch,
        "channel": channel_label,
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
