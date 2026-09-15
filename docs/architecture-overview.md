# Architecture Overview

## Product Purpose

Bark is a self-hosted Discord server management platform. It combines a Discord bot (discord.py) with a FastAPI web dashboard (server-rendered Jinja2 templates, Tailwind CSS) to give guild moderators and administrators a browser-based alternative to Discord's native moderation tools. The system is modular — each feature set (moderation, logging, welcome, …) is a pluggable `BarkModule` subclass, and add-on features can be installed at runtime as single-file plugins. Bot and dashboard run in a single process (`app.py`), with a separate media-rendering service for image work.

## Folder Structure

```
bark/
├── app.py                     # Main entry: bot + dashboard in one process, setup
│                              #   wizard, staged-restore application, 90s bot watchdog
├── bark_version.py            # Runtime version: 0.3.<git rev-list --count>
├── config.py                  # Config dataclasses, env-driven, .token file, secret key
├── run.sh / install.sh / install-main.sh
├── deploy/bark.service.example# systemd unit (Restart=always)
├── bot/
│   └── client.py              # BarkBot — discord.py commands.Bot subclass; bridges
│                              #   Discord events to the EventBus; on_ready orchestration
├── database/
│   ├── engine.py              # SQLAlchemy async engine (aiosqlite), session_scope,
│   │                          #   WAL / foreign_keys / busy_timeout pragmas, init_db
│   ├── migrations/            # Ordered schema migrations 0001–0018 (schema_migrations)
│   └── models/                # guild, module, moderation, permissions, logging, automod,
│                              #   ruleset, voice, analytics, attachments, announcements,
│                              #   auto_voice, reputation, role_manager
├── modules/                   # Core modules (each a BarkModule subclass) + base.py
│   ├── base.py                # BarkModule ABC, registration dataclasses
│   ├── welcome/module.py      # WelcomeModule v2.1.0
│   ├── moderation/module.py   # ModerationModule v4.0.0 (+ ruleset_engine.py)
│   ├── logging/module.py      # LoggingModule v3.0.0
│   ├── speak/module.py        # SpeakModule v1.0.0
│   ├── reputation/module.py   # ReputationModule v1.0.0
│   ├── role_manager/module.py # RoleManagerModule v1.0.0
│   ├── auto_voice/module.py   # AutoVoiceModule v0.4.0
│   ├── announcements/module.py# AnnouncementsModule v1.1.0 (scheduled sends)
│   └── help/module.py         # HelpModule v1.0.0 (/bark help, bark!help)
├── services/
│   ├── module_manager.py      # Lifecycle orchestration: commands, events, dispatch
│   ├── module_discovery.py    # Scans modules/ + plugins dir, instantiates BarkModules
│   ├── module_registry.py     # name → BarkModule map + page registrations
│   ├── guild_module_state.py  # Per-guild enablement policy (execution gate)
│   ├── plugin_manager.py      # Single-file plugin validation/loading (512 KB cap)
│   ├── plugin_operations.py   # Runtime plugin install/uninstall/reload
│   ├── slash_dispatcher.py    # The single flat /bark command + argument parsing
│   ├── prefix_commands.py     # bark!<cmd> text-command fallback
│   ├── module_coop.py         # Optional cross-module named providers (no coupling)
│   ├── event_bus.py           # Pub/sub: Discord events, moderation actions, lifecycle
│   ├── realtime_bridge.py     # EventBus → SSE fan-out per guild
│   ├── bark_context.py        # Module-facing gateway to bot/DB/coop
│   ├── moderation_service.py  # Moderation business logic
│   ├── permission_service.py  # RBAC + module permission definitions
│   ├── instance_auth.py       # Owner-only gate for instance-level APIs (fail-closed)
│   ├── backup_service.py      # SQLite snapshots, validation, staged restore
│   ├── update_service.py      # Git-based self-update (stable/dev channels)
│   ├── announcement_schedules.py # Queued/recurring announcement state machine
│   ├── media_engine/          # Separate-process render service (profile cards/GIFs)
│   ├── security.py            # AuthMiddleware, SecurityMiddleware, rate limiting
│   ├── response.py            # API envelope helpers, permission cache
│   ├── dashboard_access.py    # OAuth guild access snapshot helpers
│   └── …                      # data_collector, stats_recorder, paginator,
│                              #   interactions, presence_store, slug_router, …
├── dashboard/
│   ├── __init__.py            # create_app(bot) — FastAPI app factory
│   ├── app.py                 # DashboardApp — uvicorn runner + coordinated shutdown
│   ├── setup_app.py           # First-time setup wizard (dashboard-only, writes .env)
│   ├── middleware/compression.py
│   ├── routes/
│   │   ├── auth.py            # Discord OAuth2 flow
│   │   ├── setup.py           # Setup wizard routes
│   │   ├── web/               # home, docs, members, moderation, modules, settings, stats
│   │   └── api/               # manifest, guilds, modules, moderation, settings, updates,
│   │                          #   backups, actions, health, instance_invites, audit_log,
│   │                          #   realtime (SSE), notes, plugins, bot_appearance, uploads
│   ├── templates/             # Shared Jinja2 tree (base.html, pages/, components/, docs/)
│   └── static/                # css/main.css (Tailwind build output), js/, fonts/, img/
├── frontend/                  # Tailwind sources (src/*.css) + build.mjs → static CSS
├── modules/<name>/templates/  # Colocated module UI partials (extra tabs) — loaded via
│                              #   a repo-root secondary Jinja search path
├── tests/                     # pytest suites: test_dashboard/, test_database/,
│                              #   test_media_engine/, test_modules/, test_services/,
│                              #   plus app/bot/config/installer/version/package tests
└── docs/                      # api-contracts, data-model, permissions-model, testing,
                               #   media-engine, dashboard, module-workspace, …
```

