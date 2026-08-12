#!/usr/bin/env bash
# Bark — one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
#
# Installs everything Bark needs (git, curl, Python 3.13+), clones the
# repository, creates the virtualenv, and either installs a systemd user
# service or boots the first-time setup wizard — no .env hand-editing.
#
# Rootless by default: cloning, the virtualenv, and the systemd *user* unit
# all live under $HOME and need no root. If Python 3.13+ is missing, it is
# provisioned user-locally via uv (no system packages). sudo/apt is only used
# as a last resort to install missing system tools; set BARK_NO_SUDO=1 to
# forbid it entirely.
#
# Overrides (env vars):
#   BARK_REPO_URL      git URL to install from (default: warmbo/bark on GitHub)
#   BARK_BRANCH        branch to check out (default: main)
#   BARK_INSTALL_DIR   where to install (default: $HOME/bark)
#   BARK_SYSTEMD       auto | yes | no  (default: auto — use systemd when available)
#   BARK_INSTALL_HOST  dashboard bind address (default: 127.0.0.1 — set 0.0.0.0 for LAN)
#   BARK_INSTALL_PORT  dashboard port (default: 8090)
#   BARK_NO_START      set to 1 to install without launching anything
#   BARK_NO_SUDO       set to 1 to NEVER call sudo (rootless-only install)
#   BARK_LOCAL_BIN     user bin dir for a uv-managed Python (default: ~/.local/bin)
#   BARK_TMPDIR        writable temp dir (default: $HOME/.bark-tmp). Set this
#                      when the host's /tmp is unwritable — the installer
#                      never relies on /tmp.
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
# Rootless installs: set BARK_NO_SUDO=1 to make the installer NEVER call sudo
# (it will fail with guidance instead of prompting). Python 3.13+ is then
# provisioned user-locally via uv into BARK_LOCAL_BIN (default ~/.local/bin),
# so no system packages are touched.
BARK_NO_SUDO="${BARK_NO_SUDO:-0}"

# Ports < 1024 are privileged — a non-root user can't bind them (Android/Termux
# and unprivileged containers especially). Give a clear error instead of a
# cryptic "Permission denied" at runtime.
if [ "$BARK_INSTALL_PORT" -lt 1024 ] 2>/dev/null && [ "$(id -u)" -ne 0 ]; then
    die "Dashboard port $BARK_INSTALL_PORT is below 1024 — non-root users cannot bind privileged ports. Set BARK_INSTALL_PORT to 1024 or higher (e.g. 8090) and rerun."
fi

