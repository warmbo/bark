#!/usr/bin/env bash
# Bark — one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
#
# Installs everything Bark needs (git, curl, Python 3.13+), clones the
# repository, creates the virtualenv, and either installs a systemd user
# service or boots the first-time setup wizard — no .env hand-editing.
#
# Overrides (env vars):
#   BARK_REPO_URL      git URL to install from (default: warmbo/bark on GitHub)
#   BARK_BRANCH        branch to check out (default: main)
#   BARK_INSTALL_DIR   where to install (default: $HOME/bark)
#   BARK_SYSTEMD       auto | yes | no  (default: auto — use systemd when available)
#   BARK_INSTALL_HOST  dashboard bind address (default: 127.0.0.1 — set 0.0.0.0 for LAN)
#   BARK_INSTALL_PORT  dashboard port (default: 8090)
#   BARK_NO_START      set to 1 to install without launching anything
set -euo pipefail
# Quiet non-interactive apt + avoid perl locale warnings in containers.
export DEBIAN_FRONTEND=noninteractive
export LANG="${LANG:-C.UTF-8}" LC_ALL="${LC_ALL:-C.UTF-8}"

BARK_REPO_URL="${BARK_REPO_URL:-https://github.com/warmbo/bark.git}"
BARK_BRANCH="${BARK_BRANCH:-main}"
BARK_INSTALL_DIR="${BARK_INSTALL_DIR:-$HOME/bark}"
BARK_SYSTEMD="${BARK_SYSTEMD:-auto}"
BARK_INSTALL_HOST="${BARK_INSTALL_HOST:-127.0.0.1}"
BARK_INSTALL_PORT="${BARK_INSTALL_PORT:-8090}"
BARK_NO_START="${BARK_NO_START:-0}"

log()  { printf '\033[1;34m[bark]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bark]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[bark]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

python_new_enough() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null
}

resolve_python() {
    if have python3 && python_new_enough python3; then
        PY=python3
    elif have python3.13 && python_new_enough python3.13; then
        PY=python3.13
    else
        PY=""
    fi
}

install_python() {
    log "Python 3.13+ not found — installing it"
    if [ "$(id -u)" -ne 0 ] && ! have sudo; then
        die "Python 3.13+ is required. Install it (e.g. 'sudo apt install python3 python3-venv') or run this installer with sudo, then retry."
    fi
    local apt="apt-get"
    [ "$(id -u)" -ne 0 ] && apt="sudo apt-get"

    if have apt-get; then
        # Debian trixie+/Ubuntu with the python3.13 package already available.
        $apt update -qq 2>/dev/null || true
        if $apt install -y -qq python3.13 python3.13-venv >/dev/null 2>&1; then
            PY=python3.13
            return 0
        fi
        # Ubuntu 24.04 LTS: deadsnakes PPA provides python3.13.
        if have add-apt-repository && . /etc/os-release 2>/dev/null && [ "${ID:-}" = "ubuntu" ]; then
            log "Adding deadsnakes PPA for Python 3.13"
            sudo add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1
            $apt update -qq 2>/dev/null || true
            if $apt install -y -qq python3.13 python3.13-venv >/dev/null 2>&1; then
                PY=python3.13
                return 0
            fi
        fi
        # Common fallback: distro python3 + venv (works when the distro ships 3.13).
        if $apt install -y -qq python3 python3-venv >/dev/null 2>&1 && python_new_enough python3; then
            PY=python3
            return 0
        fi
    fi
    die "Could not install Python 3.13+ automatically. Install it manually (see https://www.python.org/downloads/), then rerun this installer."
}

# ── 1. System prerequisites ────────────────────────────────
log "Checking prerequisites"
missing=""
have git  || missing="$missing git"
have curl || missing="$missing curl"
if [ -n "$missing" ]; then
    log "Installing missing tools:$missing"
    if have apt-get; then
        if [ "$(id -u)" -eq 0 ]; then apt-get update -qq && apt-get install -y -qq $missing; else sudo apt-get update -qq && sudo apt-get install -y -qq $missing; fi
    else
        die "Please install:$missing (e.g. with your package manager) and rerun."
    fi