Module versions are declared as the `version` attribute on each `BarkModule` subclass (e.g. `modules/welcome/module.py: version = "2.1.0"`). The instance version is `0.3.<git rev-list --count>` (see `bark_version.py`); the base `0.3.0` comes from `pyproject.toml`.

## Module System Lifecycle

Every feature — core or plugin — is a `BarkModule` subclass (`modules/base.py`). `ModuleManager` (`services/module_manager.py`) orchestrates discovery, lifecycle, command registration, and event subscription; it delegates to `ModuleDiscovery` (package/plugin scanning), `ModuleRegistry` (instance map), `GuildModuleState` (per-guild policy), `SlashDispatcher` (command surface), and `PluginOperations` (plugin-file lifecycle).

| Phase | Method | What happens |
|---|---|---|
| **Discovery** | `ModuleDiscovery.discover()` | Scans `modules/` packages via `pkgutil.iter_modules`, instantiates each `BarkModule` subclass; then `discover_plugins()` loads single-file plugins from `<data_dir>/plugins/*.py`. |
| **Registration** | `ModuleRegistry.register()` | Stores the instance under `self._modules[name]` and its dashboard `PageRegistration`s. |
| **Enable** | `ModuleManager.enable_module(name)` | Calls `module.enable()`, registers the module's commands with the `SlashDispatcher` (and prefix adapter), subscribes EventBus handlers wrapped in `_guard_event_handler`, then flips `module.enabled`. |
| **Disable** | `ModuleManager.disable_module(name)` | Calls `module.disable()`, removes prefix commands, unregisters the module from the dispatcher, unsubscribes its EventBus handlers. |
| **Reload** | `ModuleManager.reload_module(name)` | Plugins reload from their file; core packages are re-imported via `importlib.reload`. Modules whose API router is already mounted are only lifecycled (FastAPI cannot remove routes after startup). |

Modules declare capabilities through overridable methods on `BarkModule` (`modules/base.py`): `get_commands()`, `get_events()`, `get_dashboard_pages()`, `get_settings_schema()`, `get_permissions()`, `get_api_routes()`, `get_extra_tabs()`, `get_actions()`, `get_about()`, `get_dashboard_cards()` (overview widgets), `diagnose()` (health-report hook), and `export_stats()`/`import_stats()` (backup support). Most return empty defaults — modules opt in per capability. Modules interact with the system only through their `BarkContext` (`self.ctx`).

## Plugin / Add-on System

Add-on features are **single-file plugins** — a distributable `.py` file containing exactly one `BarkModule` subclass (`services/plugin_manager.py`).

