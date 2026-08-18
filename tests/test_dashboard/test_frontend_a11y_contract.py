"""Build-free accessibility and desktop viewport contract for Bark's Jinja UI.

This intentionally uses only the standard library so it runs in every backend CI job.
It checks source contracts that do not require Discord/auth fixtures or a browser binary.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "dashboard" / "templates"
STATIC = ROOT / "dashboard" / "static"
PAGES = tuple((TEMPLATES / "pages").glob("*.html"))
ALL_TEMPLATES = tuple(TEMPLATES.rglob("*.html"))


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_templates_compile():
    """Every template must parse — catches stray {% endif %}/tag typos that
    source-regex checks can't see (e.g. settings.html line 131 regression)."""
    from unittest.mock import MagicMock

    from dashboard import create_app

    bot = MagicMock()
    bot.guilds = []
    bot.user = None
    bot.modules = MagicMock()
    bot.modules.event_bus = MagicMock()
    bot.modules.event_bus.get_subscribers.return_value = {}
    bot.modules.event_bus.event_types = []
    bot.modules.get_all_modules.return_value = {}

    app = create_app(bot)
    env = app.app.state.templates.env
    offenders = []
    for path in ALL_TEMPLATES:
        rel = path.relative_to(TEMPLATES).as_posix()
        try:
            env.get_template(rel)
        except Exception as exc:  # noqa: BLE001 — report every broken template
            offenders.append(f"{rel}: {exc}")
    assert offenders == [], f"templates that fail to compile: {offenders}"


def test_templates_do_not_use_inline_event_handlers():
    offenders = []
    for path in ALL_TEMPLATES:
        html = source(path)
        # Only scan HTML tags — ignore <script> bodies, where a bare '<'
        # (JS comparison) plus an identifier like `onlinePct =` false-positives.
        html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
        for match in re.finditer(r"<[^>]+\s(on[a-z]+)\s*=", html, re.I):
            line = source(path)[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line} ({match.group(1).lower()})")
    assert offenders == [], f"use delegated event handlers instead: {offenders}"


def test_template_controls_and_images_have_explicit_static_contracts():
    offenders = []
    for path in ALL_TEMPLATES:
        html = source(path)
        for match in re.finditer(r"<(button|input|select|textarea|img)\b[^>]*>", html, re.I | re.S):
            tag = match.group(0)
            kind = match.group(1).lower()
            line = html[: match.start()].count("\n") + 1
            location = f"{path.relative_to(ROOT)}:{line}"
            if kind == "button" and not re.search(r"\btype\s*=", tag, re.I):
                offenders.append(f"{location} button missing type")
            if kind == "img" and not re.search(r"\balt\s*=", tag, re.I):
                offenders.append(f"{location} image missing alt")
            if kind == "input" and not re.search(r"\btype\s*=", tag, re.I):
                offenders.append(f"{location} input missing type")
            if kind in {"input", "select", "textarea"} and not re.search(r"\bname\s*=", tag, re.I):
                offenders.append(f"{location} control missing name")
    assert offenders == []


def test_literal_form_controls_have_programmatic_labels():
    offenders = []
    for path in ALL_TEMPLATES:
        html = source(path)
        for match in re.finditer(r"<(input|select|textarea)\b[^>]*>", html, re.I | re.S):
            tag = match.group(0)
            if re.search(r'\btype\s*=\s*["\']hidden["\']', tag, re.I):
                continue
            control_id = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if not control_id or any(token in control_id.group(1) for token in ("{{", "${")):
                continue
            has_label = re.search(
                rf'<label\b[^>]*\bfor\s*=\s*["\']{re.escape(control_id.group(1))}["\']',
                html,
                re.I,
            )
            has_aria_name = re.search(r"\baria-(?:label|labelledby)\s*=", tag, re.I)
            if not has_label and not has_aria_name:
                line = html[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(ROOT)}:{line} #{control_id.group(1)}")
    assert offenders == [], f"controls without programmatic labels: {offenders}"


