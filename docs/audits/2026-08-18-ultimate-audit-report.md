# Bark — Ultimate Application Audit Report

**Date:** 2026-08-18
**Baseline:** branch `dev`, HEAD `a482041`
**Method:** 3 parallel read-only audits (backend/Python, security, frontend/UI) + trust-but-confirm verification of every top finding against the live tree. No files modified during discovery.

## Executive summary

The codebase is **healthy**. Zero P0 findings (no unauthenticated RCE, no auth bypass, no secrets committed, no SQLi). Full suite: **729 tests green** at baseline (730 after fixes), ruff clean, 61/61 security tests pass. The architecture is well-layered (routes → services → models → templates), business logic is centralized in a service layer, and prior audits' findings are overwhelmingly confirmed fixed.

The disorder present is **concentration and inconsistency**, not rot: two giant module files, a second modal system, dead CSS/JS, per-guild module-permission enforcement that diverges between the middleware and handlers, and one real authorization gap (stale guild access after member removal). All repaired or queued below.

## Findings register

Legend: P0 = crash/data-loss/security · P1 = instability/broken behavior · P2 = architecture · P3 = duplication/cleanup · LOW = cleanup/hardening.

### Backend — fixed (Phase A, commit `2cee569`)

| Finding | Severity | Location | Evidence | Fix (applied) |
|---|---|---|---|---|
| `create_case` trusts client-supplied `moderator_id`/`moderator_tag` | P1/P2 | `dashboard/routes/api/moderation.py:144-145` | Any moderator can POST a case attributed to another user — audit-record forgery | Derive actor from `request.session["user"]`; fall back to submitted values only in permissive mode |
| `mutation_capability` maps `modules/{name}[/(toggle\|reload)]` to global `modules.configure/manage`, not the module's own capability | P1 | `services/security.py:114-119` | Handlers check `{name}.configure`/`{name}.manage` honoring per-guild `ModuleRoleAccess` overrides; UI shows Save/Toggle/Reload (override-derived) but middleware 403s | Return `<name>.configure`/`<name>.manage` from the mapper so overrides apply uniformly |
| Removed member / removed guild keeps dashboard access (and prior manage tier) until next login | P1 | `services/security.py:253-284` | `DashboardGuildAccess` snapshot written only at OAuth login; no revocation hook | `on_member_remove`/`on_guild_remove` revoke rows immediately; regression test added |
| AutoMod legacy config-load swallows exceptions | P2 | `modules/moderation/module.py:1563-1564` | `except Exception: pass` silently drops ALL AutoMod/anti-raid rules on transient DB error, no log | `logger.exception` with a clear message |
| `import_settings` unguarded `int(version)` → 500 on malformed backup | LOW | `dashboard/routes/api/settings.py:103` | Client error raises ValueError → 500 | Guard → 400 "Invalid backup version" |
| `vc_move` reuses `duration` as `channel_id`; garbage input → 502 | LOW | `dashboard/routes/api/actions.py:486-491` | `int(ch_id)` unvalidated raises inside generic handler | Separate `channel_id` body field, numeric validation, guarded conversion |
| Sibling unguarded `int()` sites (role-assignment feed, voice history) | P3 | `guilds.py:826`, `moderation.py:346` | One non-numeric id 500s the whole endpoint | Same try/except guard as `_member_name` |

### Frontend — fixed (Phase B, commit `b22a6bb`)

| Finding | Severity | Location | Fix (applied) |
|---|---|---|---|
| `BarkDialog.pick` nests a `<button>` inside a `<button>` (media-library delete) | P1 a11y | `main.js:135-168` | Cell → `div[role=button][tabindex=0]`; delete button as child; Enter/Space support |
| Jinja `{{ icon(...) }}` inside JS `innerHTML` restore-strings → blank icons | P1 | settings/modules/members (6 sites) | `refreshIcons()` after each restore |
| "Server at a Glance" stat blocks have no live-region semantics | P1 a11y | `stats.html:18`, `guild.html:62` | `aria-live="polite"` on `#stats-metrics` + `#server-info-chips` |
| Second modal system (`#update-terminal-overlay`) has no focus management | P1 a11y | `settings.html:667-677` | Move focus into dialog on open |
| Sidebar manifest uses raw `fetch` (no timeout / 401→login) | P2 | `main.js:693` | `safeFetch` |
| Health watchdog interval never cleared across bfcache restores | P2 | `main.js:452` | `clearInterval` on `pagehide` |
| `buildDataTable` lacks caption + `scope="col"` (vs `renderDataTable`) | P1 a11y | `module-workspace.js:223` | Add both |
| `visibilitychange` reloads have no stale-response guard (guild + stats) | P2 | `guild.html:329`, `stats.html:92` | Monotonic request token, members-style |

### Verified NOT bugs (killed red herrings)

- Background tick loops catch `Exception` (not just `CancelledError`) — fixed in prior audit.
- `/api/v1/health` no longer leaks bot identity/module versions.
- `close_db()` resets `_session_factory` too.
- Anti-raid trackers prune `(guild,user)` keys.
- Non-digit guild IDs 404 in OAuth mode.
- `create_case` has the retry loop.
- Dropped-task GC fear disproven empirically (awaited futures hold strong refs).
- No `print()`, no bare `except:` in production code; ruff F-rules clean.

## Positives verified (security)

- Signed session cookie (HttpOnly + SameSite=Lax), OAuth `state` via `hmac.compare_digest`, session rotation on privilege change, bounded sliding renewal.
- Owner-only gates on backups/plugins/self-update/bot-appearance/instance-invites; per-guild scoping in every DB query (no cross-guild IDOR).
- Viewer read-only gate + management-page allowlist; GET reads handler-gated where sensitive.
- Uploads: capped chunked reads, magic-byte validation, uuid filenames, traversal guards.
- No SQLi (`text()` only for `SELECT 1`); no open redirects; Jinja autoescape everywhere; TrustedHostMiddleware; proxy-header trust loopback-defaulted; rate limiter bounded.
- No secrets committed.
