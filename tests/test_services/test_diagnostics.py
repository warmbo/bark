"""Diagnostics report tests: content, secret redaction, and the text render."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from services.diagnostics import (
    _bot_app_id,
    _database_path,
    build_diagnostics_report,
    build_runtime_diagnostics,
    build_runtime_diagnostics_async,
    render_report,
)


def test_report_contains_expected_sections():
    report = build_diagnostics_report()
    assert set(report.keys()) >= {
        "bark",
        "environment",
        "config",
        "git",
        "intents",
        "update",
        "logs",
    }
    assert report["bark"]["version"]
    assert report["bark"]["commit"]
    assert report["environment"]["install_dir"]
    assert report["environment"]["install_method"]
    assert isinstance(report["environment"]["tmp_writable"], bool)
    # Bark requests the three privileged intents whose absence causes 4014.
    assert report["intents"]["message_content"] is True
    assert report["intents"]["server_members"] is True
    assert report["intents"]["presence"] is True
    # The resolved log path is surfaced (was previously hardcoded to bark.log).
    assert report["logs"]["log_path"]


def test_bot_app_id_decodes_from_token(monkeypatch):
    import base64

    import config as config_module

    app_id = 987654321
    first = base64.urlsafe_b64encode(str(app_id).encode()).decode().rstrip("=")
    monkeypatch.setattr(config_module.config.bot, "token", f"{first}.timestamp.sig")
    assert _bot_app_id() == str(app_id)


def test_bot_app_id_no_token(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "token", "")
    assert _bot_app_id() == "(no token set)"


def test_database_path_resolves_relative_sqlite(monkeypatch, tmp_path):
    import config as config_module

    monkeypatch.setattr(config_module.config.database, "url", "sqlite+aiosqlite:///bark.db")
    monkeypatch.setattr(config_module.config, "data_dir", tmp_path)
    assert _database_path() == str(tmp_path / "bark.db")


def test_report_never_leaks_secrets(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module.config.bot, "token", "SUPERSECRETTOKEN")
    monkeypatch.setattr(config_module.config.oauth2, "client_secret", "SUPERSECRETCLIENT")
    monkeypatch.setattr(config_module.config.dashboard, "secret_key", "SUPERSECRETKEY")

    text = render_report(build_diagnostics_report())
    for secret in ("SUPERSECRETTOKEN", "SUPERSECRETCLIENT", "SUPERSECRETKEY"):
        assert secret not in text, f"secret leaked into the report: {secret}"


def test_render_report_plaintext_shape():
    report = {
        "bark": {
            "version": "0.2.1",
            "commit": "abc",
            "branch": "main",
            "update_channel": "stable",
        },
        "environment": {
            "platform": "Linux-5.15-x86_64",
            "machine": "x86_64",
            "python_version": "3.13",
            "hostname": "host",
            "install_dir": "/x",
            "install_method": "manual (python app.py)",
            "systemd_active": False,
            "tmp_writable": True,
            "disk_free_bytes": 1024,
            "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "False"},
        "intents": {"message_content": True},
        "git": {
            "update_remote": "github",
            "stable_branch": "main",
            "remotes": [],
            "refs": {"github/main": False, "origin/main": True},
        },
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"bark_log_tail": []},
    }
    text = render_report(report)
    assert "Bark diagnostic report" in text
    assert "[Config (redacted)]" in text
    assert "[Git remotes]" in text
    assert "[Environment / hardware]" in text
    # Missing refs are flagged loudly (the "can't find branch on remote" case).
    assert "github/main      ABSENT" in text
    assert "origin/main      present" in text


def test_report_builds_when_git_and_systemctl_are_unavailable(monkeypatch):
    """Termux / minimal installs without systemctl (or git off PATH) must not
    crash the diagnostic report — helpers degrade to '' instead of raising."""
    import services.diagnostics as d
    import services.update_service as us

    def _missing_binary(cmd, *args, **kwargs):
        raise FileNotFoundError(cmd[0] if cmd else "binary")

    monkeypatch.setattr(us, "_run", _missing_binary)

    # These helpers must not raise when the binary is absent.
    assert d._git("rev-parse", "HEAD") == ""
    assert d._systemctl(["is-active", "bark.service"]) == ""
    assert d._systemd_active() is False
    assert d._running_unit()  # falls back to a non-empty service name

    # The full report still builds and renders.
    report = build_diagnostics_report()
    assert report["bark"]["commit"]  # falls back to "unknown" or similar
    text = render_report(report)
    assert "Bark diagnostic report" in text


def test_config_warnings_flags_http_oauth_redirect(monkeypatch):
    """A report must flag an http:// OAuth redirect so login failures on a
    Termux box (http config behind an https site) are obvious."""
    import config as config_module
    import services.diagnostics as d

    monkeypatch.setattr(config_module.config.oauth2, "client_id", "123")
    monkeypatch.setattr(config_module.config.oauth2, "client_secret", "secret")
    monkeypatch.setattr(
        config_module.config.oauth2, "redirect_uri", "http://bark.richard.works/auth/callback"
    )
    monkeypatch.setattr(config_module.config.dashboard, "public_url", "http://bark.richard.works")
    monkeypatch.setattr(config_module.config.oauth2, "owner_discord_ids", {"1"})

    warnings = d._config_warnings()
    assert any("http://" in w and "redirect_uri" in w for w in warnings)

    report = {
        "bark": {"version": "0.2.1", "commit": "abc", "branch": "main", "update_channel": "stable"},
        "environment": {
            "platform": "Linux",
            "machine": "x86_64",
            "python_version": "3.13",
            "hostname": "host",
            "install_dir": "/x",
            "install_method": "manual",
            "systemd_active": False,
            "tmp_writable": True,
            "disk_free_bytes": 1024,
            "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "True"},
        "config_warnings": warnings,
        "intents": {"message_content": True},
        "git": {"update_remote": "github", "stable_branch": "main", "remotes": [], "refs": {}},
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"log_path": "", "bark_log_tail": []},
    }
    text = d.render_report(report)
    assert "[Config warnings]" in text
    assert "⚠" in text


# ── Capability checks ───────────────────────────────────────

_CHECK_STATUSES = ("ok", "degraded", "unavailable")


def _check_map(checks):
    return {c["name"]: c for c in checks}


def _healthy_bot():
    """A fully-wired fake bot: ready, one guild with core perms, worker alive."""
    guild = SimpleNamespace(
        id=1,
        name="Test Guild",
        member_count=5,
        owner_id="9",
        members=[],
        users=[],
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(send_messages=True, view_channel=True)
        ),
    )
    module = SimpleNamespace(
        name="help",
        version="1.0.0",
        get_commands=lambda: [],
        get_events=lambda: [],
        get_dashboard_pages=lambda: [],
        get_permissions=lambda: [],
        get_settings_schema=lambda: {"properties": {}},
    )
    mgr = SimpleNamespace(
        get_all_modules=lambda: {"help": module},
        should_run_globally=lambda n: True,
        is_enabled_for_guild=lambda gid, n: True,
        get_module=lambda n: module,
    )
    collector = SimpleNamespace(
        _task=SimpleNamespace(done=lambda: False),
        last_run_at=datetime.now(timezone.utc),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=111, name="Bark"),
        guilds=[guild],
        modules=mgr,
        is_ready=lambda: True,
        is_connected=lambda: True,
        latency=12.3,
        _data_collector=collector,
    )


def _patch_workers_healthy(monkeypatch):
    import services.stats_recorder as stats_recorder

    monkeypatch.setattr(stats_recorder, "_flush_task", SimpleNamespace(done=lambda: False))
    monkeypatch.setattr(stats_recorder, "last_flush_at", datetime.now(timezone.utc))


def test_runtime_checks_all_ok_on_healthy_bot(monkeypatch):
    import services.diagnostics as d

    _patch_workers_healthy(monkeypatch)
    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: [])

    checks = d.build_runtime_diagnostics(_healthy_bot())["runtime"]["checks"]
    by_name = _check_map(checks)
    # Sync-computable checks; database/scheduler/media_engine are appended by
    # build_runtime_diagnostics_async (covered in the async test below).
    assert set(by_name) >= {
        "process",
        "discord",
        "collectors",
        "modules",
        "permissions",
    }
    for check in checks:
        assert check["status"] in _CHECK_STATUSES, check
        assert check["detail"], check
    assert by_name["process"]["status"] == "ok"
    assert by_name["discord"]["status"] == "ok"
    assert "12.3 ms" in by_name["discord"]["detail"]
    assert by_name["collectors"]["status"] == "ok"
    assert by_name["modules"]["status"] == "ok"
    assert by_name["permissions"]["status"] == "ok"


def test_runtime_checks_discord_degraded_and_unavailable(monkeypatch):
    import services.diagnostics as d

    _patch_workers_healthy(monkeypatch)
    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: [])

    connecting = _healthy_bot()
    connecting.is_ready = lambda: False
    connecting.is_connected = lambda: True
    checks = d.build_runtime_diagnostics(connecting)["runtime"]["checks"]
    assert _check_map(checks)["discord"]["status"] == "degraded"

    disconnected = _healthy_bot()
    disconnected.is_ready = lambda: False
    disconnected.is_connected = lambda: False
    checks = d.build_runtime_diagnostics(disconnected)["runtime"]["checks"]
    assert _check_map(checks)["discord"]["status"] == "unavailable"


def test_runtime_checks_collectors_degraded_when_worker_stalled(monkeypatch):
    import services.diagnostics as d
    import services.stats_recorder as stats_recorder

    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: [])
    # Collector task finished (loop died).
    bot = _healthy_bot()
    bot._data_collector = SimpleNamespace(
        _task=SimpleNamespace(done=lambda: True),
        last_run_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(stats_recorder, "_flush_task", SimpleNamespace(done=lambda: False))
    checks = d.build_runtime_diagnostics(bot)["runtime"]["checks"]
    assert _check_map(checks)["collectors"]["status"] == "degraded"

    # Stale collector run (much older than two 15-min intervals).
    from datetime import timedelta

    bot = _healthy_bot()
    bot._data_collector = SimpleNamespace(
        _task=SimpleNamespace(done=lambda: False),
        last_run_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    monkeypatch.setattr(stats_recorder, "_flush_task", SimpleNamespace(done=lambda: False))
    checks = d.build_runtime_diagnostics(bot)["runtime"]["checks"]
    assert _check_map(checks)["collectors"]["status"] == "degraded"


def test_collectors_idle_is_ok_but_pending_counters_without_a_task_degrade(monkeypatch):
    """The stats flusher starts lazily on the first tracked event, so an idle
    instance is healthy — only counters waiting with no live task are a fault.
    (Live check on a freshly booted instance reported degraded here.)"""
    import services.diagnostics as d
    import services.stats_recorder as stats_recorder

    bot = _healthy_bot()
    bot._data_collector = SimpleNamespace(
        _task=SimpleNamespace(done=lambda: False),
        last_run_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(stats_recorder, "_flush_task", None)
    monkeypatch.setattr(stats_recorder, "_pending_messages", {})
    monkeypatch.setattr(stats_recorder, "_pending_emoji", {})
    checks = d.build_runtime_diagnostics(bot)["runtime"]["checks"]
    assert _check_map(checks)["collectors"]["status"] == "ok"

    monkeypatch.setattr(stats_recorder, "_pending_messages", {("1", "2"): [3, "general"]})
    checks = d.build_runtime_diagnostics(bot)["runtime"]["checks"]
    check = _check_map(checks)["collectors"]
    assert check["status"] == "degraded"
    assert "pending counter" in check["detail"]


def test_runtime_checks_modules_degraded_on_load_failure(monkeypatch):
    import services.diagnostics as d

    _patch_workers_healthy(monkeypatch)
    # A built-in module package failed to register.
    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: ["speak"])
    checks = d.build_runtime_diagnostics(_healthy_bot())["runtime"]["checks"]
    modules = _check_map(checks)["modules"]
    assert modules["status"] == "degraded"
    assert "speak" in modules["detail"]


def test_runtime_checks_permissions_degraded_when_guild_blocks_posting(monkeypatch):
    import services.diagnostics as d

    _patch_workers_healthy(monkeypatch)
    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: [])
    bot = _healthy_bot()
    bot.guilds[0].me = SimpleNamespace(
        guild_permissions=SimpleNamespace(send_messages=False, view_channel=True)
    )
    checks = d.build_runtime_diagnostics(bot)["runtime"]["checks"]
    permissions = _check_map(checks)["permissions"]
    assert permissions["status"] == "degraded"
    assert "send_messages" in permissions["detail"]


def test_runtime_checks_unavailable_without_bot():

    checks = build_runtime_diagnostics(None)["runtime"]["checks"]
    by_name = _check_map(checks)
    assert by_name["process"]["status"] == "ok"
    for name in (
        "discord",
        "collectors",
        "modules",
        "permissions",
        "database",
        "scheduler",
        "media_engine",
    ):
        assert by_name[name]["status"] == "unavailable", name


def test_render_report_renders_capability_checks():
    report = {
        "bark": {"version": "0.2.1", "commit": "abc", "branch": "main", "update_channel": "stable"},
        "environment": {
            "platform": "Linux",
            "machine": "x86_64",
            "python_version": "3.13",
            "hostname": "host",
            "install_dir": "/x",
            "install_method": "manual",
            "systemd_active": False,
            "tmp_writable": True,
            "disk_free_bytes": 1024,
            "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "False"},
        "intents": {"message_content": True},
        "git": {"update_remote": "github", "stable_branch": "main", "remotes": [], "refs": {}},
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"log_path": "", "bark_log_tail": []},
        "runtime": {
            "available": True,
            "checks": [
                {"name": "process", "status": "ok", "detail": "PID 1 running"},
                {"name": "discord", "status": "unavailable", "detail": "DISCONNECTED"},
                {"name": "database", "status": "degraded", "detail": "probe slow"},
            ],
        },
    }
    text = render_report(report)
    assert "[Capability checks]" in text
    assert "process: PID 1 running" in text
    assert "discord: DISCONNECTED" in text
    assert "[ degraded  ] database: probe slow" in text


async def test_db_check_ok_and_unavailable(monkeypatch):
    from contextlib import asynccontextmanager

    import database.engine as db_engine
    import services.diagnostics as d

    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return ["probe-row"]

    async def _execute(*a, **k):
        return _Rows()

    session = SimpleNamespace(execute=_execute)

    @asynccontextmanager
    async def _ok_scope():
        yield session

    monkeypatch.setattr(db_engine, "session_scope", _ok_scope)
    assert (await d._db_check())["status"] == "ok"

    @asynccontextmanager
    async def _down_scope():
        raise RuntimeError("db unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(db_engine, "session_scope", _down_scope)
    check = await d._db_check()
    assert check["status"] == "unavailable"
    assert "db unreachable" in check["detail"]


async def test_db_check_leaves_no_scratch_table(monkeypatch):
    """The write probe must prove the real database is writable without leaving
    an unmodeled scratch table behind in every install's database."""
    from contextlib import asynccontextmanager

    import database.engine as db_engine
    import services.diagnostics as d

    statements: list[str] = []

    class _Rows:
        def scalars(self):
            return self

        def all(self):
            return ["probe-row"]

    async def _execute(stmt=None, *a, **k):
        statements.append(str(stmt))
        return _Rows()

    session = SimpleNamespace(execute=_execute)

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(db_engine, "session_scope", _scope)
    assert (await d._db_check())["status"] == "ok"

    joined = " ".join(statements).upper()
    assert "CREATE TABLE IF NOT EXISTS _DIAGNOSTICS_PROBE" in joined
    assert "DROP TABLE IF EXISTS _DIAGNOSTICS_PROBE" in joined


