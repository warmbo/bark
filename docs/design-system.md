# Bark Visual System — v0.3

Bark v0.3 uses a **locally pinned shadcn/ui-derived visual system** adapted to
FastAPI/Jinja2. It is dark-only, square, dense, and Bark-branded. This document is
the active design contract; the implementation and exact pins live in `frontend/`.

## Non-negotiable identity

- **Sharp:** `--radius: 0px`; buttons, cards, dialogs, fields, dropdowns, badges,
  tables, avatars and feedback surfaces do not use soft product-style rounding.
- **Dark navy/black:** page `--background` is near-black navy; cards and popovers
  step upward in navy rather than neutral gray.
- **Blue action hierarchy:** primary actions and keyboard rings use electric blue.
  Destructive actions use semantic red, never blue.
- **Bark imagery:** the bundled Bark avatar and wallpaper are first-party assets.
  Landing uses the wallpaper visibly; the app shell uses the avatar as a subtle,
  low-opacity watermark. Do not stack extra image effects onto already-treated art.
- **No upstream drift:** CSS, fonts and icons are local static assets. Production
  must render with network access disabled.

## Semantic tokens

Source: `frontend/src/theme.css` and the final compatibility declarations in
`frontend/src/v3.css`.

| Token | Purpose |
|---|---|
| `--background` / `--foreground` | canvas and default text |
| `--card` / `--card-foreground` | cards, widgets, workspace surfaces |
| `--popover` / `--popover-foreground` | dialogs, menus, palettes, drawers |
| `--primary` / `--primary-foreground` | principal CTA, active control |
| `--secondary` / `--secondary-foreground` | neutral elevated control |
| `--muted` / `--muted-foreground` | secondary surfaces and explanatory text |
| `--accent` / `--accent-foreground` | selected/hovered interactive state |
| `--destructive` | irreversible or harmful action |
| `--border` / `--input` / `--ring` | structure, controls, keyboard focus |
| `--sidebar-*` | navigation-specific surface and active state |
| `--chart-1` … `--chart-5` | accessible chart series |

Legacy aliases such as `--bg-card`, `--text-secondary`, `--green`, and `--red`
map to these tokens so workspace behavior remains stable. New styles use semantic
shadcn tokens directly.

## Typography

- Inter: interface text; local `dashboard/static/fonts/inter-latin.woff2`.
- JetBrains Mono: versions, IDs, URLs, terminal output, diagnostics.
- Page heading: semibold, tight tracking; one `<h1>` per page.
- Card title: semibold; descriptions use `--muted-foreground`.
- Labels remain visible and associated with controls; placeholders are never labels.

## Components

Jinja primitives live in `dashboard/templates/components/primitives.html`.
Supported foundation macros: `button`, `card`, `badge`, `input_field`,
`select_field`, `textarea_field`, `separator`, and `avatar`, plus existing page,
state, status and table primitives.

Visual recipes are centralized in `frontend/src/v3.css` for:

- card, field, input/select/textarea, button and badge;
- table, tabs, sidebar, breadcrumb/context bar;
- dialog, alert-dialog, popover, dropdown, command palette and drawer;
- alert/state panel, toast, skeleton, progress and empty state;
- module, guild, workspace, moderation, statistics and settings surfaces.

JavaScript hooks (`id`, `name`, `data-*`, state classes) are behavior APIs. A visual
conversion must not rename them without changing and testing every consumer.

## Interaction and accessibility

- Every interactive control has visible `:focus-visible` using `--ring`.
- Dialogs preserve focus trap, Escape/backdrop close rules and focus restoration.
- Destructive operations require an alert-dialog confirmation.
- Tabs use roles, `aria-selected`, and keyboard navigation.
- Dynamic feedback uses `aria-live` and never relies on color alone.
- Motion honors `prefers-reduced-motion`.
- Mobile has no horizontal page scroll; wide tables scroll inside `.table-scroll`.
- Viewer/offline/permission-denied states remain complete states, not hidden errors.

## Build and ownership

```bash
cd frontend
npm ci
npm run build
```

The generated `dashboard/static/css/main.css`, local fonts, and local Lucide bundle
are committed. CT1109 does not need Node. Exact versions and the manual upgrade
process are documented in `frontend/shadcn-pin.md`. Never edit generated CSS
directly and never add a CDN to restore an icon or font.

## Verification gate

A visual change is complete only after frontend contract tests, full pytest, Ruff,
desktop/mobile browser inspection, keyboard traversal, browser-console inspection,
and a bark-dev deployment. Stable promotion requires a pre-update DB backup and an
explicit approval.
