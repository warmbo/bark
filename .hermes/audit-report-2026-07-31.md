# Bark — Python Application Audit Report

**Date:** 2026-07-31
**Auditor:** Hermes Agent
**Branch:** `audit/python-application-2026-07-31`
**Baseline commit:** `f9b619b` — the last pre-audit commit.
**Scope:** Full-stack audit of the Bark Discord management platform — core (app, config, bot), database (engine, migrations, models), services, feature modules, dashboard routes/middleware, tests, packaging, and deployment files.

---

## 1. Executive Summary

Bark is a well-architected single-process Discord bot + FastAPI dashboard. The audit found no architecture-level flaws: the EventBus pattern, service layer, module lifecycle, and SQLAlchemy async persistence are sound. The issues found were concentrated in **input validation at trust boundaries**, **concurrency safety on case numbering**, **per-request query parameters that could produce unbounded queries**, **a few genuine runtime bugs surfaced by strict typing**, and **quality gates (lint/typing/security) that were configured but not enforced**.

All findings were fixed on the audit branch. Final state:

| Gate | Baseline | Final |
|---|---|---|
| Tests | 192 passed | **208 passed** |
| Coverage (branch, same config) | 41% | **44%** |
| Ruff | 249 errors, CI gate red | **0 errors** (124 files formatted) |
| Mypy | 159 errors | **0 errors** (72 files) |
| Bandit (medium+) | 3 mediums | **0** (documented `# nosec`) |
| pip-audit | pip 25.1.1 had 2 advisories | **0 known vulnerabilities** (pip → 26.2) |
| Startup (import + engine init) | — | ~350 ms |

Behavior is preserved: no module API contract changed, no dashboard feature removed, no schema change required.

---

## 2. Prioritized Findings

### P1 — Fixed (correctness / security)

1. **Reputation daily/weekly caps were applied per-event, not per-member** (`modules/reputation/module.py`). The caps check `check_daily_cap`/`check_weekly_cap` were called with only the incoming event's points, so a user could farm unlimited events in a window. Fixed by querying the member's already-earned points in the current window and enforcing the *remaining* allowance.
2. **Voice reputation never credited `voice_minutes`** — the voice loop accumulated points but never updated the profile's voice-minute counter, so voice time was invisible to leaderboards/stats. Fixed with a `voice_minutes` increment at award time.
3. **Concurrent case-number allocation could collide** (`services/moderation_service.py`, `dashboard/routes/api/moderation.py`, `modules/moderation/module.py`, `modules/moderation/ruleset_engine.py`). Case numbers were allocated via `max(case_number) + 1` inside a transaction; two concurrent creates produced duplicate `(guild_id, case_number)` — a UNIQUE violation. Fixed with a per-guild asyncio lock plus bounded retry (3 attempts) on unique-constraint failure; warning creation is atomic with its case.
4. **Unbounded negative `limit` query parameters** — `LIMIT -1` on SQLite returns the entire table. `dashboard/routes/api/{moderation,actions,audit_log}.py` and `modules/reputation/module.py` now use FastAPI `Query(ge=1, le=…)` bounds; negative/oversized limits return 422.
5. **Health endpoint leaked database error details publicly** (`dashboard/routes/api/health.py`). Fixed: full error logged server-side, generic message returned.
6. **Rule mutation endpoint lacked guild-ownership check** (`modules/moderation/module.py`) — a request could mutate a ruleset belonging to another guild. Fixed: `ruleset_id` must belong to the requesting `guild_id`.
7. **`data_collector` could crash on invites without expiry** — `invite.max_age > 0` raised `TypeError` when `max_age` was `None`. Fixed with explicit `is not None` guard.
8. **Audit-log route reused the exception variable `e` after the `except` block** — the loop `for e in entries` referenced a deleted variable (worked by CPython detail, broken under optimized/other runtimes). Renamed.
9. **`audit_log.py` / HSTS test** — HSTS is only emitted when the deployment is public-HTTPS (`force_https` or `https://` public URL). Test now configures that mode explicitly; safe localhost defaults (`127.0.0.1`, `http://…`) no longer claim HSTS.
10. **OAuth validation was over-strict** — `oauth_disabled` mode no longer requires `client_id`/`client_secret`.
11. **Announcements module passed discord wrapper objects instead of message text** to slash commands. Fixed.
12. **Dashboard activity feed used one `result` variable for four different queries** — mypy's stale narrowing hid real attribute checks; renamed per query (`cases_result`, `audit_result`, `voice_result`, `warns_result`). Same pattern fixed in the reputation leaderboard route.