def test_rendered_page_literal_ids_are_unique_and_aria_references_resolve():
    base = source(TEMPLATES / "base.html")
    for page in PAGES:
        page_source = source(page)
        html = base + "\n" + page_source
        # Resolve {% include "components/x.html" %} so ids/for-references that
        # live in partials (e.g. bot customization) are checked with the page.
        for included in re.findall(
            r'{%\s*include\s+["\']([^"\']+)["\']\s*%}', page_source
        ):
            partial = TEMPLATES / included
            if partial.is_file():
                html += "\n" + source(partial)
        if page.name == "module_detail.html":
            # Module-specific tab templates are now colocated under each
            # module's own ``templates/`` directory.
            html += "\n" + "\n".join(
                source(path)
                for mod_dir in (ROOT / "modules").iterdir()
                if (mod_dir / "templates").is_dir()
                for path in (mod_dir / "templates").glob("*.html")
            )
        ids = re.findall(r'\bid\s*=\s*["\']([A-Za-z][\w:.-]*)["\']', html)
        duplicates = sorted(item for item in set(ids) if ids.count(item) > 1)
        assert duplicates == [], f"{page.relative_to(ROOT)} duplicate IDs: {duplicates}"
        # Strip <script> blocks before checking attribute references: JS
        # selectors like label[for="avatar-upload"] are not HTML label/aria
        # attributes and may legitimately reference ids that exist on another
        # page (e.g. bot customization lives on the Instance settings page).
        html_no_scripts = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
        for attr in ("for", "aria-controls", "aria-labelledby", "aria-describedby"):
            references = re.findall(rf'\b{attr}\s*=\s*["\']([A-Za-z][\w:.-]*)["\']', html_no_scripts)
            dangling = sorted(set(reference for reference in references if reference not in ids))
            assert dangling == [], f"{page.relative_to(ROOT)} dangling {attr}: {dangling}"


def test_templates_do_not_render_raw_extension_html():
    offenders = [
        str(path.relative_to(ROOT))
        for path in ALL_TEMPLATES
        if re.search(r"\|\s*safe\b", source(path))
    ]
    assert offenders == [], f"raw template rendering bypasses Jinja escaping: {offenders}"


def test_template_comments_and_font_url_are_html_valid():
    invalid_comments = []
    for path in ALL_TEMPLATES:
        for comment in re.findall(r"<!--(.*?)-->", source(path), re.S):
            if "--" in comment:
                invalid_comments.append(str(path.relative_to(ROOT)))
    assert invalid_comments == []
    base = source(TEMPLATES / "base.html")
    assert "&family=" not in base and "&display=" not in base
    assert "fonts.googleapis.com" not in base
    assert "/static/fonts/inter-latin.woff2" in base


def test_server_card_open_and_close_conditions_match():
    html = source(TEMPLATES / "pages" / "dashboard.html")
    # A connected server is always openable (a link) — granted members manage,
    # non-granted members get the view-only status page.
    open_connected = "guild.access_tier == 'connected'"
    add_bark = "guild.access_tier == 'manageable' and guild.invite_url"
    assert html.count(open_connected) == 4  # open-branch, meta, action, closing tag
    assert html.count(add_bark) == 3
    assert "guild.access_tier in ['connected', 'manageable']" not in html


def test_base_shell_has_skip_target_context_and_accessible_dialog():
    html = source(TEMPLATES / "base.html")
    assert 'href="#main-content"' in html
    assert 'id="main-content"' in html and 'tabindex="-1"' in html
    assert 'class="context-bar"' in html
    assert 'role="alertdialog"' in html and 'aria-modal="true"' in html
    assert 'aria-labelledby="app-dialog-title"' in html
    assert 'aria-describedby="app-dialog-message"' in html


def test_all_declared_tabs_have_relationship_and_keyboard_controller():
    tab_markup = "\n".join(source(path) for path in PAGES)
    tags = re.findall(r"<button[^>]+role=[\"']tab[\"'][^>]*>", tab_markup, re.I)
    assert tags
    assert all("aria-controls=" in tag for tag in tags), tags
    js = source(STATIC / "js" / "main.js")
    for key in ("ArrowRight", "ArrowLeft", "Home", "End", "aria-selected"):
        assert key in js


