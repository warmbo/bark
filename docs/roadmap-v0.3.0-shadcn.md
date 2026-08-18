# Bark v0.3.0 — shadcn/ui Visual System (Plan)

Branch: `bark3`. Audit: `docs/audits/2026-08-16-shadcn-audit.md`. Date: 2026-08-16.

**Goal:** utilize `ui.shadcn.com` as the entire visual system, convert every existing
page to it, and **self-host a pinned copy locally so the version can't change and
break the site.**

**Chosen path (Cody: "go with your recommended path"): Path A** — adopt shadcn's
visual system (Tailwind v4 + design tokens + component styles), vendored & pinned
locally, reimplemented as **Jinja2 macros + vanilla-JS behavior shims**. Preserves
the FastAPI/Jinja2 architecture and current deployment. **Pilot-first**: landing +
dashboard converted and visually verified before the remaining 31 templates.

---

## 1. Architecture decision (why Path A)

- shadcn/ui components are **React + Radix**. Bark is **server-rendered Jinja2 with
  vanilla JS, no npm/build step**. Dropping React components into Jinja2 is not
  possible.
- What "the entire visual system" really needs from shadcn is its **design
  language**: the `@theme` design tokens (background/foreground/card/primary/
  secondary/muted/accent/destructive/border/input/ring/radius), the Tailwind v4
  utility engine, and the component *style patterns*. That layer is pure CSS and
  works perfectly with server-rendered markup.
- Path A gives the full shadcn look with **zero change to the FastAPI stack,
  rendering, or deployment**.

---

## 2. Self-hosting / pinning strategy (the core requirement)

"Host our own version of shadcn locally so the version can't change and ruin our
site" is delivered by **vendoring source + committing build output + pinning
versions**. Nothing resolves from the internet at render time or at deploy time.

1. **`frontend/` directory** (new) holds the vendored build:
   - `package.json` + `package-lock.json` with **exact pinned versions**:
     Tailwind/CLI `4.3.3`, Lucide `1.31.0`, and Fontsource `5.3.0`.
   - `frontend/src/theme.css` — shadcn `@theme` design tokens, mapped onto Bark's
     existing dark palette (`--accent #3b82f6`, sharp `0px` radius stays on-brand).
   - `frontend/src/components/*.css` — shadcn component style layer.
   - `frontend/shadcn-pin.md` — records the exact shadcn/ui version + the date/commit
     the token+component CSS was copied from, and the deliberate upgrade procedure.
   - Vendored **Inter + JetBrains Mono woff2** fonts and **lucide icons** as local
     assets (removes both external CDNs — same "can't change on us" rationale).
2. **Committed build artifact:** `npm run build` compiles Tailwind v4 + tokens +
   component CSS into `dashboard/static/css/main.css` (single output, cache-busted
   via `?v=`). The generated CSS is **committed to the repo**, so:
   - Deploy stays a plain `StaticFiles` mount (setup_app.py) — **no Node required
     on CT1109**, production layout untouched.
   - The running site is byte-for-byte stable regardless of any upstream change.
3. **No live shadcn CLI/registry after the pin.** Upgrades happen deliberately,
   reviewed, on our schedule (per `frontend/shadcn-pin.md`). We do not run a JSON
   registry *service* because there is no React consumption path; vendoring the
   source is the practical form of self-hosting here. (A local registry service
   becomes relevant only under Path B / React.)

---

## 3. Component surface (Jinja2 macro layer)

Extend `templates/components/primitives.html` (and new `templates/components/ui/*.html`)
with macros emitting shadcn-utility-class markup. Map of current Bark primitive → shadcn component:

