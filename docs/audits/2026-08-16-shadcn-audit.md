# Bark v0.3.0 — shadcn/ui Visual System Conversion: Audit

Branch: `bark3` (created from `dev` @ `329c512`). Date: 2026-08-16.

Goal (per Cody): utilize `ui.shadcn.com` for the entire visual system, convert
everything existing to use it, and **self-host a pinned copy of shadcn locally so
the version can't change and break the site.**

---

## 1. Current frontend architecture (what we're converting FROM)

Bark's dashboard is a **server-rendered FastAPI + Jinja2** app. There is **no
Node.js, no npm, no Tailwind, no build/bundle step** — a hard architectural fact
that drives everything below.

| Area | Inventory |
|---|---|
| Static serving | `dashboard/static` mounted via `StaticFiles` (`setup_app.py:29`). No pipeline. |
| Templates | 33 `.html` Jinja2 templates (`templates/pages/*`, `templates/components/*`, `templates/module_tabs/*`) |
| Stylesheet | Single `dashboard/static/css/main.css`, **3483 lines, 539 distinct class selectors** |
| JS | 17 files, **3811 lines**, vanilla JS, loaded via plain `<script>` tags. Behaviors: `BarkDialog`, command palette, toasts, tabs, sidebar collapse, dropdown/popovers, per-module workspaces, realtime, dependency-free SVG charts |
| Icons | **lucide v1.22.0 from `unpkg.com` CDN** (external — a drift/availability risk) |
| Fonts | **Inter + JetBrains Mono from `fonts.googleapis.com` CDN** (external) |
| Existing design tokens | Documented in `docs/design-system.md`, defined as CSS custom properties in `main.css`: dark glassmorphism, `--accent #3b82f6`, sharp `0px` corners, Inter type |
| Existing macros | `templates/components/primitives.html` + `icons.html` — a nascent Jinja2 component system (foundation to extend) |
| Frontend contract tests | `test_css_contract.py`, `test_frontend_a11y_contract.py`, `test_frontend_js_contract.py`, `test_frontend_forms.py` — lock current classes/structure; **must be migrated alongside the redesign** |

### Component inventory (from 539 CSS classes → the primitives to convert)

- **Layout:** `.app-shell`, `.sidebar`, `.main-content`, `.context-bar`, `.content-container`, `.page-container`, `.settings-grid`
- **Card system:** `.content-card`, `.card-header`, `.card-title`, `.card-description`, `.card-header-actions`, `.config-body`
- **Controls:** `.btn` (+ `.btn-primary/.btn-danger/.btn-sm/.btn-xs/.btn-block`), `.form-input`, `.form-select`, `.form-textarea`, `.form-grid*`, `.form-group`, `.form-label`, `.form-hint`, `.toggle-switch`, `.checkbox-role-dropdown`
- **Feedback:** `.state-panel` (empty/error/loading/permission), `.status-badge`, `.toast`, `.skeleton*`, `.update-terminal`
- **Interactive:** `.tabs`/`.tab-panel`, `.palette*` (command palette), `.app-dialog`/`.dialog-overlay` (BarkDialog), `.hover-card`, `.role-access-popover`, `.workspace-drawer`
- **Data:** `.data-table`, `.table-scroll`, `.member-table`, `.pagination`, `.module-health-strip`
- **Layout components:** `.guild-card`, `.module-card`, `.dashboard-widget`, `.action-card`, `.danger-zone`, `.info-row`, `.event-item`

### External-dependency drift risk (the exact failure the user wants to prevent)

- `lucide` icons resolve to `https://unpkg.com/lucide@1.22.0` — the version is
  pinned today, but it's a third-party CDN outside our control (availability + the
  `@1.22.0` range could be re-resolved).
- Google Fonts stylesheet + `preconnect` resolve to Google — same availability/
  privacy consideration.
- shadcn/ui's whole value prop is "copy the source in and own it" — which is exactly
  the self-hosting model the user is asking for.

---

## 2. The core constraint: shadcn/ui is React, Bark is Jinja2

shadcn/ui components are **React components** built on **Radix primitives** (or
Base UI in the 2026 `cli v4`), styled with **Tailwind CSS v4 + CSS design tokens**.
Bark renders HTML server-side with vanilla JS. So "use shadcn for the entire visual
system" has two viable implementations:

