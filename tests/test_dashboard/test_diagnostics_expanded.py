"""Expanded diagnostics: runtime report, module diagnose() hooks, multi-instance
detection, and the guild-scoped diagnostics endpoint.

These exercise the "EVERYTHING WE CAN" expansion: a live runtime section that
enumerates modules + guilds and flags servers where more than one Bark bot is
present (the failure mode where Reputation stops posting a leaderboard/scores).
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from services.diagnostics import build_runtime_diagnostics, render_report


def _fake_guild(gid, name, member_count, owner_id, members):
    guild = SimpleNamespace(
        id=gid,
        name=name,
        member_count=member_count,
        owner_id=owner_id,
        members=members,
        users=members,
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(
                **{p: True for p in ("view_channel", "send_messages", "manage_messages")}
            )
        ),
    )
    return guild


def _fake_bot_user(uid, uname, bot=False):
    return SimpleNamespace(id=uid, name=uname, bot=bot)


def _fake_module(name, enabled_for=None, diagnose_result=None, per_guild=True):
    """A minimal stand-in for a discovered BarkModule."""
    module = SimpleNamespace(
        name=name,
        version="1.0.0",
        get_commands=lambda: [],
        get_events=lambda: [],
        get_dashboard_pages=lambda: [],
        get_permissions=lambda: [],
        get_settings_schema=lambda: {"properties": {}},
    )
    if per_guild and diagnose_result is not None:
        module.diagnose = lambda gid: diagnose_result
    else:
        module.diagnose = lambda gid=None: {"module": name, "enabled_globally": True}
    return module


def _fake_modules_mgr(modules, enabled_map):
    mgr = SimpleNamespace()
    mgr.get_all_modules = lambda: modules
    mgr.get_module = lambda n: modules.get(n)
    mgr.should_run_globally = lambda n: True
    mgr.is_enabled_for_guild = lambda gid, n: enabled_map.get((int(gid), n), False)
    return mgr


def test_runtime_diagnostics_enumerates_modules_and_guilds():
    # Guild 1 has TWO bark bots (our + an impostor) → multi-instance conflict.
    our = _fake_bot_user(111, "Bark", bot=True)
    impostor = _fake_bot_user(222, "Bark Backup", bot=True)
    human = _fake_bot_user(333, "Alice", bot=False)
    guild1 = _fake_guild(1, "Shared Server", 50, "9", [our, impostor, human])

    rep = _fake_module("reputation", diagnose_result={"module": "reputation", "status": "conflict", "other_bark_instances": [{"id": "222", "name": "Bark Backup", "bot": True}]})
    mods = {"reputation": rep}
    mgr = _fake_modules_mgr(mods, {(1, "reputation"): True})

    bot = SimpleNamespace(
        user=our,
        guilds=[guild1],
        modules=mgr,
    )

    report = build_runtime_diagnostics(bot)
    rt = report["runtime"]
    assert rt["available"] is True
    assert rt["guild_count"] == 1
    assert rt["modules"]["count"] == 1
    assert rt["modules"]["items"][0]["name"] == "reputation"
    # Per-guild diagnose surfaced.
    per_guild = rt["modules"]["items"][0].get("per_guild", [])
    assert any(g["guild_id"] == "1" for g in per_guild)

    # Guild section + multi-instance conflict captured.
    assert rt["guilds"]["count"] == 1
    assert rt["guilds"]["items"][0]["enabled_modules"] == ["reputation"]
    assert rt["guilds"]["items"][0]["other_bark_instances"] == [{"id": "222", "name": "Bark Backup", "bot": True}]
    assert len(rt["multi_instance_conflicts"]) == 1
    assert rt["multi_instance_conflicts"][0]["bots"] == [{"id": "222", "name": "Bark Backup", "bot": True}]


def test_runtime_diagnostics_clean_when_no_conflict():
    our = _fake_bot_user(111, "Bark")
    guild = _fake_guild(7, "Clean Server", 12, "5", [our])
    mgr = _fake_modules_mgr({}, {})
    bot = SimpleNamespace(user=our, guilds=[guild], modules=mgr)
    report = build_runtime_diagnostics(bot)
    assert report["runtime"]["multi_instance_conflicts"] == []
    assert report["runtime"]["guilds"]["items"][0]["other_bark_instances"] == []


def test_render_report_includes_runtime_section():
    our = _fake_bot_user(111, "Bark", bot=True)
    impostor = _fake_bot_user(222, "Bark Backup", bot=True)
    guild = _fake_guild(1, "Shared Server", 50, "9", [our, impostor])
    rep = _fake_module("reputation", diagnose_result={"module": "reputation", "status": "conflict", "other_bark_instances": [{"id": "222", "name": "Bark Backup", "bot": True}]})
    mgr = _fake_modules_mgr({"reputation": rep}, {(1, "reputation"): True})
    bot = SimpleNamespace(user=our, guilds=[guild], modules=mgr)
    runtime = build_runtime_diagnostics(bot)
    # render_report expects the full report shape (bark/env/config/... present).
    report = {
        "bark": {"version": "0.2.1", "commit": "abc", "branch": "main", "update_channel": "stable"},
        "environment": {
            "platform": "Linux", "machine": "x86_64", "python_version": "3.13",
            "hostname": "host", "install_dir": "/x", "install_method": "manual",
            "systemd_active": False, "tmp_writable": True,
            "disk_free_bytes": 1024, "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "False"},
        "intents": {"message_content": True},
        "git": {"update_remote": "github", "stable_branch": "main", "remotes": [], "refs": {}},
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"log_path": "", "bark_log_tail": []},
        **runtime,
    }
    text = render_report(report)
    assert "[Live runtime]" in text
    assert "[Multi-instance conflicts]" in text
    assert "OTHER BARK INSTANCES" in text
    assert "Shared Server" in text


def test_reputation_diagnose_flags_multi_instance(monkeypatch):
    """Reputation.diagnose() must report the shared-server conflict."""
    import asyncio

    from modules.reputation.module import ReputationModule
    from services.bark_context import BarkContext

    our = _fake_bot_user(111, "Bark", bot=True)
    impostor = _fake_bot_user(222, "Bark Backup", bot=True)
    guild = _fake_guild(1, "Shared Server", 50, "9", [our, impostor])

    bot = SimpleNamespace(
        user=our,
        guilds=[guild],
        get_guild=lambda gid: guild if int(gid) == 1 else None,
        modules=SimpleNamespace(should_run_globally=lambda n: True),
    )
    ctx = BarkContext(bot, SimpleNamespace())
    # Avoid DB/network in diagnose by stubbing config + score queries.
    module = ReputationModule(ctx)
    monkeypatch.setattr(
        ctx, "get_module_config",
        lambda name, gid: {"leaderboard_size": 10, "enabled_sources": {"messages": True}, "showoff_channel_id": ""},
    )

    result = asyncio.run(module.diagnose(1))
    assert result["module"] == "reputation"
    assert result["status"] == "conflict"
    assert result["other_bark_instances"] == [{"id": "222", "name": "Bark Backup", "bot": True}]
    assert "double-count" in result["note"]


@pytest.mark.asyncio
async def test_guild_diagnostics_endpoint_requires_admin(db, monkeypatch):
    """GET /api/v1/guilds/{id}/diagnostics is gated to owner/admin."""
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from httpx import ASGITransport, AsyncClient

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        await session.commit()

    bot = SimpleNamespace(user=_fake_bot_user(111, "Bark", bot=True), guilds=[], modules=SimpleNamespace(event_bus=SimpleNamespace()))
    app = create_app(bot)

    monkeypatch.setattr(
        "dashboard.routes.api.guilds.can_manage_instance", lambda request: False
    )
    monkeypatch.setattr(
        "dashboard.routes.api.guilds.check_api_permission",
        lambda *a, **k: False,
    )
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/guilds/1/diagnostics")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_guild_diagnostics_endpoint_returns_report(db, monkeypatch):
    """Owner can download a guild-scoped diagnostic report."""
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from httpx import ASGITransport, AsyncClient

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        await session.commit()

    our = _fake_bot_user(111, "Bark", bot=True)
    impostor = _fake_bot_user(222, "Bark Backup", bot=True)
    guild = _fake_guild(1, "Shared Server", 50, "9", [our, impostor])

    rep_module = SimpleNamespace(
        name="reputation",
        version="1.0.0",
        diagnose=lambda gid: {"module": "reputation", "status": "conflict", "other_bark_instances": [{"id": "222", "name": "Bark Backup", "bot": True}]},
    )
    mgr = SimpleNamespace(
        get_all_modules=lambda: {"reputation": rep_module},
        get_module=lambda n: rep_module,
        is_enabled_for_guild=lambda gid, n: True,
        event_bus=SimpleNamespace(),
    )
    bot = SimpleNamespace(
        user=our,
        guilds=[guild],
        get_guild=lambda gid: guild if int(gid) == 1 else None,
        modules=mgr,
    )
    app = create_app(bot)

    monkeypatch.setattr(
        "dashboard.routes.api.guilds.can_manage_instance", lambda request: True
    )
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/guilds/1/diagnostics")
    assert resp.status_code == 200
    body = resp.text
    assert "Bark guild diagnostic report" in body
    assert "Shared Server" in body
    assert "OTHER BARK INSTANCES IN THIS SERVER" in body
    assert "reputation" in body
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_reputation_diagnose_reports_rejection_ledger_and_issues(monkeypatch):
    """Reputation.diagnose() surfaces silently-swallowed Discord rejections and
    permission/misconfiguration gaps."""
    import asyncio

    from modules.reputation.module import ReputationModule
    from services.bark_context import BarkContext

    our = _fake_bot_user(111, "Bark", bot=True)
    guild = _fake_guild(1, "Clean Server", 50, "9", [our])
    bot = SimpleNamespace(
        user=our,
        guilds=[guild],
        get_guild=lambda gid: guild if int(gid) == 1 else None,
        modules=SimpleNamespace(should_run_globally=lambda n: True),
    )
    ctx = BarkContext(bot, SimpleNamespace())
    module = ReputationModule(ctx)

    async def _cfg(name, gid):
        return {"leaderboard_size": 10, "enabled_sources": {"messages": True}, "showoff_channel_id": ""}

    monkeypatch.setattr(ctx, "get_module_config", _cfg)

    # Simulate a showoff rejection that the code silently swallowed.
    module._record_rejection(1, "showoff_forbidden", "no permission to send to channel 999")
    result = asyncio.run(module.diagnose(1))
    assert result["status"] == "attention"
    assert result["recent_rejections"] == [
        {"ts": result["recent_rejections"][0]["ts"], "kind": "showoff_forbidden", "detail": "no permission to send to channel 999"}
    ]
    assert any("showoff_forbidden" in i for i in result["issues"])


def test_reputation_diagnose_flags_bot_cannot_send_to_showoff(monkeypatch):
    """When the bot can't send to the configured showoff channel, diagnose()
    reports the permission gap."""
    import asyncio

    from modules.reputation.module import ReputationModule
    from services.bark_context import BarkContext

    our = _fake_bot_user(111, "Bark", bot=True)
    # Channel the bot can VIEW but NOT send to.
    chan_perms = SimpleNamespace(view_channel=True, send_messages=False)
    channel = SimpleNamespace(
        id=999,
        permissions_for=lambda member: chan_perms,
    )
    guild = SimpleNamespace(
        id=1,
        name="Clean Server",
        member_count=50,
        owner_id="9",
        members=[our],
        users=[our],
        me=our,
        get_channel=lambda cid: channel if cid == 999 else None,
    )
    bot = SimpleNamespace(
        user=our,
        guilds=[guild],
        get_guild=lambda gid: guild if int(gid) == 1 else None,
        modules=SimpleNamespace(should_run_globally=lambda n: True),
    )
    ctx = BarkContext(bot, SimpleNamespace())
    module = ReputationModule(ctx)

    async def _cfg(name, gid):
        return {"leaderboard_size": 10, "showoff_channel_id": "999"}

    monkeypatch.setattr(ctx, "get_module_config", _cfg)
    result = asyncio.run(module.diagnose(1))
    assert result["showoff_channel"]["bot_can_send"] is False
    assert any("cannot send messages" in i for i in result["issues"])


def test_reputation_diagnose_flags_all_sources_disabled(monkeypatch):
    """When every scoring source is off, diagnose() flags the config drift so
    'reputation isn't working' is explained (no points can accrue)."""
    import asyncio

    from modules.reputation.module import ReputationModule
    from services.bark_context import BarkContext

    our = _fake_bot_user(111, "Bark", bot=True)
    guild = _fake_guild(1, "Clean Server", 50, "9", [our])
    bot = SimpleNamespace(
        user=our,
        guilds=[guild],
        get_guild=lambda gid: guild if int(gid) == 1 else None,
        modules=SimpleNamespace(should_run_globally=lambda n: True),
    )
    ctx = BarkContext(bot, SimpleNamespace())
    module = ReputationModule(ctx)

    async def _cfg(name, gid):
        return {
            "leaderboard_size": 10,
            "enabled_sources": {"messages": False, "reactions": False, "voice": False},
            "showoff_channel_id": "",
        }

    monkeypatch.setattr(ctx, "get_module_config", _cfg)
    result = asyncio.run(module.diagnose(1))
    assert any("scoring sources are disabled" in i for i in result["issues"])