async def test_scheduler_check_states(monkeypatch):
    from contextlib import asynccontextmanager

    import database.engine as db_engine
    import services.diagnostics as d

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    async def _execute(*a, **k):
        return _Rows([("queued", 2), ("failed", 1)])

    session = SimpleNamespace(execute=_execute)

    @asynccontextmanager
    async def _ok_scope():
        yield session

    monkeypatch.setattr(db_engine, "session_scope", _ok_scope)

    # Loop alive + counts readable → ok.
    bot = SimpleNamespace(
        modules=SimpleNamespace(
            get_module=lambda n: SimpleNamespace(_schedule_task=SimpleNamespace(done=lambda: False))
        )
    )
    check = await d._scheduler_check(bot)
    assert check["status"] == "ok"
    assert "2 queued, 1 failed" in check["detail"]

    # Loop dead → degraded even with readable counts.
    bot = SimpleNamespace(
        modules=SimpleNamespace(
            get_module=lambda n: SimpleNamespace(_schedule_task=SimpleNamespace(done=lambda: True))
        )
    )
    check = await d._scheduler_check(bot)
    assert check["status"] == "degraded"
    assert "NOT running" in check["detail"]

    # No modules manager → unavailable.
    check = await d._scheduler_check(SimpleNamespace(modules=None))
    assert check["status"] == "unavailable"


