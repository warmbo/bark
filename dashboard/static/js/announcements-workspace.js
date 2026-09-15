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
   * token matches cannot inject HTML. `mentionNames` (id → display name) is
   * optional and passed in so the renderer stays pure and testable. */
  function renderMarkdown(source, embedMode, mentionNames) {
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

    // Discord mentions (<@id>, <@!id>, <#id>) → the name recorded when the
    // composer offered it; unknown ids keep the raw (already escaped) token.
    // Same placement as the emoji pass, before code blocks are protected.
    if (mentionNames) {
      out = out.replace(/&lt;(@!?|#)(\d+)&gt;/g, (match, sigil, id) => {
        const name = mentionNames[id];
        if (!name) return match;
        return `<span class="discord-mention">${sigil === '#' ? '#' : '@'}${esc(name)}</span>`;
      });
    }

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

  // id → display name, filled in as the composer suggests/inserts mentions.
  const mentionNames = {};

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
          (description ? `<div class="discord-embed-desc">${renderMarkdown(description, true, mentionNames)}</div>` : '') +
          (imageUrl ? mediaImg(imageUrl, 'discord-embed-image') : '') +
          `<div class="discord-embed-footer"><span>Bark</span><span>${nowTimestamp()}</span></div>` +
        '</div>';
    } else {
      // Backend: content = message[:2000]; an image is a separate embed below.
      contentEl.innerHTML = renderMarkdown(message.slice(0, 2000), false, mentionNames);
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
      // The mention list and the emoji grid share the same anchor.
      closeMentions();
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

    // ── @ / # mention autocomplete ────────────────────────────────────────
    // Typing @ or # lists members or channels for the token being typed and
    // inserts the Discord token (<@id> / <#id>). Names are recorded so the live
    // preview can render the mention instead of a raw token.
    const mentionList = document.createElement('div');
    mentionList.className = 'announce-mention-list';
    mentionList.hidden = true;
    mentionList.setAttribute('role', 'listbox');
    mentionList.setAttribute('aria-label', 'Mention suggestions');
    fieldWrap.appendChild(mentionList);

    const membersByQuery = new Map();
    let channelItems = null;
    let mentionItems = [];
    let activeIndex = -1;
    let mentionTimer = null;

    async function fetchJson(path) {
      const res = await (window.safeFetch || fetch)(path);
      // safeFetch returns the parsed body; a bare fetch returns a Response.
      return res && typeof res.json === 'function' ? await res.json() : res;
    }

    /** The @/# token immediately before `caret` in `value`, if any.
     * Pure (takes the text + caret) so the token rules are testable. */
    function tokenAtCaret(value, caret) {
      const before = String(value ?? '').slice(0, caret);
      const match = before.match(/(?:^|\s)([@#])([\w.\-]*)$/);
      if (!match) return null;
      return {sigil: match[1], query: match[2], start: caret - match[2].length - 1};
    }

    function mentionToken() {
      return tokenAtCaret(messageInput.value, messageInput.selectionStart ?? messageInput.value.length);
    }

    function closeMentions() {
      mentionList.hidden = true;
      mentionList.innerHTML = '';
      mentionItems = [];
      activeIndex = -1;
    }

    function renderMentions() {
      if (!mentionItems.length) {
        mentionList.innerHTML = '<div class="announce-mention-empty">No matches.</div>';
        mentionList.hidden = false;
        closePicker();
        return;
      }
      mentionList.innerHTML = mentionItems.map((item, index) => {
        const face = item.avatar
          ? `<img class="announce-mention-avatar" src="${esc(item.avatar)}" alt="" loading="lazy">`
          : `<span class="announce-mention-sigil">${esc(item.sigil)}</span>`;
        return `<button type="button" class="announce-mention-item${index === activeIndex ? ' active' : ''}"` +
          ` role="option" aria-selected="${index === activeIndex}" data-mention-index="${index}">` +
          `${face}<span class="announce-mention-name">${esc(item.label)}</span>` +
          (item.meta ? `<span class="announce-mention-meta">${esc(item.meta)}</span>` : '') +
          '</button>';
      }).join('');
      mentionList.hidden = false;
      closePicker();
    }

    async function loadChannelItems() {
      if (channelItems) return channelItems;
      const gid = window.currentGuildId ? window.currentGuildId() : null;
      if (!gid) return [];
      try {
        const data = await fetchJson(`/api/v1/guilds/${gid}/channels?type=text`);
        channelItems = ((data && data.data && data.data.channels) || []).map((c) => {
          mentionNames[c.id] = c.name;
          return {id: c.id, label: `#${c.name}`, sigil: '#', meta: c.parent_name || ''};
        });
      } catch {
        channelItems = [];
      }
      return channelItems;
    }

    // Members are looked up server-side (a guild can have thousands); results
    // are cached per query so backspacing doesn't re-request.
    async function loadMemberItems(query) {
      const key = query.toLowerCase();
      if (membersByQuery.has(key)) return membersByQuery.get(key);
      const gid = window.currentGuildId ? window.currentGuildId() : null;
      if (!gid) return [];
      let items = [];
      try {
        const data = await fetchJson(
          `/api/v1/guilds/${gid}/members?limit=8&search=${encodeURIComponent(query)}`
        );
        items = ((data && data.data && data.data.members) || []).map((m) => {
          mentionNames[m.id] = m.name;
          return {id: m.id, label: m.name, sigil: '@', avatar: m.avatar_url, meta: m.tag || ''};
        });
      } catch {
        items = [];
      }
      membersByQuery.set(key, items);
      return items;
    }

    async function updateMentions() {
      const token = mentionToken();
      if (!token) {
        closeMentions();
        return;
      }
      if (token.sigil === '#') {
        const needle = token.query.toLowerCase();
        mentionItems = (await loadChannelItems())
          .filter((c) => c.label.toLowerCase().includes(needle))
          .slice(0, 8);
      } else {
        mentionItems = await loadMemberItems(token.query);
      }
      activeIndex = mentionItems.length ? 0 : -1;
      renderMentions();
    }

    function acceptMention(item) {
      const caret = messageInput.selectionStart ?? messageInput.value.length;
      const token = mentionToken();
      const start = token ? token.start : caret;
      const inserted = item.sigil === '#' ? `<#${item.id}>` : `<@${item.id}>`;
      mentionNames[item.id] = String(item.label).replace(/^#/, '');
      messageInput.value =
        messageInput.value.slice(0, start) + inserted + messageInput.value.slice(caret);
      const next = start + inserted.length;
      messageInput.setSelectionRange(next, next);
      closeMentions();
      messageInput.focus();
      messageInput.dispatchEvent(new Event('input', {bubbles: true}));
    }

    messageInput.addEventListener('input', () => {
      clearTimeout(mentionTimer);
      if (!mentionToken()) {
        closeMentions();
        return;
      }
      mentionTimer = setTimeout(updateMentions, 140);
    });

    messageInput.addEventListener('keydown', (event) => {
      if (mentionList.hidden || !mentionItems.length) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        activeIndex = (activeIndex + step + mentionItems.length) % mentionItems.length;
        renderMentions();
      } else if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        acceptMention(mentionItems[activeIndex] || mentionItems[0]);
      } else if (event.key === 'Escape') {
        closeMentions();
      }
    });

    // mousedown, not click: the textarea would blur (and the row unmount) first.
    mentionList.addEventListener('mousedown', (event) => {
      const button = event.target.closest('[data-mention-index]');
      if (!button) return;
      event.preventDefault();
      acceptMention(mentionItems[Number(button.dataset.mentionIndex)]);
    });

    document.addEventListener('click', (event) => {
      if (!mentionList.hidden && !fieldWrap.contains(event.target)) closeMentions();
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
    // The API stores a plural unit ("days"); singularise before re-pluralising
    // so it can't render "Every 3 dayss" / "Every 1 weeks".
    const unit = String(job.recurrence_unit).replace(/s$/, '');
    return `Every ${count} ${unit}${count === 1 ? '' : 's'}`;
  }

  /** Flatten Discord markdown to one readable line so a sidebar slice can't
   * leave a half-word, a stray `**`, or a wall of newlines. */
  function summarise(text, limit) {
    const flat = String(text ?? '')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/<[@#][!&]?\d+>/g, ' ')
      .replace(/[*_~`>#|]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (flat.length <= limit) return flat;
    const cut = flat.slice(0, limit);
    // Break on the last word boundary rather than mid-word; a long unbroken
    // string (a URL) has no space to find, so it hard-cuts.
    const space = cut.lastIndexOf(' ');
    return `${(space > 0 ? cut.slice(0, space) : cut).trim()}…`;
  }

  let lastJobs = [];

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
      // A job a worker already claimed ("sending") must not be rewritten mid-flight.
      const editable = ['queued', 'paused', 'failed'].includes(job.status);
      // Full text lives in the title attribute; the visible lines are clamped
      // by CSS so the narrow sidebar column stays readable.
      const title = job.title ? summarise(job.title, 60) : 'Untitled announcement';
      const titleFull = summarise(job.title || job.message, 200);
      const message = summarise(job.message, 140);
      return `<article class="announcement-queue-item" data-schedule-id="${Number(job.id)}">` +
        `<div class="announcement-queue-main"><div class="announcement-queue-head"><strong class="announcement-queue-title" title="${esc(titleFull)}">${esc(title)}</strong><span class="status-badge">${esc(job.status)}</span></div>` +
        `<p title="${esc(summarise(job.message, 300))}">${esc(message)}</p><small>${esc(when)} · ${esc(recurrenceText(job))} · ${esc(job.timezone_name)}</small>` +
        (job.last_error ? `<div class="action-result error" title="${esc(job.last_error)}">${esc(summarise(job.last_error, 200))}</div>` : '') +
        `</div><div class="table-actions">` +
        (editable ? '<button type="button" class="btn btn-xs" data-schedule-action="edit">Edit</button>' : '') +
        `<button type="button" class="btn btn-xs" data-schedule-action="${action}">${actionLabel}</button>` +
        '<button type="button" class="btn btn-xs btn-danger" data-schedule-action="delete">Delete</button></div></article>';
    }).join('')}</div>`;
  }

  async function loadQueue() {
    if (!guildId) return;
    try {
      const response = await safeFetch(schedulesUrl(), {cache: 'no-cache'});
      lastJobs = response?.data?.schedules || [];
      renderQueue(lastJobs);
    } catch (error) {
      queueBody.innerHTML = `<div class="action-result error">${esc(error.message || 'Could not load schedules')}</div>`;
    }
  }

  // ── Editing a queued schedule ─────────────────────────────────────────
  // An edit reuses the composer rather than a second form: same validation,
  // same live preview, same emoji/mention tooling, and the action runner
  // already posts whatever the form serialises. Editing only repoints
  // `data-endpoint` at the schedule's own path, so one code path serves both
  // "schedule for later" and "save changes".
  const deliverySelect = document.getElementById('action-post_announcement-delivery_mode');
  const scheduledForInput = document.getElementById('action-post_announcement-scheduled_for');
  const recurrenceUnitInput = document.getElementById('action-post_announcement-recurrence_unit');
  const recurrenceIntervalInput = document.getElementById('action-post_announcement-recurrence_interval');
  const channelSelect = document.getElementById('action-post_announcement-channel_id');

  // Appended AFTER the card's own result node so the runner's
  // querySelector('.action-result') keeps finding its own element.
  const editBanner = document.createElement('div');
  editBanner.className = 'action-result success';
  editBanner.hidden = true;
  card.append(editBanner);
  const cancelEdit = document.createElement('button');
  cancelEdit.type = 'button';
  cancelEdit.className = 'btn btn-xs';
  cancelEdit.textContent = 'Cancel edit';
  cancelEdit.addEventListener('click', () => {
    stopEdit();
    showToast('Edit cancelled', 'success');
  });

  let editingId = null;

  function setField(input, value) {
    if (!input) return;
    input.value = value ?? '';
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }

  /** The composer has no timezone field; stores are UTC by default. Carrying
   * the job's own zone keeps a re-save from silently shifting its wall clock. */
  function timezoneField() {
    let input = form.querySelector('input[name="timezone_name"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'timezone_name';
      form.append(input);
    }
    return input;
  }

  function localDatetime(iso) {
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function startEdit(job) {
    editingId = Number(job.id);
    if (job.channel_id && channelSelect && !Array.from(channelSelect.options).some((o) => o.value === String(job.channel_id))) {
      channelSelect.add(new Option(`#${job.channel_id}`, String(job.channel_id)));
    }
    setField(channelSelect, job.channel_id);
    setField(titleInput, job.title || '');
    setField(messageInput, job.message || '');
    if (embedCheck) {
      embedCheck.checked = !!job.as_embed;
      embedCheck.dispatchEvent(new Event('change', {bubbles: true}));
    }
    setField(colorHex, (job.embed_color || '#5865F2').toUpperCase());
    if (mediaHidden) {
      const media = [];
      if (job.image_url) media.push({type: 'image', url: job.image_url});
      if (job.video_url) media.push({type: 'video', url: job.video_url});
      mediaHidden.value = JSON.stringify(media);
      picker?.dispatchEvent(new CustomEvent('bark:media-changed', {bubbles: true, detail: {items: media}}));
    }
    setField(deliverySelect, 'schedule');
    setField(scheduledForInput, localDatetime(job.next_run_at));
    setField(recurrenceUnitInput, job.recurrence_unit || '');
    setField(recurrenceIntervalInput, String(job.recurrence_interval || 1));
    timezoneField().value = job.timezone_name || '';
    form.dataset.endpoint = `schedules/${editingId}`;
    editBanner.hidden = false;
    editBanner.textContent = `Editing schedule #${editingId} — saving replaces it and requeues it. `;
    editBanner.append(cancelEdit);
    updatePreview();
    card.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function stopEdit() {
    editingId = null;
    form.dataset.endpoint = 'post';
    timezoneField().value = '';
    editBanner.hidden = true;
    editBanner.textContent = '';
    setField(deliverySelect, '');
    if (scheduledForInput) scheduledForInput.value = '';
  }

  queueCard.querySelector('[data-schedule-refresh]')?.addEventListener('click', loadQueue);
  queueBody.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-schedule-action]');
    const item = button?.closest('[data-schedule-id]');
    if (!button || !item) return;
    const action = button.dataset.scheduleAction;
    if (action === 'edit') {
      const job = lastJobs.find((j) => Number(j.id) === Number(item.dataset.scheduleId));
      if (job) startEdit(job);
      return;
    }
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
    if (event.detail?.moduleName !== 'announcements') return;
    const endpoint = event.detail?.endpoint || '';
    if (endpoint.startsWith('schedules/')) stopEdit();
    if (endpoint === 'post' || endpoint.startsWith('schedules/')) loadQueue();
  });
  loadQueue();

  updatePreview();
})();