- Files live in `<data_dir>/plugins/<name>.py` and are discovered at startup; they are installed, uninstalled, and reloaded **at runtime from the dashboard** (`dashboard/routes/api/plugins.py`) without a bot restart.
- Validation: name must match `^[a-z][a-z0-9_]{1,31}$`, must not collide with `CORE_MODULES` or reserved names, file must be ≤ 512 KB and import cleanly. A plugin file is user-supplied code — installing executes it, so the install/uninstall/reload endpoints are restricted to instance owners (`services/instance_auth.py`).
- A plugin gets the full module surface: slash + prefix commands, EventBus events, dashboard pages, settings schema, permissions, and API routes. Plugin routers are wrapped in an availability guard so their routes answer 404 after uninstall (FastAPI cannot un-register routes).
- **ModuleCoop** (`services/module_coop.py`) lets modules advertise optional named data providers (`async def handler(guild_id, **kwargs)`) and consume providers from other modules with zero hard coupling — a missing provider simply yields `None`. This is how plugins compose (e.g. a birthdays plugin exposing `birthdays.upcoming` for other modules or dashboard cards).

## Per-Guild Enablement vs Instance Availability

These are two distinct concepts:

- **Instance availability** = the module is discovered/installed and its commands are registered in the `/bark` tree. Every core module and installed plugin is enabled *at the instance level* at startup so its commands exist in the synced tree (Discord's global-command cache takes ~1h to refresh — enablement must not depend on a re-sync).
- **Per-guild enablement** = an instant *execution gate*. `GuildModuleState` (`services/guild_module_state.py`) holds a `(guild_id, module_name) → enabled` map persisted in `ModuleConfig` rows. Core modules default **enabled** for each guild; add-on plugins default **disabled** — installing a plugin only makes it *available*, each server opts in via the dashboard Modules page toggle.
- The gate is enforced in three places: EventBus handlers are wrapped by `_guard_event_handler` (drops events for guilds where the module is off), slash leaves carry a `_module_gate` check that raises `CheckFailure` when the module is disabled there (fail-closed), and command menus filter out disabled modules.
- `should_run_globally(name)` keeps shared module resources alive while at least one connected guild has the module enabled.

## The Flat /bark Command Dispatcher

Bark's entire slash surface is **one top-level command** (`services/slash_dispatcher.py`):

```
/bark <command> [args...]
```

`command` is a string option naming any module/plugin command path (`help`, `warn`, `trivia start`, …); `args` is a free-form string parsed into the leaf handler's typed parameters (mentions/roles/channels resolved against the interaction's guild; the final string parameter consumes the rest verbatim). A bare `/bark` shows an interactive module/command menu; `/bark <module>` shows that module's commands; `/bark help <cmd>` shows detailed usage. Module and command aliases (`rep`→reputation, `lb`→leaderboard, …) are registered as duplicate leaves sharing the same callback.

Why a flat dispatcher instead of a native subcommand-group tree:

- Discord caps a subcommand **group at 25 children** — command-heavy modules (e.g. moderation with aliases) would exceed it and fail the entire tree sync with error 50035.
- A native tree would need every module's leaves under one global command, whose serialized payload **far exceeds Discord's 8000-byte global-command cap** (2026-09-01 incident: sync failed with 50035 "Command exceeds maximum size (8000)", leaving a stale signature and every `/bark` rejected with CommandSignatureMismatch).
- `command` is intentionally a **plain string, not autocomplete**: Discord only commits free-typed text into non-autocomplete options, so hand-typed `/bark help` binds and runs. Discovery is served by the interactive menus instead.
- Because leaf commands are never added to the tree, Discord never enforces their `@default_permissions` — the dispatcher re-applies the declared permission requirement server-side against the invoker's guild permissions before invoking any leaf (the only gate keeping a plain member from running `/bark ban @Owner`).

The command-group name follows the bot: `BARK_COMMAND_GROUP` override → the bot's Discord username → `bark` (`ModuleManager.command_group_name()`). A static `bark!` prefix (with per-module `bark!<module> <sub>` namespacing for multi-command modules) remains as a fallback via `services/prefix_commands.py`.

## Startup Flow

