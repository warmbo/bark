"""Export the Bark documentation wiki as static HTML into a target directory.

The public bark-site (bark.warx.org) is a static site (python http.server on
:8092). The docs are generated from the live module registry so they never
drift from code; this script renders the same data the dashboard's dynamic
/docs uses and writes self-contained static HTML files that the bark-site can
serve directly.

Run from the bark app repo (needs the venv):
    .venv/bin/python scripts/export_site_docs.py <out_dir>
    # e.g. .venv/bin/python scripts/export_site_docs.py ../bark-site/docs

The output is a flat set of pages under <out_dir>/ with a shared docs.css:
    index.html, modules.html, commands.html, settings.html, permissions.html,
    module/<name>.html, command/<path>.html, settings/<module>.html
Every page links back to the site root and is styled to match bark-site.

To regenerate after a code change, re-run the script and commit the bark-site
repo (additive, regenerated on each release).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Allow running from a source checkout (scripts/.. on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _build_manager():
    """Build a real ModuleManager with all core modules enabled (no Discord)."""
    from services.module_manager import ModuleManager

    class _FakeBot:
        pass

    manager = ModuleManager(MagicMock())
    manager.discover()
    import asyncio

    for name in list(manager.get_all_modules()):
        asyncio.run(manager.enable_module(name))
    return manager


def _collect(manager):
    from services import docs_registry

    return {
        "group": docs_registry.command_group_name(manager),
        "docs_base": "docs/static_base.html",
        "modules": docs_registry.collect_modules(manager),
        "commands": docs_registry.collect_commands(manager),
        "settings": docs_registry.collect_settings(manager),
        "permissions": docs_registry.collect_permissions(),
        "public_url": "https://bark.warx.org",
    }


def _render_all(out_dir: Path, ctx: dict) -> None:
    from jinja2 import Environment, FileSystemLoader

    templates_dir = Path(__file__).resolve().parents[1] / "dashboard" / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    env.globals["url_for"] = lambda *a, **k: "#"  # not used by docs pages
    env.globals["config"] = SimpleNamespace(dashboard=SimpleNamespace(public_url=ctx.get("public_url", "")))
    env.globals["base"] = ""  # per-page override below (subpages need ../)

    pages = {
        "index.html": "docs/index.html",
        "modules.html": "docs/modules.html",
        "commands.html": "docs/commands.html",
        "settings.html": "docs/settings.html",
        "permissions.html": "docs/permissions.html",
    }
    for filename, template_name in pages.items():
        html = env.get_template(template_name).render({**ctx, "base": ""})
        (out_dir / filename).write_text(_rewrite_links(html, depth=0), encoding="utf-8")

    # Per-module pages.
    module_dir = out_dir / "module"
    module_dir.mkdir(parents=True, exist_ok=True)
    for m in ctx["modules"]:
        mctx = dict(ctx)
        mctx["module"] = m
        mctx["active"] = "modules"
        html = env.get_template("docs/module.html").render({**mctx, "base": "../"})
        (module_dir / f"{m['name']}.html").write_text(_rewrite_links(html, depth=1), encoding="utf-8")

    # Per-command pages (URL-safe path).
    command_dir = out_dir / "command"
    command_dir.mkdir(parents=True, exist_ok=True)
    for c in ctx["commands"]:
        cctx = dict(ctx)
        cctx["command"] = c
        cctx["active"] = "commands"
        html = env.get_template("docs/command.html").render({**cctx, "base": "../"})
        (command_dir / f"{c['path'].replace(' ', '_')}.html").write_text(
            _rewrite_links(html, depth=1), encoding="utf-8"
        )

    # Per-module settings pages.
    settings_dir = out_dir / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    for s in ctx["settings"]:
        sctx = dict(ctx)
        sctx["setting_group"] = s
        sctx["active"] = "settings"
        html = env.get_template("docs/settings_module.html").render({**sctx, "base": "../"})
        (settings_dir / f"{s['module']}.html").write_text(_rewrite_links(html, depth=1), encoding="utf-8")

    # Not-found page.
    (out_dir / "not_found.html").write_text(
        _rewrite_links(env.get_template("docs/not_found.html").render({**ctx, "base": ""}), depth=0),
        encoding="utf-8",
    )


def _rewrite_links(html: str, depth: int) -> str:
    """Rewrite the app's absolute ``/docs/...`` links to static ``.html`` files.

    The app templates emit absolute ``/docs/modules``, ``/docs/commands/{path}``,
    ``/docs/modules/{name}`` etc. On the static bark-site these must point at the
    exported relative files. ``depth`` is the number of subdirectories below the
    docs root (0 = root page, 1 = module/command/settings subpage).
    """
    prefix = "../" * depth

    def _repl(m: re.Match[str]) -> str:
        path = m.group(1)
        if path in ("", "/"):
            return f'href="{prefix}index.html"'
        if path == "/modules":
            return f'href="{prefix}modules.html"'
        if path == "/commands":
            return f'href="{prefix}commands.html"'
        if path == "/settings":
            return f'href="{prefix}settings.html"'
        if path == "/permissions":
            return f'href="{prefix}permissions.html"'
        if path.startswith("/modules/"):
            return f'href="{prefix}module/{path[len("/modules/"):]}.html"'
        if path.startswith("/commands/"):
            return f'href="{prefix}command/{path[len("/commands/"):].replace(" ", "_")}.html"'
        if path.startswith("/settings/"):
            return f'href="{prefix}settings/{path[len("/settings/"):]}.html"'
        return m.group(0)  # leave unknown links untouched

    return re.sub(r'href="/docs([^"]*)"', _repl, html)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", help="Directory to write static docs into (e.g. ../bark-site/docs)")
    parser.add_argument("--write-css", action="store_true", help="Write docs.css into out_dir")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manager = _build_manager()
    ctx = _collect(manager)
    _render_all(out_dir, ctx)

    # Write the shared docs stylesheet (matches bark-site design tokens).
    if args.write_css:
        css = _DOCS_CSS
        (out_dir / "docs.css").write_text(css, encoding="utf-8")
        # Self-contain the brand avatar so the docs dir needs no site assets.
        avatar_src = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "img" / "bark-avatar.png"
        if avatar_src.exists():
            shutil.copy(avatar_src, out_dir / "bark-avatar.png")
        # Inter font (self-contained, no CDN per the site's no-CDN rule).
        font_src = out_dir.parent / "assets" / "fonts" / "inter-latin.woff2"
        if font_src.exists():
            fonts_dir = out_dir / "fonts"
            fonts_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(font_src, fonts_dir / "inter-latin.woff2")

    print(f"Exported {len(ctx['modules'])} modules, {len(ctx['commands'])} commands, "
          f"{len(ctx['settings'])} setting groups, {len(ctx['permissions'])} permissions → {out_dir}")
    return 0


_DOCS_CSS = """\
@font-face{font-family:'Inter';src:url('fonts/inter-latin.woff2') format('woff2');font-style:normal;font-weight:100 900;font-display:swap}
:root {
  --bg: #0b0b0e; --bg-elev: #101014; --card: #121216; --card-hover: #16161c;
  --border: #1f1f24; --border-strong: #2a2a31; --foreground: #f4f4f5;
  --muted: #9d9da6; --muted-dim: #6b6b74; --accent: #3b82f6; --accent-hover: #60a5fa;
  --accent-dim: rgba(59,130,246,.12); --green: #22c55e; --destructive: #ef4444; --amber: #f59e0b;
  --radius: 0px; --font-sans: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace; --max: 1480px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:var(--font-sans);background:var(--bg);color:var(--foreground);line-height:1.6;font-size:15px;-webkit-font-smoothing:antialiased}