### P2 — Fixed (maintainability / quality)

13. **CI gate was red and incomplete** — `.github/workflows/test.yml` targeted `main` (repo uses `master`), ran ruff with `--select` that conflicted with pyproject, and didn't run mypy/bandit/pip-audit. Rewritten to run the full gate on `master`.
14. **Pre-commit was pinned to stale ruff v0.11** (project uses 0.16) and had no mypy/bandit hooks. Updated.
15. **`httpx` was imported but missing from `pyproject.toml`** — added `httpx>=0.28,<1.0`; `pip check` clean.
16. **`config.py` defaults** — dashboard host `0.0.0.0` → `127.0.0.1`, public URL `https://bark.warx.org` → `http://127.0.0.1:8090` (production values are set via env on deploy).
17. **Database URLs logged with passwords** (`database/engine.py`) — added `_safe_database_url()` using `make_url().render_as_string(hide_password=True)`; regression test added.
18. **Unused/dead code removed** — unused imports across `database/models/__init__.py` (now explicit `__all__`), module `__init__.py` re-exports, `callable` used as a type in `realtime_bridge.py` (→ `Callable`), unused locals in `ruleset_engine.py` and `reputation/module.py`, unused `RedirectResponse` import.
19. **`assert` used for runtime validation** in `services/security.py` (stripped under `python -O`). Replaced with explicit `raise RuntimeError`.
20. **Ruff E712 `== True/False` on SQLAlchemy columns** — replaced with `.is_(True)` / `.is_(False)` (SQL NULL-safe) across moderation/reputation routes and service.
21. **Version contract** — `bark_version.py` reads installed metadata; test enforces runtime matches package.
22. **`tests/__init__.py`** — removed dead `sys.path` hack and unused pytest import.

---

## 3. File-by-File Findings

### Core
- `app.py` — startup now validates config before logging; `asyncio.gather(return_exceptions=True)` so a bot auth failure doesn't kill the dashboard. Clean shutdown path preserved.
- `config.py` — added `ConfigurationError`, `validate_startup()` (token required; OAuth partial config rejected; public dashboard with OAuth disabled rejected); safe defaults; docstring for every field.
- `bark_version.py` — new; `__version__` from installed metadata.
- `bot/client.py` — `on_ready` guards `self.user is None`; `_data_collector` typed; TYPE_CHECKING import for `GuildDataCollector`.

### Database
- `database/engine.py` — redacted URL logging; flat import ordering (E402 noqa documented).
- `database/migrations/__init__.py` — renamed shadowed `key` variables (real name-clash); three `# nosec B608` annotations on regex-validated identifier interpolation (values always parameterized); FK-rebuild verified by subagent.
- `database/models/__init__.py` — explicit `__all__` (ruff F401 clean).

### Services
- `services/moderation_service.py` — per-guild lock + retry for case creation; atomic case+warning; `.is_()` comparisons.
- `services/data_collector.py` — invite `None`-guard; `Any`-typed snapshot dict; import order.
- `services/realtime_bridge.py` — `Callable` type; removed dead `sse_message` dict.
- `services/security.py` — notes capability mapping added (`notes`, `notes/{id}` → `moderation.notes.create`); assert → RuntimeError.
- `services/reputation_service.py` — `compute_voice_points(minutes: float)`; cap helpers accept already-earned points.
- `services/bark_context.py` — formatted (E701 cleanup).

### Modules
- `modules/reputation/module.py` — **caps now window-accumulated**; `voice_minutes` counter updated; leaderboard route: bounded `Query`, distinct result vars; dead `result` assignment removed; `.is_()`.
- `modules/moderation/module.py` — cross-guild ruleset guard; `Warning` alias `W` → `WarningModel`; `.is_()`; `automod` command params typed `bool | None = None`; `_act` guards `interaction.guild is None`; `_dup_track` typed; renamed `track` shadow in cleanup loop.
- `modules/moderation/ruleset_engine.py` — removed unused locals; `ruleset`/`rule` params accept duck-typed stubs (`Any`); nickname `None`-safe.
- `modules/auto_voice/module.py` — `guild_id`/`guild` `None`-guards in three commands + presence handler; lock command uses `interaction.guild.default_role` instead of `interaction.user.guild`.
- `modules/logging/module.py` — `_format_size` accepts float; `_handle_test_action` typed `JSONResponse`; import moved top-level.
- `modules/announcements/module.py` — slash commands receive text not objects.