1. **`app.py` main()**: logging setup, version log. With no `BARK_BOT_TOKEN`, boots the **first-time setup wizard** (`dashboard/setup_app.py` — dashboard only, writes `.env` from the browser) and exits.
2. **`config.validate_startup()`** enforces token, complete OAuth, loopback-bind-without-OAuth, and owner-ID presence.
3. **Staged restore**: `apply_pending_restore_sync()` swaps in a validated `restore-pending.db` *before* SQLAlchemy opens the live file (see Backups).
4. **`init_db()`**: `Base.metadata.create_all` + ordered migrations (`database/migrations/`). If a restored schema defeats migration, `rollback_applied_restore_sync()` restores the pre-import snapshot before the supervisor restarts.
5. **`BarkBot()`** created; **`create_app(bot)`** (`dashboard/__init__.py`) builds the FastAPI app: middleware chain (Auth → Security → Session → TrustedHost, plus dev-overlay, slug-rewrite, gzip), static mounts, `/media/uploads`, all web + API + auth routers, `RealtimeBridge` startup, and the `ModuleRoleAccess` permission cache load.
6. **`bot_ready_watchdog`** (90 s) exits the process if Discord never becomes ready, so systemd restarts instead of leaving a dead-bot dashboard.
7. **`asyncio.gather(bot.start(...), dashboard_app.run())`** — coordinated SIGINT/SIGTERM shutdown stops bot, dashboard, and DB together.
8. **`on_ready`** (`bot/client.py`): register guilds, `modules.discover()` (+ plugins), register module API routers on the app, load per-guild module states from `ModuleConfig`, enable **every** module so the tree is complete, `tree.sync()` (guild-scoped instantly when `BARK_SYNC_GUILD_ID` is set), clean up stale voice sessions, restore persisted presence, start the analytics data collector.

## Event Flow

```
Discord Gateway
    ↓ (raw event)
BarkBot.on_* methods (bot/client.py)
    ↓ EventBus.emit(event_name, **data)
EventBus (services/event_bus.py) — priority-ordered pub/sub
    ↓
ModuleManager._guard_event_handler (per-guild enablement gate)
    ↓
Module handler (e.g. ModerationModule._on_message)
    ↓
BarkContext (module-facing facade) → services (SQLAlchemy CRUD)
    ↓
RealtimeBridge listens to EventBus → SSE to dashboard clients
```

No module listens directly to Discord; everything flows through the `EventBus`. Handler exceptions are logged with the originating guild.

## Realtime SSE

`RealtimeBridge` (`services/realtime_bridge.py`) subscribes to a fixed `EVENT_MAP` of EventBus events (priority 200) and fans each out to per-guild `asyncio.Queue`s (maxsize 256, drops with a warning when full). The dashboard consumes them over **Server-Sent Events** at `GET /api/v1/guilds/{guild_id}/events` (`dashboard/routes/api/realtime.py`), driven client-side by `dashboard/static/js/realtime.js` / `overview-live.js`. Mapped events: `moderation_case_created → new_moderation_case`, `discord_member_join → member_joined`, `automod_triggered → automod_triggered`.

## Database + Migrations

- SQLAlchemy 2.x async engine over aiosqlite; `session_scope()` for manual sessions; relative SQLite paths resolve against `config.data_dir`. The engine enables `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, and `busy_timeout=5000` so concurrent event-driven writes don't hit "database is locked". SQLite is the default (`sqlite+aiosqlite:///bark.db`); the URL is configurable (`BARK_DATABASE_URL`) for Postgres.
- **Migrations** (`database/migrations/__init__.py`): `init_db()` runs `create_all` then applies every pending entry from the ordered `MIGRATIONS` tuple, recording each in `schema_migrations`. Currently **18 migrations** (0001–0018): dashboard access table + delete trigger, canonical Discord guild IDs across feature tables (with legacy internal-ID repair and duplicate dedup), post-delivery retry state, legacy LogConfig → ModuleConfig migration, FK indexes, instance invites/access, roles snapshot + unique constraint, reputation emoji dedup key + indexes, activity-snapshot message breakdown, daily channel/emoji stats, voice game stats, backfill from reputation events, tier purpose, and `announcement_schedules`.
- Models live in `database/models/` per feature area (moderation, permissions, logging, automod, ruleset, voice, analytics, attachments, announcements, auto_voice, reputation, role_manager, guild).

## Media Engine

`services/media_engine/` is an in-repo render service — the engine behind the `profiles` add-on plugin's `/bark profile` cards (and available to any module wanting rendered images). It runs as a **separate process per instance** (`bark-media-engine.service` on `127.0.0.1:8094`, Bearer-token protected via `BARK_MEDIA_ENGINE_TOKEN`) so CPU-heavy Pillow renders never block the bot's event loop; the plugin calls it over localhost (`services/media_engine/client.py`) and reads the output file path directly (same host).

- Flow: `POST /v1/render` → poll `GET /v1/jobs/{id}` → read the cached PNG/GIF. Cache-first (1 GB cap) with CDN avatar caching; renders are keyed on payload + theme + art mode.
- The engine never touches Discord: the plugin supplies live facts (names, roles, channel), the engine supplies reputation/activity/badges/favorites blocks read **read-only** from `bark.db`, and optionally AI-generated art (`BARK_MEDIA_OPENAI_API_KEY`).
- It is an optional dependency (`pip install -e ".[media-engine]"` — pillow only); the dev extras include it so the `tests/test_media_engine/` suite runs in CI.

