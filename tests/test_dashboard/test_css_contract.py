"""Static contracts for Bark's build-free dashboard stylesheet."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "dashboard" / "static" / "css" / "main.css"


def css_source() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css, re.S)
    assert match, f"missing CSS rule: {selector}"
    return match.group(1)


def test_css_references_only_defined_custom_properties():
    css = css_source()
    defined = set(re.findall(r"(?<![\w-])(--[\w-]+)\s*:", css))
    referenced = set(re.findall(r"var\(\s*(--[\w-]+)", css))
    # Tailwind v4 intentionally emits internal --tw-* and --default-* references
    # with standards-based fallbacks. Bark-owned semantic variables must still
    # be declared in the committed bundle.
    bark_references = {
        name
        for name in referenced
        if not name.startswith(("--tw-", "--default-"))
    }
    assert bark_references - defined == set()


def test_css_preserves_sharp_16px_design_contract():
    css = css_source()
    assert "--font-size-body: 16px;" in css
    # Sharp-corner contract: control radii are 0px; --radius-full is the pill/avatar
    # radius (round avatars, status chips, scrollbar thumbs) and stays 999px.
    for token in ("sm", "md", "lg", "xl"):
        assert f"--radius-{token}: 0px;" in css
    assert "--radius-full: 999px" in css


def test_css_keyboard_and_reduced_motion_contracts():
    css = css_source()
    assert ".toggle-switch input:focus-visible + .toggle-slider" in css
    assert ".form-textarea:focus-visible" in css
    assert ".palette-input-wrapper:focus-within" in css
    reduced_motion = rule_body(css, "@media (prefers-reduced-motion: reduce)")
    # The media rule contains nested blocks, so check the source for its explicit
    # scroll override as well as the global animation/transition override.
    # (Single implementation lives in v3.css — the shadcn layer — which neutralizes
    # motion with ~0ms durations rather than `none`, so elements keep reachable states.)
    assert "html { scroll-behavior: auto !important; }" in css
    assert "transition-duration: .01ms !important;" in css
    assert "animation-duration: .01ms !important;" in css
    assert reduced_motion.strip()


def test_css_scroll_containers_protect_wide_dashboard_content():
    css = css_source()
    assert "overflow-x: auto" in rule_body(css, ".workspace-tabs")
    assert "overflow-x: auto" in rule_body(css, ".member-grid")
    assert "min-width: 680px" in rule_body(css, ".member-table")
    assert ".content-card:has(> .data-table) { overflow-x: auto; }" in css
    assert "flex: 0 0 auto" in rule_body(css, ".tab")


def test_context_bar_has_no_unsafe_fixed_height():
    css = css_source()
    declarations = rule_body(css, ".context-bar")
    assert not re.search(r"(?m)^\s*height\s*:", declarations)
    assert "min-height: 42px" in declarations


def test_css_avoids_unbounded_transition_all():
    assert not re.search(r"transition\s*:\s*all\b", css_source())


def test_desktop_operation_grid_keeps_odd_card_counts_uniform():
    """Multi-card operation grids (e.g. moderation's 5-card Operate tab) must
    keep every card the same grid width. A lone card still spans full width
    (:only-child), but an odd number of cards must NOT stretch the last one to
    full width (that produced a stair-stepped, 'not contained' look)."""
    css = css_source()
    assert ".operation-grid:has(> :only-child)" in css
    assert ".operation-grid > :last-child:nth-child(odd):not(:only-child)" in css
    # The odd-card-count rule must NOT stretch the last card to full width.
    assert not re.search(
        r"\.operation-grid\s*>\s*:last-child:nth-child\(odd\)[^{]*grid-column:\s*1\s*/\s*-1",
        css,
    )


def test_mobile_health_strip_stacks_labels_and_values():
    css = css_source()
    assert "@media (max-width: 480px)" in css
    assert ".module-health-strip > div { grid-template-columns: 1fr; row-gap: 2px; }" in css


def test_activity_feed_fade_mask_contract():
    css = css_source()
    assert ".activity-feed.is-masked" in css
    assert "mask-image: linear-gradient(to bottom" in css
    assert ".activity-more-wrap" in css


def test_button_size_ladder_is_monotonic():
    """Size variants must be strictly smaller than base (audit 2026-08-19: the
    ladder was inverted — .btn-sm rendered bigger than .btn). Enforce the
    v3 REMAKER values so the regression can't return."""
    css = css_source()
    assert ".btn-sm { min-height: 32px; padding: 4px 12px; font-size: 15px; }" in css
    assert ".btn-xs { min-height: 28px; min-width: 28px; padding: 2px 8px; font-size: 15px; line-height: 1.6; }" in css
    # .btn-icon must follow the sharp-corner token, not a hardcoded radius.
    btn_icon = re.search(r"\.btn-icon\s*\{[^}]*\}", css, re.S)
    assert btn_icon, "missing .btn-icon rule"
    assert "border-radius: var(--radius)" in btn_icon.group(0)
    assert "border-radius: 6px" not in btn_icon.group(0)


def test_reduced_motion_single_implementation():
    """Exactly one prefers-reduced-motion block (legacy + v3 duplication was
    merged 2026-08-19; the v3 shadcn implementation is canonical)."""
    assert css_source().count("@media (prefers-reduced-motion: reduce)") == 1


def test_no_dead_clamp_spacing_ladder():
    """The --space-xs..xl clamp ladder in tokens.css was dead (v3 fixed scale
    wins the cascade). No clamp() values may ship in the spacing tokens."""
    css = css_source()
    for token in ("--space-xs", "--space-sm", "--space-md", "--space-lg", "--space-xl"):
        m = re.search(rf"{token}:\s*([^;]+);", css)
        assert m, f"missing {token}"
        assert "clamp" not in m.group(1), f"{token} must be a fixed scale value, got {m.group(1)}"


def test_font_size_ladder_has_no_fractional_or_odd_stragglers():
    """Audit P3-14 (2026-08-19): the type ladder must not contain fractional
    (12.5/13.5px) or odd (8/9/19/21px) sizes — they read as unplanned values.
    Allowed sizes are the deliberate ladder steps."""
    allowed = {"10px", "11px", "12px", "13px", "14px", "15px", "16px",
               "17px", "18px", "20px", "22px", "24px", "30px"}
    sizes = set(re.findall(r"font-size:\s*(\d+(?:\.\d+)?px)", css_source()))
    assert sizes - allowed == set(), f"off-ladder font sizes: {sorted(sizes - allowed)}"
