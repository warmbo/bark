"""Signal-driven shutdown coordination tests.

Verifies that Bark owns the process's SIGINT/SIGTERM handlers (rather than
letting uvicorn hijack them), so a bare `kill -INT` stops the bot, the
dashboard, and closes the database together instead of hanging the process
with the Discord client still running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dashboard.app import DashboardApp, _SignalNeutralServer


def test_signal_neutral_server_does_not_capture_signals():
    """uvicorn's capture_signals is the no-op override, not the real one."""
    server = _SignalNeutralServer(MagicMock())
    # It's a context manager that yields without installing handlers.
    with server.capture_signals():
        pass  # reaching here means we never touched signal.signal


def test_dashboard_app_stop_flips_should_exit():
    """DashboardApp.stop() tells uvicorn's server to exit (safe from a handler)."""
    server = MagicMock()
    server.should_exit = False
    dashboard = DashboardApp(app=MagicMock(), bot=MagicMock())
    dashboard._server = server
    dashboard.stop()
    assert server.should_exit is True


def test_dashboard_app_stop_is_safe_before_run():
    """stop() before run() (server not yet created) must not raise."""
    dashboard = DashboardApp(app=MagicMock(), bot=MagicMock())
    assert dashboard._server is None
    dashboard.stop()  # no-op, no exception


@pytest.mark.asyncio
async def test_main_installs_signal_handlers(monkeypatch):
    """main() registers coordinated SIGINT/SIGTERM handlers on the loop."""
    import asyncio
    import signal

    import app as app_module

    bot = MagicMock(start=AsyncMock(), close=AsyncMock(), wait_until_ready=AsyncMock())
    dashboard = MagicMock(run=AsyncMock(), stop=MagicMock())
    close_db = AsyncMock()

    # The mock dashboard/init/startup; bot.start returns immediately.
    monkeypatch.setattr(app_module.config, "validate_startup", MagicMock())
    monkeypatch.setattr(app_module, "init_db", AsyncMock())
    monkeypatch.setattr(app_module, "close_db", close_db)
    monkeypatch.setattr(app_module, "BarkBot", MagicMock(return_value=bot))
    monkeypatch.setattr(app_module, "create_app", MagicMock(return_value=dashboard))

    loop = asyncio.get_running_loop()
    installed: list[int] = []

    def fake_add_signal_handler(sig, callback):
        installed.append(sig)

    monkeypatch.setattr(loop, "add_signal_handler", fake_add_signal_handler)

    await app_module.main()

    assert signal.SIGINT in installed
    assert signal.SIGTERM in installed
    bot.close.assert_awaited_once()
    close_db.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_handler_stops_dashboard_and_bot(monkeypatch):
    """The installed handler must stop the dashboard and close the bot."""
    import asyncio
    import signal

    import app as app_module

    bot = MagicMock(start=AsyncMock(), close=AsyncMock(), wait_until_ready=AsyncMock())
    dashboard = MagicMock(run=AsyncMock(), stop=MagicMock())
    close_db = AsyncMock()

    monkeypatch.setattr(app_module.config, "validate_startup", MagicMock())
    monkeypatch.setattr(app_module, "init_db", AsyncMock())
    monkeypatch.setattr(app_module, "close_db", close_db)
    monkeypatch.setattr(app_module, "BarkBot", MagicMock(return_value=bot))
    monkeypatch.setattr(app_module, "create_app", MagicMock(return_value=dashboard))

    loop = asyncio.get_running_loop()
    captured: list = []

    def fake_add_signal_handler(sig, callback):
        captured.append((sig, callback))

    monkeypatch.setattr(loop, "add_signal_handler", fake_add_signal_handler)

    await app_module.main()

    # Fire the SIGINT handler and let its scheduled bot.close() task run.
    sigint_callback = next(cb for sig, cb in captured if sig == signal.SIGINT)
    sigint_callback()
    await asyncio.sleep(0)

    dashboard.stop.assert_called()
    # close is awaited both by the handler's scheduled task and main's finally.
    bot.close.assert_awaited()
    close_db.assert_awaited_once()