### Dashboard
- `dashboard/routes/api/moderation.py` — bounded pagination; `_deleted_count()` helper (CursorResult rowcount); `.is_()`.
- `dashboard/routes/api/actions.py` — bounded pagination; import order.
- `dashboard/routes/api/audit_log.py` — bounded limit/category; fixed `e` reuse; typed `by_action`.
- `dashboard/routes/api/guilds.py` — activity feed distinct result vars; channel listing branch-typed; sort key string-safe.
- `dashboard/routes/api/manifest.py` — category dict typed; priority sort `int(str(...))`.
- `dashboard/routes/api/health.py` — internal error logging only.
- `dashboard/__init__.py`, `dashboard/app.py` — unused import removed; `_server` typed.

### Tests
- New: `test_app.py` (lifecycle), `test_database/test_engine.py` (URL redaction), `test_version.py`, `test_modules/test_announcements.py`, `test_services/test_data_collector.py`, `test_services/test_moderation_service.py` (concurrency: 8 unique cases + 8 warnings), `test_modules/test_reputation_persistence.py` (caps + voice_minutes).
- Extended: `test_config.py` (OAuth-disabled, public-dashboard validation), `test_dashboard/test_api.py` (negative-limit 422, rule boundary, health non-leak), `test_services/test_security.py` (HSTS config, notes capability), `test_modules/test_auto_voice.py` (fixture now carries `guild`).

---

## 4. Removed / Consolidated Code

- Deleted: root `__init__.py` (conflicted with hyphenated checkout name for tooling).
- Removed dead code: `sse_message` dict (realtime_bridge), unused locals in ruleset_engine (`guild_id`, `user_id`, `content`, `track`, `dup_key`, `name`), unused `result` assignment (reputation), unused `RedirectResponse` import, unused imports in `database/models/__init__.py` (resolved with `__all__`), redundant `pytest` import in `tests/__init__.py`.
- Consolidated: all case creation now flows through `ModerationService.create_case_with_retry` (dashboard route, automod, module commands) instead of three inline `max(case_number)+1` implementations.
- No abandoned prototypes, backup files, or committed generated artifacts found in the tree.

---

## 5. Dependency Review

| Dependency | Version | Status |
|---|---|---|
| discord.py | ≥2.5,<3.0 | required, no known advisories |
| fastapi | ≥0.115,<1.0 | required |
| uvicorn[standard] | ≥0.34,<1.0 | required |
| sqlalchemy | ≥2.0,<3.0 | required |
| aiosqlite | ≥0.20,<1.0 | required |
| httpx | ≥0.28,<1.0 | **added** (was missing) |
| jinja2, aiofiles, python-multipart, itsdangerous | — | required |

Dev: pytest (pinned <10), pytest-asyncio, ruff 0.16, mypy 1.20, coverage, bandit, pip-audit, pre-commit — all pinned to major/minor.

- `pip check` — clean (no broken requirements).
- `pip-audit` — 0 vulnerabilities after upgrading pip 25.1.1 → 26.2 (pip itself had PYSEC-2026-2875/2876; fix is 26.1+). Local package `bark` is not on PyPI (expected; audit skips it).
- Lockfile (`uv.lock`) is present and consistent with pyproject.

---

## 6. Security Findings Summary

1. **Credential handling** — no credentials in the repo; `.env` git-ignored; `.env.example` documents variables with placeholders; database passwords redacted from logs. The only credential touched during the audit (sshpass for remote host) was used transiently and is never persisted in reports.
2. **Input validation** — all pagination bounded; category/search length-bounded; module rule types validated; guild ownership checked on ruleset mutation.
3. **Output safety** — health endpoint no longer reflects DB error details; CSP/HSTS/X-Frame-Options/Referrer-Policy headers set; dashboard binds localhost by default.
4. **Bandit** — 0 medium+ after fixes; the three B608 flags are safe identifier interpolation with regex-validated table/column names and parameterized values (`# nosec B608` documented); B110 try/except/pass sites are intentional swallow-and-continue in Discord event paths (low severity).
5. **SQLAlchemy** — all queries use the ORM/parameterized statements; no string-built SQL in production paths outside migrations (validated identifiers only).

---

## 7. Before-and-After Performance

Measured on hermes-core (CT1115), same Python 3.13.5 venv, SQLite, cold process.