def test_modules_receive_native_workspace_content_and_live_action_forms():
    html = source(TEMPLATES / "pages" / "module_detail.html")
    # Template is generic — uses module_name variable, no per-module literals
    assert 'data-module-name="{{ module_name }}"' in html
    assert "module-workspace" in html
    for panel in ("operate", "configure", "about"):
        assert f'id="tab-{panel}"' in html
    assert 'data-endpoint="{{ action.endpoint }}"' in html
    assert "module-workspace.js" in html
    js = source(STATIC / "js" / "module-workspace.js")
    assert "/modules/${moduleName}/${form.dataset.endpoint}" in js
    assert "BarkForms.serializeFields" in js
    assert "BarkDialog.confirm" in js


def test_workspace_omits_empty_operate_tab_and_updates_toggle_in_place():
    html = source(TEMPLATES / "pages" / "module_detail.html")
    js = source(STATIC / "js" / "module-workspace.js")
    assert "has_operations" in html
    assert "No operations available" not in html
    assert 'id="module-status-badge"' in html
    assert 'id="module-runtime-status"' in html
    assert "window.location.reload" not in js
    assert "module-status-badge" in js


def test_moderation_danger_zones_are_contextual_to_their_tabs():
    workspace = source(TEMPLATES / "pages" / "module_detail.html")
    voice = source(ROOT / "modules" / "moderation" / "templates" / "moderation_voice.html")
    assert "moderation-retention-danger-zone" in workspace
    assert 'data-purge="audit-logs"' in workspace
    assert 'data-purge="attachments"' in workspace
    assert 'data-purge="voice-history"' in voice
    assert 'data-purge="audit-logs"' not in voice
    assert 'data-purge="attachments"' not in voice


def test_controls_added_by_workspace_have_programmatic_names():
    html = source(TEMPLATES / "pages" / "module_detail.html") + source(
        TEMPLATES / "components" / "primitives.html"
    )
    # Every literal workspace input/select/textarea is either associated by id/for
    # through the field macro or has an explicit accessible name.
    assert 'for="{{ field_id }}"' in html
    assert 'id="{{ field_id }}"' in html
    assert 'for="module-enabled"' in html
    assert "aria-label=\"{{ module_name | replace('_', ' ') | title }} workspace\"" in html


def test_desktop_viewport_and_zoom_contract_is_present():
    css = source(STATIC / "css" / "main.css")
    boundaries = ("1024px", "1025px", "1279px", "1280px", "1439px", "1440px", "1919px", "1920px")
    assert all(boundary in css for boundary in boundaries)
    assert "prefers-reduced-motion: reduce" in css
    assert "overflow-x: hidden" in css
    assert ".workspace-tabs { overflow-x: auto; }" in css
    assert "container-type: inline-size" in css


def test_guild_images_are_intrinsic_not_fixed_height():
    css = source(STATIC / "css" / "main.css")
    rule = re.search(
        r"\.guild-icon-small, \.guild-bar-icon, \.guild-card-icon img \{([^}]+)\}", css
    )
    assert rule
    declarations = rule.group(1)
    assert "width: 100%" in declarations
    assert "height: auto" in declarations
    for path in ALL_TEMPLATES:
        for tag in re.findall(r"<img\b[^>]*>", source(path), re.I):
            if "guild" in tag:
                assert not re.search(r"\bheight=[\"']\d+", tag)


def test_changed_static_assets_have_cache_versions():
    base = source(TEMPLATES / "base.html")
    for asset in ("main.css", "main.js", "shortcuts.js"):
        assert re.search(rf"{re.escape(asset)}\?v=\d+", base)
    module = source(TEMPLATES / "pages" / "module_detail.html")
    assert re.search(r"module-workspace\.js\?v=\d+", module)


def test_remote_bot_images_have_a_bundled_fallback():
    base = source(TEMPLATES / "base.html")
    landing = source(TEMPLATES / "pages" / "landing.html")
    fallback_js = source(STATIC / "js" / "image-fallbacks.js")
    assert 'data-fallback-src="/static/img/bark-avatar.png"' in base
    assert 'data-fallback-src="/static/img/bark-avatar.png"' in landing
    assert "function initImageFallbacks()" in fallback_js
    assert "image-fallbacks.js?v=1" in base
    assert "image-fallbacks.js?v=1" in landing


