/** Module workspace behavior. See docs/module-workspace.md. */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace');
  if (!root) return;
  const guildId = root.dataset.guildId;
  const moduleName = root.dataset.moduleName;

  // Only http(s) media URLs may be embedded. This also blocks javascript: /
  // data:text/html schemes that would execute when injected into an <img src>
  // (or a markdown embed rendered elsewhere) — the media picker accepts
  // arbitrary user/plugin strings, so the scheme is validated here, not
  // trusted from the client.
  const isSafeMediaUrl = (value) => {
    try {
      const parsed = new URL(String(value || ''), window.location.origin);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  };
  const configForm = root.querySelector('.module-config-form');
  const saveButton = document.getElementById('save-config-btn');
  const discardButton = document.getElementById('discard-config-btn');
  const snapshotForm = () => configForm ? [...configForm.elements]
    .filter(field => field.name)
    .map(field => ({field, value: field.value, checked: field.checked})) : [];
  let baseline = snapshotForm();

  const setDirty = (dirty) => {
    if (!configForm) return;
    configForm.dataset.dirty = String(dirty);
    if (saveButton) saveButton.disabled = !dirty;
    if (discardButton) discardButton.disabled = !dirty;
  };
  configForm?.addEventListener('input', () => setDirty(true));
  configForm?.addEventListener('change', () => setDirty(true));
  configForm?.addEventListener('api-select:loaded', () => {
    if (configForm.dataset.dirty !== 'true') baseline = snapshotForm();
  });
  discardButton?.addEventListener('click', () => {
    baseline.forEach(({field, value, checked}) => {
      field.value = value;
      if (field.type === 'checkbox' || field.type === 'radio') field.checked = checked;
    });
    setDirty(false);
  });

  configForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!configForm.reportValidity()) return;
    const idleHtml = saveButton.innerHTML;
    saveButton.disabled = true;
    saveButton.setAttribute('aria-busy', 'true');
    saveButton.textContent = 'Saving…';
    try {
      const config = BarkForms.serializeFields(configForm.querySelectorAll('[name]'));
      const response = await safeFetch(`/api/v1/guilds/${guildId}/modules/${moduleName}`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({config})
      });
      if (response.success === false) throw new Error(response.details?.join('; ') || response.error || 'Save failed');
      baseline = snapshotForm();
      setDirty(false);
      showToast('Configuration saved', 'success');
    } catch (error) {
      showToast(error.message || 'Unable to save configuration', 'error');
      saveButton.disabled = false;
    } finally { saveButton.removeAttribute('aria-busy'); saveButton.innerHTML = idleHtml; }
  });

  root.querySelector('.module-toggle')?.addEventListener('change', async (event) => {
    const enabled = event.target.checked;
    event.target.disabled = true;
    try {
      await safeFetch(`/api/v1/guilds/${guildId}/modules/${moduleName}/toggle`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled})
      });
      const badge = document.getElementById('module-status-badge');
      if (badge) badge.innerHTML = `<span class="status-badge status-${enabled ? 'success' : 'neutral'}"><span class="status-indicator" aria-hidden="true"></span>${enabled ? 'Enabled' : 'Disabled'}</span>`;
      const sidebarNav = document.getElementById('sidebar-nav-items');
      if (sidebarNav && typeof loadSidebarManifest === 'function') {
        try { sessionStorage.removeItem(`bark_manifest_cache_${guildId}`); } catch {}
        loadSidebarManifest(sidebarNav);
      }
      showToast(`${moduleName} ${enabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (error) {
      event.target.checked = !enabled;
      showToast(error.message, 'error');
    } finally {
      event.target.disabled = false;
      event.target.removeAttribute('aria-busy');
    }
  });

  root.querySelector('.module-reload')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      await safeFetch(`/api/v1/guilds/${guildId}/modules/${moduleName}/reload`, {method: 'POST'});
      showToast('Module reloaded', 'success');
    } catch (error) { showToast(error.message, 'error'); }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); }
  });

  root.querySelectorAll('[data-depends]').forEach((group) => {
    const controller = [...root.querySelectorAll('[name]')]
      .find((el) => el.name === group.dataset.depends);
    if (!controller) return;
    const update = () => {
      const current = controller.type === 'checkbox' ? String(controller.checked) : controller.value;
      group.hidden = current !== group.dataset.dependsValue;
      group.querySelectorAll('input,select,textarea').forEach((field) => field.disabled = group.hidden);
    };
    controller.addEventListener('change', update); update();
  });

  root.querySelectorAll('.module-action-form').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (form.dataset.destructive === 'true') {
        const confirmed = await BarkDialog.confirm({
          title: form.dataset.label,
          message: `This operation changes stored server data. Review the values above before continuing.`,
          confirmLabel: form.dataset.label,
          danger: true
        });
        if (!confirmed) return;
      }
      const button = form.querySelector('.action-submit-btn');
      const result = form.parentElement.querySelector('.action-result');
      const idleText = button.innerHTML;
      button.disabled = true; button.setAttribute('aria-busy', 'true'); button.innerHTML = 'Processing…'; result.hidden = true;
      try {
        const payload = BarkForms.serializeFields(form.querySelectorAll('[name]:not(:disabled)'));
        const response = await safeFetch(`/api/v1/guilds/${guildId}/modules/${moduleName}/${form.dataset.endpoint}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
        });
        if (response.success === false) throw new Error(response.error || 'Operation failed');
        result.className = 'action-result success';
        const table = response.data?.table;
        if (table && Array.isArray(table.columns) && Array.isArray(table.rows)) {
          result.innerHTML = buildDataTable(table);
        } else {
          result.textContent = response.message || response.data?.message || `${form.dataset.label} completed`;
        }
        result.hidden = false;
        showToast(response.message || response.data?.message || `${form.dataset.label} completed`, 'success');
        window.dispatchEvent(new CustomEvent('bark:module-action-complete', {detail: {moduleName, endpoint: form.dataset.endpoint}}));
      } catch (error) {
        result.className = 'action-result error'; result.textContent = error.message; result.hidden = false;
        showToast(error.message || 'Operation failed', 'error');
      } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = idleText; }
    });
  });

  window.addEventListener('beforeunload', (event) => {
    if (configForm?.dataset.dirty === 'true') { event.preventDefault(); event.returnValue = ''; }
  });
  document.addEventListener('click', (event) => {
    if (roleMenu?.open && !roleMenu.contains(event.target)) roleMenu.open = false;
  });

  // Export moderation cases + warnings as a downloadable JSON archive.
  root.querySelector('[data-export-moderation]')?.addEventListener('click', () => {
    const url = `/api/v1/guilds/${guildId}/modules/${moduleName}/export`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `moderation-${guildId}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  });

  function escapeCell(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function buildDataTable(table) {
    const head = table.columns.map((c) => `<th scope="col">${escapeCell(c)}</th>`).join('');
    const body = table.rows.map((row) =>
      `<tr>${row.map((cell) => `<td>${escapeCell(cell)}</td>`).join('')}</tr>`
    ).join('');
    return `<div class="table-scroll"><table class="data-table"><caption class="sr-only">${escapeCell(table.title || 'Result')}</caption><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  // Actions marked data-auto-run="true" (e.g. the trivia leaderboard) run
  // immediately so their result displays without a click.
  root.querySelectorAll('.module-action-form[data-auto-run="true"]').forEach((form) => {
    form.requestSubmit();
  });

  root.querySelectorAll('.discord-toolbar').forEach((toolbar) => {
    const targetId = toolbar.dataset.for;
    const target = document.getElementById(targetId);
    if (!target) return;

    const WRAP_TOKENS = new Set(['**', '*', '__', '~~', '||', '`']);
    const LINE_PREFIX_TOKENS = new Set(['> ', '# ', '- ', '1. ']);

    const replaceSelection = (insertion, caretOffset = 0) => {
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      target.value = target.value.slice(0, start) + insertion + target.value.slice(end);
      const newPos = Math.min(start + caretOffset, target.value.length);
      target.setSelectionRange(newPos, newPos);
      target.focus();
      target.dispatchEvent(new Event('input', {bubbles: true}));
    };

    const prefixLines = (text, prefix) =>
      text.split('\n').map((line) => prefix + line).join('\n');

    const insertToken = (raw) => {
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      const selected = target.value.slice(start, end);

      if (WRAP_TOKENS.has(raw) && selected.length) {
        const wrapped = raw + selected + raw;
        replaceSelection(wrapped, wrapped.length);
      } else if (raw === '```') {
        const block = '```\n' + (selected || 'code') + '\n```';
        replaceSelection(block, block.length);
      } else if (LINE_PREFIX_TOKENS.has(raw)) {
        const prefixed = selected.length ? prefixLines(selected, raw) : raw;
        replaceSelection(prefixed, prefixed.length);
      } else {
        replaceSelection(raw, raw.length);
      }
    };

    const askText = async (title, defaultValue = '') => {
      if (typeof BarkDialog?.prompt !== 'function') return null;
      return BarkDialog.prompt({title, defaultValue, confirmLabel: 'OK'});
    };

    const insertLink = async () => {
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      const label = target.value.slice(start, end) || 'link text';
      const url = await askText('Link URL', 'https://');
      if (!url) return;
      const markdown = `[${label}](${url})`;
      replaceSelection(markdown, markdown.length);
    };

    // Activate on mousedown (keeps the textarea focused + selection intact for
    // mouse users) AND on Enter/Space (keyboard a11y). Only keydown/mousedown
    // are bound — no click, so the two paths never double-fire.
    const bindToolbar = (el, action) => {
      el.addEventListener('mousedown', (event) => {
        event.preventDefault();
        action();
      });
      el.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          action();
        }
      });
    };

    Array.from(toolbar.querySelectorAll('button[data-insert]')).forEach((btn) => {
      bindToolbar(btn, () => insertToken(btn.dataset.insert));
    });
    const linkBtn = toolbar.querySelector('button[data-action="link"]');
    if (linkBtn) bindToolbar(linkBtn, insertLink);
  });

  // ── Media picker (action fields) ─────────────────────────
  root.querySelectorAll('.media-picker').forEach((picker) => {
    const hidden = picker.querySelector('input[type="hidden"]');
    const itemsEl = picker.querySelector('.media-picker-items');
    const fieldId = picker.dataset.fieldId;
    let media = [];
    try { media = JSON.parse(hidden.value || '[]'); } catch { media = []; }

    const render = () => {
      itemsEl.innerHTML = '';
      media.forEach((item, index) => {
        const chip = document.createElement('span');
        chip.className = 'media-chip';
        chip.dataset.index = String(index);
        if (item.type === 'image' && isSafeMediaUrl(item.url)) {
          const img = document.createElement('img');
          img.src = item.url;
          img.alt = '';
          img.loading = 'lazy';
          chip.appendChild(img);
        } else {
          chip.innerHTML = `<span class="media-chip-icon">${item.type === 'video' ? '▶' : '🖼'}</span>`;
        }
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'media-chip-remove';
        removeBtn.setAttribute('aria-label', `Remove ${item.type}`);
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => {
          media.splice(index, 1);
          hidden.value = JSON.stringify(media);
          render();
          picker.dispatchEvent(new CustomEvent('bark:media-changed', {bubbles: true}));
        });
        chip.appendChild(removeBtn);
        itemsEl.appendChild(chip);
      });
      if (media.length) itemsEl.hidden = false; else itemsEl.hidden = true;
    };

    const addMedia = (type, url) => {
      if (!url) return;
      if (type === 'image' && !isSafeMediaUrl(url)) return;
      media = media.filter((m) => m.type !== type); // keep one image + one video
      media.push({type, url});
      hidden.value = JSON.stringify(media);
      render();
      picker.dispatchEvent(new CustomEvent('bark:media-changed', {bubbles: true}));
    };

    const uploadImage = () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/png,image/jpeg,image/gif,image/webp';
      input.addEventListener('change', async () => {
        const file = input.files?.[0];
        if (!file) return;
        try {
          const formData = new FormData();
          formData.append('file', file);
          const response = await safeFetch(`/api/v1/guilds/${guildId}/uploads`, {
            method: 'POST',
            body: formData,
          });
          if (!response?.data?.url) throw new Error(response?.error || 'Upload failed');
          addMedia('image', response.data.url);
        } catch (error) {
          showToast(error.message || 'Image upload failed', 'error');
        }
      });
      input.click();
    };

    picker.querySelector('[data-media-action="image-upload"]')?.addEventListener('click', uploadImage);
    picker.querySelector('[data-media-action="image-library"]')?.addEventListener('click', async () => {
      try {
        const response = await safeFetch(`/api/v1/guilds/${guildId}/uploads`, {cache: 'no-cache'});
        const items = response?.data?.items || [];
        if (!items.length) {
          showToast('No previously uploaded images — upload one first', 'info');
          return;
        }
        const picked = await BarkDialog.pick({
          title: 'Previously uploaded images',
          items: items.map((it) => ({url: it.url, label: it.name})),
          onDelete: async (item) => {
            const name = item.label;
            if (!name) throw new Error('Missing filename');
            const del = await safeFetch(`/api/v1/guilds/${guildId}/uploads/${encodeURIComponent(name)}`, {method: 'DELETE'});
            if (del?.success === false) throw new Error(del.error || 'Delete failed');
            showToast('Upload deleted', 'success');
          },
        });
        if (picked) addMedia('image', picked.url);
      } catch (error) {
        showToast(error.message || 'Library load failed', 'error');
      }
    });

    render();
  });
})();
