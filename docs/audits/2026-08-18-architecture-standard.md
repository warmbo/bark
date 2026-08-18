# Bark — Architecture Standard

The canonical structure every developer should follow. Derived from the 2026-08-18 audit of the live tree. This is the *intended* architecture; deviations found by the audit are in the Refactor Queue.

## Request flow (the one way it works)

```
Discord/HTTP
  ↓
Caddy/OPNsense TLS termination (public)  OR  direct LAN :8090/:8091
  ↓
AuthMiddleware      login → membership (shared-guild) → per-guild gate →
                    viewer/manage tier → mutation_capability (CSRF + capability)
  ↓
SecurityMiddleware  rate limit (per-user-id, else IP) → CSP headers → module-enabled 409
  ↓
FastAPI route       (guild_id: int → 422 on garbage; never trust str+int())
  ↓
in-route gate       get_module_min_role(name, gid) → check_api_permission(request, action, gid)
  ↓
Service layer       ModerationService / BarkContext facade (business logic lives here)
  ↓
async SQLAlchemy    session_scope() (SQLite WAL + busy_timeout + FK on)
  ↓
api_success/api_error envelope → JS (safeFetch) → UI
```

## Directory responsibility

| Directory | Owns |
|---|---|
| `app.py` | Process lifecycle: bot+dashboard coordination, shutdown, watchdog. No business logic. |
| `config.py` | Environment-based config, validated at startup (`validate_startup`). Single `config` singleton. |
| `bot/client.py` | Discord gateway bridge → EventBus. **No business logic.** Event handlers only bridge. |
| `dashboard/routes/web/` | Jinja page renders (thin; delegate to API/services). |
| `dashboard/routes/api/` | REST endpoints — validate input, gate permissions, delegate to services. No business logic. |
| `dashboard/routes/auth.py` | OAuth flow + session. |
| `dashboard/middleware/` | Compression (safe gzip). |
| `database/models/` | SQLAlchemy ORM. Integrity enforced at the DB (FK/unique/not-null). |
| `database/engine.py` | Engine + `session_scope()` + `init_db`/`close_db` (resets both singletons). |
| `modules/<name>/module.py` | A `BarkModule` subclass. **Single-file by convention — see queue P2 for splitting the two giants.** |
| `services/` | Shared services: security, response, module_manager, data_collector, etc. Business logic centralization point. |
| `dashboard/static/css/main.css` | **Generated** on the shadcn branch; source edits live in `frontend/src/*.css`. On this dev HEAD it is the single maintained file. |
| `dashboard/static/js/` | Module-scoped workspaces + shared `main.js`/`forms.js`/`realtime.js`. |
| `tests/` | Per-area test suites + contract tests. |

## Dependency direction (one way)

`routes → services → database/models` and `modules → services`. Never the reverse. Templates read models only through routes/context.

## Canonical patterns (the one way to do each)

- **API response:** always `api_success` / `api_error` / `api_not_found` / `api_forbidden` / `api_paginated` from `services/response.py`. Envelope: `{"success": true, "data": ...}` / `{"success": false, "error": ...}`. Never `{"detail": ...}` for API paths (HTTPException handler envelopes it).
- **Permission gate:** every handler calls `await get_module_min_role(name, guild_id)` THEN `check_api_permission(request, "{name}.{action}", guild_id)`. Middleware maps mutations via `mutation_capability`. GET reads are handler-gated; mutations are middleware + handler gated.
- **DB session:** one `async with session_scope()` per logical operation. Never split reads/writes across sessions.
- **Datetime:** `DateTime(timezone=True)` on columns compared with aware values; guard naive reads back.
- **int conversion:** guard with `try: int(x) except (TypeError, ValueError)` on any untrusted/non-numeric field (Discord stores "dashboard" as actor ids). See `_member_name`.
- **Upload:** capped chunked reads (`read_upload_limited`), magic-byte validation, uuid filenames, path-traversal guards.
- **Background loops:** catch `Exception` per-iteration + `logger.exception`, never only `CancelledError`.
- **Bot appearance edits:** wrap Discord REST calls in `asyncio.wait_for(..., timeout=30)`.
- **Slash commands:** single `/bark` dispatcher (one top-level command, `command` autocomplete + `args`). Circumvents the 25-subcommand cap.
- **Session:** signed Starlette cookie; rotation on privilege change; bounded sliding renewal (`SESSION_RENEW_SECONDS=300`).

## Configuration model

- Env vars (`BARK_*`) → `config.py` dataclasses → single `config` singleton.
- Secrets: `BARK_SECRET_KEY` env or auto-generated `data/.secret_key` (0600).
- `validate_startup()` runs on boot (not in setup mode) and fails clearly on invalid config.

## Error flow

Custom exception categories are not yet a hierarchy (see queue P2 hardening) but the app standardizes on: `api_error` for safe client-facing messages, `logger.exception` for server errors, never leaking stack traces to users. HTTPException on `/api/` paths is enveloped to the `{success, error}` shape.
