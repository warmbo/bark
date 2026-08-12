"""Real SIGINT test against a live Bark process (dev server, mock mode).

Boots `run_dev_server.py` (mock dashboard, no Discord token), waits for the
dashboard to come up, sends SIGINT, and asserts the process actually exits
within a timeout. This is the exact scenario that used to hang.
"""
import signal
import socket
import subprocess
import sys
import time
import urllib.request

PORT = 8099  # scratch port; must not clash with running instances


def wait_for_port(port, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    proc = subprocess.Popen(
        [sys.executable, "run_dev_server.py"],
        env={**__import__("os").environ, "BARK_DASHBOARD_PORT": str(PORT)},
        cwd=".",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(f"PID: {proc.pid}")
    try:
        if not wait_for_port(PORT):
            print("FAIL: dashboard never came up")
            proc.kill()
            return 1
        # Confirm the HTTP endpoint responds (proof it's really serving).
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/", timeout=5
            ) as resp:
                print(f"HTTP status: {resp.status}")
        except Exception as e:
            print(f"WARN: health GET failed: {e}")

        # The core assertion: SIGINT must terminate the process.
        proc.send_signal(signal.SIGINT)
        try:
            rc = proc.wait(timeout=15)
            print(f"PASS: process exited with code {rc} after SIGINT")
            return 0
        except subprocess.TimeoutExpired:
            print("FAIL: process did NOT exit within 15s of SIGINT (it hung)")
            proc.kill()
            return 1
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
