# Bark — Removed Complexity Report

Tracking what the 2026-08-18 audit eliminated or made simpler. The measure of a good cleanup is how much unnecessary architecture was removed, not how much was added.

## Committed changes

| Metric | Phase A (`2cee569`) | Phase B (`b22a6bb`) |
|---|---|---|
| Files changed | 9 | 9 |
| Insertions | 176 | 47 |
| Deletions | 12 | 20 |
| New regression tests | 1 | 0 |

## Removed / simplified complexity

1. **Attribution forgery path closed** — `create_case` no longer trusts the client for `moderator_id`/`moderator_tag`. One fewer client-trusted identity (was the only moderation write that did). Server-side actor derivation.
2. **Divergent module-authz eliminated** — middleware `mutation_capability` and module handlers now resolve the **same** capability (`<name>.configure/manage`). Removed the class of "UI shows a control that 403s" bugs.
3. **Stale-access revocation added** — the dashboard authorization previously had **no lifecycle hook** for membership changes (access only refreshed at login). Two new event hooks (`on_member_remove`, `on_guild_remove`) now keep the persisted snapshot truthful, plus one shared `revoke_user_guild_access` helper. Net: one canonical path for "user lost access", used by both.
4. **Silent failure converted to logged failure** — AutoMod legacy config-load and the ruleset effects no longer `except Exception: pass`; the AutoMod load logs the exact guild that failed.
5. **Second-encoding crash class reduced** — two unguarded `int()` sites guarded to match the canonical `_member_name` pattern (the "one non-numeric id 500s the whole endpoint" class). The sibling-sweep rule means these were the known remaining instances.
6. **Dead/misleading code paths cleaned** — `vc_move` no longer reuses `duration` as `channel_id` (mystery param reuse); `import_settings` no longer 500s on a malformed `version`; sidebar manifest no longer has a second raw `fetch` bypassing `safeFetch`; the health watchdog no longer leaks an interval into bfcache.
7. **Nested-interactive a11y removed** — the media-picker delete control was a `<button>` nested in a `<button>` (invalid, keyboard-invisible). Now a `div[role=button]` with a real child button + Enter/Space.
8. **Six icon-render bugs fixed at once** — the "Jinja `{{ icon() }}` in JS innerHTML → blank icon" class fixed by `refreshIcons()` after restore, across settings/modules/members.

## What was NOT removed (deliberately)

The following were found but left in place — with reasons:

- **Two giant module files** (moderation 2835, reputation 2424 lines): splitting is high-risk (events + slash factories + routers + loops intertwined) and would touch the same files the shadcn migration is rewriting. Queued P2.
- **~35 dead CSS rules + magic spacing**: live in the `bark3-v030/frontend/src` sources for the shadcn REMAKER, not this repo's generated `main.css`. Removing here would conflict with the in-flight migration. Queued P4 (migration).
- **`page_header` macro under-use**: a P4 template consolidation; skipped to keep this pass behavior-preserving and focused on correctness/security.
- **`cors_origins` dead config, `/s/` dead allowlist entry, `plugin-catalog` dead route**: removed-from-queue candidates, but each needs a decision (delete vs wire) and a test; listed P3.

## Net effect

- **Complexity removed:** 2 crash classes (client-trusted actor, unguarded int), 1 authz-divergence, 1 silent-failure, 1 second fetch wrapper, 1 interval leak, 1 invalid-HTML pattern, 6 icon-render bugs.
- **New shared code:** 1 revocation helper (`revoke_user_guild_access`) + 2 thin event hooks.
- **Tests:** 730 passing (was 729), incl. a new regression test locking the revocation behavior.
- **No visual change to the UI** — Phase B was a11y/robustness only.

## Remaining complexity (from the register)

Full prioritized backlog in `docs/audits/2026-08-18-refactor-queue.md`. Headline deferred items: setup-wizard auth, session-cookie Secure default (P1); module file splitting, AutoMod cache invalidation (P2); dead CSS + magic spacing + CSP (migration/P5).
