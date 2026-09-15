# Bark Design Contract

Implementation guidance for the dashboard, not a mockup. Every module workspace
and page follows these rules so Bark reads as one product rather than a
collection of independently-built modules. Source of truth for values is
`frontend/src/tokens.css`; this document explains intent and usage.

Verified against the live dashboard (1600×1200, dev instance): see
`docs/module-workspace.md` for the workspace anatomy and
`frontend/src/index.css`-equivalent build (`frontend/build.mjs`) for how the
sources become `dashboard/static/css/main.css`.

## 1. Where styles live

| Layer | File | Owns |
|---|---|---|
| Tokens | `frontend/src/tokens.css` | Colors, spacing scale, radii, control heights, field widths, z-layers |
| shadcn theme | `frontend/src/theme.css` | Semantic tokens (`--background`, `--card`, `--primary`, `--border`, `--ring`) that all other tokens alias |
| Components | `frontend/src/components.css` | Cards, grids, tables, forms, dialogs, workspace patterns |
| v3 layer | `frontend/src/v3.css` | Later refinements: focus rings, motion, workspace density, destructive controls |
| Themes | `frontend/src/themes.css`, `frontend/src/advanced-themes.css` | Optional server-selectable themes (never a baseline requirement) |

Rules:

1. **Never hardcode a colour, radius, or spacing value in a module template.**
   Use a token. If the value you need does not exist, add a token (and document
   it here) rather than a literal.
2. **Never patch component CSS from a template.** One-off `<style>` blocks and
   inline `style=` attributes are not part of the contract.
3. `dashboard/static/css/main.css` is **generated**. Edit `frontend/src/*.css`,
   run `npm run build` in `frontend/`, and bump the `?v=` cache-buster on
   `main.css` in `dashboard/templates/base.html`. CI runs `npm run check`, which
   rebuilds and fails if the committed CSS does not match source.

## 2. Layout rules

- `--content-max-width: 1440px` with `--content-padding: clamp(24px, 3vw, 38px)`.
  A page is a `.page-container`; never set an independent page width.
- Module pages render through **one** template (`pages/module_detail.html`).
  The workspace header — breadcrumb, "Module workspace" eyebrow, title,
  description, role pill, enabled/disabled badge, enable toggle, Reload — is
  identical for every module and is not per-module markup. Module-specific
  content begins beneath it.
- **Workspace split:** `.workspace-split` is `main + side`, where side is the
  auxiliary column (activity, queue, summaries). When the side column is empty
  the split collapses to one full-width column
  (`.workspace-split:has(.workspace-split-side:empty)`) — an editor is never
  squeezed next to a blank column.
- **Action grid:** `.operation-grid` is two columns; one child spans the full
  width; an auto-run action (e.g. trivia leaderboard) spans and drops the submit
  button. At ≥1920px it is three columns; at ≤1279px one column.
- **Density** is container-driven: `.module-workspace` sets `--workspace-density`
  (1/2/3) per breakpoint via `container-type: inline-size`. Do not add new
  breakpoints for a single module.
- **Tables** live in `.table-scroll` (or the card's own `overflow-x: auto`) and
  get a `min-width` so narrow viewports scroll the table instead of crushing
  cells. Dense tables are allowed; horizontal page scroll is not.
- Keep Bark compact and information-dense. Large padding to imitate consumer
  SaaS is a regression, not a refresh.

## 3. Forms

- Field widths are a token decision: `--field-width-numeric: 180px` keeps
  numeric/threshold fields compact **in settings/config forms**. Inside a module
  action card the card is already narrow, so numeric fields fill the card
  (`.action-card .form-input[type=number]`). Every other control fills its form
  track.
- Layout with `.form-grid` (3 cols), `.form-grid-2`, `.form-grid-3` — never with
  per-field widths.
- Labels: `.form-label` above the control; required fields get a visible `*`
  plus a `sr-only` "required"; help text uses `.form-hint`.
- **Validation** is server-authoritative. Client-side checks are a convenience;
  the API must reject malformed input with a 400 and a message naming the field.
- **Partial updates:** an omitted field means *leave unchanged*. Only an explicit
  `null` (where the API defines it) means *clear*. This is a project-wide rule —
  the reputation tier `role_id` clobber was this rule missing.
- Validate every stored parameter that an operation needs **before** the
  external side effect starts (send/act, then record), not after.

## 4. Action states and feedback

- Every submitted action enters a visible processing state, prevents duplicate
  submission, and ends in a success or error result rendered in the card.
- Report external boundaries honestly: "saved", "Discord operation completed",
  and "Discord rejected the operation" are three different outcomes.
- Destructive actions use `btn-danger`, carry the `Destructive` status badge,
  and are grouped under the `Maintenance & destructive actions` heading
  (actions flagged `destructive` are sorted last by the page route).
- Support a dry-run where the operation is reversible or bulk; label it and make
  the result say plainly that nothing was changed.

## 5. Accessibility (non-negotiable)

- Keyboard reachable: navigation, tabs, dropdowns, tables, forms, dialogs and
  destructive confirmations. Tabs use `role="tablist"`/`role="tabpanel"` with
  `aria-selected` and roving `tabindex`.
- Visible focus: the shared `:focus-visible` ring in `v3.css`. Do not remove
  outlines to "clean up" a control.
- Icon-only controls need an accessible name (`aria-label` or `sr-only` text).
- Status is never colour alone — pair colour with a badge or text.
- Motion respects `prefers-reduced-motion` (single global neutralizer in
  `v3.css`); do not add per-component opt-outs.
- Minimum font size is 15px (`--font-size-caption`); body copy is 16px.

## 6. Adding a module

1. Declare actions, pages, tabs and settings schema in the module; the workspace
   renders them. Do not write a bespoke page unless the module genuinely needs a
   different interaction (document why).
2. Use tokens and existing components; add a token rather than a literal.
3. Rebuild CSS, bump the cache-buster, and run the contract tests
   (`test_css_contract.py`, `test_frontend_a11y_contract.py`,
   `test_frontend_js_contract.py`) plus `npm run check`.
4. Verify in a real browser at 1600px, 1280px and 390px — contract tests cannot
   prove layout.

## 7. Known gaps (deliberately not fixed yet)

- Role Manager still shows raw IDs in places where resolved names would read
  better; the behavior column is verbose.
- Retention/privacy disclosure for logs, attachments and analytics is not in the
  UI yet (Milestone D).
- Destructive confirmation text is per-action; a single confirmation component
  with an explicit impact summary is still to come.