- **Path A — Adopt shadcn's design system, keep server rendering.** Bring in
  Tailwind v4 + shadcn's design-token layer + shadcn's component *styles*, all
  **vendored and pinned locally**, and reimplement the components as Jinja2 macros
  (`{% macro button, card, dialog, badge, tabs, ... %}`) with small vanilla-JS
  behavior shims mirroring Radix. Preserves FastAPI/Jinja2 architecture and the
  existing deployment. This is the realistic, low-risk path for a self-hosted app.
- **Path B — Full React/Next.js rewrite** using real shadcn React components.
  Massive effort, replaces the rendering stack and deployment model (needs a Node
  build + separate frontend), much higher risk.

### How "self-host shadcn locally so the version can't change" works

shadcn already has an official **component registry** model
(`ui.shadcn.com/docs/registry`): a `registry.json` + per-item JSON served over HTTP,
which the `shadcn` CLI resolves. Two layers of pinning:

1. **Vendor the source.** After one initial install, the component source, the
   Tailwind v4 stylesheet, the design tokens, and the shadcn CSS are committed to
   the repo and owned locally. No live `npx shadcn add` against the remote registry
   after the pin; upgrades happen deliberately, reviewed, on our schedule.
2. **Pin the registry + deps.** Record the exact shadcn/ui version, Tailwind v4
   version, and dependency versions in a lockfile/manifest so nothing auto-resolves.
   Also move `lucide` + Google Fonts off their CDNs into local assets (same
   self-hosting rationale).

> **Decision needed from Cody:** Path A (recommended) vs Path B. Everything in the
> plan downstream (build tooling, deployment, timeline) depends on this choice.

---

## 3. What a conversion touches (size estimate, Path A)

1. **Add a frontend build/render path** for Tailwind v4 + shadcn tokens + component
   CSS (vendored Tailwind standalone CLI or a tiny npm build producing a single
   committed CSS output — decided in the plan).
2. **Tokens:** replace the hand-rolled `main.css` token block with shadcn's
   `@theme` design tokens (background, foreground, card, primary, secondary, muted,
   accent, destructive, border, input, ring, radius), mapped onto Bark's existing
   dark palette so the look is deliberately shadcn but on-brand.
3. **Primitives as Jinja2 macros:** build out `primitives.html` (and new
   `ui/*.html` macro files) covering button, card, badge, input, select, textarea,
   label, toggle/switch, tabs, dialog, dropdown, tooltip, popover, command
   (palette), table, skeleton, toast, separator, avatar, breadcrumb — emitting
   shadcn-utility-class markup.
4. **Convert all 33 templates** onto the macro layer; remove dead/duplicate CSS.
5. **JS behavior shims:** rewrite `BarkDialog`, palette, tabs, dropdowns, toasts as
   tiny headless-behavior shims matching Radix semantics (focus trap, aria, Esc
   close, keyboard nav) without React.
6. **Migrate the 4 frontend contract tests** to assert against the new class/token
   contract instead of the old `main.css` classes.
7. **Self-host assets:** vendor lucide icons (local sprite/module) + Inter/JetBrains
   Mono fonts locally; drop the two CDNs.
8. **Deployment:** confirm CT1109 can produce the build output (or commit the
   generated CSS as a build artifact so the deploy stays a plain `StaticFiles`
   mount — preferred, zero new runtime deps).

---

## 4. Risks / guardrails

- **Visual-regression contract:** the a11y + CSS + JS contract tests are the safety
  net; convert them in lockstep, don't leave them red on the old contract.
- **No-React honesty:** shadcn *React components* can't be dropped into Jinja2. Path
  A delivers shadcn's **visual system** (which is what "entire visual system"
  means) via the token + style layer, not the React source. If Cody truly needs the
  React components themselves, that forces Path B.
- **Pin discipline:** the whole point is "the version can't change and ruin our
  site" — so: commit generated assets, lock versions, never auto-pull.
- **Deployment unchanged** (uvicorn + StaticFiles) if we commit build artifacts —
  avoids touching the production service layout.
