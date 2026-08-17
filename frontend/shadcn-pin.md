# Bark's locally pinned shadcn visual system

Bark v0.3 uses the shadcn/ui visual language in a server-rendered Jinja2 app.
The upstream React components are not runtime dependencies: their design tokens,
component recipes, Tailwind v4 utilities, Lucide icons, and fonts are vendored and
compiled into committed static assets.

## Pin

- Snapshot date: 2026-08-16
- shadcn generation: CLI v4 / Tailwind v4 design-token model
- Tailwind CSS and CLI: `4.3.3`
- Lucide: `1.31.0`
- Inter / JetBrains Mono: `5.3.0`
- Lock: `frontend/package-lock.json`

Production never contacts shadcn, npm, Google Fonts, or unpkg. The generated
`dashboard/static/css/main.css`, local fonts, and local Lucide UMD bundle are
committed so CT1109 needs no Node runtime.

## Build

```bash
cd frontend
npm ci
npm run build
```

Edit only `frontend/src/theme.css`, `frontend/src/legacy.css`, or
`frontend/src/v3.css`; `dashboard/static/css/main.css` is generated.

## Deliberate upgrade procedure

There are no automatic upgrades. For a deliberate upgrade:

1. Create a dedicated branch and record the current lockfile + generated hashes.
2. Pin exact replacement versions in `package.json` (never `latest`, `^`, or `~`).
3. Run `npm install`, inspect the lockfile diff, then `npm run build`.
4. Run frontend contracts and the full Python suite.
5. Visually compare desktop/mobile pages and all dialogs, tabs, dropdowns, forms,
   module workspaces, and owner-only settings against the previous build.
6. Deploy only to bark-dev and obtain explicit approval before stable promotion.

Bark intentionally keeps sharp `0px` corners, black/navy surfaces, electric-blue
primary actions, and the bundled Bark avatar/wallpaper imagery instead of adopting
a stock white shadcn preset.