def test_all_remote_dashboard_avatars_use_the_shared_fallback():
    base = source(TEMPLATES / "base.html")
    members = source(TEMPLATES / "pages" / "members.html")
    detail = source(TEMPLATES / "pages" / "member_detail.html")

    assert 'class="sidebar-user-avatar"' in base
    assert 'data-fallback-src="/static/img/bark-avatar.png"' in base
    assert 'data-fallback-src="/static/img/bark-avatar.png"' in members
    assert 'data-fallback-src="/static/img/bark-avatar.png"' in detail
    assert "initImageFallbacks();" in members
    assert "initImageFallbacks();" in detail


def test_member_detail_empty_state_icons_are_interpolated():
    """Empty-state icon helpers must not render as literal template source."""
    detail = source(TEMPLATES / "pages" / "member_detail.html")

    assert not re.search(r":\s*'[^'\n]*\$\{memberIconSvg", detail)
    for icon in ("scroll-text", "alert-triangle", "headphones", "file-text"):
        literal = '${memberIconSvg("' + icon + '", 18)}'
        assert re.search(r":\s*`[^`\n]*" + re.escape(literal), detail)


def test_module_toggle_uses_the_human_readable_module_name():
    detail = source(TEMPLATES / "pages" / "module_detail.html")
    assert "Enable {{ module_name | replace('_', ' ') | title }}" in detail


# ═══════════════════════════════════════════════════════
# ── BarkDialog.confirm Usage Contract ─────────────────
# ═══════════════════════════════════════════════════════


def test_no_window_confirm_or_alert_or_prompt():
    """No JS or HTML file may use window.confirm, alert(), or window.prompt."""
    js_files = list(STATIC.rglob("*.js")) + list(TEMPLATES.rglob("*.html"))
    for path in js_files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        # window.confirm (standalone confirm() without window is also banned)
        if "confirm(" in text and "BarkDialog.confirm" not in text:
            # Only report if it's actual window.confirm and not a false positive
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                if "confirm(" in line and "BarkDialog.confirm" not in line:
                    stripped = line.strip()
                    # Skip false positives in comments
                    if (
                        stripped.startswith("//")
                        or stripped.startswith("#")
                        or stripped.startswith("<!--")
                        or stripped.startswith("/*")
                    ):
                        continue
                    if "confirm(" in stripped:
                        pytest.fail(
                            f"{rel}:{i} uses window.confirm instead of BarkDialog.confirm: {stripped}"
                        )
        if "alert(" in text:
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                if "alert(" in line:
                    stripped = line.strip()
                    if stripped.startswith("//") or stripped.startswith("#"):
                        continue
                    # Allow known non-modal patterns (console.log-based alerts, etc.)
                    if "getAlert" not in stripped and "showAlert" not in stripped:
                        pytest.fail(f"{rel}:{i} uses alert() instead of BarkDialog: {stripped}")
        if "window.prompt" in text:
            pytest.fail(f"{rel} uses window.prompt instead of a modal dialog")


def test_destructive_operations_use_barkdialog_confirm():
    """Every destructive CRUD function must call BarkDialog.confirm first."""
    js = source(STATIC / "js" / "moderation-workspace.js")
    # Every delete/clear operation should gate on BarkDialog.confirm
    # Check all function signatures that have "delete" or "clear" in their name
    delete_fns = re.findall(r"(?:async\s+)?function\s+(delete\w+|clear\w+)\s*\(", js)
    for fn_name in delete_fns:
        # Find the function body and verify it calls BarkDialog.confirm
        idx = js.index(f"function {fn_name}(")
        # Look for async variant too
        fn_body = js[idx:]
        assert "BarkDialog.confirm" in fn_body[:2000], (
            f"Function {fn_name}() must call BarkDialog.confirm before destroying data"
        )
    # Also check the purgeData function
    assert "BarkDialog.confirm" in js, "moderation-workspace.js must use BarkDialog.confirm"

    workspace_js = source(STATIC / "js" / "module-workspace.js")
    assert "BarkDialog.confirm" in workspace_js, "module-workspace.js must use BarkDialog.confirm"

    shortcuts_js = source(STATIC / "js" / "shortcuts.js")
    assert "BarkDialog.confirm" in shortcuts_js, "shortcuts.js must use BarkDialog.confirm"

    # Check that every data-purge button has a corresponding confirm in JS
    all_html = "\n".join(source(p) for p in ALL_TEMPLATES)
    purge_buttons = re.findall(r'data-purge="([^"]+)"', all_html)
    assert purge_buttons, "At least one purge button should exist"
    # The purgeData function uses BarkDialog.confirm generically
    # Verify the confirm call references data-purge-label
    assert "data-purge-label" in js or "purgeLabel" in js