fi

resolve_python
if [ -z "${PY:-}" ]; then
    install_python
fi
log "Using Python: $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"

# Debian/Ubuntu don't ship the bundled pip wheels in the base python3 —
# `import ensurepip` succeeds but `python3 -m venv` fails without the
# python3-venv package. Probe actual venv creation instead of trusting
# module presence.
ensure_venv_works() {
    local probe
    probe=$(mktemp -d)
    if ! "$PY" -m venv "$probe" >/dev/null 2>&1 || [ ! -x "$probe/bin/pip" ]; then
        rm -rf "$probe"
        log "Python venv support missing — installing ${PY}-venv"
        if have apt-get; then
            local apt="apt-get"
            [ "$(id -u)" -ne 0 ] && apt="sudo apt-get"
            $apt install -y -qq "${PY}-venv" >/dev/null 2>&1 \
                || $apt install -y -qq python3-venv >/dev/null 2>&1 \
                || true
        fi
        probe=$(mktemp -d)
        if ! "$PY" -m venv "$probe" >/dev/null 2>&1 || [ ! -x "$probe/bin/pip" ]; then
            rm -rf "$probe"
            die "Could not create a Python virtualenv. Install the python3-venv package for this Python and rerun."
        fi
    fi
    rm -rf "$probe"
}
ensure_venv_works

# ── 2. Clone / update the repository ───────────────────────
# Stop a previously installed Bark before mutating its checkout, so git
# reset/pip can't race a live process and the dashboard port is freed for
# rebind. Only ever touches Bark's own unit / processes — never anything else.
stop_old_instance() {
    if have systemctl; then
        if systemctl --user is-active bark.service >/dev/null 2>&1; then
            log "Stopping running Bark service (bark.service)"
            systemctl --user stop bark.service || true
        fi
    fi
    # Stray foreground process (BARK_SYSTEMD=no / manual run.sh): kill any
    # process whose working directory is the install dir and whose command
    # matches the bark launcher/app — never ourselves or unrelated processes.
    if have pgrep && have readlink; then
        for pid in $(pgrep -f "app\.py|run\.sh" 2>/dev/null || true); do
            [ "$pid" = "$$" ] && continue
            cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
            if [ "$cwd" = "$BARK_INSTALL_DIR" ]; then
                log "Stopping stray Bark process (pid $pid)"
                kill "$pid" 2>/dev/null || true
            fi
        done
    fi
}

if [ -d "$BARK_INSTALL_DIR/.git" ]; then
    log "Updating existing install in $BARK_INSTALL_DIR"
    stop_old_instance
    git -C "$BARK_INSTALL_DIR" fetch --quiet origin
    git -C "$BARK_INSTALL_DIR" checkout --quiet "$BARK_BRANCH" || true
    git -C "$BARK_INSTALL_DIR" reset --hard --quiet "origin/$BARK_BRANCH"
else
    log "Cloning Bark into $BARK_INSTALL_DIR"
    mkdir -p "$(dirname "$BARK_INSTALL_DIR")"
    git clone --quiet --branch "$BARK_BRANCH" "$BARK_REPO_URL" "$BARK_INSTALL_DIR"
fi
cd "$BARK_INSTALL_DIR"

# ── 3. Virtualenv + dependencies ───────────────────────────
log "Creating virtualenv"
# A previous failed run can leave a .venv dir with a python but no pip
# (Debian without python3-venv) — check for pip, not just the interpreter.
if [ ! -x .venv/bin/pip ]; then
    if [ -d .venv ]; then
        log "Recreating broken virtualenv"
        rm -rf .venv
    fi
    "$PY" -m venv .venv
fi
log "Installing dependencies (this can take a minute)"
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet .

