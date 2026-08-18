# Bark — shadcn UI Migration Audit

Branch: `feat/shadcn-migration` (off `origin/dev` @ `e4eaca0`, v0.3.287)
Date: 2026-08-18
Status: Foundation done · Adoption pending · Audit below

---

## A. Current UI Architecture

Bark is a **server-rendered FastAPI + Jinja2** app (no React, no Node on the deploy host). The frontend uses the **Path A** shadcn adoption model (vendored + pinned):

- **Build pipeline:** `frontend/` holds exact-pinned `package.json` (tailwindcss + @tailwindcss/cli `4.3.3`, lucide `1.31.0`, Inter/JetBrains Mono `5.3.0`). `npm run build` → `build.mjs` compiles `frontend/src/{theme,v3,legacy}.css` into the **committed** `dashboard/static/css/main.css` (4,101 lines). The server serves static CSS/fonts/lucide UMD — **no Node needed on CT1109**. Upstream version can't drift (pinned lockfile + `frontend/shadcn-pin.md`).
- **Design tokens:** `frontend/src/theme.css` defines shadcn semantic tokens (`--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--border`, `--ring`, sidebar tokens, chart tokens…) mapped onto Bark's brand palette — **dark-only, 0px radius**, steel/black surfaces, electric-blue primary, ivory foreground, using `oklch`.
- **Component layer:** `dashboard/templates/components/primitives.html` (8.4 KB) exposes Jinja macros — `button`, `card`, `badge`, `status_badge`, `input_field`, `select_field`, `textarea_field`, `schema_field`, `separator`, `avatar`, `page_header`, `state_panel` — that emit semantic-class markup while preserving stable IDs/data-attrs for the behavior layer. `components/icons.html` provides the `icon()` Lucide macro.
- **Behavior layer:** vanilla-JS (`main.js` + per-workspace files) with hand-rolled shims for interactive primitives: `BarkDialog` (confirm/dialog/modal — 18+35+21 refs), toast (16), the command palette, tabs, dropdowns.
- **CSS scale:** 4,180 source lines (legacy 3,481 + theme 84 + v3 615). `legacy.css` has **852 distinct class selectors**, 15 `!important`, and ~40 hardcoded hex/rgba values. `v3.css` (615) is the new shadcn-utility layer. `main.css` = merged output.

### Where adoption stands
Only **`module_detail.html`** imports and uses the primitives macros. The other **20+ templates** (base, landing, dashboard, guild, members, moderation, settings, stats, module tabs…) still use raw legacy classes. So the new design system exists but is applied to ~1 of 21 pages.

---

## B. Major Inconsistencies

1. **Two design systems live simultaneously** — legacy classes (`content-card`, `btn btn-primary`, `form-input`, `status-badge`) coexist with the shadcn/token layer. No page besides `module_detail` exercises the new layer.
2. **852 legacy selectors vs. semantic tokens** — `legacy.css` hardcodes ~40 hex/rgba colors (`#3b82f6`, `#4ade80`, `#f87171`, `#86d9a4`, `rgba(255,255,255,.08)`…) instead of `--primary`, `--destructive`, `--muted`, `--border`.
3. **15 `!important`** in legacy.css — specificity/workarounds that the token layer should render unnecessary.
4. **Interactive primitives reimplemented per-context** — `BarkDialog`/`confirm`/`toast` are invoked 50+ times across JS but there's no single shim set shared cleanly (dialog 35 + modal 21 + confirm 52 overlap).
5. **Page headers, cards, settings sections, forms** each hand-rolled — no shared `page_header`/`card`/`settings_section`/`settings_row` usage outside `module_detail`.
6. **Button variants** — legacy uses `btn btn-primary / btn-danger / btn-sm / btn-xs`; the macro maps these but variants are not yet a deliberate small set (`default/secondary/outline/ghost/destructive/link`).
7. **Cache-buster drift risk** — CSS/JS `?v=N` must bump when `main.css` rebuilds or templates gain new helpers; stale caches break returning users.

---

## C. shadcn Replacement Map