# ═══════════════════════════════════════════════════════
# ── Danger Zone Contextual Verification ───────────────
# ═══════════════════════════════════════════════════════


def test_danger_zones_are_tab_specific():
    """Danger zone purge buttons must only appear in their correct tab context."""
    workspace = source(TEMPLATES / "pages" / "module_detail.html")
    voice = source(ROOT / "modules" / "moderation" / "templates" / "moderation_voice.html")

    # Configure tab (module_detail.html) has audit and attachment purge
    assert 'data-purge="audit-logs"' in workspace, "Configure tab needs audit-logs purge"
    assert 'data-purge="attachments"' in workspace, "Configure tab needs attachments purge"

    # Voice tab has voice-history purge
    assert 'data-purge="voice-history"' in voice, "Voice tab needs voice-history purge"

    # Cross-contamination checks
    assert 'data-purge="audit-logs"' not in voice, "Voice tab must not have audit-logs purge"
    assert 'data-purge="attachments"' not in voice, "Voice tab must not have attachments purge"
    assert 'data-purge="voice-history"' not in workspace, (
        "Configure tab must not have voice-history purge"
    )
    assert 'data-purge-label="voice history"' not in workspace, (
        "Configure tab must not reference voice history"
    )

    # Both danger zones must have admin badges
    voice_has_admin = "Admin only" in voice or "admin-only" in voice or "can_manage_module" in voice
    assert voice_has_admin, "Voice danger zone should be admin-only"
    assert "danger-zone" in workspace or "retention-danger-zone" in workspace


def test_mobile_drawer_contract():
    """Mobile nav drawer: base.html exposes a hamburger + scrim + close
    control wired to the sidebar, and main.js implements slide/gesture
    open-close behaviour with proper inert/aria state."""
    base = source(TEMPLATES / "base.html")
    js = source(STATIC / "js" / "main.js")

    # Hamburger toggle: labelled, controls the sidebar, reflects state
    toggle = re.search(
        r"<button[^>]*data-toggle-sidebar[^>]*>", base, re.I | re.S
    )
    assert toggle, "base.html must have a data-toggle-sidebar button"
    tag = toggle.group(0)
    assert 'type="button"' in tag
    assert 'aria-controls="sidebar"' in tag
    assert 'aria-expanded="false"' in tag
    assert 'aria-label="Open navigation menu"' in tag

    # Scrim + close control exist and are wired the same way
    assert 'id="nav-scrim"' in base and 'data-close-sidebar' in base
    assert re.search(
        r'<button[^>]*class="sidebar-close"[^>]*>', base, re.I
    ), "sidebar needs a visible close button for the open drawer"
    assert 'data-close-sidebar' in base

    # JS: drawer init + gesture handlers + focus/inert management
    for key in (
        "initMobileDrawer",
        "matchMedia('(max-width: 768px)')",
        "touchstart",
        "touchend",
        "sidebar.classList.add('open')",
        "sidebar.setAttribute('inert'",
        "aria-expanded",
        "preventScroll",
    ):
        assert key in js, f"main.js missing drawer behaviour: {key}"


def test_pages_use_shared_container_primitives():
    """Every page (except the bespoke landing/marketing page and the invite
    utility) is built on the shared container primitives — page-container /
    page-header / content-card / state-panel / modules-grid / settings-grid — so
    no page drifts into a fully bespoke wrapper (tighter, uniform UI)."""
    allowed = (
        "page-container",
        "page-header",
        "content-card",
        "state-panel",
        "modules-grid",
        "settings-grid",
    )
    exempt = {"landing.html", "invite.html"}  # intentionally bespoke/utility
    for page in PAGES:
        if page.name in exempt:
            continue
        html = source(page)
        assert any(cls in html for cls in allowed), (
            f"{page.name} does not use any shared container primitive"
        )