| Bark today (main.css) | shadcn macro | Behavior shim |
|---|---|---|
| `.btn` / `.btn-primary` / `.btn-danger` / sizes | `button` | — |
| `.content-card` / `.card-header` / `.card-title` | `card` | — |
| `.status-badge` / variants | `badge` | — |
| `.form-input` / `.form-select` / `.form-textarea` / `.form-label` | `input` / `select` / `textarea` / `label` | — |
| `.toggle-switch` / `.checkbox-role-dropdown` | `switch` / `checkbox` | focus, aria |
| `.tabs` / `.tab-panel` / `.workspace-tabs` | `tabs` | keyboard arrows, aria-selected |
| `.app-dialog` / `.dialog-overlay` (BarkDialog) | `dialog` / `alert-dialog` | focus trap, Esc, backdrop, aria-modal |
| `.palette*` (command palette) | `command` | existing logic, re-styled |
| `.role-access-popover` / `.hover-card` / `.role-access-menu` | `dropdown-menu` / `popover` | click-outside, Esc, keyboard nav |
| `.data-table` / `.member-table` / `.pagination` | `table` | — |
| `.toast` | `toast` | existing logic, re-styled |
| `.skeleton*` | `skeleton` | — |
| `.nav-collapse-group` / `.getting-started-toggle` | `collapsible` / `accordion` | toggle state |
| `.context-breadcrumb` | `breadcrumb` | — |
| `.update-progress` | `progress` | — |
| `.sidebar-user-avatar` / guild icons | `avatar` | — |
| `.form-hint` / `.field-error` | `form-description` / form error | — |
| `.separator` / `.info-row` / `.danger-zone` | `separator` / description-list / alert | — |

### Vanilla-JS behavior shims (no React)

A small `frontend/behaviors.js` (replacing/absorbing parts of `main.js`) reimplements
Radix *headless semantics* with ~zero-dependency vanilla JS: dialog focus trap +
Esc + aria-modal, dropdown/popover click-outside + Esc + keyboard nav, tabs
arrow-key nav + aria-selected, switch/checkbox, collapsible toggle. Keeps the exact
accessibility contract the current `test_frontend_a11y_contract.py` enforces.

---

## 4. Migrating the frontend contract tests

Convert in lockstep with the redesign (never left red against a stale contract):
- `test_css_contract.py` → assert shadcn tokens (`--primary`, `--card`, …) and the
  new macro-emitted class contract instead of legacy `main.css` classes.
- `test_frontend_a11y_contract.py` → keep the same a11y guarantees (heading
  hierarchy, focus-visible, table semantics, sr-only), re-asserted on new markup.
- `test_frontend_js_contract.py` → assert the new behavior-shim API surface.
- `test_frontend_forms.py` → unchanged (forms behavior), re-verified on new macros.

---

## 5. Phased roadmap (pilot-first)

**Phase 0 — Scaffold + pin (foundation)**
1. Create `frontend/` with pinned `package.json`/lock, Tailwind v4, `theme.css`
   (shadcn tokens on Bark dark palette), component CSS, vendored fonts + lucide.
2. `npm run build` → commit generated `dashboard/static/css/main.css` (v= bump).
3. Rewrite the 4 contract tests to the new contract (green before any template work).
4. `frontend/shadcn-pin.md` upgrade procedure. Cache-buster now auto-derived.

**Phase 1 — PILOT (prove the look)**
5. Convert `base.html` shell (sidebar, context-bar, mobile drawer, top chrome) to
   macros.
6. Convert `landing.html` + `dashboard.html` (+ dashboard widgets + stats strip).
7. **Visual verification** (browser, desktop + mobile): hierarchy, contrast,
   overflow, reduced-motion, a11y — per production-web-design skill. Deploy to
   bark-dev. **Gate: Cody signs off before continuing.**

**Phase 2 — Shared primitives + remaining pages (in batches)**
8. Batch A: servers (`guild.html`, `guild_offline`, `guild_viewer`), `setup.html`.
9. Batch B: `settings.html` (+ Bot Customization), `modules.html`, `module_detail.html`.
10. Batch C: moderation suite (`moderation.html` + all `module_tabs/moderation_*`),
    `members.html`, `member_detail.html`.
11. Batch D: `stats.html`, `plugin_catalog.html`, `invite.html`; workspace tabs +
    per-module tab panels; all `module_tabs/*` remaining.
12. Remove dead/duplicate CSS as pages land (539 classes → only what shadcn macros emit).

**Phase 2.5 — Whole-project layout rhythm**
13. Define one Bark-owned 4px spacing scale and shared page/card/form/table/tab/
    dialog composition tokens in `frontend/src/v3.css`.
14. Remove page-specific inline spacing overrides; normalize setup, offline, settings,
    module catalog/workspaces, members, statistics, plugin and add-on surfaces.
