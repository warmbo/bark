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
    assert referenced - defined == set()


def test_css_preserves_sharp_16px_design_contract():
    css = css_source()
    assert "--font-size-body: 16px;" in css
    for token in ("sm", "md", "lg", "xl", "full"):
        assert f"--radius-{token}: 0px;" in css


def test_css_keyboard_and_reduced_motion_contracts():
    css = css_source()
    assert ".toggle-switch input:focus-visible + .toggle-slider" in css
    assert ".form-textarea:focus-visible" in css
    assert ".palette-input-wrapper:focus-within" in css
    reduced_motion = rule_body(css, "@media (prefers-reduced-motion: reduce)")
    # The media rule contains nested blocks, so check the source for its explicit
    # scroll override as well as the global animation/transition override.
    assert "html { scroll-behavior: auto !important; }" in css
    assert "transition: none !important;" in css
    assert "animation: none !important;" in css
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


def test_desktop_operation_grid_balances_incomplete_rows():
    css = css_source()
    assert ".operation-grid:has(> :only-child)" in css
    assert ".operation-grid > :last-child:nth-child(odd) { grid-column: 1 / -1; }" in css


def test_mobile_health_strip_stacks_labels_and_values():
    css = css_source()
    assert "@media (max-width: 480px)" in css
    assert ".module-health-strip > div { grid-template-columns: 1fr; row-gap: 2px; }" in css


def test_activity_feed_fade_mask_contract():
    css = css_source()
    assert ".activity-feed.is-masked" in css
    assert "mask-image: linear-gradient(to bottom" in css
    assert ".activity-more-wrap" in css
