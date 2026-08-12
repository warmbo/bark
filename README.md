<div align="center">

<img src="assets/bark-avatar.png" alt="Bark" width="132" />

# Bark

**Dashboard-first Discord server management.** Moderation, reputation, roles, and automation — self-hosted in a single asynchronous Python process.

[![CI](https://github.com/warmbo/bark/actions/workflows/test.yml/badge.svg)](https://github.com/warmbo/bark/actions/workflows/test.yml)
![Python](https://img.shields.io/badge/python-3.13-3776AB)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![License](https://img.shields.io/badge/license-MIT-blue)

</div>

---

## Dashboard

![Bark dashboard](assets/dashboard.png)

Bark pairs the Discord client with a FastAPI + Jinja dashboard in one process, so server operators manage their community from the browser instead of chat commands. The UI is a glassmorphism design system with role-gated pages, live server-sent-event updates, and a shared module workspace — one cohesive application, not a pile of panels.

## Features

- **Moderation** — cases, warnings, private notes, timeouts, kicks, bans, voice actions, rulesets, and word lists
- **Reputation & levels** — message, emoji, reaction, voice, and thanks scoring with named tiers and leaderboards
- **Role management** — welcome, tenure, voice, Twitch-live, and reaction-claimed role rules
- **Auto voice** — dynamic temporary voice channels with configurable naming
- **Logging & welcome** — Discord event logging and member welcome automation
- **Live dashboard** — server/member search, audit history, activity summaries, and SSE updates
- **Modular by design** — per-server module enablement, JSON-schema configuration, and role-based access
- **Single process** — SQLite by default with async SQLAlchemy; one service to run, back up, and watch

## Modules

| Module | What it does |
|---|---|
| `announcements` | Scheduled announcements |
| `auto_voice` | Dynamic temporary voice channels |
| `help` | `/bark help` command reference DM |
| `logging` | Discord event logging |
| `moderation` | Cases, warnings, rulesets, voice tracking |
| `reputation` | Levels, thanks, reactions, voice, tiers |
| `role_manager` | Welcome/tenure/voice/Twitch/reaction roles |
| `speak` | `/bark speak <key>` preset phrases |
| `welcome` | Member welcome automation |

Every module subclasses `BarkModule` and declares its commands, events, settings schema, dashboard actions, and workspace tabs. See [Module workspace](docs/module-workspace.md) to build one.

**Plugins.** Extra functionality can be installed at runtime as single-file plugins — upload a `.py` file from the server's Modules page (Plugins box; owner-only) and it becomes *available* on the instance (no restart). Availability is an instance decision; whether a plugin runs is decided per Discord server — add-ons are off by default on every server and their owners/admins turn them on from that server's Modules page. Plugins follow the same `BarkModule` contract as built-in modules. See the [bark-plugins](https://github.com/warmbo/bark-plugins) repository for a ready-made set and the plugin format guide.

## Related repositories

- [**bark-site**](https://github.com/warmbo/bark-site) — the landing page at bark.warx.org (static HTML served on :8092; lists every core module).
- [**bark-plugins**](https://github.com/warmbo/bark-plugins) — single-file add-on plugins installed from the dashboard.
- `bark-dev` is not a separate repository: it is the **`dev` branch** of this repo, deployed as a second instance alongside `main`.

The self-update manager (`services/update_service.py`) always pulls from the **GitHub** mirror — stable channel tracks `main`, dev tracks `dev` — and refuses any update that would move the instance backwards (stale-mirror guard). Channels are enforced server-side: a Dev-channel instance can only update from `dev`, never jump to `main` on version number alone. Every update snapshots the database first; a failed backup aborts the update. The mirror must be kept in sync by the owner; Forgejo (`origin`) remains the authoritative push target.

## Quick start

One command installs everything (git, curl, Python 3.13+ if missing), clones the repo, builds the virtualenv, and starts Bark:

```bash
curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
```

> **Shell-agnostic.** The installer works piped to `bash`, `sh`, `zsh`, `fish`, or any POSIX shell — the one-liner hands off to `bash` internally, so use your normal shell:
> ```fish
> curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | fish
> ```

> **Fresh Debian/Ubuntu?** The minimal image ships no `curl` — install it first: `apt-get install -y curl` (or use `wget -qO- … | bash`).

When it finishes, open the printed URL (default `http://127.0.0.1:8090/setup`) — Bark boots a **first-time setup wizard** and writes its own `.env` from the browser, so no hand-editing is required. On a remote server, SSH-tunnel to that URL or reinstall with `BARK_INSTALL_HOST=0.0.0.0` for LAN access.

Useful overrides (export before running):

| Variable | Default | Purpose |
|---|---|---|
| `BARK_INSTALL_DIR` | `~/bark` | Install location |
| `BARK_SYSTEMD` | `auto` | `yes`/`no` to force a systemd user service or foreground run |
| `BARK_INSTALL_HOST` / `BARK_INSTALL_PORT` | `127.0.0.1` / `8090` | Dashboard bind address / port |
| `BARK_BRANCH` | `main` | Branch to check out (`dev` for pre-release) |
| `BARK_NO_START` | unset | `1` to install but not launch |

Manual install (requires Python 3.13+):

```bash
git clone https://github.com/warmbo/bark.git
cd bark
uv sync --extra dev        # or: python3 -m venv .venv && .venv/bin/pip install .
```

**No `.env` needed to start** — Bark detects that it's unconfigured and boots a first-time setup wizard:

```bash
uv run python app.py
```

Open `http://localhost:8090/setup` and enter your Discord bot token, public dashboard URL, and (optionally) the OAuth2 pair. Bark writes its own `.env` (restrictive permissions) and restarts — no hand-editing required. For a manual install you can still `cp .env.example .env` and set values yourself:

```dotenv
BARK_BOT_TOKEN=replace-with-your-discord-bot-token
BARK_PUBLIC_URL=https://bark.example.com
```

The dashboard serves on `BARK_DASHBOARD_HOST:BARK_DASHBOARD_PORT` (default `127.0.0.1:8090`); health is at `/api/v1/health`. Add the `deploy/bark.service.example` systemd user unit for a persistent install, and terminate TLS at a reverse proxy in production.

**Behind a reverse proxy / Cloudflare.** Set `BARK_PUBLIC_URL` to the public `https://` hostname (the OAuth callback is derived from it). Bark trusts `X-Forwarded-*` headers from the proxies listed in `BARK_FORWARDED_ALLOW_IPS` (default `127.0.0.1`, which covers a same-host reverse proxy or a Cloudflare Tunnel, whose `cloudflared` connects to loopback). This keeps `force_https`, secure session cookies, and per-client rate limiting correct. If Cloudflare connects to the origin directly (not via Tunnel), set `BARK_FORWARDED_ALLOW_IPS=*` — and firewall the origin to Cloudflare's IP ranges so clients can't spoof the headers. Real-time updates use SSE (`text/event-stream`), so no WebSocket toggle is needed in Cloudflare; if live events appear buffered, disable response buffering for the dashboard (e.g. a Cloudflare Worker or transform rule). Note the default dashboard port `8090` is **not** in Cloudflare's proxied-port list — behind Cloudflare use a supported port (e.g. `8080`, `8443`, `8880`, or `BARK_INSTALL_PORT=8080` at install) or a Cloudflare Tunnel, which proxies any port.

## Dashboard access

Dashboard authorization has four ordered roles: `viewer < moderator < admin < owner`. Page and API authorization are both enforced — hiding a button is not a substitute for checking its route. Discord OAuth2 login is optional: with OAuth disabled the dashboard runs fully public for trusted local networks, with `BARK_OWNER_DISCORD_IDS` reserved for production deployments.

## Documentation

| Doc | Covers |
|---|---|
| [Architecture overview](docs/architecture-overview.md) | Process layout, module system, lifecycle |
| [API contracts](docs/api-contracts.md) | Route map, response envelope, pagination |
| [Permissions model](docs/permissions-model.md) | Role hierarchy and capability checks |
| [Data model](docs/data-model.md) | Persistent schema |
| [Dashboard UI](docs/dashboard.md) | Page/API control contract and audit checklist |
| [Design system](docs/design-system.md) | Visual tokens and layout primitives |
| [Module workspace](docs/module-workspace.md) | Standard module tab layout and behavior |
| [Moderation workflows](docs/moderation-workflows.md) | Case, warning, and voice flows |
| [Testing](docs/testing.md) | Test suite layout and conventions |
| [Install test (Debian 13)](docs/install-test-debian13.md) | Verbatim quick-start run on a fresh container + installer issues found |

## Development

```bash
uv run pytest -v --tb=short
```

CI runs the full quality gate on every push and pull request: `ruff` lint + format, `mypy`, `bandit`, `pip-audit`, and `pytest`. Frontend code uses browser-native APIs and shared utilities instead of inline event handlers — when editing templates, preserve accessible labels, tab relationships, keyboard behavior, and loading/empty/error states.

## License

MIT
