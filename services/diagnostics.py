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
import pkgutil
import platform
import shutil
import tempfile
from datetime import datetime, timezone
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


def _config_warnings() -> list[str]:
    """Config-level problems that commonly break a self-hosted instance,
    surfaced in the report even on a minimal Termux box (no bot runtime).

    The big one: OAuth redirect_uri / public_url scheme must match what the
    browser and the Discord app use. A mismatch (http config vs https site)
    makes Discord reject the callback with redirect_uri_mismatch, so the owner
    can never complete login — and therefore can never reach owner-gated pages
    like Settings → Update.
    """
    warnings: list[str] = []
    pub = (config.dashboard.public_url or "").strip().rstrip("/")
    redirect = (config.oauth2.redirect_uri or "").strip().rstrip("/")

    if config.oauth2.enabled:
        if redirect and not redirect.endswith("/auth/callback"):
            warnings.append(f"OAuth redirect_uri does not end in /auth/callback ({redirect})")
        for label, url in (("public_url", pub), ("redirect_uri", redirect)):
            if url and url.startswith("http://"):
                warnings.append(
                    f"{label} uses http:// ({url}) — if the dashboard is served "
                    "over https, Discord OAuth will reject the callback "
                    "(redirect_uri_mismatch) and login will fail."
                )
        if config.oauth2.enabled and not config.oauth2.owner_discord_ids:
            warnings.append("OAuth enabled but BARK_OWNER_DISCORD_IDS is empty")
    else:
        warnings.append("OAuth is disabled — the dashboard runs public (no login)")

    if pub and redirect and pub != redirect.rsplit("/auth/callback", 1)[0].rstrip("/"):
        warnings.append(f"public_url ({pub}) does not match the host of redirect_uri ({redirect})")
    return warnings


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
        "config_warnings": _config_warnings(),
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
    content are ever included. Pass ``bot=None`` to get a runtime section that
    says the bot runtime is unavailable (e.g. a dashboard process without a
    wired bot), so the report still renders a [Live runtime] block.
    """
    if bot is None:
        return {
            "runtime": {
                "available": False,
                "bot_user": None,
                "bot_id": "",
                "guild_count": 0,
                "latency_ms": None,
                "is_ready": None,
                "is_connected": None,
                "modules": {"count": 0, "items": [], "errors": []},
                "guilds": {"count": 0, "items": [], "errors": []},
                "multi_instance_conflicts": [],
                "checks": _none_bot_checks(),
            }
        }
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
            item["our_permissions"] = [
                p for p in dir(perms) if not p.startswith("_") and getattr(perms, p) is True
            ]
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
            "bot_id": str(getattr(getattr(bot, "user", None), "id", "") or ""),
            "guild_count": len(guilds),
            "latency_ms": _safe_number(getattr(bot, "latency", None)),
            "is_ready": _safe_bool(getattr(bot, "is_ready", None)),
            "is_connected": _safe_bool(getattr(bot, "is_connected", None)),
            "modules": modules_section,
            "guilds": guilds_section,
            "multi_instance_conflicts": multi_instance,
            "checks": _sync_checks(bot, modules_mgr, modules_section, guilds),
        }
    }


def _none_bot_checks() -> list[dict[str, str]]:
    """Capability checks for a dashboard process with no bot wired."""
    return [
        {"name": "process", "status": "ok", "detail": f"PID {os.getpid()} running"},
        {"name": "discord", "status": "unavailable", "detail": "no bot wired to this dashboard"},
        {
            "name": "collectors",
            "status": "unavailable",
            "detail": "no bot runtime — data collector / stats flush not running",
        },
        {
            "name": "modules",
            "status": "unavailable",
            "detail": "no bot runtime — modules not enumerated",
        },
        {
            "name": "permissions",
            "status": "unavailable",
            "detail": "no bot runtime — guild permissions not checked",
        },
        {
            "name": "database",
            "status": "unavailable",
            "detail": "bot runtime unavailable — not checked",
        },
        {
            "name": "scheduler",
            "status": "unavailable",
            "detail": "bot runtime unavailable — not checked",
        },
        {
            "name": "media_engine",
            "status": "unavailable",
            "detail": "bot runtime unavailable — not checked",
        },
    ]


def _sync_checks(bot, modules_mgr, modules_section, guilds) -> list[dict[str, str]]:
    """Checks computable without I/O: process, gateway, workers, modules, perms.

    The async checks (database, scheduler, media engine) are appended by
    ``build_runtime_diagnostics_async`` so the sync builder stays testable.
    """
    checks: list[dict[str, str]] = []
    checks.append({"name": "process", "status": "ok", "detail": f"PID {os.getpid()} running"})

    ready = _safe_bool(getattr(bot, "is_ready", None))
    connected = _safe_bool(getattr(bot, "is_connected", None))
    latency = _safe_number(getattr(bot, "latency", None))
    if ready is True:
        detail = (
            f"connected to gateway ({latency} ms)"
            if latency is not None
            else "connected to gateway"
        )
        checks.append({"name": "discord", "status": "ok", "detail": detail})
    elif connected is False:
        checks.append(
            {
                "name": "discord",
                "status": "unavailable",
                "detail": "DISCONNECTED — no events are being processed; check token/intents",
            }
        )
    else:
        checks.append(
            {
                "name": "discord",
                "status": "degraded",
                "detail": "connecting — gateway up but not ready (no on_ready yet)",
            }
        )

    checks.append(_collectors_check(bot))
    checks.append(_modules_check(modules_mgr, modules_section))
    checks.append(_permissions_check(bot, guilds))
    return checks


# Two collector intervals (15 min) without a run means the background loop stalled.
_COLLECTOR_STALE_SECONDS = 2 * 15 * 60


def _collectors_check(bot) -> dict[str, str]:
    """Background worker freshness: guild data collector + stats flush task."""
    from services import stats_recorder

    collector = getattr(bot, "_data_collector", None)
    collector_task = getattr(collector, "_task", None) if collector is not None else None
    collector_alive = collector_task is not None and not collector_task.done()
    last_run = getattr(collector, "last_run_at", None)
    age_min: int | None = None
    if last_run is not None:
        try:
            age_min = max(0, int((datetime.now(timezone.utc) - last_run).total_seconds() // 60))
        except TypeError:
            age_min = None
    stale = age_min is not None and age_min * 60 > _COLLECTOR_STALE_SECONDS

    flush_task = getattr(stats_recorder, "_flush_task", None)
    flush_alive = flush_task is not None and not flush_task.done()
    # The flusher is started lazily by the first tracked event, so "no task
    # yet" is only a problem when counters are actually waiting. Treating it as
    # a fault made every idle instance report degraded, which is how a
    # diagnostics panel trains people to ignore it.
    pending = len(getattr(stats_recorder, "_pending_messages", None) or {}) + len(
        getattr(stats_recorder, "_pending_emoji", None) or {}
    )
    last_flush = getattr(stats_recorder, "last_flush_at", None)

    parts = []
    if last_run is not None:
        parts.append(f"collector last run {age_min} min ago" + (" (STALE)" if stale else ""))
    else:
        parts.append("collector has not run yet")
    if flush_alive:
        parts.append("stats flush task running")
    elif pending:
        parts.append(f"stats flush task NOT running with {pending} pending counter(s)")
    else:
        parts.append("stats flush idle (no pending counters)")
    if last_flush is not None:
        try:
            flush_age_min = max(
                0, int((datetime.now(timezone.utc) - last_flush).total_seconds() // 60)
            )
            parts.append(f"last flush {flush_age_min} min ago")
        except TypeError:
            pass
    ok = collector_alive and (flush_alive or not pending) and not stale
    return {"name": "collectors", "status": "ok" if ok else "degraded", "detail": "; ".join(parts)}


def _modules_check(modules_mgr, modules_section) -> dict[str, str]:
    """Per-module health: enumeration errors and packages that failed to load."""
    errors = list(modules_section.get("errors") or [])
    failed = _failed_to_load(modules_mgr)
    if errors or failed:
        detail = "; ".join(errors[:2])
        if failed:
            detail = (detail + "; " if detail else "") + f"failed to load: {', '.join(failed)}"
        return {"name": "modules", "status": "degraded", "detail": detail}
    enabled = 0
    if modules_mgr is not None and hasattr(modules_mgr, "should_run_globally"):
        try:
            for name in modules_mgr.get_all_modules() or {}:
                if modules_mgr.should_run_globally(name):
                    enabled += 1
        except Exception:
            enabled = 0
    return {
        "name": "modules",
        "status": "ok",
        "detail": f"{modules_section.get('count', 0)} modules discovered, {enabled} enabled globally",
    }


def _failed_to_load(modules_mgr) -> list[str]:
    """Built-in module packages that did not register (import/instantiate error).

    Module discovery logs load failures but does not record them anywhere;
    diffing the modules package tree against the registry is the cheapest
    honest signal. Plugins live outside the ``modules`` package and are
    covered by their own load logging.
    """
    try:
        import modules as modules_pkg

        expected = {
            name
            for _, name, is_pkg in pkgutil.iter_modules(modules_pkg.__path__)
            if is_pkg and name != "base"
        }
        if modules_mgr is None:
            return sorted(expected)
        loaded = set((modules_mgr.get_all_modules() or {}).keys())
        return sorted(expected - loaded)
    except Exception:
        return []


def _permissions_check(bot, guilds) -> dict[str, str]:
    """Permission-dependent feature status: core posting perms per guild."""
    missing: list[str] = []
    for guild in guilds:
        gid = getattr(guild, "id", None)
        me = getattr(guild, "me", None) or getattr(bot, "user", None)
        perms = getattr(me, "guild_permissions", None) if me is not None else None
        if perms is None:
            continue
        lacks = [p for p in ("send_messages", "view_channel") if getattr(perms, p, True) is False]
        if lacks:
            missing.append(f"{getattr(guild, 'name', gid)}: missing {', '.join(lacks)}")
    if missing:
        return {"name": "permissions", "status": "degraded", "detail": "; ".join(missing)}
    if not guilds:
        return {"name": "permissions", "status": "ok", "detail": "no guilds to check"}
    return {
        "name": "permissions",
        "status": "ok",
        "detail": "can send messages and view channels in all guilds",
    }


async def build_runtime_diagnostics_async(bot) -> dict:
    """``build_runtime_diagnostics`` plus the checks that need I/O.

    Appends the database read+write probe, announcement-schedule state, and
    media-engine ping to ``runtime.checks``. The sync function stays sync so
    existing tests and embeddings keep working.
    """
    report = build_runtime_diagnostics(bot)
    checks = report["runtime"].get("checks")
    if bot is None or not isinstance(checks, list):
        return report
    for check in await _async_checks(bot):
        checks.append(check)
    return report


async def _async_checks(bot) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for name, coro in (
        ("database", _db_check()),
        ("scheduler", _scheduler_check(bot)),
        ("media_engine", _media_engine_check()),
    ):
        try:
            results.append(await coro)
        except Exception as exc:
            results.append(
                {
                    "name": name,
                    "status": "unavailable",
                    "detail": f"check failed: {type(exc).__name__}: {exc}",
                }
            )
    return results


async def _db_check() -> dict[str, str]:
    """Read+write probe against the real database, leaving no residue.

    The probe has to hit the real file to prove the real file is writable, but
    it must not leave an unmodeled table behind in every install's database:
    create the scratch table, write, read back, then drop it in the same
    transaction.
    """
    from sqlalchemy import text

    from database.engine import session_scope

    try:
        async with session_scope() as session:
            await session.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS _diagnostics_probe "
                    "(id INTEGER PRIMARY KEY, ts TEXT NOT NULL)"
                )
            )
            await session.execute(
                text("INSERT INTO _diagnostics_probe (ts) VALUES (:ts)"),
                {"ts": datetime.now(timezone.utc).isoformat()},
            )
            rows = (
                (await session.execute(text("SELECT ts FROM _diagnostics_probe"))).scalars().all()
            )
            await session.execute(text("DROP TABLE IF EXISTS _diagnostics_probe"))
        if rows:
            return {"name": "database", "status": "ok", "detail": "read+write probe succeeded"}
        return {"name": "database", "status": "degraded", "detail": "write probe returned no rows"}
    except Exception as exc:
        return {
            "name": "database",
            "status": "unavailable",
            "detail": f"probe failed: {type(exc).__name__}: {exc}",
        }


async def _scheduler_check(bot) -> dict[str, str]:
    """Announcement schedule loop state + queued/failed schedule counts."""
    mgr = getattr(bot, "modules", None)
    if mgr is None:
        return {"name": "scheduler", "status": "unavailable", "detail": "no bot runtime"}
    from sqlalchemy import func, select

    from database.engine import session_scope
    from database.models.announcements import AnnouncementSchedule

    try:
        module = mgr.get_module("announcements") if hasattr(mgr, "get_module") else None
        task = getattr(module, "_schedule_task", None) if module is not None else None
        loop_alive = task is not None and not task.done()
        queued = failed = 0
        db_ok = True
        try:
            async with session_scope() as session:
                rows = (
                    await session.execute(
                        select(AnnouncementSchedule.status, func.count()).group_by(
                            AnnouncementSchedule.status
                        )
                    )
                ).all()
            for status, count in rows:
                if status == "queued":
                    queued = int(count)
                elif status == "failed":
                    failed = int(count)
        except Exception:
            db_ok = False
        counts = f"{queued} queued, {failed} failed schedule(s)"
        if loop_alive and db_ok:
            return {
                "name": "scheduler",
                "status": "ok",
                "detail": f"announcement loop running; {counts}",
            }
        if loop_alive:
            return {
                "name": "scheduler",
                "status": "degraded",
                "detail": f"loop running but schedule table unreadable ({counts})",
            }
        if db_ok:
            return {
                "name": "scheduler",
                "status": "degraded",
                "detail": f"announcement schedule loop NOT running; {counts}",
            }
        return {
            "name": "scheduler",
            "status": "degraded",
            "detail": "announcement schedule loop NOT running; schedule table unreadable",
        }
    except Exception as exc:
        return {
            "name": "scheduler",
            "status": "unavailable",
            "detail": f"check failed: {type(exc).__name__}: {exc}",
        }


async def _media_engine_check(client=None) -> dict[str, str]:
    """Reachability of the local media-engine service (open /health)."""
    try:
        from services.media_engine.client import MediaEngineClient

        engine = client or MediaEngineClient()
        ok = await engine.health()
        if ok:
            return {
                "name": "media_engine",
                "status": "ok",
                "detail": f"reachable at {engine.base_url}",
            }
        return {
            "name": "media_engine",
            "status": "unavailable",
            "detail": f"unreachable at {engine.base_url}",
        }
    except Exception as exc:
        return {
            "name": "media_engine",
            "status": "unavailable",
            "detail": f"check failed: {type(exc).__name__}: {exc}",
        }


def _safe_bool(fn) -> bool | None:
    """Call a bot predicate safely; None on any failure (bot not fully wired)."""
    try:
        return bool(fn()) if callable(fn) else None
    except Exception:
        return None


def _safe_number(value) -> int | float | None:
    """Return a numeric value if sensible, else None (e.g. bot not connected)."""
    try:
        v = float(value)
        return int(v) if v.is_integer() else round(v, 3)
    except (TypeError, ValueError):
        return None


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
    warnings = report.get("config_warnings") or []
    if warnings:
        lines.append("")
        lines.append("[Config warnings]")
        for w in warnings:
            lines.append(f"  ⚠ {w}")
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
        if runtime.get("available") is False:
            lines.append("  ⚠ bot runtime unavailable — no bot is wired to this dashboard")
            lines.append("    (modules/guilds not enumerated; bot may not be running)")
        lines.append(
            f"  bot user      : {runtime.get('bot_user', '(unknown)')} (id {runtime.get('bot_id', '')})"
        )
        ready = runtime.get("is_ready")
        connected = runtime.get("is_connected")
        lines.append(
            f"  connected     : {('yes' if ready else 'no') if ready is not None else '(unknown)'}"
        )
        if connected is not None:
            lines.append(f"  gateway       : {'connected' if connected else 'DISCONNECTED'}")
        latency = runtime.get("latency_ms")
        if latency is not None:
            lines.append(f"  latency       : {latency} ms")
        lines.append(f"  guild count   : {runtime.get('guild_count', 0)}")
        if ready is False or connected is False:
            lines.append(
                "  ⚠ BOT IS NOT CONNECTED — no events are being processed; "
                "modules cannot post or score. Check the token/intents on Discord."
            )
        checks = runtime.get("checks")
        if isinstance(checks, list) and checks:
            lines.append("")
            lines.append("[Capability checks]")
            for check in checks:
                name = check.get("name", "?")
                status = check.get("status", "?")
                detail = check.get("detail", "")
                lines.append(f"  [{status:^11}] {name}: {detail}")
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
            lines.append(
                f"      pages:     {', '.join(entry.get('dashboard_pages', [])) or '(none)'}"
            )
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
            lines.append(
                f"      enabled_modules: {', '.join(g.get('enabled_modules', [])) or '(none)'}"
            )
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
