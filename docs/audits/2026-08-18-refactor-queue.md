# Bark — Refactor Queue

Prioritized backlog from the 2026-08-18 audit. **P0–P1 that were confirmed and fixed are listed with their commit.** Remaining items are confirmed findings not yet repaired — either because they carry refactor risk (deferred to a dedicated pass), touch the in-flight shadcn-migration branch, or are low-value cleanup.

Legend: **P0** Critical · **P1** Stability/Security · **P2** Architecture · **P3** Consistency · **P4** Cleanup · **P5** Optimization.

## P1 — Stability / Security

- [x] **Case attribution forgery** — `moderation.py` `create_case` now derives `moderator_id`/`moderator_tag` from the session. *(commit `2cee569`)*
- [x] **Module-override authz mismatch** — `mutation_capability` now resolves `modules/{name}` to the module's own capability so per-guild `ModuleRoleAccess` overrides apply. *(commit `2cee569`)*
- [x] **Stale guild access after member/guild removal** — revoked via `on_member_remove`/`on_guild_remove`. *(commit `2cee569`)*
- [ ] **Setup wizard can bind non-loopback unauthenticated** — `/api/setup` writes `.env` with no auth when `config.needs_setup`; if `BARK_DASHBOARD_HOST=0.0.0.0` + unconfigured token, anyone can claim the instance. Fix: require `BARK_SETUP_TOKEN` for `/api/setup` when host is non-loopback, or force loopback bind in setup mode. (`dashboard/routes/setup.py`, `dashboard/setup_app.py:44-58`)
- [ ] **Session cookie not `Secure` by default on HTTP/LAN** — `secure_cookies` is False when `public_url` is http; sniffable over shared Wi-Fi. Fix: require secure cookies whenever binding a non-loopback host (mirror `validate_startup`). (`dashboard/__init__.py:50-56`, `config.py:67-69`)

## P2 — Architecture

- [ ] **AutoMod 30s config cache never invalidated by dashboard saves** — `_config_cache` (TTL 30s) survives a save, so rules enforce stale values ≤30s. Fix: override `save_dashboard_config` to pop `_config_cache`. (`modules/moderation/module.py:1502-1503,1566-1567`)
- [ ] **Split the two giant module files** — `modules/moderation/module.py` (2835 lines) and `modules/reputation/module.py` (2424) mix events, slash factories, API routers, and background loops. Fix: split per concern (routes/service/loops). **Deferred — high refactor risk, needs its own verified pass.**
- [ ] **Cold module-role cache silently enforces admin** — a handler checking `check_api_permission` without priming `get_module_min_role` enforces the fail-closed admin default until another endpoint primes the cache. Safe but inconsistent. Fix: centralize/audit the priming contract; add a cold-cache regression test. (`services/response.py:101-112`)
- [ ] **`test_module_action` hardcodes `isinstance(module, LoggingModule)`** — every new module with a test action needs another branch. Fix: standard `module.handle_test_action(...)` contract. (`modules.py:356-359`)
- [ ] **Hardcoded LAN IP `10.0.0.227`** in `_TRUSTED_ORIGIN_HOSTS` + `allowed_hosts` — CSRF/TrustedHost break if the host IP changes. Fix: `BARK_TRUSTED_HOSTS` env feeding both. (`security.py:30`, `dashboard/__init__.py:62`)

## P3 — Consistency

- [ ] **`get_module_config` cache asymmetry** — hit returns shared cached dict; miss deepcopies then returns the original (the deepcopy protects nothing). Fix: always return `copy.deepcopy(cached[1])`. (`services/bark_context.py:113-114,132`)
- [ ] **Mixed naive/aware DateTime columns** — `DateTime` (naive) mixed with `DateTime(timezone=True)` forces per-site tzinfo patches. Fix: standardize `DateTime(timezone=True)` + aware read guard. (`models/moderation.py:40`, `guild.py:23`, `analytics.py:35`)
- [ ] **`ruleset_engine` effect failures swallowed** — kick/ban/timeout effects use `except Exception: pass`, so a failed kick looks like the rule never fired. Fix: log + audit on effect failure. (`ruleset_engine.py:545,556,606,647,665,684`)
- [ ] **`_message_stats`/guild rows never pruned on guild leave** — unbounded in-memory growth. Fix: cap keys / drop on `on_guild_remove`. (`bot/client.py:71,391-392`)
- [ ] **`cors_origins` is dead config** — zero readers, no CORSMiddleware. Fix: delete the field or wire CORS. (`config.py:54`)
- [ ] **`/s/` public-path allowlist entry is dead** (no route exists) — future `/s/` route would silently become public. Fix: remove or wire it. (`security.py:41`)
- [ ] **`/api/v1/guilds/plugin-catalog` permanently 404'd** — dead endpoint, and if the guard loosens it becomes open. Fix: move off `/guilds/` + add authz. (`manifest.py:64-66`)
- [ ] **`update_general_settings` accepts arbitrary keys** (no allowlist) — safe today, fragile for future sensitive keys. Fix: allowlist per section. (`settings.py:285-315`)

