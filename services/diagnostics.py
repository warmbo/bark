"""Build a redacted diagnostic report for remote support.

Users who run Bark on their own hardware (Termux, containers, VMs) can download
a text report from the Settings page and paste it back to us. It captures the
version, installation method, environment/hardware, git + remote state (the
usual "could not find branch on remote" culprit), the last update-check error,
and recent logs — with secrets redacted so it is safe to share.
"""

from __future__ import annotations

import logging
import platform
import shutil
import tempfile
from pathlib import Path

from bark_version import __version__
from config import config
from services import update_service

logger = logging.getLogger("bark.diagnostics")

# (remote, branch) pairs of interest so a missing/renamed remote or branch
# (e.g. the "could not find branch 'main' on remote 'github'" failure on a
# fresh one-line install, which clones GitHub as `origin`) shows up instantly.
_REMOTE_REFS = (
    ("origin", "main"),
    ("origin", "dev"),
    ("github", "main"),
    ("github", "dev"),
)

# Bark requests these privileged gateway intents; if the Developer Portal app
# lacks them, Discord returns 4014 and the bot never connects.
_INTENTS = {
    "message_content": True,
    "server_members": True,
    "presence": True,
    "moderation": True,
}


def repo_root() -> Path:
    return update_service.repo_root()


def _git(*args: str) -> str:
    result = update_service._run(["git", *args])
    return result.stdout.strip() if result.returncode == 0 else ""


def _systemd_active() -> bool:
    try:
        result = update_service._run(
            ["systemctl", "--user", "is-active", config.instance.service_name]
        )
        if result.returncode == 0 and result.stdout.strip() == "active":
            return True
        result = update_service._run(["systemctl", "is-active", config.instance.service_name])
        return result.returncode == 0 and result.stdout.strip() == "active"
    except Exception:
        return False


def install_method() -> str:
    if _systemd_active():
        return f"systemd service ({config.instance.service_name}.service)"
    if (repo_root() / "run.sh").exists():
        return "foreground / manual (run.sh or python app.py)"
    return "manual (python app.py)"


def _tmp_writable() -> bool:
    try:
        with tempfile.TemporaryFile() as fh:
            fh.write(b"x")
        return True
    except OSError:
        return False


def _redact_url(url: str) -> str:
    """Strip credentials from a git URL; keep the host/path for reference."""
    cleaned = url
    if "://" in cleaned:
        scheme, _, rest = cleaned.partition("://")
        host = rest.split("@")[-1]
        cleaned = f"{scheme}://{host}"
    return cleaned.rstrip(".git")


def _redacted_config() -> dict[str, str]:
    """A safe, redacted snapshot of the instance configuration.

    Explicit whitelist only — tokens, secrets, passwords and owner IDs are
    never included.
    """
    oauth = config.oauth2
    dash = config.dashboard
    inst = config.instance
    bot = config.bot
    return {
        "dashboard_host": str(dash.host),
        "dashboard_port": str(dash.port),
        "public_url": dash.public_url,
        "force_https": str(dash.force_https),
        "forwarded_allow_ips": dash.forwarded_allow_ips,
        "rate_limit_per_minute": str(dash.rate_limit_per_minute),
        "oauth_enabled": str(oauth.enabled),
        "oauth_client_id": oauth.client_id or "(not set)",
        "oauth_redirect_uri": oauth.redirect_uri or "(not set)",
        "oauth_owners_count": str(len(oauth.owner_discord_ids)),
        "update_remote": inst.update_remote,
        "stable_branch": inst.stable_branch,
        "command_prefix": bot.command_prefix,
        "sync_commands": str(bot.sync_commands),
        "sync_guild_id": str(bot.sync_guild_id or ""),
        "activity_text": bot.activity_text,
        "log_level": config.logging.level,
    }


