# Bark — Ultimate Audit, Round 2 (2026-08-18)

**Re-audit of `dev` @ `f325b80` (60 commits past the round-1 baseline `a482041`).**
Round 1 (same day) already produced the five deliverables and a refactor queue; this
round re-ran the full audit against the current tree — the shadcn REMAKER had landed,
stats went DB-backed, settings merged, and role badges shipped — and repaired the five
live P1 findings it surfaced.

**Method:** 3 parallel read-only subagent audits (backend/Python, security, frontend) +
trust-but-confirm verification of every top finding against the tree. 774 tests green,
ruff clean throughout.

---

## Findings register (41 total, 0 P0)

### Backend — 16 findings (0 P0, 3 P1, 13 P2)

| # | Sev | Finding | Location | Status |
|---|---|---|---|---|
| 1 | P1 | Free-form `/bark` args assigned one token per param, shredding multi-word content | `services/slash_dispatcher.py:498-524` | ✅ fixed |
| 2 | P1 | `_resolve_member` falls back to the invoker → mistyped mention self-moderates | `services/slash_dispatcher.py:527-544` | ✅ fixed |
| 3 | P1 | Per-message synchronous DB upsert on the hot path (every non-bot message) | `bot/client.py:384-389`, `services/stats_recorder.py:28-59` | queued |
| 4 | P2 | `services/media_engine/` (1,749 LOC) orphaned — zero production imports | `services/media_engine/` | queued |
| 5 | P2 | `_apply_escalation` dead (inlined at `module.py:1384-1407`) | `modules/moderation/ruleset_engine.py:668-685` | queued |
| 6 | P2 | `_get_bark_group`/`_module_subgroup` dead (abandoned tree-group path) | `services/module_manager.py:121-155` | queued |
| 7 | P2 | `_json_dict`/`_json_list` byte-identical duplication | moderation module + ruleset_engine | queued |
| 8 | P2 | `except Exception: pass` silent swallows on hot paths (purge, unregister, member fetch) | `module_manager.py:375`, `ruleset_engine.py:660`, `data_collector.py:201` | queued |
| 9 | P2 | Fire-and-forget `create_task` with no stored ref/cancellation | `reputation/module.py:1093`, `speak/module.py:208` | queued |
| 10 | P2 | Hardcoded LAN IP `10.0.0.227` in CSRF origins + allowed_hosts | `security.py:30`, `dashboard/__init__.py:62` | ✅ fixed (round 2) |
| 11 | P2 | God modules — moderation 2,879 / reputation 2,425 / guilds.py 1,343 lines | — | queued |
| 12 | P2 | `_path_enabled` fails OPEN (`except Exception: return True`) | `slash_dispatcher.py:477-483` | queued |
| 13 | P2 | Untyped "mystery dict" plumbing (`get_module_config -> dict`, untyped payloads) | `bark_context.py`, `reputation/module.py` | queued |
| 14 | P2 | Per-route `_can_*` permission wrappers duplicated across 5 API files | `audit_log.py`, `notes.py`, `uploads.py`, `moderation.py`, `plugins.py` | queued |
| 15 | P2 | Tree error handler leaks raw exception text (contradicts its own docstring) | `bot/client.py:147` | queued |
| 16 | P2 | `save_module_config` check-then-act insert race (duplicate rows) | `bark_context.py:164-176` | queued |

### Security — 7 findings (0 P0, 2 P1, 5 P2)

| # | Sev | Finding | Location | Status |
|---|---|---|---|---|
| 1 | P1 | Stale login snapshot + fail-open actor check → removed moderator keeps rights ≤30 days | `actions.py:389-411`, `security.py:260` | ✅ fixed |
| 2 | P1 | CSRF origin guard compares hostname only → same-host cross-port CSRF | `security.py:405-412` | ✅ fixed |
| 3 | P2 | First-run setup API unauthenticated (writes `.env`) | `setup.py:62-92`, `setup_app.py` | ✅ fixed |
| 4 | P2 | `POST /moderation/cases` no in-handler permission check (middleware-only) | `moderation.py:134-182` | queued |
| 5 | P2 | Settings write endpoints accept arbitrary `GuildSetting` keys; import bypasses schema validation | `settings.py:150-156,289-319` | queued |
| 6 | P2 | No rate limiting on `/auth/login`, `/auth/callback`, `/auth/share/*` | `security.py:437` | queued |
| 7 | P2 | `GET /guilds/{gid}/settings` exposes all `GuildSetting` values to moderators | `settings.py:268-286` | queued |

