"""Build a redacted diagnostic report for remote support.

Users who run Bark on their own hardware (Termux, containers, VMs) can download
a text report from the Settings page and paste it back to us. It captures the
version, installation method, environment/hardware, git + remote state (the
usual "could not find branch on remote" culprit), the last update-check error,
and recent logs — with secrets redacted so it is safe to share.
"""

from __future__ import annotations

import base64
import logging
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Any

from bark_version import __version__
from config import config
from services import update_service

logger = logging.getLogger("bark.diagnostics")

# (remote, branch) pairs of interest so a missing/renamed remote or branch
# (e.g. the "could not find branch 'main' on remote 'github'" failure on a
# fresh one-line install, which clones GitHub as `origin`) shows up instantly.
# `master` is included because the Forgejo mirror uses `master` as its default
# branch while GitHub uses `main` — checking only `main`/`dev` produced a false
# "origin/main ABSENT" on mirror installs.
_REMOTE_REFS = (
    ("origin", "main"),
    ("origin", "master"),
    ("origin", "dev"),
    ("github", "main"),
    ("github", "master"),
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
    """Run a git subprocess safely; return stdout (or '') without raising.

    Termux and other minimal installs may not have ``systemctl``, and even git
    may live off PATH or be unavailable mid-boot. A diagnostic report must
    never 500 because a helper binary is missing — capture that as a string
    result instead so the section can still render.
    """
    try:
        result = update_service._run(["git", *args])
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as exc:  # FileNotFoundError, OSError, etc.
        logger.debug("git helper unavailable (%s): %s", exc.__class__.__name__, exc)
        return ""


def _safe_update_call(fn, fallback):
    """Call a git-dependent update_service function, returning ``fallback`` on
    any failure (e.g. git missing on Termux). Keeps the report buildable."""
    try:
        result = fn()
        return result if result not in (None, "") else fallback
    except Exception as exc:
        logger.debug("update_service call failed (%s): %s", fn.__name__, exc)
        return fallback


def _systemctl(args: list[str]) -> str:
    """Run ``systemctl ...`` safely; '' on any failure (incl. no systemd).

    Termux has no systemd; returning '' lets callers fall back to manual
    install detection instead of crashing the report.
    """
    try:
        result = update_service._run(["systemctl", *args])
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as exc:  # FileNotFoundError, OSError
        logger.debug("systemctl unavailable (%s): %s", exc.__class__.__name__, exc)
        return ""


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


def _running_unit() -> str:
    """Best-effort name of the systemd unit running this process.

    Reads the scoped unit from /proc/self/cgroup. This is the *actual* unit
    (e.g. ``bark-dev.service``) rather than the configured default
    (``bark.service``), which fixes the wrong-unit report on dev instances.
    Returns the configured service_name as a fallback.
    """
    try:
        raw = Path("/proc/self/cgroup").read_text(errors="replace")
        for line in raw.splitlines():
            # last field is e.g. /system.slice/bark-dev.service or bark-dev.scope
            name = line.rsplit(":", 1)[-1].strip().split("/")[-1]
            if name.endswith(".service"):
                return name
    except OSError:
        pass
    return config.instance.service_name


def _log_path() -> Path:
    """Resolve the real application log the running systemd unit writes to.

    The diagnostics used to hardcode ``bark.log`` at the repo root, but a
    multi-instance host writes each instance's logs to its own file
    (``bark-dev.log`` via ``StandardOutput=append:``). The ground truth is the
    running process's own stdout — we read the unit's MainPID and follow
    ``/proc/<pid>/fd/1`` to the actual log file. Falls back to the unit's
    StandardOutput target, then ``bark.log`` at the repo root.
    """
    unit = _running_unit()
    # 1) Follow the main process's stdout fd — the definitive destination.
    try:
        result = update_service._run(["systemctl", "show", unit, "-p", "MainPID", "--value"])
        pid = result.stdout.strip() if result.returncode == 0 else ""
        if pid and pid.isdigit() and pid != "0":
            fd = Path(f"/proc/{pid}/fd/1")
            if fd.is_symlink():
                target = fd.resolve()
                if target.is_file():
                    return target
    except Exception:
        pass
    # 2) Parse StandardOutput=append:<path> if present.
    try:
        result = update_service._run(["systemctl", "show", unit, "-p", "StandardOutput", "--value"])
        if result.returncode == 0:
            value = result.stdout.strip()
            if value.startswith("append:"):
                path = Path(value[len("append:") :].strip())
                if path.is_absolute() and path.exists():
                    return path
    except Exception:
        pass
    return repo_root() / "bark.log"


def _database_path() -> str:
    """Resolve the on-disk database path (relative sqlite URLs resolved like engine)."""
    url = config.database.url
    if url.startswith("sqlite+aiosqlite:///"):
        rel = url[len("sqlite+aiosqlite:///") :]
        if not rel.startswith("/"):
            return str(config.data_dir / rel)
        return rel
    # Non-sqlite: return the DSN with credentials redacted.
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url


def _bot_app_id() -> str:
    """Decode the bot's application ID from the token's first (base64) segment.

    Discord bot tokens are ``<base64(app_id)>.<base64(timestamp)>.<base64(hmac)>``.
    The first segment base64-decodes to the decimal application ID — a public
    identifier, safe to include (we never print the token itself). Empty if no
    token configured or it can't be decoded.
    """
    token = config.bot.token or ""
    if not token:
        return "(no token set)"
    first = token.split(".", 1)[0]
    try:
        padded = first + "=" * (-len(first) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
        return decoded if decoded.isdigit() else "(unable to decode)"
    except Exception:
        return "(unable to decode)"


def install_method() -> str:
    unit = _running_unit()
    if _systemd_active():
        return f"systemd service ({unit}.service)"
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
        "bot_app_id": _bot_app_id(),
        "database_path": _database_path(),
        "systemd_unit": _running_unit(),
        "update_remote": inst.update_remote,
        "stable_branch": inst.stable_branch,
        "command_prefix": config.bot.command_prefix or "bark!",  # instance default
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
        f"{remote}/{branch}": bool(
            _git("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}")
        )
        for remote, branch in _REMOTE_REFS
    }

    # Recent application log (resolved from the running systemd unit's
    # StandardOutput so multi-instance hosts report their own log file,
    # falling back to bark.log at the repo root).
    log_path = _log_path()
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
            "commit": _safe_update_call(update_service.current_commit, "unknown"),
            "branch": _safe_update_call(update_service.current_branch, ""),
            "update_channel": _safe_update_call(update_service.get_channel, "unknown"),
        },
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "install_dir": str(root),
            "install_method": install_method(),
            "systemd_active": _systemd_active(),
            "pid": os.getpid(),
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
        "logs": {"log_path": str(log_path), "bark_log_tail": log_tail},
    }


