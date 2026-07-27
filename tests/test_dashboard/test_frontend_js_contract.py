"""Build-free JavaScript integration contracts for Bark's dashboard.

These checks cover cross-file invariants that are easy to break without a JS build:
shared globals, API-derived markup safety, busy-state recovery, lifecycle cleanup,
and frontend/backend endpoint agreement.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "dashboard" / "static" / "js"
TEMPLATES = ROOT / "dashboard" / "templates"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_module_toggle_releases_busy_state_after_success_or_failure():
    js = source(JS / "module-workspace.js")
    handler = js[js.index("root.querySelector('.module-toggle')"):js.index("root.querySelector('.module-reload')")]
    assert "finally" in handler
    assert "event.target.disabled = false" in handler
    assert "event.target.removeAttribute('aria-busy')" in handler


def test_dynamic_form_and_module_names_do_not_build_raw_css_selectors():
    main = source(JS / "main.js")
    workspace = source(JS / "module-workspace.js")
    modules = source(TEMPLATES / "pages" / "modules.html")
    assert "form.elements.namedItem(name)" in main
    assert "el.name === group.dataset.depends" in workspace
    assert "item.dataset.module === moduleName" in modules
    assert '`[name="${group.dataset.depends}"]`' not in workspace
    assert '`[data-module="${moduleName}"]`' not in modules


def test_palette_preserves_shared_helpers_and_sanitizes_manifest_markup():
    js = source(JS / "palette.js")
    assert "function escHtml(" not in js, "palette.js must not override main.js's global escHtml helper"
    assert "safeLocalUrl(item.url" in js
    assert "paletteEscapeHtml(item.desc)" in js
    render = js[js.index("function renderPaletteResults("):js.index("function rerenderPaletteIcons(")]
    assert "highlightPaletteItem(container.querySelectorAll('.palette-item'));" in render
    assert "rerenderPaletteIcons();" in render


def test_main_sanitizes_manifest_routes_module_attributes_and_icons():
    js = source(JS / "main.js")
    assert "function safeLocalUrl(" in js
    assert "function safeResourceUrl(" in js
    assert "function safeClassToken(" in js
    assert "const pageRoute = safeLocalUrl(page.route" in js
    assert "escHtml(page.module)" in js
    icon_body = js[js.index("function getIconSvg("):]
    assert "safeClassToken(name" in icon_body


def test_moderation_busy_helper_refreshes_dynamic_idle_markup():
    text = source(JS / "moderation-workspace.js")
    assert "button.dataset.idleHtml = button.innerHTML" in text
    assert "button.dataset.idleHtml ||= button.innerHTML" not in text
    assert "delete button.dataset.idleHtml" in text


def test_preset_creation_rolls_back_partial_rulesets_on_async_failure():
    text = source(JS / "moderation-workspace.js")
    assert "let createdRulesetId = null" in text
    assert "rulesets/${createdRulesetId}`), {method: 'DELETE'}" in text
    assert "Preset cleanup failed" in text


def test_realtime_connection_has_bfcache_lifecycle_cleanup():
    js = source(JS / "realtime.js")
    assert 'window.addEventListener("pagehide"' in js
    assert 'window.addEventListener("pageshow"' in js
    assert "clearInterval(pathWatchTimer)" in js


def test_inline_api_renderers_escape_dynamic_attributes_and_refresh_icons():
    guild = source(TEMPLATES / "pages" / "guild.html")
    members = source(TEMPLATES / "pages" / "members.html")
    detail = source(TEMPLATES / "pages" / "member_detail.html")

    assert "safeClassToken(a.type" in guild
    assert "escHtml(a.icon || '📝')" in guild
    assert "safeResourceUrl(m.avatar_url" in members
    assert "safeResourceUrl(m.avatar_url" in detail
    assert "safeClassToken(c.action_type" in detail
    assert "lucide.createIcons()" in detail
    assert "function formatDuration(" not in detail
    assert "function iconSvg(" not in detail


def test_avatar_upload_targets_visible_label_and_has_one_persistent_error_listener():
    html = source(TEMPLATES / "pages" / "settings.html")
    assert 'document.querySelector(\'label[for="avatar-upload"]\')' in html
    load_start = html.index("async function loadBotAppearance()")
    load_end = html.index("// Avatar upload", load_start)
    assert "addEventListener('error'" not in html[load_start:load_end]
    assert re.search(r"avatarPreview\?\.addEventListener\('error'", html)
    banner_start = html.index("bannerUpload?.addEventListener('change'")
    banner_end = html.index("// Presence form", banner_start)
    banner_handler = html[banner_start:banner_end]
    assert "bannerUpload.disabled = true" in banner_handler
    assert "bannerUpload.disabled = false" in banner_handler


def test_member_action_payload_matches_backend_minutes_and_supported_ban_fields():
    html = source(TEMPLATES / "pages" / "member_detail.html")
    assert "const durationMultipliers = {minutes: 1, hours: 60}" in html
    assert "body.duration = Math.max(1, duration * durationMultipliers[unit])" in html
    assert '<option value="seconds">' not in html
    assert "ban-delete-days" not in html
    assert "body.delete_days" not in html


def test_frontend_api_paths_have_matching_backend_routes():
    moderation_js = source(JS / "moderation-workspace.js")
    module_routes = source(ROOT / "modules" / "moderation" / "module.py")
    standalone_routes = "\n".join(source(path) for path in (ROOT / "dashboard" / "routes" / "api").glob("*.py"))

    for route in (
        '/guilds/{guild_id}/rulesets',
        '/guilds/{guild_id}/rulesets/{ruleset_id}',
        '/guilds/{guild_id}/rulesets/{ruleset_id}/rules',
        '/guilds/{guild_id}/wordlists',
        '/guilds/{guild_id}/wordlists/{list_id}',
    ):
        assert route in module_routes
    for route in (
        '/guilds/{guild_id}/moderation/cases',
        '/guilds/{guild_id}/moderation/warnings',
        '/guilds/{guild_id}/moderation/voice-history',
        '/guilds/{guild_id}/notes',
        '/guilds/{guild_id}/events',
    ):
        assert route in standalone_routes
    assert "moderation/cases?" in moderation_js
    assert "api('rulesets')" in moderation_js
    assert "api('wordlists')" in moderation_js
