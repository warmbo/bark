# Bark

Bark is a dashboard-first Discord management bot built for the ZENHAWX community. It runs the Discord client and a FastAPI/Jinja dashboard in one asynchronous Python process. Server operators can manage members, run moderation actions, inspect cases and warnings, configure modules, review voice history, and receive live dashboard updates without moving routine administration into chat commands.

## Features

- Discord slash and prefix commands powered by `discord.py`
- FastAPI dashboard with Discord OAuth2 sessions and role-based access
- Per-server module enablement, configuration, and access overrides
- Moderation cases, warnings, private notes, rulesets, word lists, and voice history
- Styled confirmation dialogs for destructive actions, inline progress, and success/error feedback
- Server/member search, member actions, audit history, activity summaries, and SSE updates
- SQLite by default, with asynchronous SQLAlchemy persistence
- systemd user-service deployment

## Requirements

- Python 3.13+
- A Discord application and bot token
- Discord gateway intents required by the enabled modules (including member intent for member management)
- A reverse proxy and HTTPS for production OAuth2 deployments

## Setup

```bash
git clone <repository-url> bark
cd bark
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set at least the bot token in `.env`:

```dotenv
BARK_BOT_TOKEN=replace-with-your-discord-bot-token
BARK_PUBLIC_URL=http://127.0.0.1:8090
BARK_DASHBOARD_HOST=127.0.0.1
BARK_DASHBOARD_PORT=8090
```

For Discord login, add a redirect URL matching `<BARK_PUBLIC_URL>/auth/callback` in the Discord developer portal, then configure:

```dotenv
BARK_OAUTH2_CLIENT_ID=your-application-id
BARK_OAUTH2_CLIENT_SECRET=your-client-secret
BARK_OAUTH2_REDIRECT_URI=https://your-host.example/auth/callback
BARK_OWNER_DISCORD_IDS=123456789012345678
BARK_FORCE_HTTPS=true
```

Run Bark in the foreground:

```bash
source .venv/bin/activate
python app.py
```

The dashboard listens on `BARK_DASHBOARD_HOST:BARK_DASHBOARD_PORT` (default `127.0.0.1:8090`). Health is available at `/api/v1/health`.

### systemd user service

`bark.service` contains deployment-specific absolute paths. Update its `WorkingDirectory`, `EnvironmentFile`, `ExecStart`, `ReadWritePaths`, and log paths before installing on another host. Then:

```bash
mkdir -p ~/.config/systemd/user
cp bark.service ~/.config/systemd/user/bark.service
systemctl --user daemon-reload
systemctl --user enable --now bark
systemctl --user status bark
journalctl --user -u bark -f
```

## Architecture overview

```text
app.py
├── bot/client.py                 Discord connection and event dispatch
├── services/module_manager.py    Discovery, dependency order, lifecycle, reload
├── services/permission_service.py Dashboard role checks and module overrides
├── modules/
│   ├── base.py                   BarkModule contract and BarkContext
│   ├── moderation/               Cases, warnings, rulesets, voice tracking
│   ├── logging/                  Discord event logging
│   └── welcome/                  Member welcome automation
├── dashboard/
│   ├── factory.py                FastAPI construction, middleware, routers
│   ├── routes/web/               Jinja page routes
│   ├── routes/api/               Versioned JSON and SSE routes
│   ├── templates/                Server-rendered shell and workspaces
│   └── static/                   Shared CSS and dependency-free JavaScript
└── database/
    ├── engine.py                 Async SQLAlchemy sessions/migrations
    └── models/                   Guild, moderation, analytics, and module data