| Metric | Baseline | Final |
|---|---|---|
| Test suite runtime | 192 tests, 11.5 s | 208 tests, 7.6 s (no coverage) |
| Coverage run runtime | — | 208 tests, 12.8 s |
| Config import | — | 6 ms |
| BarkBot import | — | 333 ms |
| Engine init | — | 11 ms |
| Full import + engine init (startup floor) | — | ~350 ms |
| Case creation (concurrent, 8 parallel) | potential UNIQUE violation | 8/8 unique, 0.76 s test |

Remote production observation (2026-07-31): Bark on CT1109, single process on :8090, ~152 MiB RSS, DB ~500 KiB, no post-startup tracebacks in logs. No performance regression expected — the added cap queries are index-backed and window-bounded.

---

## 8. Test Results and Coverage

- **208 passed, 0 failed** (was 192 at baseline; +16 net new regression tests).
- Coverage (branch, identical config): **41% → 44%**, with flat modules (`app`, `config`, `bark_version`) now included in the measurement.
- Key regression tests: concurrency case numbering (8 unique), reputation daily-cap enforcement, voice_minutes accumulation, negative-limit 422, cross-guild ruleset 403, health non-leak, DB URL redaction, HSTS emission under HTTPS config, notes capability mapping.

Coverage is intentionally not near 100%: large Discord-integration paths (message handlers, voice lifecycle) are thin under unit tests. The audit's regression tests target the correctness fixes rather than chasing coverage vanity.

---

## 9. Database and Storage Review

- SQLite via `sqlite+aiosqlite`, async SQLAlchemy 2.x; migrations in `database/migrations/__init__.py` with PRAGMA-based rebuilds; FK checks run post-migration.
- Concurrency: case numbering now lock+retry safe; all writes go through `session_scope()`; warnings atomic with cases.
- Storage: production DB ~500 KiB; no unbounded growth paths found (voice history has purge endpoints; cleanup loop prunes in-memory trackers every 5 min).
- Migration verification (subagent): mixed NULL/datetime timestamps and internal-id/snowflake duplicate guilds migrate cleanly; FK integrity holds.

---

## 10. Deployment and Runtime Review

- **Deployment** — systemd user service; runs from source with `pip install -e .`; Caddy (OPNsense) proxies `bark.warx.org` → 10.0.0.227:8090. Documented remaining item: make deployment build a wheel (or use `uv sync --frozen`) for reproducible installs; the service override file is untracked and should be committed under `deploy/`.
- **Runtime** — single async process; graceful shutdown closes bot, dashboard, DB engine, and realtime bridge; `asyncio.gather(return_exceptions=True)` prevents one service failure from killing the app; data collector runs at 15-min interval; no unbounded background work found.
- **CI/CD** — CI now gates ruff, format, mypy, bandit, pip-audit, and pytest on `master`.

---

## 11. Updated Documentation

- `README.md` — corrected dashboard host/public-URL defaults to match code (`127.0.0.1:8090`).
- `.env.example` — comprehensive, all 17 `BARK_*` variables with placeholders and safe defaults.
- This report and the remaining-issues list below.

---

## 12. Remaining Issues and Next Actions

| # | Issue | Priority | Next action |
|---|---|---|---|
| 1 | Moderation module (`modules/moderation/module.py`, 1093 lines) and dashboard `routes/api/moderation.py` are oversized | Medium | Split into per-concern files (cases, warnings, voice, rulesets, automod commands) in a follow-up refactor; do not block deploy |
| 2 | Coverage 44% — Discord-integration paths thin | Medium | Add integration tests with a mocked gateway (or `discord.py` test harness) for message-handler and voice-lifecycle paths |
| 3 | Deployment installs editable source; service override untracked | Medium | Commit `deploy/bark.service` + use `pip wheel`/`uv sync --frozen`; add a `deploy/` checklist |
| 4 | `ruleset_engine` param types widened to `Any` for duck-typed stubs | Low | Introduce a `RulesetLike`/`RuleLike` Protocol so the ORM model and stub share a type |
| 5 | `presence_store.py` and a few service helpers have 0% coverage | Low | Add unit tests when next touching presence features |
| 6 | `run_test_server.py` E402 is per-file-ignored | Low | Optional: convert to a proper pytest fixture server |

---

*Credentials: none appear in this report. Any values that could be sensitive were replaced with `[REDACTED]` or are placeholders.*