log()  { printf '\033[1;34m[bark]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bark]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[bark]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

# Remove our own launcher staging file (downloaded by install.sh into $HOME,
# plus any leftover from the old /tmp path). We run from it, but unlink is
# safe on Linux — bash keeps the inode via its open fd — and it stops a
# successful install from leaving a droppings file behind.
rm -f "$HOME/bark-install-main.sh" /tmp/bark-install-main.sh

# ── 0. Writable temp dir ──────────────────────────────────
# Some hosts have an unwritable /tmp (managed/immutable images, corporate
# lockdowns, a full or read-only tmpfs) that the user cannot fix. Everything
# that touches temp files — mktemp (venv probe below), pip, `python -m venv`,
# git — honors TMPDIR, so point it at a writable dir under the user's home
# BEFORE any of those run. Override with BARK_TMPDIR.
BARK_TMPDIR="${BARK_TMPDIR:-$HOME/.bark-tmp}"
if ! mkdir -p "$BARK_TMPDIR" 2>/dev/null || [ ! -w "$BARK_TMPDIR" ]; then
    die "Cannot use temp dir '$BARK_TMPDIR' and /tmp is not writable on this host. Set BARK_TMPDIR to a writable path (e.g. BARK_TMPDIR=\$HOME/tmp) and rerun."
fi
chmod 700 "$BARK_TMPDIR" 2>/dev/null || true
export TMPDIR="$BARK_TMPDIR" TEMP="$BARK_TMPDIR" TMP="$BARK_TMPDIR"
log "Using temp dir: $BARK_TMPDIR"

have() { command -v "$1" >/dev/null 2>&1; }

LOCAL_BIN="${BARK_LOCAL_BIN:-$HOME/.local/bin}"
PY_PROVIDER="system"
UV_BIN=""

# Any remaining system-package install requires root. BARK_NO_SUDO=1 enforces a
# strict rootless install: we never call sudo/apt and instead fail with
# guidance so a locked-down box can't be mutated.
need_root_or_fail() {
    if [ "$BARK_NO_SUDO" = "1" ]; then
        die "$1 — BARK_NO_SUDO=1 is set, so the installer will not use sudo. Install the missing package yourself (no root) or rerun with BARK_NO_SUDO=0 to allow sudo."
    fi
    if [ "$(id -u)" -ne 0 ] && ! have sudo; then
        die "$1 — requires root or sudo, which is not available."
    fi
}

# Install uv into the user's home ($LOCAL_BIN). Fully rootless. Returns 0 when
# uv is usable (already present, or freshly installed).
ensure_uv() {
    if have uv; then
        UV_BIN="$(command -v uv)"
        return 0
    fi
    if [ -x "$LOCAL_BIN/uv" ]; then
        UV_BIN="$LOCAL_BIN/uv"
        export PATH="$LOCAL_BIN:$PATH"
        return 0
    fi
    if have curl; then
        mkdir -p "$LOCAL_BIN"
        log "Installing uv to $LOCAL_BIN (user-local, no root)"
        if curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$LOCAL_BIN" sh >/dev/null 2>&1 \
            && [ -x "$LOCAL_BIN/uv" ]; then
            UV_BIN="$LOCAL_BIN/uv"
            export PATH="$LOCAL_BIN:$PATH"
            return 0
        fi
        warn "uv install to $LOCAL_BIN failed — will fall back to a system Python"
    fi
    return 1
}

# Provision a standalone CPython 3.13 via uv — no system packages, no root.
provision_python_uv() {
    ensure_uv || return 1
    if ! "$UV_BIN" python install 3.13 >/dev/null 2>&1; then
        return 1
    fi
    PY_PROVIDER="uv"
    log "Provisioned Python 3.13 via uv (user-local, no root)"
    return 0
}

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
    log "Python 3.13+ not found — provisioning a rootless one via uv"
    if provision_python_uv; then
        return 0
    fi
    warn "Could not provision Python 3.13 rootlessly — falling back to a system package install"
    need_root_or_fail "Python 3.13+ is required"
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
    warn "Missing tools:$missing"
    need_root_or_fail "Installing missing system tools:$missing"
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
if [ "$PY_PROVIDER" = "uv" ]; then
    log "Using Python: uv-managed 3.13"
else
    log "Using Python: $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"
fi

# Debian/Ubuntu don't ship the bundled pip wheels in the base python3 —
# `import ensurepip` succeeds but `python3 -m venv` fails without the
# python3-venv package. Probe actual venv creation instead of trusting
# module presence.
ensure_venv_works() {
    local probe
    if [ "$PY_PROVIDER" = "uv" ]; then
        # uv venv always carries a matching interpreter + pip — no system pkg.
        probe=$(mktemp -d)
        if "$UV_BIN" venv --python 3.13 "$probe" >/dev/null 2>&1 && [ -x "$probe/bin/python" ]; then
            rm -rf "$probe"
            return 0
        fi
        rm -rf "$probe"
        die "Could not create a Python virtualenv with uv. Install Python 3.13 manually and rerun."
    fi
    probe=$(mktemp -d)
    if "$PY" -m venv "$probe" >/dev/null 2>&1 && [ -x "$probe/bin/pip" ]; then
        rm -rf "$probe"
        return 0
    fi
    rm -rf "$probe"
    # venv broken with a system python: switch to a rootless uv-managed python
    # before ever reaching for sudo.
    log "System Python venv support missing — switching to a rootless uv-managed Python"
    if provision_python_uv; then
        probe=$(mktemp -d)
        if "$UV_BIN" venv --python 3.13 "$probe" >/dev/null 2>&1 && [ -x "$probe/bin/python" ]; then
            rm -rf "$probe"
            return 0
        fi
        rm -rf "$probe"
    fi
    # Last resort: install the distro's python3-venv (needs root).
    need_root_or_fail "Python venv support is missing"
    local apt="apt-get"
    [ "$(id -u)" -ne 0 ] && apt="sudo apt-get"
    $apt install -y -qq "${PY}-venv" >/dev/null 2>&1 \
        || $apt install -y -qq python3-venv >/dev/null 2>&1 \
        || true
    probe=$(mktemp -d)
    if ! "$PY" -m venv "$probe" >/dev/null 2>&1 || [ ! -x "$probe/bin/pip" ]; then
        rm -rf "$probe"
        die "Could not create a Python virtualenv. Install the python3-venv package for this Python and rerun."
    fi
    rm -rf "$probe"
}
ensure_venv_works

# ── 1b. Disk pre-flight ───────────────────────────────────
# Give a clear error instead of a cryptic curl/git/pip write failure when the
# target disk is full or not writable (e.g. a full/read-only /tmp used to kill
# the bootstrap with "curl: (23)" before we moved the staging file to $HOME).
nearest_existing_dir() {
    local d="${1%/}"
    while [ -n "$d" ] && [ ! -d "$d" ]; do
        d="${d%/*}"
    done
    [ -n "$d" ] && printf '%s' "$d" || printf '%s' "/"
}

check_writable_with_space() {
    local label="$1" path="$2" need_kb="$3"
    local target avail_kb probe
    target="$(nearest_existing_dir "$path")"
    avail_kb="$(df -Pk "$target" 2>/dev/null | awk 'NR==2{print $4}')"
    if [ -z "$avail_kb" ]; then
        die "Cannot determine free space on '$target' (parent of $label '$path'). Check the mount and rerun."
    fi
    if [ "$avail_kb" -lt "$need_kb" ]; then
        die "Not enough free space for $label at '$path' — '$target' has only ${avail_kb} KB free (need ~${need_kb} KB). Free up disk and rerun."
    fi
    probe="$target/.bark-write-probe-$$"
    if ! touch "$probe" 2>/dev/null; then
        die "$label directory '$target' is not writable. Fix permissions (or set BARK_INSTALL_DIR to a writable path) and rerun."
    fi
    rm -f "$probe"
}

# ~512 MB covers the repo clone plus a full .venv + pip deps (discord.py,
# fastapi, uvicorn, sqlalchemy, ...) with room to spare.
check_writable_with_space "install directory" "$BARK_INSTALL_DIR" 524288
# Temp dir needs only a little room, but must be writable (already ensured by
# the section-0 bootstrap) and not on a full filesystem.
check_writable_with_space "temp directory" "$BARK_TMPDIR" 8192

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
# (Debian without python3-venv) — recreate when either piece is missing.
if [ ! -x .venv/bin/python ] || [ ! -x .venv/bin/pip ]; then
    if [ -d .venv ]; then
        log "Recreating broken virtualenv"
        rm -rf .venv
    fi
    if [ "$PY_PROVIDER" = "uv" ]; then
        "$UV_BIN" venv --python 3.13 .venv
    else
        "$PY" -m venv .venv
    fi
fi
log "Installing dependencies (this can take a minute)"
if [ "$PY_PROVIDER" = "uv" ]; then
    "$UV_BIN" pip install --python .venv/bin/python --upgrade pip
    "$UV_BIN" pip install --python .venv/bin/python .
else
    ./.venv/bin/python -m pip install --quiet --upgrade pip
    ./.venv/bin/pip install --quiet .
fi

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
log "  3. Bot -> Privileged Gateway Intents -> enable Presence, Server Members, and"
log "     Message Content intents (Bark requires all three; missing them = gateway"
log "     error 4014 / connection restart loop)."
log "  4. OAuth2 -> Redirects -> add: $url_callback"
log "  5. Paste them into the setup page; Bark writes .env and restarts itself."

if [ "$BARK_INSTALL_PORT" = "8090" ]; then
    warn "If the dashboard will sit behind Cloudflare: port 8090 is NOT proxied by Cloudflare."
    warn "Use a proxied port (8080/8443/8880) via BARK_INSTALL_PORT, or a Cloudflare Tunnel."
fi

if [ "$use_systemd" = "no" ]; then
    cd "$BARK_INSTALL_DIR"
    export BARK_DASHBOARD_HOST="$BARK_INSTALL_HOST"
    export BARK_DASHBOARD_PORT="$BARK_INSTALL_PORT"
    exec ./run.sh
fi