```

A single process owns the Discord cache and dashboard, so API handlers can resolve live guilds, members, roles, channels, and voice state directly from the bot. Persistent records use asynchronous SQLAlchemy sessions. API responses use a consistent `{ "success": true, "data": ... }` envelope; failures include a machine-readable error and HTTP status.

## Module system

Every module subclasses `BarkModule` in `modules/base.py`. A module declares metadata and exposes commands, event handlers, configuration schema, dashboard actions, optional workspace tabs, and lifecycle hooks. Modules receive a restricted `BarkContext` rather than importing the bot internals directly.

A typical module supplies:

- metadata: `name`, `description`, `version`, `author`, `priority`
- `get_commands()` and `get_events()`
- `get_settings_schema()` for dashboard-generated fields
- `get_dashboard_actions()` for runnable operation cards
- `get_dashboard_tabs()` for module-specific data views
- `on_load()` / `on_unload()` and optional health validation

Create a package under `modules/<name>/`, export the module class, and ensure the package follows the existing moderation, logging, or welcome examples. Module code should keep Discord behavior in the module and reusable persistence/business logic in `services/`.

### Module lifecycle

`ModuleManager` discovers module packages, validates dependencies, sorts by priority, calls `on_load`, registers event handlers and commands, and tracks runtime state. Per-guild enabled/configuration state is stored separately from the Python module instance. Reload unregisters the old contribution, runs `on_unload`, reloads the package, creates the replacement, and registers it again. A failed reload is surfaced to the API and dashboard rather than reported as success.

The dashboard can:

- enable or disable a module for one server
- update configuration after JSON-schema validation
- reload module code for operators with sufficient access
- test module health
- set a per-module minimum dashboard role (`viewer`, `moderator`, `admin`, or `owner`)

## Dashboard and module workspace

`dashboard/templates/pages/module_detail.html` is the standard module workspace layout. Its compact header contains module identity, status, enable toggle, reload control, role-access summary/editor, runtime health, and tabs. The standard tabs are:

- **Operate** — schema-driven dashboard actions with confirmation for destructive operations
- **Configure** — typed module settings with dirty-state, discard, save, and validation feedback
- **About** — module metadata, behavior summaries, and commands
- **Module tabs** — module-owned operational data loaded with explicit loading, empty, error, and populated states

The moderation module adds Cases, Warnings, Notes, Rulesets, Word Lists, and Voice tabs. Destructive retention controls for voice history, audit records, and attachments are grouped in the Voice tab's Danger Zone. Shared UI behavior lives in `static/js/main.js`; generic workspace behavior lives in `module-workspace.js`; moderation data controls live in `moderation-workspace.js`.

Dashboard authorization has four ordered roles: `viewer < moderator < admin < owner`. Page and API authorization must both be enforced; hiding a button is not a substitute for checking its API route.

## API routes

All JSON routes use the `/api/v1` prefix.

| Area | Routes |
|---|---|
| Health | `GET /health` |
| Guilds | `GET /guilds`, `GET /guilds/{guild_id}`, `GET /guilds/{guild_id}/stats` |
| Discord resources | `GET /guilds/{guild_id}/roles`, `GET /guilds/{guild_id}/channels` |
| Members | `GET /guilds/{guild_id}/members`, `GET /guilds/{guild_id}/members/{user_id}` |
| Actions | `POST /guilds/{guild_id}/actions/{warn|timeout|kick|ban|unban|vc_kick|vc_move|vc_mute|vc_unmute}` |
| Modules | `GET /guilds/{guild_id}/modules`, `GET|PUT /guilds/{guild_id}/modules/{module_name}` |
| Module runtime | `POST /guilds/{guild_id}/modules/{module_name}/{toggle|reload|test}` |
| Module access | `GET /guilds/{guild_id}/modules/role-access`, `PATCH|DELETE /guilds/{guild_id}/modules/{module_name}/role-access` |
| Moderation cases | `GET|POST /guilds/{guild_id}/moderation/cases`, `GET|DELETE /guilds/{guild_id}/moderation/cases/{case_number}` |
| Warnings | `GET /guilds/{guild_id}/moderation/warnings`, `DELETE /guilds/{guild_id}/moderation/warnings/{warning_id}` |
| Notes | `GET|POST /guilds/{guild_id}/notes`, `PATCH|DELETE /guilds/{guild_id}/notes/{note_id}` |
| Voice/retention | `GET|DELETE /guilds/{guild_id}/moderation/voice-history`, `DELETE .../audit-logs`, `DELETE .../attachments` |
| Settings | `GET /guilds/{guild_id}/settings`, `PUT /guilds/{guild_id}/settings/general`, logging and automod subroutes |
| Audit | `GET /guilds/{guild_id}/audit-log`, `GET /guilds/{guild_id}/audit-log/summary` |
| Live updates | `GET /guilds/{guild_id}/events` (server-sent events) |
| Sidebar manifest | `GET /guilds/{guild_id}/manifest` |

Module-specific routers are mounted below `/api/v1/guilds/{guild_id}/modules/{module_name}/...`; inspect each module's `get_api_routes()` for its action and data endpoints. OpenAPI route metadata is available at `/openapi.json` when enabled by the app factory.

## Configuration

Environment variables take precedence over defaults. Bark currently loads configuration from environment variables (commonly via `.env` when launched by the supplied systemd unit).

| Variable | Default | Purpose |
|---|---|---|
| `BARK_BOT_TOKEN` | none | Discord bot token; `.token` is a supported local fallback |
| `BARK_COMMAND_PREFIX` | `!` | Prefix command marker |
| `BARK_SYNC_COMMANDS` | `true` | Sync Discord application commands at startup |
| `BARK_DASHBOARD_HOST` | `127.0.0.1` | Dashboard bind address; set to `0.0.0.0` only behind a reverse proxy |
| `BARK_DASHBOARD_PORT` | `8090` | Dashboard bind port |
| `BARK_PUBLIC_URL` | `http://127.0.0.1:8090` | Browser-facing origin, without trailing slash; use `https://bark.warx.org` in production |
| `BARK_FORCE_HTTPS` | `false` | Secure cookies and HTTPS enforcement |
| `BARK_SECRET_KEY` | generated in data dir | Session signing secret; set explicitly in clustered deployments |
| `BARK_DATABASE_URL` | `sqlite+aiosqlite:///bark.db` | Async SQLAlchemy database URL |
| `BARK_DATABASE_ECHO` | `false` | SQL statement logging |
| `BARK_DATA_DIR` | `data` | Persistent data and generated secret directory |
| `BARK_LOG_LEVEL` | `INFO` | Python logging level |
| `BARK_OAUTH2_CLIENT_ID` | none | Discord OAuth2 application ID |
| `BARK_OAUTH2_CLIENT_SECRET` | none | Discord OAuth2 secret |
| `BARK_OAUTH2_REDIRECT_URI` | `<public-url>/auth/callback` | OAuth2 callback URI |
| `BARK_OWNER_DISCORD_IDS` | none | Comma-separated dashboard owner IDs |
| `BARK_INVITE_URL` | none | Bot invite shown in server selection |

Do not commit `.env`, `.token`, `.secret_key`, database files, OAuth secrets, or bot tokens. In production, terminate TLS at a trusted reverse proxy, set `BARK_PUBLIC_URL` to the HTTPS origin, enable `BARK_FORCE_HTTPS`, and use a persistent secret key.

## Development and verification

```bash
source .venv/bin/activate
python -m pytest -v --tb=short
```

Frontend code intentionally uses browser-native APIs and shared utilities instead of inline event handlers. When editing templates, preserve accessible labels, tab relationships, keyboard behavior, loading/empty/error states, and the `BarkDialog` confirmation pattern. Run the full test suite before restarting the service.

## License

MIT