## Announcement Scheduler

The `announcements` module (v1.1.0) schedules one-off and recurring message/embed sends via `services/announcement_schedules.py`. Rows in `announcement_schedules` move `queued → sending → completed|failed`, with recurrence in `hour/day/week/month` units computed timezone-aware (`ZoneInfo`, wall-clock preserved through DST). A guarded UPDATE is the ownership boundary (`claim_next_due`), so concurrent workers can't double-send; on startup `recover_interrupted_deliveries()` marks jobs left in `sending` as failed (review-and-retry, never auto-replayed). The send loop runs inside the module's `enable()` task, restricted to guilds where the module is enabled.

## Backups / Staged Restore

`services/backup_service.py`:

- **Backups**: consistent SQLite snapshots via the sqlite3 stdlib backup API run in a worker thread (safe while the live DB is open), landing in `<data_dir>/backups/bark-backup-<utc timestamp>.db`. Owner-gated API in `dashboard/routes/api/backups.py`.
- **Validation** (`validate_database_backup`): SQLite magic header, `PRAGMA integrity_check`, known migration set (rejects backups from newer/incompatible releases), `guilds` table presence, SHA-256.
- **Staged restore**: an upload is validated and written to `<data_dir>/restore/restore-pending.db` + a marker JSON — the live database is never touched by the request. At the next startup, `apply_pending_restore_sync()` re-validates (checksum), snapshots the current live DB into `backups/` as an explicit rollback artifact, drops WAL sidecars, swaps the file in, and ordered migrations bring older schemas forward. If startup migrations reject the imported DB, `rollback_applied_restore_sync()` puts the pre-import snapshot back. Inconsistent artifact pairs are quarantined so Bark still boots.

## Updater / Deployment

- **Self-update** (`services/update_service.py`): the instance is a git checkout. `apply_update` fetches the channel branch from the configured remote (`update_remote`, default `github`, falling back to `origin`), takes a mandatory pre-update backup (a failed backup **blocks** the update — every update must be revertible), `git reset --hard`s, reinstalls via `pip install .` when `requirements.txt`/`pyproject.toml` changed, then exits the process; the systemd unit (`Restart=always`) brings the new build up. Progress streams to the dashboard as a live terminal log (`GET /instance/update/log` with `?after=<seq>`; phases fetch → backup → reset → deps → restart).
- **Channels**: stable → `main` (`config.instance.stable_branch`), dev → `dev`. Moving stable → dev is allowed and persisted in the local git config (`bark.update.channel`); dev instances may only update from the dev branch. A no-downgrade guard refuses any target commit that is an ancestor of the running build.
- **Versioning**: availability is decided by version number — patch = commit count, mirrored on both sides (`0.3.<remote rev-list count>` vs local `0.3.<count>`), with the ancestor check as belt-and-braces.
- **Instance-level auth** (`services/instance_auth.py`): owner-gated APIs (backups, plugins, updates, bot appearance, instance invites) pass only when — with OAuth enabled — the session user's Discord ID is in `BARK_OWNER_DISCORD_IDS` (fail-closed if no owner IDs are configured); with OAuth disabled, everyone is permitted (dev/mock harnesses).
- **Deployment**: `deploy/bark.service.example`, `install.sh` (one-line installer → `install-main.sh`), `run.sh`. The dashboard binds `127.0.0.1:8090` by default and is meant to sit behind a TLS reverse proxy (Caddy/Cloudflare) with `BARK_FORWARDED_ALLOW_IPS` controlling trusted proxy headers.

## Dashboard Navigation Structure

The manifest API (`dashboard/routes/api/manifest.py`) returns the structured navigation tree:

```
Core Pages (category "" or _core)
├── /                     # Landing / invite / privacy / terms
├── /dashboard            # Guild selection (catalog of connected guilds + access tiers)
├── /guild/{id}           # Overview — stats, activity feed, quick actions
├── /guild/{id}/members   # Member directory
├── /guild/{id}/modules   # Modules grid + per-module workspace
├── /guild/{id}/settings  # General settings
├── /guild/{id}/stats     # Statistics (charts)
└── /g/{slug}/…           # Slug-rewritten guild URLs (no numeric IDs exposed)

Module Pages (from PageRegistration, per enabled module)
├── moderation → Cases / Warnings / Notes / Rulesets / Word Lists / Voice (extra tabs)
├── logging, reputation, role_manager, announcements, auto_voice, speak, welcome
└── plugins (installed add-ons)

Settings Pages (category "settings")
└── General + per-module configure panels
```