# ── 4. Service or foreground ───────────────────────────────
port_busy() {
    (exec 3<>"/dev/tcp/127.0.0.1/$BARK_INSTALL_PORT") 2>/dev/null && { exec 3>&-; return 0; } || return 1
}
if port_busy; then
    warn "Port $BARK_INSTALL_PORT is already in use — Bark would fail to bind."
    warn "Pick a free port and rerun:  BARK_INSTALL_PORT=8091 curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash"
    if [ "$BARK_SYSTEMD" != "no" ] && [ "$BARK_NO_START" != "1" ]; then
        die "Aborting before installing the service — the repo is installed at $BARK_INSTALL_DIR; set BARK_INSTALL_PORT to a free port and rerun."
    fi
fi

if [ "$BARK_NO_START" = "1" ]; then
    log "Install complete (not started — BARK_NO_START=1)"
    log "Run it yourself:  cd $BARK_INSTALL_DIR && ./run.sh"
    exit 0
fi

use_systemd="no"
if [ "$BARK_SYSTEMD" = "yes" ]; then
    use_systemd="yes"
elif [ "$BARK_SYSTEMD" = "auto" ] && have systemctl && [ "$(ps -p 1 -o comm= 2>/dev/null || true)" = "systemd" ]; then
    if systemctl --user status >/dev/null 2>&1; then
        use_systemd="yes"
    fi
fi

if [ "$use_systemd" = "yes" ]; then
    log "Installing systemd user service 'bark'"
    unit="$HOME/.config/systemd/user/bark.service"
    mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<EOF
[Unit]
Description=Bark Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BARK_INSTALL_DIR
# Leading '-' ignores a missing .env: on a fresh install the file doesn't exist
# yet (Bark boots into the browser setup wizard). Without the dash, systemd
# fails the whole service start with "unavailable resources or another error".
EnvironmentFile=-$BARK_INSTALL_DIR/.env
Environment=BARK_DASHBOARD_HOST=$BARK_INSTALL_HOST
Environment=BARK_DASHBOARD_PORT=$BARK_INSTALL_PORT
ExecStart=$BARK_INSTALL_DIR/.venv/bin/python $BARK_INSTALL_DIR/app.py
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# The install dir must be writable: the first-time setup wizard writes .env to
# the repo root, and Python writes .pyc/__pycache__ under .venv at runtime.
# ProtectSystem=strict makes everything read-only except ReadWritePaths; adding
# only the .env FILE still fails (file creation needs the parent dir writable),
# so expose the whole $BARK_INSTALL_DIR. Verified live under systemd.
ReadWritePaths=$BARK_INSTALL_DIR
StandardOutput=append:$BARK_INSTALL_DIR/bark.log
StandardError=append:$BARK_INSTALL_DIR/bark.log

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now bark
    sleep 3
    systemctl --user is-active bark >/dev/null 2>&1 || warn "Service installed but not active — check: journalctl --user -u bark -n 50"
    log "Bark service installed and started."
else
    log "Starting Bark in the foreground (Ctrl+C to stop)"
fi

url="http://${BARK_INSTALL_HOST}:${BARK_INSTALL_PORT}/setup"
url_callback="http://${BARK_INSTALL_HOST}:${BARK_INSTALL_PORT}/auth/callback"
log "First-time setup: open $url in your browser"
if [ "$BARK_INSTALL_HOST" = "127.0.0.1" ]; then
    warn "If this is a remote server, use an SSH tunnel:  ssh -L ${BARK_INSTALL_PORT}:127.0.0.1:${BARK_INSTALL_PORT} user@server"
    warn "or reinstall with BARK_INSTALL_HOST=0.0.0.0 for LAN access."
fi
log "Setup steps:"
log "  1. Create an app at https://discord.com/developers/applications -> New Application"
log "  2. Bot -> Reset Token -> copy it; OAuth2 -> copy Client ID / Client Secret"
log "  3. OAuth2 -> Redirects -> add: $url_callback"
log "  4. Paste them into the setup page; Bark writes .env and restarts itself."

if [ "$use_systemd" = "no" ]; then
    cd "$BARK_INSTALL_DIR"
    export BARK_DASHBOARD_HOST="$BARK_INSTALL_HOST"
    export BARK_DASHBOARD_PORT="$BARK_INSTALL_PORT"
    exec ./run.sh
fi