| Existing Bark UI | shadcn Replacement |
|---|---|
| `content-card` + nested cards | `card()` macro / flattened sections (avoid card-in-card) |
| `btn btn-primary/btn-danger/btn-sm/btn-xs` | `button()` macro → deliberate `default/secondary/outline/ghost/destructive/link` set |
| `form-input / form-select / form-textarea` + inline hints | `input_field / select_field / textarea_field / schema_field` macros (label + desc + error contract) |
| `status-badge status-*` | `badge()` / `status_badge()` macro (semantic color via `status-{kind}`) |
| Per-page `page-header` implementations | `page_header()` macro (breadcrumb + title + desc + actions) |
| Custom modal / confirm / alert | `BarkDialog` (focus trap, Esc, click-outside, aria-modal) — consolidate 3 modal variants |
| Custom toast / green success banners | `BarkToast` (subtle ephemeral feedback) |
| `toggle-switch` checkboxes | Keep markup, ensure it maps to shadcn switch styling via tokens |
| Avatar rendering | `avatar()` macro (img + fallback + sr-only) |
| Loading placeholders | `state_panel(kind='loading')` → Skeleton-style |
| Custom dropdown / palette | Command palette (Lucide + keyboard nav) |

## D. Shared Bark Components (worth retaining/creating)

- **Retain (built):** `page_header`, `card`, `button`, `input_field`, `select_field`, `textarea_field`, `schema_field` (schema-driven settings rendering — high value), `badge`/`status_badge`, `avatar`, `separator`, `state_panel`, `icon`.
- **Create:** `settings_section` / `settings_row` (grouped settings per §6), `guild_selector` (already in sidebar, formalize), `discord_role` / `discord_channel` / `case_status` display primitives (§16), `empty_state` wrapper, `data_table` for moderation/audit/member lists (§13), `confirm_action` (dialog-confirm wrapper).

## E. CSS Cleanup Opportunities

- Fold hardcoded colors in `legacy.css` → semantic tokens (`--primary`, `--destructive`, `--muted-foreground`, `--border`, `--accent`).
- Remove/replace the 15 `!important` (verify each; token layer should eliminate the need).
- Prune dead/duplicate selectors as pages convert to macros (the css-js-audit probe can quantify — target substantially reducing the 852-selector legacy surface).
- Unify shadows: reserve elevation for dialogs/dropdowns/palette; strip shadow-from-every-card.
- Normalize radius via `--radius` (already 0px), font scale via `--font-sans`/`--font-mono`, spacing via a small scale.
- Remove `rgba(0,0,0,…)` overlays in favor of token-based surfaces.

## F. Migration Risk (visual changes that could affect behavior)

| Risk | Mitigation |
|---|---|
| **Contract tests** (60 across a11y/JS/CSS) assert current classes/structure — a redesign left against stale contracts goes red. | Migrate contract tests **in lockstep**, green first; never leave red. |
| **IDs / data-attrs** drive the JS behavior layer — replacing markup must not break `data-action`, `data-endpoint`, form names. | Macros preserve IDs/data-attrs (already designed for this). Add a contract test asserting key selectors survive. |
| **Stale-cache ReferenceError** — new helpers in main.js with old `?v=N`. | Bump cache-buster in the same commit as any main.js/template change. |
| **Dark-mode contrast** regressions on rebuilt components. | Verify both themes + contrast after each batch (vision + probes). |
| **Responsive overflow** at 375/768/1024/1440/1920. | Automated viewport checks per batch. |
| **Live prod** is on the same code — must not deploy broken CSS. | Work on `feat/shadcn-migration` → deploy only to **bark-dev**, sign-off gate before stable promotion. |

## G. Migration Sequence (safest order)

1. **Phase 1 — Foundation (DONE):** tokens, Tailwind v4, vendored build, macro layer. ✅
2. **Phase 2 — Application Shell (pilot):** `base.html` (sidebar, header, guild selector, palette, main container) + `landing.html` + `dashboard.html`. **Visual verify desktop+mobile, sign-off gate.**
3. **Phase 3 — Shared Controls:** convert buttons/inputs/selects/tabs/dropdowns/dialogs/toasts; remove legacy equivalents.
4. **Phase 4 — Settings Architecture:** `settings_section`/`settings_row`; migrate `settings.html`, `guild.html`, module Configure tabs.
5. **Phase 5 — Data Interfaces:** moderation/audit/member/case tables + filters + pagination.
6. **Phase 6 — Secondary:** empty/loading/error states, confirmation flows, help text, error pages.
7. **Phase 7 — Cleanup:** remove redundant CSS/components/JS; regression test (contracts + 5 viewports + both themes).

**Each phase:** convert templates → rebuild `main.css` → bump cache-buster → run full suite + contract tests green → deploy to bark-dev → visual verify. **Only Phase 2 pilot goes through a sign-off gate before proceeding.**

---

## Definition of Done (matching spec)
When completed: majority of standard controls use shadcn primitives; pages share spacing/hierarchy; settings share structure; nav uniform; custom CSS substantially reduced; duplicates removed; semantic tokens control UI; dark mode first-class; responsive consistent; a11y + keyboard functional; existing functionality intact; no visible legacy/new mixture.
