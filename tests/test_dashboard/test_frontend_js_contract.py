"""Build-free JavaScript integration contracts for Bark's dashboard.

These checks cover cross-file invariants that are easy to break without a JS build:
shared globals, API-derived markup safety, busy-state recovery, lifecycle cleanup,
and frontend/backend endpoint agreement.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "dashboard" / "static" / "js"
TEMPLATES = ROOT / "dashboard" / "templates"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_inline_template_scripts_have_no_interpolation_in_single_quoted_strings():
    """Inline <script> bodies must not use `${...}` inside single-quoted strings.

    Regression: members.html/member_detail.html empty-state markup used
    `${getIconSvg('users', 18)}` inside a single-quoted JS string, which broke
    the page with 'Unexpected identifier'. Single-quoted strings do not
    interpolate — the interpolation opener inside one is a literal quote that
    terminates the string early.

    Only the single-quote context is a syntax error: ``${...}`` inside backtick
    template literals (the normal case) and inside double-quoted strings
    (rendered literally but valid) are both fine. The scanner walks the script
    and remembers the last unescaped quote delimiter that opened the current
    string; a ``${`` seen while that delimiter is a single quote is a bug.
    """
    offenders = []
    for path in (TEMPLATES / "pages").glob("*.html"):
        html = source(path)
        for match in re.finditer(r"<script>(.*?)</script>", html, re.S):
            body = match.group(1)
            line = html[: match.start()].count("\n") + 1
            delimiter: str | None = None
            escaped = False
            for i, ch in enumerate(body):
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if delimiter:
                    if ch == delimiter:
                        delimiter = None
                    continue
                if ch in ("'", '"', "`"):
                    delimiter = ch
                    continue
                if ch == "$" and body[i + 1 : i + 2] == "{":
                    # Interpolation inside a single-quoted string is a parse
                    # error (the quote terminates the string early).
                    if delimiter == "'":
                        offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert offenders == [], (
        f"${'{...}'} interpolation inside a single-quoted JS string breaks the page: {offenders}"
    )


def test_module_toggle_releases_busy_state_after_success_or_failure():
    js = source(JS / "module-workspace.js")
    handler = js[
        js.index("root.querySelector('.module-toggle')") : js.index(
            "root.querySelector('.module-reload')"
        )
    ]
    assert "finally" in handler
    assert "event.target.disabled = false" in handler
    assert "event.target.removeAttribute('aria-busy')" in handler


def test_dynamic_form_and_module_names_do_not_build_raw_css_selectors():
    main = source(JS / "main.js")
    workspace = source(JS / "module-workspace.js")
    modules = source(TEMPLATES / "pages" / "modules.html")
    # No dynamic form/module name may be interpolated into a raw CSS selector;
    # the one dynamic selector in main.js escapes via CSS.escape.
    assert '`[name="${' not in main
    assert "CSS.escape(panelId)" in main
    assert "el.name === group.dataset.depends" in workspace
    assert "item.dataset.module === moduleName" in modules
    assert '`[name="${group.dataset.depends}"]`' not in workspace
    assert '`[data-module="${moduleName}"]`' not in modules


def test_palette_preserves_shared_helpers_and_sanitizes_manifest_markup():
    js = source(JS / "palette.js")
    assert "function escHtml(" not in js, (
        "palette.js must not override main.js's global escHtml helper"
    )
    assert "safeLocalUrl(item.url" in js
    assert "paletteEscapeHtml(item.desc)" in js
    render = js[
        js.index("function renderPaletteResults(") : js.index("function rerenderPaletteIcons(")
    ]
    assert "highlightPaletteItem(container.querySelectorAll('.palette-item'));" in render
    assert "rerenderPaletteIcons();" in render


def test_main_sanitizes_manifest_routes_module_attributes_and_icons():
    js = source(JS / "main.js")
    assert "function safeLocalUrl(" in js
    assert "function safeResourceUrl(" in js
    assert "function safeClassToken(" in js
    assert "const pageRoute = safeLocalUrl(page.route" in js
    assert "escHtml(page.module)" in js
    icon_body = js[js.index("function getIconSvg(") :]
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


def test_auto_voice_workspace_registers_live_template_preview():
    """Auto Voice's name-template demo must be wired into the module page and
    mirror the backend token/transform rendering."""
    detail = source(TEMPLATES / "pages" / "module_detail.html")
    av = source(JS / "auto-voice-workspace.js")

    assert "auto-voice-workspace.js" in detail
    assert "config-channel_name_template" in av
    assert "config-fallback_name" in av
    assert "template-preview" in av
    assert "@@game_name@@" in av
    assert "applyAvcTransforms" in av
    assert "aria-live" in av
    # Case-transform checkboxes wired into the live preview.
    assert "config-name_uppercase" in av
    assert "config-name_lowercase" in av
    assert "config-name_titlecase" in av
    assert "readCaseFlags" in av
    assert "rendered.toUpperCase()" in av
    assert "rendered.toLowerCase()" in av


def test_announcements_workspace_registers_live_discord_preview():
    """Announcements' post action must have a live Discord preview wired into
    the module page that mirrors the backend's embed/text rendering decisions."""
    detail = source(TEMPLATES / "pages" / "module_detail.html")
    ann = source(JS / "announcements-workspace.js")
    workspace = source(JS / "module-workspace.js")

    assert "announcements-workspace.js" in detail
    assert "moduleName !== 'announcements'" in ann
    assert "action-post_announcement" in ann
    assert "announcement-preview" in ann
    assert "discord-preview" in ann
    # Live wiring: message/title typing, embed toggle, and media picker changes.
    assert "action-post_announcement-title" in ann
    assert "action-post_announcement-message" in ann
    assert "action-post_announcement-as_embed" in ann
    assert "bark:media-changed" in ann
    assert "aria-live" in ann
    # The media picker must notify the preview when chips are added/removed.
    assert "CustomEvent('bark:media-changed'" in workspace
    # Backend-mirrored rendering decisions.
    assert "message.slice(0, 2000)" in ann
    assert "message.slice(0, 4096)" in ann
    assert "Watch Video" in ann
    assert "renderMarkdown" in ann
    assert "discord-spoiler" in ann


def test_discord_markdown_renderer_covers_discord_tokens():
    """The announcements preview's markdown renderer must escape HTML before
    formatting and cover Discord's core inline/block tokens."""
    ann = source(JS / "announcements-workspace.js")
    start = ann.index("function esc(")
    end = ann.index("// ── Preview UI", start)
    renderer = ann[start:end]

    script = f"""
{renderer}
const cases = [
  ['**bold** and *it*', '<strong>bold</strong> and <em>it</em>'],
  ['__under__ ~~strike~~', '<u>under</u> <s>strike</s>'],
  ['||spoil||', '<span class="discord-spoiler">spoil</span>'],
  ['`code`', '<code class="discord-code">code</code>'],
  ['```js\\nconst x = 1;\\n```', '<pre class="discord-codeblock">js\\nconst x = 1;\\n</pre>'],
  ['# Head', '<h2 class="discord-h2">Head</h2>'],
  ['- item', '<span class="discord-li">• item</span>'],
  ['> quote', '<blockquote class="discord-quote">quote</blockquote>'],
  ['[link](https://x.dev)', '<a class="discord-link" href="https://x.dev" target="_blank" rel="noopener noreferrer">link</a>'],
  ['<script>alert(1)</script>', '&lt;script&gt;alert(1)&lt;/script&gt;'],
];
for (const [input, expected] of cases) {{
  const out = renderMarkdown(input, false);
  if (!out.includes(expected)) throw new Error(`missing ${{expected}} in ${{out}}`);
}}
const embedOut = renderMarkdown('# Head\\n- item', true);
if (embedOut.includes('discord-h2') || embedOut.includes('discord-li')) {{
  throw new Error('embeds must not render block-level tokens');
}}
console.log('OK');
"""
    subprocess.run(
        ["node", "-e", script],
        check=True,
        env={**os.environ, "TZ": "America/New_York"},
        capture_output=True,
        text=True,
    )


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


def test_guild_activity_refreshes_from_server_and_ages_visible_timestamps():
    guild = source(TEMPLATES / "pages" / "guild.html")

    assert "const GUILD_DATA_REFRESH_MS = 5 * 60 * 1000" in guild
    assert "setInterval(loadGuildOverview, GUILD_DATA_REFRESH_MS)" in guild
    assert "data-activity-timestamp" in guild
    assert "setInterval(refreshActivityTimes, ACTIVITY_TIME_REFRESH_MS)" in guild
    assert "if (event.persisted) startGuildOverviewRefresh()" in guild
    assert 'data-activity-timestamp="${escHtml(a.timestamp).replaceAll(' in guild
    # The inline script must not depend on functions added to main.js recently:
    # browsers cache main.js by version query, so a stale cached copy would
    # throw ReferenceError and render "Activity unavailable".
    assert "escAttr(" not in guild


def test_time_ago_uses_explicit_utc_and_handles_invalid_or_future_values():
    main = source(JS / "main.js")
    match = re.search(r"function timeAgo\(iso\) \{.*?^\}", main, re.MULTILINE | re.DOTALL)
    assert match is not None

    script = f"""
{match.group(0)}
Date.now = () => Date.parse('2026-08-03T23:00:00+00:00');
const actual = [
  timeAgo('2026-08-03T20:00:00+00:00'),
  timeAgo('not-a-date'),
  timeAgo('2026-08-04T00:00:00+00:00'),
];
const expected = ['3h ago', '', 'just now'];
if (JSON.stringify(actual) !== JSON.stringify(expected)) {{
  throw new Error(JSON.stringify({{actual, expected}}));
}}
"""
    subprocess.run(
        ["node", "-e", script],
        check=True,
        env={**os.environ, "TZ": "America/New_York"},
        capture_output=True,
        text=True,
    )


def test_activity_feed_paginates_with_fade_and_load_more():
    guild = source(TEMPLATES / "pages" / "guild.html")

    assert "const ACTIVITY_PAGE_SIZE = 10" in guild
    assert "activityItems.slice(0, (activityPage + 1) * ACTIVITY_PAGE_SIZE)" in guild
    assert "activityPage += 1" in guild
    assert "renderActivityPage" in guild
    assert 'id="activity-load-more"' in guild
    assert 'id="activity-more-wrap"' in guild
    # The bottom fade is a CSS mask toggled only while more pages exist.
    assert "classList.toggle('is-masked', hasMore)" in guild
    # Pagination must stay self-contained: no helpers from main.js that a stale
    # cached copy could lack.
    assert "escAttr(" not in guild


def test_discord_toolbar_covers_discord_markdown_and_images():
    include = source(TEMPLATES / "components" / "discord_toolbar.html")
    primitives = source(TEMPLATES / "components" / "primitives.html")
    detail = source(TEMPLATES / "pages" / "module_detail.html")

    for token in (
        'data-insert="**"',
        'data-insert="*"',
        'data-insert="__"',
        'data-insert="~~"',
        'data-insert="||"',
        'data-insert="`"',
        'data-insert="```"',
        'data-insert="> "',
        'data-insert="# "',
        'data-insert="- "',
        'data-insert="1. "',
        'data-action="link"',
    ):
        assert token in include

    # Both renderers reuse the shared include instead of duplicating the toolbar.
    assert '{% include "components/discord_toolbar.html" %}' in primitives
    assert '{% include "components/discord_toolbar.html" %}' in detail
    # Image/upload moved out of the markdown toolbar into the dedicated media picker.
    assert 'data-action="image-upload"' not in include
    assert 'data-action="image-url"' not in include
    assert 'data-action="image-upload"' not in primitives
    assert 'data-action="image-upload"' not in detail


def test_module_workspace_media_picker_handles_uploads_and_library():
    workspace = source(JS / "module-workspace.js")
    detail = source(TEMPLATES / "pages" / "module_detail.html")

    assert "WRAP_TOKENS" in workspace
    assert "LINE_PREFIX_TOKENS" in workspace
    assert "prefixLines" in workspace
    assert "replaceSelection" in workspace
    assert 'button[data-action="link"]' in workspace
    assert 'data-action="image-upload"' not in workspace
    assert 'data-action="image-url"' not in workspace
    # Media picker wiring: upload + library picker, chips, hidden payload.
    assert "media-picker" in workspace
    assert "media-picker" in detail
    assert 'data-media-action="image-upload"' in detail
    assert 'data-media-action="image-library"' in detail
    assert 'data-media-action="image-url"' not in detail
    assert 'data-media-action="video-url"' not in detail
    assert "guildId}/uploads" in workspace
    assert "FormData" in workspace
    assert "BarkDialog.pick" in workspace
    assert 'data-schema-type="array"' in detail


def test_avatar_upload_targets_visible_label_and_has_one_persistent_error_listener():
    html = source(TEMPLATES / "pages" / "settings.html")
    assert "document.querySelector('label[for=\"avatar-upload\"]')" in html
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
    standalone_routes = "\n".join(
        source(path) for path in (ROOT / "dashboard" / "routes" / "api").glob("*.py")
    )

    for route in (
        "/guilds/{guild_id}/rulesets",
        "/guilds/{guild_id}/rulesets/{ruleset_id}",
        "/guilds/{guild_id}/rulesets/{ruleset_id}/rules",
        "/guilds/{guild_id}/wordlists",
        "/guilds/{guild_id}/wordlists/{list_id}",
    ):
        assert route in module_routes
    for route in (
        "/guilds/{guild_id}/moderation/cases",
        "/guilds/{guild_id}/moderation/warnings",
        "/guilds/{guild_id}/moderation/voice-history",
        "/guilds/{guild_id}/notes",
        "/guilds/{guild_id}/events",
    ):
        assert route in standalone_routes
    assert "moderation/cases?" in moderation_js
    assert "api('rulesets')" in moderation_js
    assert "api('wordlists')" in moderation_js