a{color:var(--accent-hover);text-decoration:none}
a:hover{text-decoration:underline}
.docs-header{position:sticky;top:0;z-index:50;background:var(--bg);border-bottom:1px solid var(--border);backdrop-filter:blur(8px)}
.docs-header-inner{max-width:var(--max);margin:0 auto;padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.docs-brand{display:flex;align-items:center;gap:10px;font-weight:700;color:var(--foreground)}
.docs-brand img{width:30px;height:30px;border-radius:6px}
.docs-brand small{font-weight:400;color:var(--muted);margin-left:4px}
.docs-nav{display:flex;gap:18px;align-items:center}
.docs-nav a{color:var(--muted);font-size:14px;font-weight:500}
.docs-nav a:hover,.docs-nav a.active{color:var(--foreground);text-decoration:none}
.docs-nav a.active{color:var(--accent-hover)}
.docs-home{color:var(--muted);font-size:14px}
.docs-layout{max-width:var(--max);margin:0 auto;padding:32px 24px 64px}
.docs-crumb{font-size:13px;color:var(--muted-dim);margin-bottom:10px}
.docs-crumb a{color:var(--muted)}
.docs-crumb span{margin:0 6px}
h1{font-size:30px;font-weight:750;margin-bottom:6px;letter-spacing:-.02em}
h2{font-size:20px;font-weight:650;margin:34px 0 12px}
h3{font-size:16px;font-weight:600;margin:24px 0 8px}
.lead{color:var(--muted);max-width:820px;margin-bottom:22px}
p{color:var(--muted);max-width:820px}
code{font-family:var(--font-mono);background:var(--bg-elev);border:1px solid var(--border);border-radius:4px;padding:1px 6px;font-size:13px;color:var(--foreground)}
/* Content classes used by the docs page templates (shared with the app's
   docs/base.html so the static export renders identically). */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-top:8px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;display:block;transition:border-color .15s,transform .15s}
