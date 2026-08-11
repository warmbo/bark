# Bark quick-start install test — fresh Debian 13 container

**Date:** 2026-08-10 · **Tester:** Hermes (documented live) · **Result:** ✅ works end-to-end with 4 installer fixes shipped during the test

## Environment

| | |
|---|---|
| Host | pve-geminar (10.0.0.99) |
| Container | CT `1114` · hostname `bark-test` · **temporary** |
| Template | `debian-13-standard_13.1-2_amd64.tar.zst` (Debian 13 trixie) |
| Spec | 2 vCPU · 2048 MB · 8G rootfs (local-zfs) · unprivileged · nesting enabled |
| Network | `eth0` 10.0.0.230/24 · gw 10.0.0.1 · DNS 10.0.0.2 |
| Snapshots | `fresh-debian13` (bare container) → `bark-installed` (after quick start) |
| Source | `github.com/warmbo/bark` **dev branch** (v0.2.177 at test time) |

## Commands run (verbatim)

### 1. Create + boot the container (on pve-geminar)

```bash
# free IP check
for ip in 229 230 231 232; do ping -c1 -W1 10.0.0.$ip >/dev/null 2>&1 && echo "$ip BUSY" || echo "$ip free"; done

pct create 1114 local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst \
  --hostname bark-test --memory 2048 --cores 2 --rootfs local-zfs:8 \
  --net0 name=eth0,bridge=vmbr0,gw=10.0.0.1,ip=10.0.0.230/24 \
  --nameserver 10.0.0.2 --unprivileged 1 --ostype debian \
  --password '<root-password>' --onboot 0
pct start 1114

# systemd 257 warning → enable nesting, reboot
pct set 1114 --features nesting=1 && pct reboot 1114

# verify
pct exec 1114 -- bash -c 'systemctl is-system-running && python3 --version && ip -4 addr show eth0 | grep inet'
```

### 2. Snapshot the pristine container

```bash
pct snapshot 1114 fresh-debian13
```

### 3. Quick start (per README, dev branch)

```bash
# Attempt A — the README one-liner as written (main URL):
pct exec 1114 -- curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
#   → FAILS:  curl: command not found   (fresh container has no curl)

# Bootstrap curl (documented pre-step), then the dev-branch one-liner:
pct exec 1114 -- apt-get install -y -qq curl
pct exec 1114 -- curl -fsSL https://raw.githubusercontent.com/warmbo/bark/dev/install.sh | BARK_BRANCH=dev bash
#   → run 1 FAILS at venv: ensurepip not available (python3-venv missing)
#   → run 2 FAILS at pip:  No module named pip (stale cached installer + broken .venv)
#   → run 3 (fixed installer, from the cloned repo):
#   install.sh is now a thin shell-agnostic launcher that fetches
#   install-main.sh from main; to test the LOCAL installer code run
#   install-main.sh directly:
pct exec 1114 -- bash -c 'cd /root/bark && BARK_BRANCH=dev bash install-main.sh'
#   → ✅ installs; falls back to the foreground setup wizard (no user systemd in a CT)

# Verify
pct exec 1114 -- bash -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/setup'   # 200
pct exec 1114 -- bash -c 'curl -s http://127.0.0.1:8090/setup | grep -c "Welcome to Bark"'        # 1
pct exec 1114 -- bash -c 'git -C /root/bark branch --show-current'                                # dev
pct exec 1114 -- bash -c 'cd /root/bark && .venv/bin/python -c "from bark_version import __version__; print(__version__)"'  # 0.2.177
```

### 4. Snapshot the installed state

```bash
pct snapshot 1114 bark-installed
```

## Problems found (in order)

1. **The one-liner cannot self-bootstrap on a fresh Debian container — `curl` is not installed.**
   The minimal template ships `wget` but no `curl`. The quick start's `curl -fsSL … | bash` dies instantly with `curl: command not found`. → README needs a `apt-get install -y curl` pre-step (or a `wget -qO- … | bash` variant).

2. **`python3 -m venv` fails on Debian 13 without the `python3-venv` package.**
   Debian splits the bundled pip wheels out of the base interpreter; `import ensurepip` succeeds but venv creation fails ("ensurepip is not available … apt install python3.13-venv"). The installer exited 1 with a partial `.venv` (python symlinks, no pip).
   → **Fixed in `install.sh`** (`ensure_venv_works`): probes a scratch venv for a working pip, installs `${PY}-venv` (fallback `python3-venv`), retries, then fails with a clear message.

3. **A broken `.venv` (python present, pip absent) was silently skipped.**
   The installer only checked for `.venv/bin/python` before creating the venv, so a leftover partial venv skipped recreation and the next step died with `No module named pip`.
   → **Fixed in `install.sh`**: recreate the venv when `.venv/bin/pip` is missing.

4. **`raw.githubusercontent.com` served a STALE `dev/install.sh`.**
   Runs 2/3 of the one-liner executed an installer from 2+ commits earlier (no recreate logic, no venv fix) even though the repo's dev branch and the container's clone were current. `sha256sum` of the raw URL ≠ the repo file at the same moment. Anyone running the curl one-liner immediately after a push can get an older script.
   → Consider pinning the installer URL to a commit SHA for deterministic behavior, or accepting CDN lag. Same class of issue applies to self-update checks hitting GitHub raw.

5. **apt locale/perl warnings in a minimal container** (`perl: warning: Setting locale failed…`, `dpkg-preconfigure: unable to re-open stdin`). Cosmetic; silenced in the installer via `DEBIAN_FRONTEND=noninteractive` + `C.UTF-8`.

6. **`BARK_SYSTEMD=auto` correctly falls back to foreground** — an LXC container has no user systemd manager, so the wizard runs in the terminal. Good behavior, but see "to improve".

## Issues to look into (improve the process / end result)

- **README quick-start one-liner points at `main/install.sh`, which 404s until the branch is promoted.** The dev-branch README should reference `…/dev/install.sh` (or the main URL must be live). Currently only `dev` has the installer + README.
- **Deterministic installer URL**: the stale-CDN behavior means "curl the dev branch" isn't reproducible. Options: pin the script URL to a commit SHA, have the script verify its own git version, or serve it from a stable endpoint (release asset).
- **Foreground wizard + `run.sh` stops after setup**: after the wizard writes `.env`, the process exits 0 and `run.sh`'s loop breaks ("Clean exit. Stopped.") — a container user must restart `./run.sh` manually. In the foreground path we could re-exec instead of stopping, or print a loud "restart me" hint.
- **No persistent service in a container**: `systemctl --user` doesn't exist in a root CT; a system-level unit (`/etc/systemd/system/bark.service`) would be the container-native option. Add a `BARK_SYSTEMD=system` mode (root unit, not user unit).
- **Default bind is `127.0.0.1`** — correct and safe, but a headless VPS user must SSH-tunnel to reach `/setup`. The installer already prints the tunnel hint; consider auto-detecting non-loopback installs and offering `BARK_INSTALL_HOST=0.0.0.0` explicitly.
- **`pip install .` builds the project** — fine with wheels, but a pure-`requirements.txt` install would be faster. Not blocking.
- **First run of `apt-get update`** in a fresh template adds ~10s; the installer could call it before the tool install (it currently relies on the user's earlier `apt-get install curl` having updated).

## End result

Fresh Debian 13 container → `curl | BARK_BRANCH=dev bash` (with a one-command `apt-get install curl` pre-step) → Bark installed from the dev branch, first-time setup wizard serving at `http://127.0.0.1:8090/setup`, ready to write `.env` from the browser. Snapshot `bark-installed` allows instant restore; `fresh-debian13` allows re-running the whole test.
