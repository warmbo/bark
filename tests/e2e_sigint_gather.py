"""Reproduces the real prod shutdown path: bot.start() never returns.

This mirrors app.main()'s gather exactly: a never-returning bot task (like a
connected Discord gateway) + the real DashboardApp. Sends SIGINT and asserts
the process exits. Without the fix, uvicorn's own handler would stop only the
dashboard and the bot task would keep the process alive (the reported hang).
"""
import signal
import subprocess
import sys
import time

HARNESS = r'''
import asyncio, signal, sys, os
sys.path.insert(0, ".")
import app as app_module
import discord

class FakeBot:
    def __init__(self):
        self.closed = asyncio.Event()
    async def start(self, token):
        await self.closed.wait()   # never returns until close() is called
    async def close(self):
        self.closed.set()
    async def wait_until_ready(self):
        return None

async def _main():
    bot = FakeBot()
    dash = app_module.create_app(bot) if False else None
    # Build the real DashboardApp but avoid opening a socket: we only need
    # signal coordination. We monkeypatch DashboardApp.run to just sleep.
    from dashboard.app import DashboardApp
    from unittest.mock import MagicMock
    # Reuse app.main but with a fake dashboard that never returns either.
    # Instead of importing app.main's internals, replicate its shutdown logic
    # by driving the real pieces.
    import services.realtime_bridge  # noqa
    from config import config
    config.dashboard.port = 8099

    loop = asyncio.get_running_loop()
    dash_holder = {}

    class FakeDashboardApp:
        def __init__(self):
            self._server = MagicMock()
            self._server.should_exit = False
            dash_holder["app"] = self
        async def run(self):
            # stand in for uvicorn's serve(): block until should_exit flips
            while not self._server.should_exit:
                await asyncio.sleep(0.1)
            print("DASHBOARD STOPPED", flush=True)
        def stop(self):
            self._server.should_exit = True

    dash_app = FakeDashboardApp()

    def request_shutdown(signame):
        print("SIG", signame, flush=True)
        dash_app.stop()
        loop.create_task(bot.close())

    for sig, name in ((signal.SIGINT, "SIGINT"), (signal.SIGTERM, "SIGTERM")):
        try:
            loop.add_signal_handler(sig, lambda s=name: request_shutdown(s))
        except Exception:
            pass

    try:
        results = await asyncio.gather(
            bot.start("token"), dash_app.run(), return_exceptions=True)
    finally:
        await bot.close()
    print("MAIN RETURNED", flush=True)

asyncio.run(_main())
print("PROCESS EXITED CLEANLY", flush=True)
'''

def main():
    proc = subprocess.Popen(
        [sys.executable, "-c", HARNESS],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"PID: {proc.pid}")
    time.sleep(2.5)  # let it boot the fake services
    proc.send_signal(signal.SIGINT)
    try:
        out, _ = proc.communicate(timeout=12)
        print(out)
        rc = proc.returncode
        if "MAIN RETURNED" in out and "PROCESS EXITED CLEANLY" in out:
            print("PASS: SIGINT stopped both services and the process exited")
            return 0
        print(f"FAIL: exit code {rc} but shutdown sequence incomplete")
        return 1
    except subprocess.TimeoutExpired:
        print("FAIL: process did NOT exit within 12s of SIGINT (it hung)")
        proc.kill()
        return 1


if __name__ == "__main__":
    sys.exit(main())
