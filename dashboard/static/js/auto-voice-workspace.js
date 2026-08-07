/** Auto Voice workspace extras: live channel-name template preview + reference.
 *
 * Mirrors modules/auto_voice/module.py `_render_name` and `_apply_avc_transforms`
 * so the dashboard demo shows exactly what Bark will name a channel. Loaded only
 * on the auto_voice module detail page (see pages/module_detail.html).
 */
(() => {
  'use strict';

  const root = document.querySelector('.module-workspace');
  if (!root || root.dataset.moduleName !== 'auto_voice') return;

  // Grouped schema (module v0.4.0) prefixes field ids with the section name;
  // fall back to the legacy flat ids for older renders.
  const templateInput = document.getElementById('config-channel-channel_name_template')
    || document.getElementById('config-channel_name_template');
  const fallbackInput = document.getElementById('config-channel-fallback_name')
    || document.getElementById('config-fallback_name');
  if (!templateInput) return;

  // ── Renderer (mirrors the Python implementation) ──────────────

  const AVC_TRANSFORM = /""([^":]+):\s*(.*?)""/g;

  const OPERATIONS = {
    caps: (value) => value.toUpperCase(),
    upper: (value) => value.toUpperCase(),
    lower: (value) => value.toLowerCase(),
    title: (value) => value.replace(/\w\S*/g, (word) =>
      word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()),
    swap: (value) => value.split('').map((ch) =>
      ch === ch.toUpperCase() ? ch.toLowerCase() : ch.toUpperCase()).join(''),
    acro: (value) => value.split(/\s+/).filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase()).join(''),
    spaces: (value) => value.replace(/\s+/g, ''),
  };

  function applyAvcTransforms(template) {
    let previous;
    do {
      previous = template;
      template = template.replace(AVC_TRANSFORM, (match, modes, value) => {
        let out = value.trim();
        for (const rawMode of modes.split('+')) {
          const operation = OPERATIONS[rawMode.trim().toLowerCase()];
          if (operation) out = operation(out);
        }
        return out;
      });
    } while (template !== previous);
    return template;
  }

  function renderChannelName(template, fallback, caseFlags) {
    const game = (fallback && fallback.trim()) || 'General';
    const guildName = document.querySelector('.sidebar-guild-copy strong')?.textContent?.trim()
      || 'ZENHAWX';
    const replacements = {
      '##': '#2',
      '@@game_name@@': game,
      '{game}': game,
      '{display_name}': 'Alex',
      '{username}': 'alex',
      '{guild}': guildName,
    };
    let rendered = template || '## [@@game_name@@]';
    for (const [token, value] of Object.entries(replacements)) {
      rendered = rendered.split(token).join(value);
    }
    rendered = applyAvcTransforms(rendered);
    rendered = rendered.replace(/\s+/g, ' ').trim().slice(0, 100);
    if (caseFlags?.uppercase) rendered = rendered.toUpperCase();
    else if (caseFlags?.lowercase) rendered = rendered.toLowerCase();
    else if (caseFlags?.titlecase) rendered = rendered.replace(/\w\S*/g, (word) =>
      word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
    return rendered || 'Voice 02';
  }

  // ── Preview + reference UI ─────────────────────────────────────

  const preview = document.createElement('div');
  preview.className = 'template-preview';
  preview.setAttribute('aria-live', 'polite');
  preview.innerHTML =
    '<span class="template-preview-label">Preview</span>' +
    '<code class="template-preview-name" id="auto-voice-preview-name"></code>';

  const help = document.createElement('details');
  help.className = 'template-help';
  help.innerHTML =
    '<summary>Name template reference</summary>' +
    '<table>' +
    '<thead><tr><th>Token</th><th>Replaced with</th><th>Example</th></tr></thead>' +
    '<tbody>' +
    '<tr><td><code>##</code></td><td>Channel number</td><td><code>#2</code></td></tr>' +
    '<tr><td><code>@@game_name@@</code> or <code>{game}</code></td><td>Most-played game in the channel, or the fallback name when nobody is playing</td><td><code>Counter-Strike 2</code></td></tr>' +
    '<tr><td><code>{display_name}</code></td><td>Owner\'s display name</td><td><code>Alex</code></td></tr>' +
    '<tr><td><code>{username}</code></td><td>Owner\'s username</td><td><code>alex</code></td></tr>' +
    '<tr><td><code>{guild}</code></td><td>Server name</td><td><code>ZENHAWX</code></td></tr>' +
    '<tr><td><code>""caps: text""</code></td><td>AVC transform: UPPERCASE</td><td><code>RANKED</code></td></tr>' +
    '<tr><td><code>""title: text""</code></td><td>AVC transform: Title Case</td><td><code>Ranked</code></td></tr>' +
    '<tr><td><code>""acro: text""</code></td><td>AVC transform: initials</td><td><code>CS</code></td></tr>' +
    '<tr><td><code>""spaces: text""</code></td><td>AVC transform: remove spaces</td><td><code>""spaces: my room""</code> → <code>myroom</code></td></tr>' +
    '</tbody></table>' +
    '<p class="form-hint">Transforms combine with <code>+</code> (e.g. <code>""caps+acro: counter strike""</code> → <code>CS</code>). ' +
    'The channel is renamed live when the majority game changes.</p>';

  templateInput.closest('.form-group')?.after(preview, help);

  // ── Live preview update ────────────────────────────────────────

  const previewName = document.getElementById('auto-voice-preview-name');
  const caseInputs = [
    document.getElementById('config-naming-name_uppercase') || document.getElementById('config-name_uppercase'),
    document.getElementById('config-naming-name_lowercase') || document.getElementById('config-name_lowercase'),
    document.getElementById('config-naming-name_titlecase') || document.getElementById('config-name_titlecase'),
  ].filter(Boolean);

  const readCaseFlags = () => ({
    uppercase: caseInputs[0]?.checked ?? false,
    lowercase: caseInputs[1]?.checked ?? false,
    titlecase: caseInputs[2]?.checked ?? false,
  });

  const updatePreview = () => {
    if (!previewName) return;
    previewName.textContent = renderChannelName(
      templateInput.value,
      fallbackInput ? fallbackInput.value : '',
      readCaseFlags()
    );
  };

  templateInput.addEventListener('input', updatePreview);
  fallbackInput?.addEventListener('input', updatePreview);
  caseInputs.forEach((input) => input.addEventListener('change', updatePreview));
  updatePreview();
})();