.card:hover{border-color:var(--border-strong);transform:translateY(-1px);text-decoration:none}
.card h3{color:var(--foreground);margin:0 0 4px;font-size:16px}
.card .ver{color:var(--muted-dim);font-size:12px;font-weight:400;margin-left:6px}
.card p{font-size:13.5px;color:var(--muted);margin:0}
.card .meta{margin-top:12px;font-size:12.5px;color:var(--muted-dim);display:flex;gap:14px;flex-wrap:wrap}
.cmd{display:flex;align-items:baseline;gap:12px;padding:9px 0;border-bottom:1px solid var(--border)}
.cmd:last-child{border-bottom:none}
.cmd .path{font-family:var(--font-mono);color:var(--foreground);font-size:13.5px;white-space:nowrap}
.cmd .desc{color:var(--muted);font-size:13.5px}
.docs-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;margin-top:8px}
.docs-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;display:block;transition:border-color .15s,transform .15s}
.docs-card:hover{border-color:var(--border-strong);transform:translateY(-1px);text-decoration:none}
.docs-card h3{color:var(--foreground);margin:0 0 4px;font-size:16px}
.docs-card .ver{color:var(--muted-dim);font-size:12px;font-weight:400;margin-left:6px}
.docs-card p{font-size:13.5px;color:var(--muted);margin:0}
.docs-card .meta{margin-top:12px;font-size:12.5px;color:var(--muted-dim);display:flex;gap:14px;flex-wrap:wrap}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:8px 0 20px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted-dim);font-size:12px;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
td code{white-space:nowrap}
tr:hover td{background:var(--bg-elev)}
.cmd{display:flex;align-items:baseline;gap:12px;padding:9px 0;border-bottom:1px solid var(--border)}
.cmd:last-child{border-bottom:none}
.cmd .path{font-family:var(--font-mono);color:var(--foreground);font-size:13.5px;white-space:nowrap}
.cmd .desc{color:var(--muted);font-size:13.5px}
.badge{display:inline-block;padding:1px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;border:1px solid transparent}
.badge.anyone{background:rgba(59,130,246,.12);color:var(--accent-hover);border-color:rgba(59,130,246,.3)}
.badge.moderator{background:rgba(245,158,11,.12);color:var(--amber);border-color:rgba(245,158,11,.3)}
.badge.admin{background:rgba(239,68,68,.12);color:var(--destructive);border-color:rgba(239,68,68,.3)}
.role-key{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:6px 0 18px;align-items:center}
.req{color:var(--amber);font-weight:600}
.opt{color:var(--muted-dim)}
.docs-footer{border-top:1px solid var(--border);padding:26px 24px;text-align:center;color:var(--muted-dim);font-size:13px}
.docs-footer a{color:var(--muted)}
.notfound{color:var(--muted);font-size:16px}
@media (max-width:820px){.docs-nav{display:none}.docs-header-inner{padding:12px 16px}.docs-layout{padding:22px 16px 48px}.docs-grid{grid-template-columns:1fr}}
"""


if __name__ == "__main__":
    raise SystemExit(main())
