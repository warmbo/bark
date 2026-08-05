/** Announcements workspace extras: live Discord preview for the post action.
 *
 * Mirrors modules/announcements/module.py `post_announcement` rendering so the
 * Operate tab shows exactly what Bark will post: plain-text mode vs embed mode,
 * the title/description, embed accent color, media image, the appended
 * "[Watch Video]" link, and the 2000/4096 character caps. The action card is
 * re-laid out as a split pane — composer left, live preview right. Loaded only
 * on the announcements module detail page (see pages/module_detail.html).
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

    // Protect code blocks from inline token processing.
    const blocks = [];
    let out = text.replace(/```([\s\S]*?)```/g, (_, code) => {
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

    if (!embedMode) {
      // Block-level formatting only in real message content.
      out = out.replace(/^### (.+)$/gm, '<h4 class="discord-h4">$1</h4>');
      out = out.replace(/^## (.+)$/gm, '<h3 class="discord-h3">$1</h3>');
      out = out.replace(/^# (.+)$/gm, '<h2 class="discord-h2">$1</h2>');
      out = out.replace(/^&gt; (.+)$/gm, '<blockquote class="discord-quote">$1</blockquote>');
      out = out.replace(/^- (.+)$/gm, '<span class="discord-li">• $1</span>');
      out = out.replace(/^\d+\. (.+)$/gm, '<span class="discord-li">$&</span>');
    }

    // Line breaks before restoring code blocks so fenced content keeps its
    // real newlines (white-space: pre in the preview).
    out = out.replace(/\n/g, '<br>');

    // Restore protected code blocks.
    blocks.forEach((block, i) => {
      out = out.split(`\u0000CB${i}\u0000`).join(block);
    });

    return out;
  }

  // ── Split-pane layout: composer left, preview right ───────────────────

  const configBody = card.querySelector('.config-body');
  const form = card.querySelector('.module-action-form');
  const result = card.querySelector('.action-result');

  const split = document.createElement('div');
  split.className = 'announcement-split';

  const formCol = document.createElement('div');
  formCol.className = 'announcement-form-col';
  if (form) formCol.appendChild(form);
  if (result) formCol.appendChild(result);

  const previewCol = document.createElement('div');
  previewCol.className = 'announcement-preview-col';

  split.append(formCol, previewCol);
  if (configBody) configBody.replaceChildren(split);

  // ── Preview UI ────────────────────────────────────────────────────────

  const preview = document.createElement('div');
  preview.className = 'announcement-preview';
  preview.setAttribute('aria-live', 'polite');
  preview.innerHTML =
    '<div class="announcement-preview-label">Discord preview</div>' +
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
  previewCol.appendChild(preview);

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

  updatePreview();
})();