def test_runtime_diagnostics_handles_none_bot():
    """A report must still render a [Live runtime] block when no bot is wired."""
    report = build_runtime_diagnostics(None)
    rt = report["runtime"]
    assert rt["available"] is False
    assert rt["guild_count"] == 0
    # Render a full-shaped report with the runtime.
    full = {
        "bark": {"version": "0.2.1", "commit": "abc", "branch": "main", "update_channel": "stable"},
        "environment": {
            "platform": "Linux", "machine": "x86_64", "python_version": "3.13",
            "hostname": "host", "install_dir": "/x", "install_method": "manual",
            "systemd_active": False, "tmp_writable": True,
            "disk_free_bytes": 1024, "disk_total_bytes": 2048,
        },
        "config": {"dashboard_host": "127.0.0.1", "oauth_enabled": "False"},
        "intents": {"message_content": True},
        "git": {"update_remote": "github", "stable_branch": "main", "remotes": [], "refs": {}},
        "update": {"last_check_error": "", "log_tail": []},
        "logs": {"log_path": "", "bark_log_tail": []},
        **report,
    }
    text = render_report(full)
    assert "[Live runtime]" in text
    assert "bot runtime unavailable" in text


def test_runtime_diagnostics_reports_bot_connection_status():
    """The runtime section surfaces connection state so a pasted report shows
    whether the bot is online (which gates whether modules can post/score)."""
    bot = SimpleNamespace(
        user=SimpleNamespace(id=111, name="Bark"),
        guilds=[],
        modules=SimpleNamespace(get_all_modules=lambda: {}),
        is_ready=lambda: False,
        is_connected=lambda: False,
        latency=12.3,
    )
    report = build_runtime_diagnostics(bot)
    rt = report["runtime"]
    assert rt["is_ready"] is False
    assert rt["is_connected"] is False
    assert rt["latency_ms"] == 12.3
    assert rt["bot_id"] == "111"


@pytest.mark.asyncio
async def test_privacy_and_terms_pages_are_public(db):
    """Privacy/Terms pages (needed for Discord verification) are reachable
    without authentication."""
    from dashboard import create_app
    from database.engine import session_scope
    from database.models.guild import Guild
    from httpx import ASGITransport, AsyncClient

    async with session_scope() as session:
        session.add(Guild(discord_id="1", name="Test Guild"))
        await session.commit()

    bot = SimpleNamespace(
        user=SimpleNamespace(id=111, name="Bark", bot=True),
        guilds=[],
        modules=SimpleNamespace(event_bus=SimpleNamespace(), get_all_modules=lambda: {}),
        is_ready=lambda: True,
        is_connected=lambda: True,
    )
    app = create_app(bot)
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        privacy = await client.get("/privacy")
        terms = await client.get("/terms")
    assert privacy.status_code == 200
    assert "Bark Privacy Policy" in privacy.text
    assert terms.status_code == 200
    assert "Bark Terms of Service" in terms.text
