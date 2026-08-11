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

    # Stage the bootstrap in $HOME, not /tmp — a full/read-only tmpfs used to
    # kill the download with a cryptic "curl: (23)" before the installer ran.
    assert '"$HOME/bark-install-main.sh"' in line, "launcher must stage in $HOME"
    assert "/tmp/bark-install-main.sh" not in line, "launcher must not stage in /tmp"

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


def test_install_stops_old_instance_before_update():
    """The update path (existing .git) must stop the running instance BEFORE
    mutating the checkout — git reset/pip must not race a live process, and the
    dashboard port must be freed for rebind."""
    src = INSTALL_MAIN.read_text()

    # The stop helper exists and is referenced from the update branch.
    assert "stop_old_instance()" in src, "stop_old_instance helper missing"

    # It must be invoked inside the "existing install" (update) branch, before
    # any git fetch/reset that mutates the tree.
    update_branch = src.split("Updating existing install", 1)[1]
    upd_head = update_branch.split("# ──", 1)[0]  # up to the next section marker
    stop_idx = upd_head.find("stop_old_instance")
    fetch_idx = upd_head.find("git -C")
    assert stop_idx != -1, "stop_old_instance not called in the update path"
    assert (
        stop_idx < fetch_idx
    ), "stop_old_instance must run before git mutates the checkout"

    # The helper stops the systemd unit if active...
    assert "systemctl --user is-active bark.service" in src
    assert "systemctl --user stop bark.service" in src

    # ...and kills only stray bark processes whose cwd is the install dir
    # (never unrelated processes), self-exclusion included.
    assert "pgrep -f" in src and "readlink" in src
    assert '"$cwd" = "$BARK_INSTALL_DIR"' in src, "must scope the kill by cwd"
    assert '= "$$"' in src, "must never kill itself"


def test_install_main_cleans_launcher_staging_file():
    """install-main.sh must remove its own launcher bootstrap file (the new
    $HOME path and the legacy /tmp path) so a successful install leaves no
    droppings behind. Unlink of the file we run from is safe on Linux."""
    src = INSTALL_MAIN.read_text()
    assert 'rm -f "$HOME/bark-install-main.sh" /tmp/bark-install-main.sh' in src


def test_install_main_disk_preflight():
    """Before cloning, install-main.sh must check the target is writable and
    has room, and die with a clear message (not a cryptic curl/git/pip write
    failure) when it does not."""
    src = INSTALL_MAIN.read_text()
    assert "nearest_existing_dir()" in src
    assert "check_writable_with_space()" in src
    # Invoked for the install dir with a ~512 MB requirement.
    assert (
        'check_writable_with_space "install directory" "$BARK_INSTALL_DIR" 524288'
        in src
    )
    # Clear, human-readable failure messages.
    assert "Not enough free space" in src
    assert "is not writable" in src


def test_install_main_never_relies_on_tmp():
    """A host with an unwritable /tmp (managed images, corporate lockdown,
    full/read-only tmpfs) must not break the install. The installer must point
    TMPDIR/TEMP/TMP at a writable dir under $HOME before any temp-using step
    (mktemp venv probe, pip, venv, git)."""
    src = INSTALL_MAIN.read_text()

    # Default temp dir is under $HOME, overridable.
    assert 'BARK_TMPDIR="${BARK_TMPDIR:-$HOME/.bark-tmp}"' in src
    # Export the writable dir so every temp consumer honors it.
    assert 'export TMPDIR="$BARK_TMPDIR" TEMP="$BARK_TMPDIR" TMP="$BARK_TMPDIR"' in src
    # Clear failure when neither the override nor /tmp is writable.
    assert "Set BARK_TMPDIR to a writable path" in src
    # The temp dir is also space/writability pre-flighted.
    assert 'check_writable_with_space "temp directory" "$BARK_TMPDIR" 8192' in src

    # The TMPDIR export must come BEFORE the first mktemp (venv probe) so the
    # probe — and pip/venv/git that follow — use the writable dir, not /tmp.
    tmdir_export = src.index('export TMPDIR="$BARK_TMPDIR"')
    first_mktemp = src.index("mktemp -d")
    assert tmdir_export < first_mktemp, "TMPDIR must be set before any mktemp"
