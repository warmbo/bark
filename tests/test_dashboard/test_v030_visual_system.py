"""Contracts for the locally-pinned Bark v0.3 shadcn visual system."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "dashboard/templates/base.html"
CSS = ROOT / "dashboard/static/css/main.css"
V3_SOURCE = ROOT / "frontend/src/v3.css"
PRIMITIVES = ROOT / "dashboard/templates/components/primitives.html"
PACKAGE = ROOT / "frontend/package.json"
PIN = ROOT / "frontend/shadcn-pin.md"
SETTINGS = ROOT / "dashboard/templates/pages/settings.html"
ADVANCED_JS = ROOT / "dashboard/static/js/advanced-themes.js"
ADVANCED_CSS = ROOT / "frontend/src/advanced-themes.css"
THREE = ROOT / "dashboard/static/js/vendor/three.module.0.185.1.min.js"


def test_v030_uses_local_assets_only():
    base = BASE.read_text()
    assert "fonts.googleapis.com" not in base
    assert "fonts.gstatic.com" not in base
    assert "unpkg.com" not in base
    assert "/static/fonts/inter-latin.woff2" in base or "fonts.css" in base
    assert "/static/js/lucide.min.js" in base


def test_v030_shadcn_tokens_are_present_and_sharp():
    css = CSS.read_text()
    for token in (
        "--background:",
        "--foreground:",
        "--card:",
        "--card-foreground:",
        "--primary:",
        "--primary-foreground:",
        "--secondary:",
        "--muted:",
        "--accent:",
        "--destructive:",
        "--border:",
        "--input:",
        "--ring:",
    ):
        assert token in css
    assert "--radius: 0px" in css
    assert "Bark v0.3 shadcn visual system" in css


def test_v030_frontend_dependencies_are_exact_pinned():
    import json

    package = json.loads(PACKAGE.read_text())
    dependencies = package["devDependencies"]
    assert dependencies == {
        "@fontsource/inter": "5.3.0",
        "@fontsource/jetbrains-mono": "5.3.0",
        "@fontsource-variable/cormorant": "5.3.0",
        "@fontsource-variable/space-grotesk": "5.3.0",
        "@fontsource-variable/syne": "5.3.0",
        "@fontsource-variable/unbounded": "5.3.0",
        "@fontsource/cinzel": "5.3.0",
        "@tailwindcss/cli": "4.3.3",
        "lucide": "1.31.0",
        "tailwindcss": "4.3.3",
        "three": "0.185.1",
    }
    assert PIN.is_file()
    assert "deliberate upgrade" in PIN.read_text().lower()


def test_v030_has_shadcn_jinja_primitives():
    primitives = PRIMITIVES.read_text()
    for macro in (
        "button",
        "card",
        "badge",
        "input_field",
        "select_field",
        "textarea_field",
        "separator",
        "avatar",
    ):
        assert f"macro {macro}(" in primitives


def test_v030_owns_a_responsive_whole_project_spacing_system():
    source = V3_SOURCE.read_text()

    for step, value in {
        1: 4,
        2: 8,
        3: 12,
        4: 16,
        5: 20,
        6: 24,
        8: 32,
        10: 40,
        12: 48,
    }.items():
        assert f"--space-{step}: {value}px" in source

    for contract in (
        ".page-container {",
        ".content-card {",
        ".form-group {",
        ".data-table th,",
        ".workspace-tabs {",
        ".settings-grid {",
        ".stats-charts {",
        "@media (max-width: 768px)",
        "@media (max-width: 480px)",
        "@media (min-width: 640px) and (max-width: 1024px)",
        "grid-template-columns: minmax(0, 1fr)",
        "flex-direction: column",
    ):
        assert contract in source


def test_python_release_line_is_v030():
    assert 'version = "0.3.0"' in (ROOT / "pyproject.toml").read_text()


def test_advanced_themes_are_local_labeled_and_motion_safe():
    base = BASE.read_text()
    settings = SETTINGS.read_text()
    runtime = ADVANCED_JS.read_text()
    css = ADVANCED_CSS.read_text()

    assert THREE.is_file()
    assert THREE.stat().st_size > 100_000
    assert 'src="/static/js/advanced-theme-loader.js?v=' in base
    assert "import('/static/js/advanced-themes.js?v=2')" in (ROOT / "dashboard/static/js/advanced-theme-loader.js").read_text()
    assert "from '/static/js/vendor/three.module.0.185.1.min.js'" in runtime
    assert "https://" not in runtime and "http://" not in runtime
    assert "Advanced themes" in settings
    for theme in (
        "hud", "aurora", "neon", "ocean", "sunset", "forest",
        "candy", "slate", "crimson", "honey", "deepspace", "graffiti",
    ):
        assert f'(\"{theme}\"' in settings
        assert theme in runtime or theme == "hud"
    assert "prefers-reduced-motion" in runtime
    assert "@media (prefers-reduced-motion: reduce)" in V3_SOURCE.read_text()
    assert ".advanced-theme-canvas" in css
    assert ".graffiti-pause-button" in css
