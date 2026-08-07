/* Speak module workspace — phrase editor for /bark speak.
 * Loads the guild's phrases, lets admins add/edit/remove rows, and saves
 * them via the module API. Self-contained: no external deps beyond the
 * shared escHtml helper from main.js.
 */
(function () {
  'use strict';

  const container = document.getElementById('speak-phrases-content');
  const actions = document.getElementById('speak-phrases-actions');
  const saveBtn = document.getElementById('speak-phrases-save');
  const statusEl = document.getElementById('speak-phrases-status');
  if (!container || !saveBtn) return;

  const guildId = (typeof currentGuildId === 'function' ? currentGuildId() : '') ||
    (document.querySelector('[data-guild-id]') || {}).dataset?.guildId || '';

  function phraseEndpoint() {
    return `/api/v1/guilds/${guildId}/modules/speak/phrases`;
  }

  function rowHtml(key, text) {
    const safeKey = escHtml(key || '');
    const safeText = escHtml(text || '');
    return `
      <div class="speak-row" data-speak-row>
        <input type="text" class="form-input speak-key" value="${safeKey}" placeholder="word1" aria-label="Phrase key" maxlength="64" spellcheck="false">
        <input type="text" class="form-input speak-text" value="${safeText}" placeholder="The text /bark speak word1 will output" aria-label="Phrase text" maxlength="1900">
        <button type="button" class="btn btn-sm speak-remove" aria-label="Remove phrase"><i data-lucide="trash-2" width="14" height="14"></i></button>
      </div>`;
  }

  function render(phrases) {
    const entries = Object.entries(phrases || {});
    if (!entries.length) {
      container.innerHTML =
        '<div class="state-panel state-empty" role="status"><div><strong>No phrases yet</strong>' +
        '<p>Click <em>Add Phrase</em> to create the first one, then tell members to run <code>/bark speak &lt;key&gt;</code>.</p></div></div>';
      actions.hidden = true;
      return;
    }
    container.innerHTML = entries.map(([k, v]) => rowHtml(k, v)).join('');
    actions.hidden = false;
    if (window.lucide) lucide.createIcons();
  }

  async function loadPhrases() {
    container.innerHTML = '<div class="skeleton skeleton-card"></div>';
    try {
      const result = await safeFetch(phraseEndpoint(), { cache: 'no-cache' });
      render(result?.data?.phrases || {});
    } catch (error) {
      container.innerHTML =
        `<div class="state-panel state-error" role="status"><div><strong>Could not load phrases</strong>` +
        `<p>${escHtml(error.message || 'Unknown error')}</p></div></div>`;
      actions.hidden = true;
    }
  }

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    statusEl.style.color = isError ? 'var(--red)' : 'var(--green)';
  }

  function collectRows() {
    const phrases = {};
    for (const row of container.querySelectorAll('[data-speak-row]')) {
      const key = (row.querySelector('.speak-key') || {}).value?.trim() || '';
      const text = (row.querySelector('.speak-text') || {}).value?.trim() || '';
      if (key) phrases[key] = text;
    }
    return phrases;
  }

  async function savePhrases() {
    saveBtn.disabled = true;
    setStatus('Saving…', false);
    try {
      const result = await safeFetch(phraseEndpoint(), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phrases: collectRows() }),
      });
      setStatus(`Saved ${result?.data?.saved ?? 0} phrase(s).`, false);
      await loadPhrases();
    } catch (error) {
      setStatus(error.message || 'Save failed', true);
    } finally {
      saveBtn.disabled = false;
    }
  }

  // ── Wire up ────────────────────────────────────────

  document.querySelector('[data-speak-add]')?.addEventListener('click', () => {
    if (container.querySelector('.state-panel')) container.innerHTML = '';
    container.insertAdjacentHTML('beforeend', rowHtml('', ''));
    actions.hidden = false;
    if (window.lucide) lucide.createIcons();
    const lastRow = container.lastElementChild;
    lastRow.querySelector('.speak-key')?.focus();
  });

  container.addEventListener('click', (event) => {
    const removeBtn = event.target.closest('[data-speak-row] .speak-remove');
    if (!removeBtn) return;
    const row = removeBtn.closest('[data-speak-row]');
    row.remove();
    if (!container.querySelector('[data-speak-row]')) {
      container.innerHTML =
        '<div class="state-panel state-empty" role="status"><div><strong>No phrases yet</strong>' +
        '<p>Click <em>Add Phrase</em> to create the first one.</p></div></div>';
      actions.hidden = true;
    }
  });

  saveBtn.addEventListener('click', savePhrases);
  document.querySelector('[data-refresh-section="phrases"]')?.addEventListener('click', loadPhrases);

  loadPhrases();
})();