def build_runtime_diagnostics(bot) -> dict:
    """Gather live bot/module/guild state for the diagnostic report.

    This is the "EVERYTHING WE CAN" section: it enumerates every discovered
    module (capabilities + a per-guild ``diagnose()`` self-report), every guild
    the bot is in (identity, size, our permission summary, enabled modules, and
    any other Bark-like bot sharing the server — the classic cause of modules
    like Reputation silently failing to post a leaderboard or scores).

    Must be called from an async context with the live ``bot`` object (e.g.
    ``request.app.state.bot``). Failures are captured per-section so one broken
    module or guild can't blank the whole report. No secrets, tokens, or message
    content are ever included.
    """
    # Imported lazily so this module stays importable in stripped-down test/dev
    # contexts where the bot package isn't fully wired.
    modules_mgr = getattr(bot, "modules", None)
    guilds = list(getattr(bot, "guilds", []) or [])

    modules_section: dict[str, Any] = {"count": 0, "items": [], "errors": []}
    if modules_mgr is not None:
        try:
            all_modules = modules_mgr.get_all_modules() or {}
            modules_section["count"] = len(all_modules)
            for name, module in all_modules.items():
                try:
                    entry = {
                        "name": name,
                        "version": getattr(module, "version", None),
                        "enabled_globally": None,
                        "commands": [c.name for c in module.get_commands()],
                        "events": [e.event_name for e in module.get_events()],
                        "dashboard_pages": [p.route for p in module.get_dashboard_pages()],
                        "permissions": [p.name for p in module.get_permissions()],
                        "schema_keys": list(
                            (module.get_settings_schema() or {}).get("properties", {}).keys()
                        ),
                    }
                    if hasattr(modules_mgr, "should_run_globally"):
                        try:
                            entry["enabled_globally"] = modules_mgr.should_run_globally(name)
                        except Exception:
                            entry["enabled_globally"] = None
                    # Per-guild self-report (the high-value part).
                    per_guild = []
                    for guild in guilds:
                        gid = getattr(guild, "id", None)
                        if gid is None:
                            continue
                        try:
                            enabled = (
                                modules_mgr.is_enabled_for_guild(int(gid), name)
                                if hasattr(modules_mgr, "is_enabled_for_guild")
                                else None
                            )
                        except Exception:
                            enabled = None
                        if not enabled:
                            continue
                        try:
                            report = module.diagnose(int(gid))
                            per_guild.append({"guild_id": str(gid), "report": report})
                        except Exception as exc:  # module diagnose shouldn't crash the report
                            per_guild.append(
                                {"guild_id": str(gid), "error": f"{type(exc).__name__}: {exc}"}
                            )
                    if per_guild:
                        entry["per_guild"] = per_guild
                    modules_section["items"].append(entry)
                except Exception as exc:
                    modules_section["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            modules_section["errors"].append(f"module enumeration: {type(exc).__name__}: {exc}")

    guilds_section: dict[str, Any] = {"count": len(guilds), "items": [], "errors": []}
    multi_instance: list[dict[str, Any]] = []
    for guild in guilds:
        gid = getattr(guild, "id", None)
        if gid is None:
            continue
        item: dict[str, Any] = {
            "id": str(gid),
            "name": getattr(guild, "name", None),
            "member_count": getattr(guild, "member_count", None),
            "owner_id": str(getattr(guild, "owner_id", "") or ""),
            "enabled_modules": [],
            "other_bark_instances": [],
        }
        # Our permission summary (public bitfield names, no secrets).
        me = getattr(guild, "me", None) or getattr(bot, "user", None)
        perms = getattr(me, "guild_permissions", None) if me is not None else None
        if perms is not None:
            item["our_permissions"] = [p for p in dir(perms) if not p.startswith("_") and getattr(perms, p) is True]
        # Enabled modules for this guild.
        if modules_mgr is not None and hasattr(modules_mgr, "is_enabled_for_guild"):
            try:
                item["enabled_modules"] = [
                    name
                    for name in (modules_mgr.get_all_modules() or {})
                    if modules_mgr.is_enabled_for_guild(int(gid), name)
                ]
            except Exception:
                item["enabled_modules"] = []
        # Other Bark-like bots in the same server.
        others = []
        members = getattr(guild, "members", None) or getattr(guild, "users", None) or []
        self_id = getattr(getattr(bot, "user", None), "id", None)
        for member in members:
            bot_flag = getattr(member, "bot", getattr(member, "bot", False))
            if not bot_flag:
                continue
            uid = getattr(member, "id", None)
            uname = getattr(member, "name", "") or ""
            if uid == self_id or "bark" not in uname.lower():
                continue
            others.append({"id": str(uid), "name": uname, "bot": True})
        item["other_bark_instances"] = others
        if others:
            multi_instance.append(
                {"guild_id": str(gid), "guild_name": item["name"], "bots": others}
            )
        guilds_section["items"].append(item)

    return {
        "runtime": {
            "available": True,
            "bot_user": getattr(getattr(bot, "user", None), "name", None),
            "guild_count": len(guilds),
            "latency_ms": None,
            "modules": modules_section,
            "guilds": guilds_section,
            "multi_instance_conflicts": multi_instance,
        }
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
    cfg = report["config"]
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
    lines.append(f"  Bot app ID     : {cfg.get('bot_app_id', '(n/a)')}")
    # Cross-check: the token's app id should match the OAuth client id. If the
    # installed token points at a different Discord app than the one the
    # dashboard is configured for, that's a misconfiguration worth flagging.
    app_id = cfg.get("bot_app_id", "")
    oauth_id = cfg.get("oauth_client_id", "")
    if app_id and oauth_id and app_id != oauth_id:
        lines.append(
            f"  ⚠ app/token mismatch: token decodes to app {app_id} but "
            f"OAuth client_id is {oauth_id}"
        )
    lines.append("")
    lines.append("[Environment / hardware]")
    lines.append(f"  Platform   : {env['platform']}")
    lines.append(f"  Machine    : {env['machine']}")
    lines.append(f"  Python     : {env['python_version']}")
    lines.append(f"  Hostname   : {env['hostname']}")
    lines.append(f"  PID        : {env.get('pid', '(n/a)')}  (kill -INT <pid> / systemctl restart)")
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
    lines.append("[Recent log]")
    log_path = report["logs"].get("log_path", "")
    if log_path:
        lines.append(f"  (source: {log_path})")
    for entry in report["logs"]["bark_log_tail"]:
        lines.append(f"  {entry}")
    if not report["logs"]["bark_log_tail"]:
        lines.append("  (no log found)")
    lines.append("")

    # ── Live runtime (modules / guilds / multi-instance) ──
    runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else None
    if runtime is not None:
        lines.append("[Live runtime]")
        lines.append(f"  bot user      : {runtime.get('bot_user', '(unknown)')}")
        lines.append(f"  guild count   : {runtime.get('guild_count', 0)}")
        lines.append("")
        lines.append("[Modules]")
        mods = runtime.get("modules", {})
        lines.append(f"  discovered    : {mods.get('count', 0)}")
        for entry in mods.get("items", []):
            lines.append(f"  - {entry['name']} (v{entry.get('version') or '?'})")
            eg = entry.get("enabled_globally")
            lines.append(f"      enabled_globally: {eg}")
            lines.append(f"      commands: {', '.join(entry.get('commands', [])) or '(none)'}")
            lines.append(f"      events:    {', '.join(entry.get('events', [])) or '(none)'}")
            lines.append(f"      pages:     {', '.join(entry.get('dashboard_pages', [])) or '(none)'}")
            lines.append(f"      perms:     {', '.join(entry.get('permissions', [])) or '(none)'}")
            for pg in entry.get("per_guild", []):
                gid = pg.get("guild_id")
                rep = pg.get("report")
                if isinstance(rep, dict):
                    lines.append(f"      guild {gid}: status={rep.get('status', '?')}")
                    cfg = rep.get("config")
                    if isinstance(cfg, dict):
                        lines.append(f"        config: {cfg}")
                    so = rep.get("showoff_channel")
                    if so is not None:
                        lines.append(f"        showoff_channel: {so}")
                    act = rep.get("recent_score_activity")
                    if act is not None:
                        lines.append(f"        score_activity: {act}")
                    rej = rep.get("recent_rejections")
                    if isinstance(rej, list) and rej:
                        lines.append(f"        ⚠ RECENT REJECTIONS: {rej}")
                    iss = rep.get("issues")
                    if isinstance(iss, list) and iss:
                        lines.append(f"        ⚠ issues: {iss}")
                    obi = rep.get("other_bark_instances")
                    if isinstance(obi, list) and obi:
                        lines.append(f"        ⚠ OTHER BARK INSTANCES: {obi}")
                elif "error" in pg:
                    lines.append(f"      guild {gid}: diagnose error: {pg['error']}")
        for err in mods.get("errors", []):
            lines.append(f"  ⚠ module error: {err}")
        lines.append("")

        lines.append("[Guilds]")
        gsec = runtime.get("guilds", {})
        lines.append(f"  count         : {gsec.get('count', 0)}")
        for g in gsec.get("items", []):
            lines.append(f"  - {g.get('name')} ({g.get('id')}) members={g.get('member_count')}")
            lines.append(f"      owner_id: {g.get('owner_id')}")
            lines.append(f"      enabled_modules: {', '.join(g.get('enabled_modules', [])) or '(none)'}")
            perms = g.get("our_permissions")
            if perms:
                lines.append(f"      our_perms: {', '.join(perms)}")
            obi = g.get("other_bark_instances") or []
            if obi:
                lines.append(f"      ⚠ OTHER BARK INSTANCES SHARING THIS SERVER: {obi}")
        for err in gsec.get("errors", []):
            lines.append(f"  ⚠ guild error: {err}")

        conflicts = runtime.get("multi_instance_conflicts") or []
        lines.append("")
        lines.append("[Multi-instance conflicts]")
        if conflicts:
            for c in conflicts:
                lines.append(
                    f"  ⚠ guild {c.get('guild_name')} ({c.get('guild_id')}): "
                    f"other Bark bots = {c.get('bots')}"
                )
            lines.append(
                "  ↑ These servers have more than one Bark bot. Modules that post to "
                "channels (Reputation leaderboard/showoff, Welcome, Logging) may "
                "double-post, double-count, or suppress output."
            )
        else:
            lines.append("  (none detected)")

    lines.append("")
    lines.append("--- end of report ---")
    return "\n".join(lines)