15. Exercise 375px mobile, 768px tablet, 1280px desktop, and wide desktop layouts;
    fix document overflow, cramped description rows, wasted tablet columns, sticky
    anchor offsets, chart clipping, and horizontal tab/table behavior.

**Phase 3 — Behavior shims + de-CDN**
16. Wire `frontend/behaviors.js` shims into `base.html`; port dialog/palette/toast/
    dropdown logic; drop `main.js` legacy blocks.
17. Remove lucide CDN (`unpkg`) → local vendored icons.
18. Remove Google Fonts CDN → local vendored woff2.

**Phase 4 — Verify + ship (dev-only)**
19. Full pytest green, ruff clean, 4 contract tests green.
20. Desktop + tablet + mobile visual/overflow/console/reduced-motion verification.
21. Deploy to bark-dev (:8091), live-verify. **Await Cody's explicit promotion
    instruction to stable** (dev-only discipline).

---

## 6. Version / naming note

Displayed version is `0.2.<commitcount>` (pyproject base `0.2.0` + commit count).
The prior dev "v0.3 roadmap" (stats/slash) already claimed the v0.3 name on `dev`.
For this shadcn release to read as `0.3.x`, bump the **pyproject base to `0.3.0`**
at promotion time (this branch, `bark3`, is separate from `dev`; when it merges it
supersedes the old v0.3 naming). Flag for Cody's confirmation before shipping.

---

## 7. Definition of done (v0.3.0)

- Every page renders through the shadcn macro layer; `main.css` is the committed
  Tailwind v4 + shadcn token output — **no hand-rolled component CSS classes remain**
  that aren't shadcn-style.
- shadcn/ui version, Tailwind, lucide, fonts all **pinned & vendored locally**; zero
  external CDNs; site renders identically regardless of upstream changes.
- All 4 frontend contract tests + full suite green; a11y contract preserved.
- Deployment unchanged (StaticFiles mount + committed CSS); live on bark-dev.
- Pilot signed off; full conversion visually verified at 375/768/1280px and wide
  desktop, with no document-level overflow and a consistent spacing scale.

---

## 8. Risks / guardrails

- **Pilot gate** prevents a wholesale visual rejection late in the project.
- **Committed build artifact** means no deploy-time drift; upgrades are deliberate.
- **Contract tests first** (Phase 0.3) means the redesign never outruns its safety net.
- **Keep the dark/glass + sharp-corner identity**: shadcn tokens are mapped onto
  Bark's palette, not the default white "new-york" theme.
- **No React debt**: we implement the *visual system*, not React components; if Cody
  later needs React itself, that is Path B and a separate project.

---

## 9. Implementation record

The implementation uses a behavior-preserving visual adapter rather than replacing
all endpoint/DOM hooks at once. `frontend/src/components.css` (formerly `legacy.css`)
is the pre-v0.3 layout contract; Tailwind v4 emits utilities/tokens and `frontend/src/v3.css`
overrides every shared component family with shadcn recipes. This is intentional:
the 17 mature workspace scripts depend on stable IDs, `data-*` attributes and state
classes. Rebuilding those hooks simultaneously would increase feature-loss risk
without changing what users see.

Completed implementation scope:

- exact frontend pins + lockfile + reproducible build script;
- committed generated CSS, local Inter/JetBrains Mono, and local Lucide bundle;
- black/navy shadcn semantic tokens, electric-blue actions/rings, universal sharp
  component corners, Bark wallpaper/avatar imagery;
- Jinja primitives for button/card/badge/input/select/textarea/separator/avatar;
- base shell, landing, invite, setup and all existing page component selectors on
  the v0.3 visual system; behavior hooks preserved;
- owner-only v0.2/v0.3 SQLite upload, double validation, SHA-256 marker, startup
  atomic restore, pre-restore rollback snapshot, and ordered migrations;
- existing bare/wrapped v1 JSON settings import retained;
- frontend/a11y/CSS contracts migrated to local assets and Tailwind internals.
- whole-project 4px spacing rhythm, responsive card/grid/form/table/tab composition,
  settings container behavior, chart gutters, and setup/offline spacing refinements.

This adapter is Bark-owned source, not a transition CDN or runtime compatibility
dependency. Future template cleanup can replace repeated markup with the macros
incrementally while preserving byte-stable production assets and tested behaviors.