Categories: `_core` (priority −1), uncategorized core (priority 0), `community` (2), `_modules` (3), plugin pages (3.5), `settings` (4). Module workspaces render Operate/Configure/About from `get_actions()` / `get_settings_schema()` / `get_about()`, plus extra tabs from `get_extra_tabs()` (colocated `modules/<name>/templates/` partials, resolved via a repo-root secondary Jinja search path).

Frontend: Tailwind CSS built from `frontend/src/*.css` via `frontend/build.mjs` into `dashboard/static/css/main.css`; vanilla JS workspace controllers per module (`moderation-workspace.js`, `reputation-workspace.js`, …), `realtime.js` for SSE, lucide icons, and a vendored three.js bundle for visuals. No SPA framework.

## Testing / Gates

- **pytest** (`asyncio_mode=auto`, `tests/`): suites for dashboard API/UI contracts, database engine + migrations + models, media engine, every module, services (dispatcher, dispatcher field limits, tree caps, command group, plugin manager, module coop, backup/restore, update service, realtime bridge, security, paginator, …), plus app/bot/config/installer/version/package-contract tests. See `docs/testing.md`.
- **CI** (`.github/workflows/test.yml`, on push/PR to dev/main/master): `ruff check` + `ruff format --check`, `mypy` over the app packages, `bandit -ll`, `pip-audit`, full `pytest`, and `npm run check` in `frontend/` (rebuilds the Tailwind CSS and fails if the committed generated assets drift).
- **Pre-commit** (`.pre-commit-config.yaml`): ruff (auto-fix + format), trailing-whitespace/EOF/YAML/merge-conflict checks, mypy, bandit.

## Key Architectural Decisions

| Decision | Rationale |
|---|---|
| **FastAPI + Jinja2 (not SPA)** | Server-rendered HTML avoids client-side bundle complexity; JS enhances only (event delegation, no framework). Tailwind CSS is generated once at build time and committed. |
| **Modular plugin system** | Every feature is a `BarkModule`; add-ons are runtime-installable single-file plugins. Independent development, testing, per-guild toggling, and dashboard opt-in. |
| **Flat /bark dispatcher** | One slash command hosts every module/plugin command — sidesteps Discord's 25-child subcommand-group cap and the 8000-byte global-command payload cap that broke tree syncs (50035). Free-typed `command` string + interactive menus. |
| **Per-guild enablement as an execution gate** | Instance availability (installed + registered) is separate from per-guild policy, so toggling a module is instant and never waits on Discord's ~1h global-command cache. |
| **Service layer** | Business logic lives in services (e.g. `ModerationService`); API routes and commands both delegate. |
| **EventBus for decoupling** | Modules never call each other directly; they emit and subscribe through the bus. Optional cross-module composition via `ModuleCoop` providers. |
| **SSE for real-time** | Server-Sent Events over WebSockets — simpler infrastructure, unidirectional server→client, works through standard proxies. |
| **SQLite + ordered migrations** | Single-file deployment with WAL/busy_timeout for concurrency; 18 ordered migrations keep deployed databases forward-compatible (and are what backup validation checks). |
| **Staged restore** | An uploaded database never touches the live file; validation, rollback snapshot, and WAL-sidecar handling happen atomically at startup, with automatic rollback if migrations reject it. |
| **Git-based self-update** | Instance is a git checkout; updates fetch only from the configured remote, require a pre-update backup, refuse downgrades, and restart via systemd. |
| **Instance-owner auth (fail-closed)** | Backups/plugins/updates are owner-only when OAuth is enabled; with OAuth disabled they are permissive (no other identity exists). |
| **Permission cache** | `ModuleRoleAccess` overrides are loaded into a sync dict at startup so auth middleware checks permissions without awaiting the DB. |
| **Separate media process** | Pillow rendering runs in its own service on :8094 so image work never blocks the bot's event loop; optional dependency keeps the core install lean. |
| **Security posture** | Strict CSP headers, per-identity rate limiting, CORS/trusted-origin enforcement in `SecurityMiddleware`; Discord OAuth2 + session middleware; access snapshots revoked live on member/guild removal. |
