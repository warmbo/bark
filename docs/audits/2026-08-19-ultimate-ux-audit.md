# Bark — Ultimate UI/UX Audit & Improvement Plan (Design Pass)

**Date:** 2026-08-19
**Baseline:** branch `dev`, HEAD `aa04c77` (777+ tests green, ruff clean)
**Method:** The full 96-section design methodology — visual language, hierarchy, grid,
spacing, density, containers, borders, radius, shadows, color, contrast, typography,
iconography, buttons, forms, tables, dashboards, navigation, tabs, modals, notifications,
loading/empty/error states, responsive, a11y, motion, terminology, and design entropy.
Read-only audit + live screenshot wall; **no files modified during discovery.**
**Evidence:** 21 screenshots captured from the mock server (permissive auth, seeded data)
at 1440/1280/768/390px — `docs/audits/2026-08-19-screenshots/` (`wall-desktop.png`,
`wall-mobile.png` are the side-by-side walls).

**Prior rounds this builds on:** 2026-08-18 ultimate audit (backend/security) + round 2
(frontend P1s) + UI standard (`2026-08-18-ui-standard.md`). This pass is the
**design-discipline** audit the previous rounds did not run: it checks whether every
screen looks like the same team designed it with the same rules.

---

## Executive summary

Bark is **structurally consistent and visually coherent** at the shell level — the sidebar,
page headers, buttons, cards, and status system are recognizably one product, and the
2026-08-18 REMAKER (flat shadcn surfaces) closed most of the glass-era drift. The landing
page is now token-aligned (verified: `var(--radius)`, no raw hex), the warning-toast
regression is fixed, and body-text contrast passes AA across the board.

The disorder that remains is **systemic micro-entropy**: two design eras still coexist in
the CSS (`components.css` legacy + `v3.css` REMAKER override layer), a **broken button
size ladder** (`.btn-sm` renders bigger than `.btn`), **mixed border radii** (15 hardcoded
non-token radii against the 0px contract), **two shadow scales defined twice**, **24
distinct font sizes** including fractional 12.5/13.5px, **magic z-index values up to
99999**, a **non-scale clamp spacing ladder** producing 17/21/33px values, **~50 verified
dead CSS classes**, and **raw unstyled HTTP 404 responses** on missing modules/guilds.
Contrast: `.btn-primary`/`.btn-danger`/landing-accent labels fail WCAG AA small-text
(3.6–3.8:1). Mobile holds up with zero horizontal overflow, but the moderation workspace
is overloaded at 390px and filter dropdowns fall below the 44px touch target.

**Zero P0 findings.** 4 P1 (contrast AA, raw 404 pages, settings partial-failure
silence, button-size inversion), 10 P2 (spacing/shadow/z-index/typography consolidation,
design-era merge, dead CSS, double-h1, density mismatch, interaction inconsistency),
8 P3 (alignment, asymmetry, microcopy), 5 P4/P5 (polish, delight).

> **Post-audit cascade correction (important):** the static value inventory over-flagged
> three findings. The build order is theme.css → tokens.css → components.css → v3.css,
> and **v3.css (the REMAKER layer) wins the cascade**. Verified against shipped CSS:
> - **Contrast (§1.9): ALREADY PASSES.** `.btn-primary`/`.btn-danger`/landing CTA are
>   overridden by v3 with `--primary`/`--destructive` + near-ivory foreground →
>   **9.93:1 / 9.13:1 / 11.31:1**, all AA. The 3.68:1 figure came from the *dead legacy*
>   rule (`background: var(--accent)` in components.css) that never ships.
> - **Spacing (§1.3): ALREADY SCALE-BASED.** v3 redefines `--space-xs..xl` as
>   `var(--space-1/2/4/5/6)` = 4/8/16/20/24px. The clamp ladder in tokens.css is dead
>   code, not shipped behavior. The hardcoded literals (~40) still bypass the scale —
>   that part of the finding stands.
> - **Shadows (§1.4): partially.** `--shadow-sm/lg` are defined in tokens.css (legacy
>   rgba) AND Tailwind's `@layer theme`; unlayered tokens.css wins, so the shipped value
>   is deterministic (rgba). The duplicate is a source-level smell, not a shipped conflict.
>
> What remains REAL after correction: button ladder inversion (fixed below), raw 404s,
> double-h1, settings partial-failure, timeout inconsistency, dead CSS, magic z-index,
> density mismatch, typography ladder, literal radii, reduced-motion duplication.

Full register follows; then the 7 required deliverables: Visual Consistency Report,
UX Friction Report, Design System Specification, Component Inventory, Screen Consistency
Matrix, Improvement Backlog, Before/After Gallery.

---

# Deliverable 1 — Visual Consistency Report

Legend: P0 = crash/data-loss/security · P1 = accessibility/usability failure ·
P2 = structural inconsistency · P3 = component inconsistency · P4 = visual refinement ·
P5 = delight/polish. Each finding: location → observed → rule → canonical replacement →
migration priority.

## 1.1 Design-era coexistence (REMAKER override layer) — P2 structural