async def test_media_engine_check_ok_and_unreachable():
    import httpx

    import services.diagnostics as d
    from services.media_engine.client import MediaEngineClient

    ok_client = MediaEngineClient(
        base_url="http://engine.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
    )
    assert (await d._media_engine_check(ok_client))["status"] == "ok"

    def _down(request):
        raise httpx.ConnectError("connection refused")

    down_client = MediaEngineClient(
        base_url="http://engine.test", transport=httpx.MockTransport(_down)
    )
    check = await d._media_engine_check(down_client)
    assert check["status"] == "unavailable"


async def test_build_runtime_diagnostics_async_appends_async_checks(monkeypatch):
    import services.diagnostics as d

    _patch_workers_healthy(monkeypatch)
    monkeypatch.setattr(d, "_failed_to_load", lambda mgr: [])

    async def _db():
        return {"name": "database", "status": "ok", "detail": "probe ok"}

    async def _scheduler(bot):
        return {"name": "scheduler", "status": "degraded", "detail": "loop down"}

    async def _media(client=None):
        return {"name": "media_engine", "status": "unavailable", "detail": "unreachable"}

    monkeypatch.setattr(d, "_db_check", _db)
    monkeypatch.setattr(d, "_scheduler_check", _scheduler)
    monkeypatch.setattr(d, "_media_engine_check", _media)

    report = await build_runtime_diagnostics_async(_healthy_bot())
    rt = report["runtime"]
    by_name = _check_map(rt["checks"])
    # All eight required capabilities present with valid statuses.
    assert set(by_name) >= {
        "process",
        "discord",
        "collectors",
        "modules",
        "permissions",
        "database",
        "scheduler",
        "media_engine",
    }
    assert all(c["status"] in _CHECK_STATUSES for c in rt["checks"])
    assert by_name["database"]["status"] == "ok"
    assert by_name["scheduler"]["status"] == "degraded"
    assert by_name["media_engine"]["status"] == "unavailable"
    # Pre-existing keys are untouched.
    assert rt["available"] is True
    assert rt["guild_count"] == 1
    assert rt["latency_ms"] == 12.3
