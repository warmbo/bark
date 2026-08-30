/** Announcements workspace extras: live Discord preview for the post action.
 *
 * Mirrors modules/announcements/module.py `post_announcement` rendering so the
 * Operate tab shows exactly what Bark will post: plain-text mode vs embed mode,
 * the title/description, embed accent color, media image, the appended
 * "[Watch Video]" link, and the 2000/4096 character caps. The composer stays a
 * standard operation-grid action card; the live preview renders in a canonical
 * workspace-data-card below the grid (same pattern as moderation's activity
 * card). Loaded only on the announcements module detail page.
 */
(() => {
  'use strict';

  const root = document.querySelector('.module-workspace');
  if (!root || root.dataset.moduleName !== 'announcements') return;

  const card = document.getElementById('action-post_announcement');
  if (!card) return;

  const titleInput = document.getElementById('action-post_announcement-title');
  const messageInput = document.getElementById('action-post_announcement-message');
  const embedCheck = document.getElementById('action-post_announcement-as_embed');
  const colorInput = document.getElementById('action-post_announcement-embed_color');
  const colorHex = document.getElementById('action-post_announcement-embed_color-hex');
  const picker = card.querySelector('.media-picker');
  const mediaHidden = picker ? picker.querySelector('input[type="hidden"]') : null;

  // ── Discord markdown renderer (safe; mirrors the client) ──────────────

  function esc(t) {
    return String(t ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** Render Discord message markdown (full client support) or embed-description
   * markdown (embeds drop block-level formatting). Source is escaped first, so
   * token matches cannot inject HTML. */
  function renderMarkdown(source, embedMode) {
    const text = esc(source);

    // Discord custom emoji: <:name:id> (static) and <a:name:id> (animated) →
    // CDN <img>. The source is escaped first, so these tokens appear as
    // &lt;…&gt; and can never inject HTML; we emit only an id-derived CDN img
    // with the emoji name as alt/title.
    let out = text.replace(
      /&lt;(a?):([A-Za-z0-9_]+):(\d+)&gt;/g,
      (_, animated, name, id) =>
        `<img class="discord-emoji" src="https://cdn.discordapp.com/emojis/${id}.${animated ? 'gif' : 'png'}?size=48&amp;quality=lossless" alt=":${name}:" title="${name}" loading="lazy">`
    );

    // Protect code blocks from inline token processing.
    const blocks = [];
    out = out.replace(/```([\s\S]*?)```/g, (_, code) => {
      blocks.push(`<pre class="discord-codeblock">${code}</pre>`);
      return `\u0000CB${blocks.length - 1}\u0000`;
    });

    // Inline code.
    out = out.replace(/`([^`\n]+)`/g, '<code class="discord-code">$1</code>');

    // Links.
    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a class="discord-link" href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // Bold / italic / bold-italic.
    out = out.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    out = out.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');

    // Underline / strikethrough / spoiler.
    out = out.replace(/__([^_]+)__/g, '<u>$1</u>');
    out = out.replace(/~~([^~]+)~~/g, '<s>$1</s>');
    out = out.replace(/\|\|([^|]+)\|\|/g, '<span class="discord-spoiler">$1</span>');

    // Block-level formatting. Discord's client parses embed descriptions with
    // the same markdown engine as message content, so headings, subtext,
    // blockquotes, and lists render inside embeds too — no embedMode gate.
    out = out.replace(/^### (.+)$/gm, '<h4 class="discord-h4">$1</h4>');
    out = out.replace(/^## (.+)$/gm, '<h3 class="discord-h3">$1</h3>');
    out = out.replace(/^# (.+)$/gm, '<h2 class="discord-h2">$1</h2>');
    out = out.replace(/^&gt; (.+)$/gm, '<blockquote class="discord-quote">$1</blockquote>');
    out = out.replace(/^- (.+)$/gm, '<span class="discord-li">• $1</span>');
    out = out.replace(/^\d+\. (.+)$/gm, '<span class="discord-li">$&</span>');
    // Subtext (Discord extension): `-# line` renders smaller and greyed out.
    out = out.replace(/^-# (.+)$/gm, '<span class="discord-subtext">$1</span>');

    // Line breaks before restoring code blocks so fenced content keeps its
    // real newlines (white-space: pre in the preview).
    out = out.replace(/\n/g, '<br>');

    // Restore protected code blocks.
    blocks.forEach((block, i) => {
      out = out.split(`\u0000CB${i}\u0000`).join(block);
    });

    return out;
  }

  // ── Canonical preview card: composer stays a normal operation-grid card,
  //    the live Discord preview is a standard workspace-data-card below the
  //    grid (same pattern as moderation's "Recent Activity"). (remake 2026-08-19)

  const previewCard = document.createElement('article');
  previewCard.className = 'content-card workspace-data-card announcement-preview-card';
  previewCard.innerHTML =
    '<div class="card-header"><div><h2 class="card-title">' + (typeof getIconSvg === 'function' ? getIconSvg('eye', 16) : '') + ' Live Preview</h2>' +
    '<p class="card-description">Exactly what Bark will post, updating as you type.</p></div></div>' +
    '<div class="config-body announcement-preview-body"></div>';
  card.after(previewCard);
  // Drop the preview card into the workspace side column (canonical
  // side-by-side composition: composer left, live preview right).
  const sideCol = card.closest('.tab-panel')?.querySelector('.workspace-split-side');
  if (sideCol) sideCol.appendChild(previewCard);
  if (typeof refreshIcons === 'function') refreshIcons();

  const previewBody = previewCard.querySelector('.announcement-preview-body');

  // ── Preview UI ────────────────────────────────────────────────────────

  const preview = document.createElement('div');
  preview.className = 'announcement-preview';
  preview.setAttribute('aria-live', 'polite');
  preview.innerHTML =
    '<div class="discord-preview">' +
      '<div class="discord-message">' +
        '<img class="discord-avatar" src="/static/img/bark-avatar.png" alt="" loading="lazy">' +
        '<div class="discord-message-body">' +
          '<div class="discord-message-header">' +
            '<span class="discord-username">Bark</span>' +
            '<span class="discord-bot-badge">BOT</span>' +
            '<span class="discord-timestamp"></span>' +
          '</div>' +
          '<div class="discord-message-content"></div>' +
          '<div class="discord-embed" hidden></div>' +
        '</div>' +
      '</div>' +
    '</div>';
  previewBody.appendChild(preview);

  const timestampEl = preview.querySelector('.discord-timestamp');
  const contentEl = preview.querySelector('.discord-message-content');
  const embedEl = preview.querySelector('.discord-embed');

  function nowTimestamp() {
    const d = new Date();
    let hours = d.getHours();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `Today at ${hours}:${minutes} ${ampm}`;
  }

  function readMedia() {
    if (!mediaHidden) return {image: '', video: ''};
    try {
      const items = JSON.parse(mediaHidden.value || '[]');
      const image = items.find((item) => item && item.type === 'image' && item.url);
      const video = items.find((item) => item && item.type === 'video' && item.url);
      return {image: image ? image.url : '', video: video ? video.url : ''};
    } catch {
      return {image: '', video: ''};
    }
  }

  /** Current embed accent color: #RRGGBB or blurple fallback. Mirrors the
   * backend `_parse_embed_color` (invalid/empty degrades to blurple). */
  function readColor() {
    const raw = colorInput ? colorInput.value : '';
    return /^#[0-9a-fA-F]{6}$/.test(raw) ? raw.toLowerCase() : '#5865f2';
  }

  /** Hide preview images that fail to load (dead/blocked URLs render as a
   * broken icon in Discord; a silent collapse is cleaner in the dashboard).
   * Uses a delegated capture listener so re-rendered images are covered too.
   * Loads eagerly so the error fires immediately rather than on scroll. */
  function mediaImg(src, cls) {
    return `<img class="${cls}" src="${esc(src)}" alt="">`;
  }

  function updatePreview() {
    timestampEl.textContent = nowTimestamp();

    const title = titleInput ? titleInput.value.trim() : '';
    const message = messageInput ? messageInput.value : '';
    const asEmbed = embedCheck ? embedCheck.checked : false;
    const {image, video} = readMedia();

    // Mirror backend: embed mode with no picked image falls back to an image
    // URL auto-detected from markdown, else the invisible spacer (show none).
    let imageUrl = image;
    if (asEmbed && !imageUrl && message) {
      const match = message.match(/!\[.*?\]\((https?:\/\/\S+)\)/);
      if (match) imageUrl = match[1];
    }

    const hasContent = message.trim() || title || imageUrl;

    if (!hasContent) {
      contentEl.innerHTML = '<span class="discord-placeholder">Your announcement will appear here…</span>';
      embedEl.hidden = true;
      return;
    }

    if (asEmbed) {
      // Backend: description = message[:4096], then append "[Watch Video](url)".
      let description = message.slice(0, 4096);
      if (video) {
        const link = `[Watch Video](${video.replace(/\/+$/, '')})`;
        description = description ? `${description}\n\n${link}` : link;
      }
      contentEl.innerHTML = '';
      embedEl.hidden = false;
      embedEl.innerHTML =
        `<div class="discord-embed-bar" style="background:${readColor()}"></div>` +
        '<div class="discord-embed-body">' +
          (title ? `<div class="discord-embed-title">${esc(title)}</div>` : '') +
          (description ? `<div class="discord-embed-desc">${renderMarkdown(description, true)}</div>` : '') +
          (imageUrl ? mediaImg(imageUrl, 'discord-embed-image') : '') +
          `<div class="discord-embed-footer"><span>Bark</span><span>${nowTimestamp()}</span></div>` +
        '</div>';
    } else {
      // Backend: content = message[:2000]; an image is a separate embed below.
      contentEl.innerHTML = renderMarkdown(message.slice(0, 2000), false);
      if (image) {
        embedEl.hidden = false;
        embedEl.innerHTML =
          '<div class="discord-embed-bar"></div>' +
          '<div class="discord-embed-body">' +
            mediaImg(image, 'discord-embed-image') +
          '</div>';
      } else {
        embedEl.hidden = true;
      }
    }
  }

  // ── Color swatch ↔ hex text sync ──────────────────────────────────────

  const HEX_RE = /^#?[0-9a-fA-F]{6}$/;

  function normalizeHex(raw) {
    const value = String(raw ?? '').trim();
    if (!HEX_RE.test(value)) return null;
    const hex = value.replace(/^#?/, '#');
    return hex.toLowerCase();
  }

  function syncHexToSwatch() {
    const hex = normalizeHex(colorHex ? colorHex.value : '');
    if (hex && colorInput) {
      colorInput.value = hex;
      if (colorHex) colorHex.classList.remove('invalid');
    } else if (colorHex) {
      colorHex.classList.add('invalid');
    }
    updatePreview();
  }

  function syncSwatchToHex() {
    if (colorHex && colorInput) colorHex.value = colorInput.value.toUpperCase();
    updatePreview();
  }

  colorHex?.addEventListener('input', syncHexToSwatch);
  colorHex?.addEventListener('change', () => {
    // Commit a valid typed value; otherwise restore the swatch's value.
    const hex = normalizeHex(colorHex.value);
    if (colorHex && colorInput && hex) {
      colorHex.value = hex.toUpperCase();
      colorHex.classList.remove('invalid');
    } else if (colorHex && colorInput) {
      colorHex.value = colorInput.value.toUpperCase();
      colorHex.classList.remove('invalid');
    }
    updatePreview();
  });
  colorInput?.addEventListener('input', syncSwatchToHex);

  // ── Live wiring ───────────────────────────────────────────────────────

  // Collapse broken preview images (dead/blocked URLs) instead of showing
  // Discord's broken-image icon in the dashboard.
  preview.addEventListener('error', (event) => {
    if (event.target instanceof HTMLImageElement) event.target.style.display = 'none';
  }, true);

  titleInput?.addEventListener('input', updatePreview);
  messageInput?.addEventListener('input', updatePreview);
  embedCheck?.addEventListener('change', updatePreview);
  // module-workspace.js's media picker re-renders chips into the hidden input;
  // it dispatches bark:media-changed so the preview stays in sync.
  picker?.addEventListener('bark:media-changed', updatePreview);

  // ── Server emoji picker ───────────────────────────────────────────────
  // Inserts a custom emoji (:name:) into the message at the caret. Fetches the
  // server's emojis from the guilds emojis API on first open and caches them.
  if (messageInput) {
    const emojiBtn = document.createElement('button');
    emojiBtn.type = 'button';
    emojiBtn.className = 'btn btn-xs announce-emoji-btn';
    emojiBtn.title = 'Insert server emoji';
    emojiBtn.setAttribute('aria-label', 'Insert server emoji');
    emojiBtn.textContent = '🙂';
    emojiBtn.style.position = 'absolute';
    emojiBtn.style.right = '8px';
    emojiBtn.style.bottom = '8px';
    emojiBtn.style.zIndex = '2';

    const pickerWrap = document.createElement('div');
    pickerWrap.className = 'announce-emoji-picker';
    pickerWrap.hidden = true;
    pickerWrap.innerHTML =
      '<div class="announce-emoji-picker-head">Server emojis</div>' +
      '<div class="announce-emoji-picker-grid" role="listbox" aria-label="Server emojis"></div>';

    // Position the picker over the textarea (the message field wrapper).
    const fieldWrap = messageInput.closest('.form-group') || messageInput.parentElement;
    fieldWrap.style.position = 'relative';
    fieldWrap.appendChild(emojiBtn);
    fieldWrap.appendChild(pickerWrap);

    let emojisCache = null;
    let loading = false;

    async function loadEmojis() {
      if (emojisCache) return emojisCache;
      if (loading) return [];
      loading = true;
      try {
        const guildId = window.currentGuildId ? window.currentGuildId() : null;
        if (!guildId) return [];
        const res = await (window.safeFetch || fetch)(`/api/v1/guilds/${guildId}/emojis`);
        // safeFetch returns the parsed JSON body; a bare fetch returns a Response.
        const data = res && typeof res.json === 'function' ? await res.json() : res;
        emojisCache = (data && data.data && data.data.emojis) || [];
      } catch {
        emojisCache = [];
      } finally {
        loading = false;
      }
      return emojisCache;
    }

    function insertEmoji(name) {
      const start = messageInput.selectionStart ?? messageInput.value.length;
      const end = messageInput.selectionEnd ?? messageInput.value.length;
      const token = `:${name}:`;
      messageInput.value = messageInput.value.slice(0, start) + token + messageInput.value.slice(end);
      const newPos = Math.min(start + token.length, messageInput.value.length);
      messageInput.setSelectionRange(newPos, newPos);
      messageInput.focus();
      messageInput.dispatchEvent(new Event('input', { bubbles: true }));
    }

    async function openPicker() {
      const grid = pickerWrap.querySelector('.announce-emoji-picker-grid');
      const emojis = await loadEmojis();
      if (!emojis.length) {
        grid.innerHTML = '<div class="announce-emoji-empty">No custom emojis on this server.</div>';
      } else {
        grid.innerHTML = emojis.map((e) =>
          `<button type="button" class="announce-emoji-item" data-name="${esc(e.name)}" title=":${esc(e.name)}:" role="option">` +
            `<img src="${esc(e.url)}" alt=":${esc(e.name)}:" loading="lazy">` +
          `</button>`
        ).join('');
      }
      pickerWrap.hidden = false;
      emojiBtn.setAttribute('aria-expanded', 'true');
      grid.querySelector('.announce-emoji-item')?.focus();
    }

    function closePicker() {
      pickerWrap.hidden = true;
      emojiBtn.setAttribute('aria-expanded', 'false');
    }

    emojiBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (pickerWrap.hidden) openPicker();
      else closePicker();
    });

    pickerWrap.querySelector('.announce-emoji-picker-grid')?.addEventListener('click', (e) => {
      const item = e.target.closest('.announce-emoji-item');
      if (!item) return;
      insertEmoji(item.dataset.name);
      closePicker();
    });

    // Close the picker on outside click / Escape.
    document.addEventListener('click', (e) => {
      if (!pickerWrap.hidden && !pickerWrap.contains(e.target) && e.target !== emojiBtn) closePicker();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !pickerWrap.hidden) closePicker();
    });

    // Keep the picker above the preview toggle button if one exists.
    updatePreview();
  }

  // ── Scheduled announcement queue ──────────────────────────────────────

  const form = card.querySelector('.module-action-form');
  const timezoneInput = document.createElement('input');
  timezoneInput.type = 'hidden';
  timezoneInput.name = 'timezone_name';
  timezoneInput.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  form?.appendChild(timezoneInput);
  const intervalInput = document.getElementById('action-post_announcement-recurrence_interval');
  if (intervalInput && !intervalInput.value) intervalInput.value = '1';

  const queueCard = document.createElement('article');
  queueCard.className = 'content-card workspace-data-card announcement-queue-card';
  queueCard.innerHTML =
    '<div class="card-header"><div><h2 class="card-title">' + (typeof getIconSvg === 'function' ? getIconSvg('clock', 16) : '') + ' Scheduled Queue</h2>' +
    '<p class="card-description">One-time and recurring announcements for this server.</p></div>' +
    '<button type="button" class="btn btn-xs" data-schedule-refresh>Refresh</button></div>' +
    '<div class="config-body announcement-queue-body" aria-live="polite"><div class="state-panel">Loading schedules…</div></div>';
  if (sideCol) sideCol.appendChild(queueCard);
  else previewCard.after(queueCard);
  if (typeof refreshIcons === 'function') refreshIcons();

  const queueBody = queueCard.querySelector('.announcement-queue-body');
  const guildId = window.currentGuildId ? window.currentGuildId() : null;
  const schedulesUrl = () => `/api/v1/guilds/${guildId}/modules/announcements/schedules`;

  function recurrenceText(job) {
    if (!job.recurrence_unit) return 'One time';
    const count = Number(job.recurrence_interval) || 1;
    return `Every ${count} ${job.recurrence_unit}${count === 1 ? '' : 's'}`;
  }

  function renderQueue(jobs) {
    if (!jobs.length) {
      queueBody.innerHTML = '<div class="state-panel"><strong>No scheduled announcements</strong><span>Choose “Schedule for later” in the composer to add one.</span></div>';
      return;
    }
    queueBody.innerHTML = `<div class="announcement-queue-list">${jobs.map((job) => {
      const when = new Date(job.next_run_at).toLocaleString();
      const paused = job.status === 'paused' || job.status === 'failed';
      const action = paused ? 'resume' : 'pause';
      const actionLabel = job.status === 'failed' ? 'Retry' : (paused ? 'Resume' : 'Pause');
      return `<article class="announcement-queue-item" data-schedule-id="${Number(job.id)}">` +
        `<div class="announcement-queue-main"><div class="announcement-queue-head"><strong>${esc(job.title || job.message.slice(0, 80))}</strong><span class="status-badge">${esc(job.status)}</span></div>` +
        `<p>${esc(job.message.slice(0, 180))}</p><small>${esc(when)} · ${esc(recurrenceText(job))} · ${esc(job.timezone_name)}</small>` +
        (job.last_error ? `<div class="action-result error">${esc(job.last_error)}</div>` : '') +
        `</div><div class="table-actions"><button type="button" class="btn btn-xs" data-schedule-action="${action}">${actionLabel}</button>` +
        '<button type="button" class="btn btn-xs btn-danger" data-schedule-action="delete">Delete</button></div></article>';
    }).join('')}</div>`;
  }

  async function loadQueue() {
    if (!guildId) return;
    try {
      const response = await safeFetch(schedulesUrl(), {cache: 'no-cache'});
      renderQueue(response?.data?.schedules || []);
    } catch (error) {
      queueBody.innerHTML = `<div class="action-result error">${esc(error.message || 'Could not load schedules')}</div>`;
    }
  }

  queueCard.querySelector('[data-schedule-refresh]')?.addEventListener('click', loadQueue);
  queueBody.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-schedule-action]');
    const item = button?.closest('[data-schedule-id]');
    if (!button || !item) return;
    const action = button.dataset.scheduleAction;
    if (action === 'delete' && typeof BarkDialog?.confirm === 'function') {
      const confirmed = await BarkDialog.confirm({title: 'Delete scheduled announcement?', message: 'This removes it from the queue permanently.', confirmLabel: 'Delete', danger: true});
      if (!confirmed) return;
    }
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      const url = `${schedulesUrl()}/${item.dataset.scheduleId}`;
      if (action === 'delete') await safeFetch(url, {method: 'DELETE'});
      else await safeFetch(url, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({paused: action === 'pause'})});
      await loadQueue();
      showToast(action === 'delete' ? 'Schedule deleted' : `Schedule ${action}d`, 'success');
    } catch (error) {
      showToast(error.message || 'Schedule update failed', 'error');
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  });
  window.addEventListener('bark:module-action-complete', (event) => {
    if (event.detail?.moduleName === 'announcements' && event.detail?.endpoint === 'post') loadQueue();
  });
  loadQueue();

  updatePreview();
})();