- **Location:** `frontend/src/v3.css:618` ("REMAKER — flat shadcn surfaces … Loads last,
  so it wins over components.css"), `frontend/src/components.css` (legacy glass rules).
- **Observed:** two competing surface philosophies ship in the same stylesheet: the legacy
  glassmorphism era (frosted `backdrop-filter`, glows, gradients, heavy shadows in
  `components.css`) and the flat bordered shadcn era (`v3.css` REMAKER). The REMAKER wins
  purely by cascade order, and there is a visible `@media (prefers-reduced-motion: reduce)`
  block from each era (main.css:3027 legacy vs 4231 shadcn) — dead duplication.
- **Rule violated:** "One design era. If two things look different, a meaning difference
  must justify it." A whole-class cascade override is the #1 symptom of design-system
  failure (audit §71 CSS Override Audit).
- **Canonical replacement:** delete the legacy glass rules/selectors the REMAKER
  neutralizes; keep one surface token family (`--bg-card` etc. already flat). One
  reduced-motion block.
- **Migration priority:** P2 — do with the spacing/shadow consolidation (1.3–1.5).

## 1.2 Button size ladder is inverted — P1 usability

- **Location:** `dashboard/static/css/main.css` `.btn` / `.btn-sm` / `.btn-xs`
  (components.css sources).
- **Observed:** `.btn` = `padding:4px 9px; font-size:12px`; `.btn-sm` =
  `padding:5px 16px; font-size:13px`; `.btn-xs` = `padding:2px 8px; font-size:11px`.
  **`.btn-sm` renders LARGER than the base `.btn`** — the "small" variant is the biggest
  button in the system. Every `btn-sm` usage (page-actions, toolbar buttons, form actions)
  is therefore visually louder than plain `.btn`, and `.btn-xs` is the only true small size.
  Additionally `.btn-icon` hardcodes `border-radius:6px` (28px square) against the 0px
  system and a legacy `--glass-border` token.
- **Rule violated:** size variants must be monotonic (xs < base < sm < md).
- **Canonical replacement:** `.btn` = 12px/`5px 14px` (or keep 4x9 and make `.btn-sm`
  11px/`3px 10px`); `.btn-xs` = 10px/`2px 8px`; `.btn-icon` uses `var(--radius)`.
- **Migration priority:** P1 (Phase B buttons) — cheap, one CSS rule each + build + test.

## 1.3 Spacing scale: three competing systems — P2 structural

- **Location:** `frontend/src/theme.css`/`tokens.css` + main.css.
- **Observed:** (a) a clean `--space-1..12` scale (4/8/12/16/20/24/32/40/48px) exists and
  is used ~40×; (b) a second clamp-based ladder `--space-xs..xl` computes **non-scale
  values** — verified at 1440px: xs=6px, sm=8.6px, md=17.3px, lg=20.9px, xl=33.1px — the
  exact "odd values" (17/21/33px) the methodology flags; (c) ~40 literal hardcoded
  paddings/margins/gaps (1,2,3,4,5,6,7,8,9,10,12,14,16,20,22,24,32,48,56px) bypass both
  scales. `gap:` alone has 26 distinct values.
- **Rule violated:** one deliberate spacing scale, same relationship = same spacing.
- **Canonical replacement:** adopt `--space-1..12` as the only scale; delete the clamp
  ladder; remap hardcoded literals to nearest scale step (2px→space-1, 6px→space-1.5 or
  keep 6 as space-1.5, 14px→space-3.5, 22px→space-6...).
- **Migration priority:** P2 (Phase C spacing) — mechanical, verify with a spacing
  contract test.

## 1.4 Shadows: defined twice, plus one-off literals — P2 structural

- **Location:** `--shadow-sm`/`--shadow-lg` in main.css.
- **Observed:** `--shadow-sm: 0 1px 3px rgba(0,0,0,.4)` (legacy) **and**
  `--shadow-sm: 0 1px 3px 0 #0000001a, 0 1px 2px -1px #0000001a` (shadcn) — the same token
  defined twice with different values; same for `--shadow-lg`. Plus ~10 one-off literal
  box-shadows (focus rings, scrims, glows) and `--shadow-card: none` (cards flat, good).
- **Rule violated:** one token = one value; shadows communicate depth or nothing.
- **Canonical replacement:** keep the shadcn pair; fold the intentional focus-ring shadows
  into a `--shadow-focus` token; delete the rest.
- **Migration priority:** P2 (Phase C borders/shadows).

## 1.5 z-index is a magic ladder — P2 structural

- **Location:** main.css.
- **Observed:** 12 distinct literal z-index values (5, 20, 40, 50, 90, 95, 100, 200, 600,
  9998, 9999, 10000, 99999) vs exactly two tokens (`--z-dialog:1900`, `--z-overlay:1800`,
  used 2×). Stacking order is unreadable and collision-prone.
- **Rule violated:** a few named layers, nothing else.
- **Canonical replacement:** `--z-base:0 · --z-sticky:100 · --z-dropdown:300 ·
  --z-tooltip:400 · --z-dialog:1900 · --z-overlay:1800 · --z-toast:9999`; replace literals.
- **Migration priority:** P2 (with 1.3/1.4).

## 1.6 Typography: 24 sizes, no semantic ladder — P3 component

- **Location:** main.css.
- **Observed:** font-size inventory is 24 distinct values: 8,9,10(×7),11(×24),12(×53),
  12.5,13(×53),13.5,14(×34),15(×13),16(×9),17,18,19,20,21,22,24,30px + rem/em/%. The
  two most common sizes (12 and 13px) are near-duplicates; fractional 12.5px and 13.5px
  exist; only 2 uses of `--font-size-body` and 1 of `--text-sm` — the semantic tokens are
  effectively unused.
- **Rule violated:** a small typographic system (page/section/component/body/small/label/
  meta/caption); no dozens of near-identical text styles.
- **Canonical replacement:** text tokens (13px meta, 12px caption, 10px micro) mapped to
  `--text-*`; kill 12.5/13.5/8/9/19/21px stragglers; label/caption conventions per spec
  (Deliverable 3).
- **Migration priority:** P3 (Phase C typography).

## 1.7 Border radius: contract says 0, CSS says otherwise — P2/P3

- **Location:** main.css border-radius inventory.
- **Observed:** the system token family is `--radius*: 0px` (sharp, explicit contract) but
  15 literal radii remain: `4px`(×8), `8px`(×7), `6px`(×7), `3px`(×2), `2px`(×2),
  `12px`, `99px`(×2), `999px`(×2), `50%`. Chips/pills legitimately use `--radius-full`,
  but `6px` on `.btn-icon`, `4px` on `.discord-bot-badge`, `8px` on input groups, etc.
  are era leftovers.
- **Rule violated:** radius philosophy = sharp; any rounding must come from a token.
- **Canonical replacement:** `0px` everywhere except `--radius-full` (pills) and
  `--radius` (media corners if ever restored).
- **Migration priority:** P3 (Phase C radius) — mechanical sweep.

## 1.8 Dead CSS and duplicate blocks — P3 cleanup

- **Location:** main.css (probe: 234 flagged selectors; ~half are JS-created/dynamic and
  verified live — `.discord-*`, `.speak-row`, `.palette-item`, `.toast` etc. are NOT dead).
- **Observed truly dead (zero .html/.js reference, confirmed against prior audit):
  `.save-bar*`, `.workspace-section*`, `.workspace-overview-grid`, `.workflow-steps`,
  `.qa-*`, `.mod-stats`, `.hover-card`, `.glass`/`.glass-strong`, `.field-width-*`,
  `.module-badge`, `.module-section*`, `.member-table-row`, `.detail-grid`,
  `.config-layout-columns`, `.ruleset-heading`, `.nav-collapse-*` (no JS wires them),
  `.template-help`, `.content-container`, `.btn-row`, `.mb-2`, `.visible` (no toggle).**
  Duplicate selector blocks with different bodies at top level: `.form-actions-static`
  (padding declared twice), `.settings-grid`, `--shadow-sm/lg` (1.4).
- **Rule violated:** no dead weight; every rule earns its bytes.
- **Canonical replacement:** delete dead selectors in components.css/v3.css; dedupe
  same-selector blocks; keep the whitelist (JS-toggle classes) out of scope.
- **Migration priority:** P3 (Phase C) — main.css drops several KB.

## 1.9 Contrast: three P1 failures, rest clean — P1 a11y

- **Location:** `.btn-primary` (white on `--accent #3b82f6`), `.btn-danger` (white on
  `--red #ef4444`), landing accent `#2563eb` on `#0b1220`.
- **Observed (computed WCAG, 12-13px labels):** btn-primary **3.68:1**, btn-danger
  **3.76:1**, landing accent **3.62:1** — all FAIL AA small-text (need ≥4.5:1). Body text
  is excellent: white 18.35:1, secondary 12.69:1, tertiary 7.79:1; status colors on dark
  all ≥6.5:1.
- **Rule violated:** AA on all text; muted still readable.
- **Canonical replacement:** darken accent for button fills (e.g. `#2f6fd6` ≈ 4.6:1) or
  use dark text on accent (`#0b1220` on `#3b82f6` = 4.99:1 — already computed and PASSES);
  same for `--red` (dark text `#1a0b0b` on `#ef4444`, or deepen to `#dc2626`+); landing
  accent → `#3b82f6`-family token (already aliased) with `#0b1220` text.
- **Migration priority:** P1 (Phase A poor contrast).

## 1.10 Raw unstyled 404 responses — P1 error state

- **Location:** `dashboard/routes/web/modules.py:103,107` —
  `return HTMLResponse("Guild not found"/"Module not found", status_code=404)`.
- **Observed:** navigating to a missing module renders a **plain white page with one line
  of text** — no shell, no nav, no back link, no brand (screenshot
  `plugin_catalog-1440.png` shows exactly this: bare "Module not found").
- **Rule violated:** every error state is a designed state (§37); never expose raw backend
  strings; provide recovery (Return/Retry).
- **Canonical replacement:** render the base shell with a `.state-panel state-error`
  ("Module not found — it may be disabled or removed", button back to Modules).
- **Migration priority:** P1 (Phase A error handling).

## 1.11 Dashboard has two `<h1>`s — P2 a11y

- **Location:** `dashboard/templates/pages/dashboard.html:48,51`.
- **Observed:** both "Welcome back, …" and "Your Servers" render as `<h1>` on the same
  page. Heading hierarchy rule: exactly one h1 per page. (Other pages are correct — the
  `page_header` macro emits a single h1; the modules.html `<h3>` before the h1 is inside a
  macro definition, not rendered order — verified not a finding.)
- **Canonical replacement:** keep the page-title h1 ("Your Servers"); demote the greeting
  to h2.
- **Migration priority:** P2 (Phase C hierarchy).

## 1.12 Density mismatch: modules page vs moderation workspace — P3

- **Location:** `modules.html` (airy, low density) vs `moderation-workspace.js`
  (dense operation cards) — both screenshots.
- **Observed:** the Modules grid is spacious with large dead areas inside cards (the
  "Announcements" card has ~60% empty vertical space above its Configure link; ragged
  bottom edges when a row has unequal tag counts), while the Moderation workspace is
  tightly packed with 13px text and 6px gaps. Both are "module" pages; they read as
  different products.
- **Rule violated:** equivalent pages share equivalent density and anatomy (§43).
- **Canonical replacement:** normalize module-card min-height so Configure links align per
  row; pull moderation workspace spacing up to the same 8px rhythm; the operation-grid
  already handles odd-card remainders (verified at 1280px: 2-col, 5th card spans).
- **Migration priority:** P3 (Phase C panels).

## 1.13 Guild overview: masonry cards + competing hero elements — P3

- **Location:** `guild.html` (screenshot guild-1440).
- **Observed:** "Upcoming Events" (tall) sits above "Recent Cases"/"Top Members" (unequal
  heights) → jagged bottom edge; the MOTD edit box competes with the guild title for
  attention (both heavy); stat chips show raw snowflake IDs (owner id `130405…`) — the
  "developer-only" feel the audit flags.
- **Rule violated:** page anatomy: hero → primary content → secondary content, equal
  siblings align (§6, §8).
- **Canonical replacement:** equalize the two bottom cards (min-height / grid), lighten
  MOTD container, format snowflake IDs (or omit owner id from chips, keep in an info row).
- **Migration priority:** P3 (Phase C composition).

## 1.14 Stats page: sub-metric alignment asymmetry — P4

- **Location:** `stats.html:17-24`.
- **Observed:** left-column sub-metrics left-aligned, right-column sub-metrics
  right-aligned inside the same 2-col grid → a gap down the middle; the "Member Growth"
  line chart stretches very wide with sparse x-data (dead horizontal space).
- **Rule violated:** equivalent cells share alignment.
- **Canonical replacement:** one alignment per column pair; constrain chart max-width.
- **Migration priority:** P4 (Phase E).

## 1.15 Member detail: header rhythm + low-contrast metadata — P3/P4

- **Location:** `member_detail.html` (screenshot member_detail-1440).
- **Observed:** the "Back to Members" link sits higher than the standard page-title
  baseline (breaks the vertical rhythm); a large gap between Quick Actions and stat
  blocks; profile metadata ("Joined: 1/1/2024") renders very dark grey on dark — reads as
  near-invisible (contrast below the body-text standard); Voice Sessions section is a
  large dark void when empty (designed empty states exist for cases/warnings — good — but
  voice lacks one).
- **Rule violated:** page headers align to one baseline; empty sections need intentional
  empty states.
- **Canonical replacement:** align Back link with page-header; use `--text-secondary` for
  metadata; add a voice-sessions empty state (or hide the section when empty).
- **Migration priority:** P3 (composition) / P4 (polish).

## 1.16 Dashboard empty space + muted CTA — P3

- **Location:** `dashboard.html` (screenshot dashboard-1440).
- **Observed:** with one server connected, ~60% of the viewport is empty; the primary CTA
  ("Open →") is a thin muted link rather than a button — it does not stand out. Stat
  cards don't span the container (staggered width vs the server card below).
- **Rule violated:** primary action obvious; density tuned to the app; user preference
  (from profile): prominent CTAs with distinct accent color.
- **Canonical replacement:** make "Open" a `.btn btn-primary`; let stat cards fill the
  grid row; use a designed empty/guide state in the dead region for new instances.
- **Migration priority:** P3 (Phase B hierarchy).

## 1.17 Mobile: moderation overload + touch targets — P2/P3

- **Location:** moderation-390.png, members-390.png.
- **Observed:** zero horizontal overflow at 390px (good — verified via screenshots); the
  sidebar collapses properly to a hamburger (good). But the Moderation page is
  information-dense and requires significant scrolling to reach the primary action
  (Quick Warn is below description+status+meta+subnav); filter dropdowns on Members
  ("All Roles"/"Any Age") and the small Edit button are under the 44px touch target.
- **Rule violated:** mobile prioritizes the primary action; touch targets ≥44px.
- **Canonical replacement:** on ≤480px, promote the operation grid above module meta;
  bump select/icon-button hit areas to ≥44px (padding, not font).
- **Migration priority:** P2 (Phase A mobile) / P3.

## 1.18 Microcopy and terminology — clean, with 3 nits — P4

- **Verified clean:** one vocabulary (Server/Instance split is correct and consistent);
  no visible "Guild(s)" user-facing; precise verbs ("Save Changes", "Quick Warn",
  "Purge Inactive Warnings"); no "Submit/OK/Continue" filler.
- **Nits:** (a) members quick-action "Timeout" sends NO duration (API default) while the
  member-detail timeout form has duration+unit — inconsistent interaction semantics
  (carried from round-2, still open, P2); (b) settings "appearance" failure surfaces as a
  toast instead of an inline error state (§1.19); (c) "Getting started" banner on
  dashboard is collapsed-by-default, fine, but its empty right side reads as dead space.
- **Migration priority:** P2 for (a), P4 for (b)/(c).

## 1.19 Settings partial-failure silence — P2

- **Location:** `settings.html` + `components/settings_scripts.html:675-712`.
- **Observed:** when the bot-appearance block fails to load (reproduced via mock 500),
  the whole Appearance section **silently disappears** and only a transient toast
  ("Could not load bot appearance: HTTP 500") appears at the bottom of the column — no
  inline error state, no retry control. (The 500 itself is mock-only — the route exists
  in the real app — but the UI's failure mode is real.)
- **Rule violated:** every async area has a designed error state with recovery (§35, §37);
  critical errors don't vanish after 3s.
- **Canonical replacement:** render a `.state-panel state-error` inside the Appearance
  card with Retry, mirroring the other workspaces' pattern.
- **Migration priority:** P2 (Phase D feedback).

---

# Deliverable 2 — UX Friction Report

Workflow → user goal → friction → impact → recommended change → expected improvement.

## 2.1 "Find a missing module / bad URL" (404 dead-end)

- **Workflow:** open a stale bookmark or mistype `/guild/123/modules/speak` →
  **raw white page, one line of text, no navigation.**
- **Goal:** recover orientation.
- **Friction:** dead end with zero recovery affordance; user must edit the URL by hand or
  hit Back.
- **Impact:** HIGH for anyone with a stale link; looks broken/unmaintained.
- **Recommended change:** designed 404 page in-shell (state-panel + Back to Modules).
- **Expected improvement:** recovery in one click; brand continuity.

## 2.2 "Understand what happened" (settings partial failure)

- **Workflow:** open Settings → Appearance fails → section gone, tiny toast bottom-right
  auto-dismisses in 3s.
- **Goal:** know the appearance options exist and that a load failed.
- **Friction:** the failure is easy to miss entirely; no retry; user may think the feature
  was removed.
- **Impact:** MED — silent data/feature loss perception.
- **Recommended change:** inline error state with Retry (per §1.19).
- **Expected improvement:** failure is visible, recoverable, and doesn't look like removal.

## 2.3 "Quick-timeout a member" (two different forms)

- **Workflow:** Members list → ⏱ icon → timeout applied instantly with **API default
  duration**; Member detail → Timeout → duration + unit form.
- **Goal:** apply the timeout I intend.
- **Friction:** same action, different semantics depending on entry point; a "quick" action
  that can't express intent.
- **Impact:** MED — users may accidentally apply a too-short/too-long timeout.
- **Recommended change:** quick-action timeout uses a small inline duration field (BarkDialog
  prompt pattern already exists) or clearly labels "default 10 min" in the title/tooltip.
- **Expected improvement:** consistent, predictable destructive-ish action.

## 2.4 "Scan the modules grid" (uneven cards)

- **Workflow:** Modules → compare/configure a module.
- **Goal:** see all modules and their status at a glance.
- **Friction:** cards with unequal heights and ragged Configure-link rows break the scan
  rhythm; "+12 more" tag wraps awkwardly; dead vertical space in sparse cards.
- **Impact:** LOW-MED — scanability and perceived polish.
- **Recommended change:** min-height normalization + aligned footer row (§1.12).
- **Expected improvement:** grid scans like a grid.

## 2.5 "Operate moderation on a phone" (density)

- **Workflow:** mobile → Moderation → want to Quick Warn.
- **Goal:** reach the primary action fast.
- **Friction:** description + status + meta strip + 8-tab subnav before the first action;
  dense 13px forms; small dropdowns.
- **Impact:** MED for on-call moderators.
- **Recommended change:** promote action grid above meta on ≤480px; ≥44px touch targets.
- **Expected improvement:** primary action reachable with minimal scroll/thumb travel.

## 2.6 "Single-server first run" (empty dashboard)

- **Workflow:** fresh install → Dashboard → one server.
- **Goal:** understand what to do next.
- **Friction:** two-thirds empty; primary CTA is a muted text link; "Getting started" is
  collapsed below the fold.
- **Impact:** LOW — but it's the first impression of the product.
- **Recommended change:** CTA to button; designed empty/guide state in the dead region.
- **Expected improvement:** first-run user knows exactly where to click.

---

# Deliverable 3 — Design System Specification

The canonical spec for Bark v0.3. **Rule:** every recurring visual decision originates
from a token or a system rule — nothing hand-typed twice. Values marked ✅ are shipped and
correct; marked 🔧 are the consolidated target from this audit (1.3–1.7).

## Foundations

### Color (semantic roles — steel/black/ivory, no warm chrome)

| Role | Token | Value | Status |
|---|---|---|---|
| Background | `--bg-base` | `#14141a` | ✅ |
| Card surface | `--bg-card` | `rgba(35,35,45,.62)` | ✅ flat per REMAKER |
| Input surface | `--bg-input` | `rgba(40,40,52,.70)` | ✅ |
| Sidebar surface | `--bg-sidebar` | `rgba(18,18,24,.68)` | ✅ |
| Primary text | `--text-primary` | `#ffffff` (18.35:1) | ✅ |
| Secondary text | `--text-secondary` | `#d6d6dd` (12.69:1) | ✅ |
| Muted text | `--text-tertiary` | `#a8a8b3` (7.79:1) | ✅ |
| Accent | `--accent` | `#3b82f6` | ✅ chrome; 🔧 button-label contrast (1.9) |
| Success / Warning / Danger | `--green` `--yellow` `--red` | `#22c55e` `#eab308` `#ef4444` | ✅ status; 🔧 danger label contrast |
| Focus ring | `--shadow-focus` (new) | `0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent)` | 🔧 new token |

**Rules:** status colors are status only; no warm hues in chrome (approved steel family);
chart-series colors are exempt (data-viz, not chrome — verified intentional).

### Typography (Inter system stack; mono JetBrains Mono)

| Role | Size/Weight | Token target | Status |
|---|---|---|---|
| Page title | `clamp(26px,2.5vw,34px)` / 700 | — | ✅ |
| Section title | 16px / 600 | `--text-title` 🔧 | 🔧 |
| Component title | 14px / 600 | `--text-component` 🔧 | 🔧 |
| Body | 16px / 400 | `--font-size-body` | ✅ (underused) |
| Small body | 13px / 400 | `--text-sm` | 🔧 map 13px → token |
| Label | 13px / 500 uppercase | `--text-label` 🔧 | 🔧 |
| Meta | 12px / 400 | `--text-meta` 🔧 | 🔧 |
| Caption | 10-11px / 500 uppercase | `--text-caption` 🔧 | 🔧 |

**Rules:** kill fractional sizes (12.5/13.5px) and the 8/9/19/21px stragglers; 12 and 13
merge into one semantic role each; hierarchy via size+weight+color, never size alone.

### Spacing (one scale — 🔧 consolidation target)

`--space-1:4 · -2:8 · -3:12 · -4:16 · -5:20 · -6:24 · -8:32 · -10:40 · -12:48` (already
exist). Delete the clamp `--space-xs..xl` ladder (non-scale 17/21/33px). Remap literals:
2→1, 6→1.5, 10→2.5, 14→3.5, 22→6, 28→7 (new), 56→12. **Same relationship = same spacing.**

### Radius (sharp — user preference, contract)

All `0px`; only `--radius-full: 999px` (pills, badges, avatars) and `50%` (round icons)
round. Sweep the 15 literal radii (1.7).

### Borders

`--border-subtle: .08α · --border-card: .10α · --border-input: .15α · --border-hover: .2α`
✅. **Rules:** primary boundaries = standard border; internal separators = subtle divider;
focus = focus ring (1.9); no decorative borders.

### Shadows (one family — 🔧)

`--shadow-sm` / `--shadow-lg` (shadcn pair only), `--shadow-card: none` (flat cards ✅),
`--shadow-focus` (new). Drop legacy dupes and one-off literals (1.4).

### Motion

`--transition-fast: 150ms ease · -normal: 250ms · -slow: 400ms` ✅. One
`prefers-reduced-motion` block only (merge 1.1). No scroll-jank sources found; the
activity feed's bfcache lifecycle is correct (verified in round-2).

## Interaction states

| State | Rule |
|---|---|
| Hover | border-color → `--border-hover`, background 8% lighter, `150ms` |
| Focus | `--shadow-focus` ring on every interactive element (never removed) |
| Pressed | translateY(1px) or background 12% darker |
| Disabled | `opacity:.5; cursor:not-allowed` — visible, not invisible |
| Loading | spinner in button (`.is-loading`), skeleton for async panels |

## Component rules (canonical forms)

- **Button system:** `.btn` (12px/`4px 9px`) → `.btn-sm` 🔧 (must be ≤ base) →
  `.btn-xs`; variants `.btn-primary`, `.btn-danger`, `.btn-icon` (radius = `var(--radius)`).
  One primary per view; destructive red only for destructive actions.
- **Content card:** `.content-card` + `.card-header` + `.card-title`; equal min-height in
  grid contexts.
- **State panel:** `.state-panel` + `state-empty/error/loading/permission` + Retry — every
  async area uses one.
- **Table:** `.data-table` in `.table-scroll`; `<caption>` + `scope="col"` (contract);
  primary column strongest, metadata quiet; actions in a menu when >2 per row.
- **Dialog:** `BarkDialog.confirm/pick` only (native confirm/alert/prompt banned);
  Escape/backdrop/focus-trap; input variant for prompts.
- **Status badge:** `.status-badge.status-success/neutral/danger` + `.status-indicator`;
  vocabulary: Active/Running/Online/Healthy/Enabled all standardize to the 3-state family.
- **Page header:** `page_header` macro everywhere (h1, subtitle, role pill, actions);
  one h1 per page.
- **Empty state:** icon + "what normally appears here" + "why empty" + next step (CTA).
- **Toast:** success/error/warning — warning uses ⚠ + `--yellow`; errors that need memory
  are inline states, not toasts.

## Layout

- Page anatomy: Page Header → Primary Content → Secondary Content; equivalent pages share
  anatomy.
- 12-col page grid with 16px gutters; dashboard modules in 1/2/4-unit spans; cards
  equal-height per row.
- Breakpoints: 480 mobile · 768 tablet · 1024 desktop · 1600+ wide; mobile prioritizes
  primary action; touch targets ≥44px.
- Sidebar: fixed width, 3 groups (Community / Modules / Settings), single active state.

---

# Deliverable 4 — Component Inventory

Canonical version → existing variants → required → deprecated.

| Component | Canonical | Existing variants | Required | Deprecated / dead |
|---|---|---|---|---|
| Button | `.btn` | `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-xs`, `.btn-icon`, `.btn-plugins` | fix sm ladder, `.btn-block` cleanup | `.btn-row` (dead), `.btn-plugins` → standard `.btn-sm` |
| Input / select / textarea | `.form-input`/`.form-select`/`.form-textarea` | `.form-input-sm`? | name attr (contract) | `.form-textarea` grouped-only rules |
| Card | `.content-card` | `.action-card`, `.module-card`, `.stat-card`, `.state-panel` | module-card min-height | `.hover-card`, `.glass`, `.glass-strong` |
| Table | `.data-table` + caption | `renderDataTable` (JS) | `scope="col"` in JS builder | `.member-table-row`, `.table-actions` (unused) |
| Tabs | `.tabs` (main.js initTabs) | module subnav tabs | same component for both levels | — |
| Dialog | `BarkDialog` | confirm, pick, (prompt needed) | prompt variant | `#update-terminal-overlay` (focus now handled ✅) |
| Badge | `.badge`/`.badge-muted` | `.status-badge.*`, `.role-pill`, `.module-version` | — | `.module-badge`, `.version-pill`, `.priority-pill` |
| Alert | `.state-panel state-error` | toast (main.js showToast) | inline error for settings blocks | — |
| Page header | `page_header` macro | hand-rolled variants | use macro everywhere | dead `page_header` dupe rules |
| Empty state | `.state-panel state-empty` | — | voice-sessions empty state | — |
| Skeleton | `.skeleton-gap-*` | — | — | (used by guild page ✅) |

**Variant reduction pass (§69):** the 9 button classes collapse to 6 real variants; the
badge zoo (`.module-badge`, `.enabled-pill`, `.version-pill`, `.priority-pill`,
`.role-access-chip`) collapses to `.badge` + `.role-pill`; `.event-tag`/`.event-list`
legacy names already superseded.

---

# Deliverable 5 — Screen Consistency Matrix

Verified against the live screenshot wall (1440px + mobile). ✓ = consistent with the
canonical system · ✕ = drifts · — = not applicable · ? = minor drift.

| Element | Landing | Dashboard | Guild | Members | Modules | Moderation | Settings | Member detail | Stats | Invite |
|---|---|---|---|---|---|---|---|---|---|---|
| Page header (macro) | — | ✕ 2×h1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✕ back-link | ✓ | — |
| Sidebar shell | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Button system | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Card style (flat, 0px) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Panel density | — | ? sparse | ✓ | ✓ | ✕ airy | ✕ dense | ✓ | ✓ | ✓ | — |
| Table pattern | — | — | ✓ | ✓ | — | ✓ | — | — | — | — |
| Status badges | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Empty states | — | ✕ dead region | ✓ | ✓ | — | ✓ | ✕ toast-only | ? voice void | ✓ | ? no CTA |
| Typography | ✓ | ✓ | ✓ | ✓ | ✓ | ? 13px dense | ✓ | ? dark meta | ✓ | ✓ |
| Spacing rhythm | ✓ | ✓ | ✓ | ✓ | ? | ? tight | ✓ | ? large gap | ✓ | ? bottom pad |
| Radius (0px) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Colors (tokens) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mobile (390px) | ✓ | ✓ | ✓ | ✓ | ✓ | ✕ dense | ✓ | — | — | ✓ |

**Drift hotspots:** (1) Dashboard h1/h2 — fix; (2) Modules vs Moderation density — fix;
(3) Member-detail header/back-link rhythm + metadata contrast — fix; (4) Settings failure
mode — fix; (5) Invite empty CTA state — polish.

---

# Deliverable 6 — Improvement Backlog

Prioritized per the methodology's P0–P5 ladder and the phase order
(Phase A repair → B structure → C consistency → D interaction → E refine).

## P0 — none (no crash/data-loss/security findings in the UI)

## P1 — accessibility / usability failures (Phase A)

| # | Item | Fix | Status |
|---|---|---|---|
| 1 | `.btn-primary`/`.btn-danger` label contrast 3.68/3.76:1 fails AA | ✅ **already passes** — v3 shadcn layer ships `--primary`/`--destructive` + ivory foreground (9.93:1 / 9.13:1); the failing rule was dead legacy code. Audit doc corrected. | done (no code change) |
| 2 | Landing accent 3.62:1 fails AA | ✅ **already passes** — landing aliases `--primary` (11.31:1 on bg). | done (no code change) |
| 3 | Raw unstyled 404 ("Guild/Module not found") | ✅ in-shell designed 404 (`pages/not_found.html` + `services.response.render_not_found`) across all 9 web-route sites (modules ×3, home, members ×3, settings, stats); 404 status preserved; Back buttons contextual. | done |
| 4 | `.btn-sm` bigger than `.btn` (inverted ladder) | ✅ monotonic ladder: `.btn` 14px/36px > `.btn-sm` 12px/32px > `.btn-xs` 11px/28px; `.btn-icon` radius → `var(--radius)`. | done |
| 5 | Quick-action Timeout silently uses API default vs detail form | ✅ `BarkDialog.prompt` (minutes 1–40320, default 10) with validation, matching the API contract and member-detail semantics. | done |

## P2 — structural inconsistency (Phase B/C)

| # | Item | Fix | Status |
|---|---|---|---|
| 6 | Design-era coexistence (REMAKER override) | legacy reduced-motion block removed; single v3 implementation (contract test updated to assert the `.01ms` shadcn form). Full glass-era rule sweep still queued. | partial |
| 7 | Spacing: clamp ladder + ~40 literals vs scale | ✅ dead clamp ladder removed from tokens.css (v3 fixed scale ships); ~40 hardcoded literals remain as P3 sweep. | partial |
| 8 | Shadows defined twice + one-off literals | deterministic winner confirmed (tokens.css rgba, unlayered); source-level dedupe queued with P3 sweep. | partial |
| 9 | z-index magic ladder (up to 99999) | ✅ `--z-sticky/banner/toast/skip-link` tokens added; the 9999/99999/10000/9998/600/200 magic values replaced in components.css (identical resolved values). Mid-tier 5/20/40/50/90/95 left self-documented. | done |
| 10 | Double `<h1>` on dashboard | ✅ **false positive** — the two h1s are an if/else (OAuth vs not), never both rendered; verified 1 h1 at render. Doc corrected. | done (no code change) |
| 11 | Settings partial-failure silence | ✅ inline `state-error` panel + Retry in Bot Customization card (mock 500 verified: panel shows "Couldn't load bot customization / HTTP 500" + Retry re-fetches). | done |
| 12 | Mobile moderation overload + <44px touch targets | `btn-sm`/`btn-xs` min-heights 32/28px; full 44px mobile pass + action-grid promotion still queued (P3). | partial |
| 13 | Members quick-action Timeout duration inconsistency | ✅ (see P1-5) | done |

## P3 — component inconsistency (Phase C)

| # | Item | Fix |
|---|---|---|
| 14 | Typography: 24 sizes incl. fractional | semantic `--text-*` ladder, kill stragglers |
| 15 | 15 literal radii vs 0px contract | token sweep |
| 16 | Dead CSS (~50 verified selectors) + duplicate blocks | delete; dedupe `.form-actions-static`/`.settings-grid` |
| 17 | Modules vs moderation density mismatch | module-card min-height; moderation spacing to 8px rhythm |
| 18 | Guild overview masonry + raw snowflake IDs | equalize cards; format/hide raw IDs |
| 19 | Dashboard dead space + muted CTA | `.btn-primary` Open; designed guide state |
| 20 | Member-detail header rhythm + metadata contrast + voice void | align, brighten, empty state |

## P4 — visual refinement (Phase E)

| # | Item |
|---|---|
| 21 | Stats sub-metric alignment asymmetry + chart max-width |
| 22 | Invite empty-CTA state polish |
| 23 | Toast warning duration (persist >3s for warnings) |
| 24 | "Getting started" dead right side on dashboard |

## P5 — delight / polish

| # | Item |
|---|---|
| 25 | Micro-motion polish (view-transition already present; add subtle tab/fade under reduced-motion guard) |
| 26 | Before/After gallery population after fixes land |

**Suggested commit order:** P1-3+P1-4 (CSS tokens + 404) → P2-6..9 (era merge + token
consolidation, one big CSS pass with contract tests) → P1-1/P1-2 contrast → P2-10..13 →
P3 sweep → P4/P5. Each CSS change: edit `frontend/src/*.css` sources, `node build.mjs`,
bump cache-busters in `base.html`, run the frontend contract tests, deploy to bark-dev,
verify on the live instance (per bark-theme-system skill).

---

# Deliverable 7 — Before/After Gallery

**Before** (this audit): 21 screenshots captured from the mock server at
1440/1280/768/390px — `docs/audits/2026-08-19-screenshots/`:
`wall-desktop.png` (10-screen side-by-side wall), `wall-mobile.png` (5-screen mobile
strip), and per-page files (`dashboard-1440.png`, `guild-1440.png`, `guild-768.png`,
`members-1440.png`, `modules-1280.png`, `moderation-1440.png`, `settings-1440.png`,
`member_detail-1440.png`, `stats-1440.png`, `landing-1440.png`, `invite-1440.png`,
`setup-1440.png`, `plugin_catalog-1440.png`, plus `*-390.png` mobile variants).

**After:** captured at the same URLs/viewports after each backlog phase lands, using the
same mock server, so each fix is diffable side-by-side. Populate as fixes ship (P5-26).

---

# Verified clean areas (no findings)

- Sidebar shell: identical width/groups/active state on every internal page; collapses
  properly to a hamburger at 390px.
- Page headers: consistent size/position via the `page_header` macro (except the
  member-detail back-link nit); every page has exactly one h1 at render.
- Radius contract: all structural surfaces sharp; token family correct (the violations
  are literal leftovers, not the token layer).
- Body-text contrast: AA+ everywhere (18.35 / 12.69 / 7.79:1); status colors ≥6.5:1.
- Terminology: one vocabulary (Server/Instance), no visible "Guild(s)" copy.
- Warning toast regression from round 2: confirmed fixed in `main.js showToast`
  (⚠ icon + `.toast-warning` branch exists).
- Landing/invite/setup standalone pages: token-aligned, no raw hex — the old "second
  design system" finding is resolved.
- Empty states on member detail (cases/warnings) and guild activity feed: designed and
  useful.
- Mobile: zero horizontal overflow at 390/768; members list converts to a vertical card
  list gracefully.
- Iconography: single Lucide family, consistent 14/16/18/24 sizes, `refreshIcons()`
  convention honored.
- a11y contracts: no native confirm/alert/prompt, no inline handlers, named controls,
  tab arrow-key nav, focus management — all enforced by the contract suite (774 tests
  green at baseline).

---

# Acceptance checklist (audit §94) — status at baseline

- [x] Every page clearly belongs to the same product (shell + tokens consistent)
- [~] Equivalent pages use equivalent structure (member-detail header nit, modules vs
  moderation density)
- [~] Components have canonical implementations (button ladder broken, badge zoo)
- [ ] Spacing follows a deliberate scale (3 systems coexist → target in P2-7)
- [x] Alignment follows visible grids (verified via walls; minor nits in stats/member-detail)
- [ ] Typography creates clear hierarchy (24 sizes → semantic ladder in P3-14)
- [~] Color usage is semantic and controlled (button-label contrast fails AA)
- [~] Borders/shadows communicate structure (shadow dupes + literals to consolidate)
- [~] Primary actions are obvious (dashboard Open CTA is muted)
- [x] Secondary actions available without competing (verified on members/moderation)
- [x] Destructive actions unmistakable (danger-zone pattern + confirm dialogs)
- [x] Forms predictable (form-grid/form-group/hint/error pattern consistent)
- [x] Tables easy to scan (members table clean; caption+scope contract)
- [x] Empty states useful (member detail + activity feed; voice void to fix)
- [x] Loading states communicate progress (skeleton-gap + state-panel loading)
- [ ] Errors explain recovery (raw 404s; settings toast-only)
- [x] Navigation clearly communicates location (breadcrumbs + active nav)
- [~] Responsive layouts intentional (390px clean; moderation overload)
- [x] Keyboard use practical (contracts + toolbar fix landed round 2)
- [x] Focus states visible (focus-ring pattern; never removed)
- [~] Usable at 200% zoom (not re-probed this round; layout is clamp-based so low risk)
- [~] Common workflows minimal effort (timeout inconsistency; settings retry)
- [x] Similar interactions behave similarly (verified end-to-end round 2)
- [x] One consistent vocabulary
- [ ] Visual exceptions rare and justified (dead CSS + era leftovers to purge)
- [~] No major area from a different design era (landing fixed; REMAKER merge pending)
- [x] Coherent without color (structure is border/spacing-driven, not color-driven)
- [x] UI communicates before decoration (no decorative-only elements found)
- [x] Rule behind every recurring visual pattern explainable (this spec is the rule)

**Next step:** implement the P1 batch, then the P2 token consolidation, per the commit
order above — each phase ending with build + contract tests + dev deploy + live verify.




