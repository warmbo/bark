"""The one-line installer must work piped to any shell (bash/sh/zsh/fish).

fish (and other non-POSIX shells) parse the entire piped script before
running anything, so `install.sh` (the launcher) must be written only in the
syntax shared by fish and POSIX shells — a plain command with `&&`. It must
NOT contain POSIX-isms fish rejects (``${VAR:-default}``, ``$()``, ``local``)
on any executable line, and it must hand the real installer (`install-main.sh`)
off to bash.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
INSTALL_MAIN = ROOT / "install-main.sh"

# Constructs fish rejects (full-parse) that must never appear on an
# executable line of the launcher.
FISH_HOSTILE = ("${", "$(", "local ", "export ")


def _executable_lines(path: Path) -> list[str]:
    """Non-comment, non-shebang lines — i.e. what a shell actually runs."""
    lines = []
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("#!"):
            continue
        lines.append(s)
    return lines


def test_install_launcher_handoff_to_bash():
    assert INSTALL.exists(), "install.sh launcher missing"
    exec_lines = _executable_lines(INSTALL)

    # The launcher is one statement: fetch install-main.sh and run it under bash.
    assert len(exec_lines) == 1, f"launcher should be a single command, got: {exec_lines}"
    line = exec_lines[0]
    assert "install-main.sh" in line, "launcher must reference the real installer"
    assert "&& bash " in line, "launcher must hand off to bash with &&"

    # No fish-hostile POSIX-isms on the executable line.
    for bad in FISH_HOSTILE:
        assert bad not in line, f"launcher uses fish-hostile construct {bad!r}"


def test_install_launcher_parses_in_other_shells():
    # Parse-check the launcher under every available shell. bash/sh are
    # always present; fish is optional (skip gracefully if absent).
    checked = []
    for shell in ("sh", "bash"):
        if shutil.which(shell):
            subprocess.run([shell, "-n", str(INSTALL)], check=True)
            checked.append(shell)
    fish = shutil.which("fish")
    if fish:
        subprocess.run([fish, "-n", str(INSTALL)], check=True)
        checked.append("fish")
    assert checked, "no shell available to parse-check the launcher"


def test_install_main_is_bash_valid():
    assert INSTALL_MAIN.exists(), "install-main.sh missing"
    assert shutil.which("bash"), "bash is required to run the installer"
    subprocess.run(["bash", "-n", str(INSTALL_MAIN)], check=True)