## P4 — Cleanup / Standardize UI

- [ ] **`page_header` macro defined but zero importers** — 8 pages hand-roll identical `.page-header` markup. Fix: import+use the macro; extract `settings_card`/`settings_section` macros (settings.html hand-rolls 9 near-identical cards). **Template layer, not migration territory.**
- [ ] **Second modal system** — `#update-terminal-overlay` (focus now fixed) is a parallel modal to `BarkDialog`. Longer-term: route through `BarkDialog`. (`settings.html:299-315`)
- [ ] **~35 dead CSS rules** + unused template classes (`.save-bar`, `.glass`, `.qa-*`, `.stats-placeholder-text`, `.settings-grid` dup at main.css:630). **Migration territory — lives in `bark3-v030/frontend/src` (REMAKER strips glass).**
- [ ] **Token bypasses / magic spacing** — 8px×120/12px×108/14px×74 etc. despite `--space-*`; `.mt-1/.mt-2` magic utilities; `.text-sm{font-size:13px!important}`; 16 breakpoints incl. near-dupes. **Migration territory.**
- [ ] **`palette.js` broken listbox semantics** — `role=option` anchors interleaved with group divs, no `aria-activedescendant`. Fix: flat option list + `aria-activedescendant`. (`palette.js:156-168`)
- [ ] **mod-roles `<details>` vs workspace role-menu** — two different close behaviors. Fix: shared outside-click handler. (`settings.html:441-444`)
- [ ] **Sidebar "Connected" label never updated by health poll** — banner appears but label still claims Connected; shortcuts.js closes classes that no longer exist. Fix: drive label from health; drop dead cleanup selectors. (`base.html:122-135`, `shortcuts.js:14`)
- [ ] **`restore_applied` / other shadcn-migration orphans** — see the separate `feat/shadcn-migration` branch for Phase 2.5/2.6/3.8/3.10 roadmap items.

## P5 — Optimization

- [ ] **`get_guild_stats`/roles/channels/dashboard are any-member reads** (by design) — viewer tier can enumerate members/roles. Confirm acceptable or gate. (`guilds.py:257,362,456,485`)
- [ ] **Per-event DB churn on hot paths** — TTL cache on the config accessor (save invalidates) was the pattern; verify remaining hot-path queries are batched.
- [ ] **CSP `script-src` includes `'unsafe-inline'` + `connect-src ws: wss:` to any host** — move inline scripts to static files/nonces, restrict `connect-src`. **Migration territory (REMAKER self-hosts).**
- [ ] **Uploaded media validated by magic bytes only; public `/media/` never expires** — decode with Pillow before persisting; GC orphaned uploads. (`image_validate.py:16-28`, `uploads.py:129-148`)

## Deferred / shadow-migration note

CSS-source findings (dead rules, tokens, breakpoints, `.settings-grid` dup, CSP, upload hardening) **live in the `bark3-v030/frontend/src` sources** for the shadcn REMAKER branch, not this repo's generated `main.css`. They belong to the in-flight migration and were intentionally not touched here to avoid a three-way conflict with the shadcn worktree. Template-layer and JS-layer fixes (a11y, safeFetch, dead macros) were applied in this repo.

## Validation after each batch

Formatting (`ruff check`) · Type check (`mypy`) · Unit+integration (`pytest`) · Security tests (`tests/test_dashboard/test_auth_access.py`, `test_oauth_loop.py`) · Frontend contract tests (`test_frontend_a11y_contract.py` incl. the compile-all Jinja guard) · Manual smoke (Playwright local mock-mode server).
