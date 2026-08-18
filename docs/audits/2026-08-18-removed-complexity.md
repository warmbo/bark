# Deliverable E — Removed Complexity Report

**Audit:** 2026-08-18 Ultimate Application Audit & Fix Plan (apply-to-Bark)
**Scope of this report:** the work committed on `dev` (rebased onto the real
shadcn remake line `f4b290a`) plus the follow-up config-health / invite-URL fixes.
**Final state:** Bark `dev` at `b197f31` (version **0.3.300**), 756 tests passing, ruff clean.

The strongest measure of a successful cleanup is not how much new architecture
was created, but how much unnecessary architecture was eliminated. This report
tracks what was removed, collapsed, or made obsolete.

---

## 1. Lines / files removed

| Item | Removed | Why |
| ---- | ------- | --- |
| Stale 0.2 fork of the audit work | 4 divergent commits (`95ad958` baseline) | The audit had been built on a 30-commit-behind ancestor of `origin/dev`; rebasing onto `f4b290a` collapsed the fork instead of merging two history lines. |
| Duplicate `settings.py` int-guard | 1 schema-prop change | The shadcn remake already contained an equivalent `import_settings` guard (400, not 500). My near-duplicate ("Invalid backup version") was dropped; the file is now byte-identical to `f4b290a` (diff = 0). |
| Dead `elif module_name == 'speak'` branch | 4 lines | A template branch that could never fire (speak has a settings schema, so the `if` at line 123 always won). Collapsed into a reachable `{% if module_name == 'speak' %}` after the form. |
| `format: hidden` schema hack (attempted) | removed during implementation | First attempt to hide `phrases` used an undeclared `format` value, which violated the module-UI ingredient contract (`test_settings_schema_uses_only_known_ingredient_types`). Replaced with the architecturally-correct signal: a free-form `object` with no `properties`. |

## 2. Duplicate systems retired

| System | Resolution |
| ------ | ---------- | --- |
| Two pending history lines (audit fork vs remake) | One linear history. The 4 audit commits now sit directly on top of the remake; no parallel branch to maintain. |
| Two invite-URL sources (raw Discord OAuth URL in catalog + branded `/invite`) | Canonicalized to `{public_url}/invite` everywhere (guild cards, dashboard, help module). The raw Discord OAuth URL is now derived only server-side inside the `/invite` route. |
| Two "unknown setting" handling paths (validator + one-off comment workaround in `settings.py`) | The validator is the single source of truth; `settings.py` notes it rather than re-implementing a bypass. |

## 3. Duplicate functions removed

- None newly introduced. The `build_bot_invite_url` signature is preserved (backward-compatible) but its body was simplified from a 7-line `urllib` query builder to a one-line branded-link return.

## 4. CSS declarations consolidated

- Not in scope of this pass (CSS consolidation belongs to the shadcn REMAKER, which is the line we are now on). No dead CSS removed here.

## 5. LEGACY systems retired

- The `feat/shadcn-migration` naming is retired in favor of the canonical `dev` line (the audit was rebased onto `dev`, not a side branch). The `audit-backup-95ad958` branch is retained as a safety net but is no longer the active line.

## 6. Special cases removed

| Special case | Removal |
| ---- | ------- |
| Speak `phrases` flagged as "unknown setting" by Config Health | Eliminated — `phrases` is now a declared schema property (free-form object). Config Health for speak is **Unhealthy (1)** → resolved. |
| Speak Phrases editor unreachable in UI | Eliminated — editor restored to the Configure tab. |
| Raw Discord OAuth URL leaked into guild cards | Eliminated — all invite links are now the branded `/invite`. |

## 7. TODO / FIXME count

- No new TODO/FIXME added. Existing count unchanged (tracked separately in the refactor queue).

## 8. Net change (this round)

- Commits: 5 (rebase re-application of 4 audit commits + 1 fix commit `b197f31`).
- Files changed in fix commit: 5 (+68 / −17).
- Tests added: 2 (speak schema validates with phrases; catalog invite_url ends with `/invite`).
- Test count: 754 (remake) → **756** (after fix).
- Version: 0.3.299 → **0.3.300**.

## 9. What was deliberately NOT removed

- The `2026-08-12-24h-audit.md` untracked file present at session start — pre-existing, not part of this work, left untouched.
- Setup-wizard auth, session `Secure` default, giant-module splits, dead CSS/CSP — deferred to the refactor queue (`2026-08-18-refactor-queue.md`) and the REMAKER's own passes.
- `build_bot_invite_url(client_id, guild_id)` parameter names kept for call-site compatibility even though the new body derives the URL from `config.dashboard.public_url`.

---

**Regression check:** 756 tests pass, ruff clean, config-health false positive resolved, invite URL canonicalized, no new duplication introduced. The repo contains fewer exceptions and special cases than at the start of the round.