def build_diagnostics_report() -> dict:
    """Gather everything into a structured (redacted) diagnostic bundle."""
    root = repo_root()
    disk_free = disk_total = None
    try:
        usage = shutil.disk_usage(root)
        disk_free, disk_total = usage.free, usage.total
    except OSError:
        pass

    # Remotes (name + redacted URL), de-duplicated, update_remote first.
    seen: set[str] = set()
    remotes: list[dict[str, str]] = []
    for name in (config.instance.update_remote, "origin", "github"):
        url = _git("remote", "get-url", name)
        if url and name not in seen:
            seen.add(name)
            remotes.append({"name": name, "url": _redact_url(url)})

    refs = {
        f"{remote}/{branch}": bool(_git("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"))
        for remote, branch in _REMOTE_REFS
    }

    # Recent application log (the systemd/installer unit writes bark.log at
    # the repo root when present).
    log_path = root / "bark.log"
    log_tail: list[str] = []
    if log_path.exists():
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            log_tail = lines[-250:]
        except OSError:
            log_tail = []

    return {
        "bark": {
            "version": __version__,
            "commit": update_service.current_commit(),
            "branch": update_service.current_branch(),
            "update_channel": update_service.get_channel(),
        },
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "install_dir": str(root),
            "install_method": install_method(),
            "systemd_active": _systemd_active(),
            "tmp_writable": _tmp_writable(),
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total,
        },
        "config": _redacted_config(),
        "intents": dict(_INTENTS),
        "git": {
            "update_remote": config.instance.update_remote,
            "stable_branch": config.instance.stable_branch,
            "remotes": remotes,
            "refs": refs,
        },
        "update": {
            "last_check_error": update_service.last_check_error(),
            "log_tail": [
                entry["line"] for entry in update_service.get_update_log().get("entries", [])
            ][-100:],
        },
        "logs": {"bark_log_tail": log_tail},
    }


def render_report(report: dict) -> str:
    """Flatten the structured report into a paste-friendly text document."""

    def _fmt_bytes(value: int | None) -> str:
        if value is None:
            return "(unknown)"
        size = float(value)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if abs(size) < 1024 or unit == "TiB":
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.2f} {unit}"
            size /= 1024
        return "(unknown)"

    bark = report["bark"]
    env = report["environment"]
    lines: list[str] = []
    lines.append(f"Bark diagnostic report — v{bark['version']}")
    lines.append("=" * 60)
    lines.append(f"Generated : {env['platform']}")
    lines.append("")
    lines.append("[Bark]")
    lines.append(f"  Version        : v{bark['version']}")
    lines.append(f"  Commit         : {bark['commit']}")
    lines.append(f"  Branch         : {bark['branch']}")
    lines.append(f"  Update channel : {bark['update_channel']}")
    lines.append("")
    lines.append("[Environment / hardware]")
    lines.append(f"  Platform   : {env['platform']}")
    lines.append(f"  Machine    : {env['machine']}")
    lines.append(f"  Python     : {env['python_version']}")
    lines.append(f"  Hostname   : {env['hostname']}")
    lines.append(f"  Install dir: {env['install_dir']}")
    lines.append(f"  Install    : {env['install_method']}")
    lines.append(f"  systemd    : {'yes' if env['systemd_active'] else 'no'}")
    lines.append(f"  tmp writable: {'yes' if env['tmp_writable'] else 'NO (tempdir not writable)'}")
    lines.append(
        f"  Disk free  : {_fmt_bytes(env['disk_free_bytes'])} / {_fmt_bytes(env['disk_total_bytes'])}"
    )
    lines.append("")
    lines.append("[Config (redacted)]")
    for key, value in report["config"].items():
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("[Intents requested]")
    for name, on in report["intents"].items():
        lines.append(f"  {name}: {'requested' if on else 'off'}")
    lines.append("")
    lines.append("[Git remotes]")
    lines.append(f"  update_remote : {report['git']['update_remote']}")
    lines.append(f"  stable_branch : {report['git']['stable_branch']}")
    for remote in report["git"]["remotes"]:
        lines.append(f"  {remote['name']:12s} -> {remote['url']}")
    lines.append("  tracking refs :")
    for ref, present in report["git"]["refs"].items():
        lines.append(f"    {ref:16s} {'present' if present else 'ABSENT'}")
    lines.append("")
    lines.append("[Update check]")
    err = report["update"]["last_check_error"]
    lines.append(f"  last check error: {err or '(none)'}")
    for entry in report["update"]["log_tail"]:
        lines.append(f"  | {entry}")
    if not report["update"]["log_tail"]:
        lines.append("  (no update log entries)")
    lines.append("")
    lines.append("[Recent log (bark.log tail)]")
    for entry in report["logs"]["bark_log_tail"]:
        lines.append(f"  {entry}")
    if not report["logs"]["bark_log_tail"]:
        lines.append("  (no bark.log found)")
    lines.append("")
    lines.append("--- end of report ---")
    return "\n".join(lines)