### Frontend — 18 findings (0 P0, 2 P1, 16 P2)

| # | Sev | Finding | Location |
|---|---|---|---|
| 1 | P1 | Warning toasts render as green "success" (no `.toast-warning` branch) | `realtime.js:55`, `main.js:274-283`, `components.css:2600` |
| 2 | P1 | Markdown formatting toolbar keyboard-inaccessible (`mousedown`-only) | `module-workspace.js:304,309` |
| 3-18 | P2 | Quick-action timeout sends no duration; Thanks-Log search labels name but filters ID; `timeAgoRel` "NaNy ago"; ~50 dead CSS classes; hardcoded role-dot hex; near-duplicate token ladders; duplicate selector blocks + v3.css override layer; magic z-index; sidebar guild icon no fallback; large inline page scripts reimplement helpers; collapse MutationObserver workaround; hi-DPI stacked headers; guild-id parsed 4 ways; two reduced-motion impls; realtime.js toast wrapper drops messages | see `2026-08-18-refactor-queue.md` |

---

## Fixed this round (Phase A — Protect)

All five P1 findings + the two P2 security hardening items, each with a regression test:

1. **Setup-token gate** — `BARK_SETUP_TOKEN` env; setup server forces loopback when unset;
   `/api/setup` requires `X-Setup-Token` (hmac.compare_digest) when configured.
   (`config.py`, `dashboard/setup_app.py`, `dashboard/routes/setup.py`, `setup.html`, `tests/test_setup.py`)
2. **Fail-closed moderation actor** — `_mod_action` returns 403 when the session actor isn't a
   resolvable live member, instead of proceeding on a stale login snapshot.
   (`actions.py`, `tests/test_services/test_security_hardening.py`)
3. **Port-aware CSRF origins** — the origin guard now compares full `scheme://host:port`
   against a config-derived allowlist (`public_url` + bind host + loopback + `BARK_TRUSTED_ORIGINS`);
   the hardcoded `10.0.0.227` is gone from both `security.py` and `dashboard/__init__.py`.
   (`security.py`, `dashboard/__init__.py`, `config.py`, `tests/test_services/test_security.py`)
4. **Free-form `/bark` args** — the final string parameter is now a free-form sink (consumes all
   remaining tokens); parsing stops when tokens run out so callback defaults apply.
   (`slash_dispatcher.py`, `tests/test_services/test_slash_dispatcher.py`)
5. **No self-targeting** — `_resolve_member` returns `None` (not the invoker) on failure, and the
   dispatcher shows a "couldn't find that member" error for unresolved required targets.
   (`slash_dispatcher.py`, `tests/test_services/test_slash_dispatcher.py`)

**Baseline:** 768 → **774 tests** (+6), ruff clean (also fixed 2 pre-existing unused-import +
import-order errors).

## Deployment note (required before promoting)

The CSRF + setup changes add two env vars the live instances must set in `.env`, or LAN
dashboard writes will 403 and remote setup will bind loopback-only:

- `BARK_TRUSTED_ORIGINS=http://10.0.0.227:8090` (prod) / `...:8091` (dev) — the direct LAN origin(s).
- `BARK_SETUP_TOKEN=` (optional — only needed for remote first-time setup).

`.env.example` documents both.

## Remaining queue

The P2–P5 findings above, plus the still-open round-1 items, are unchanged and prioritized in
`docs/audits/2026-08-18-refactor-queue.md`. Next up by fix-order: backend P1 #3 (per-message DB
churn), security P2 #4 (moderation/cases handler gate), then Phase C duplication/dead-code passes.
