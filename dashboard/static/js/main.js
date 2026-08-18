/**
 * Bark Dashboard — Main JavaScript
 * Manifest-driven sidebar, tab switching, toast notifications
 * Consolidated utilities shared by all templates
 */

// ── Resilient fetch with AbortController, timeout, session handling ──

const apiCache = new Map();

async function safeFetch(url, options = {}) {
    const { timeout = 15000, cache = false, retries = 0, ...fetchOpts } = options;

    const controller = new AbortController();
    fetchOpts.signal = controller.signal;

    // Cache check — only when caller explicitly passes `cache: true`
    if (cache === true && apiCache.has(url)) {
        const { data, expiry } = apiCache.get(url);
        if (Date.now() < expiry) return data;
        apiCache.delete(url);
    }

    // Pass cache string hint (e.g. 'no-cache', 'no-store') through to fetch()
    if (typeof cache === 'string') fetchOpts.cache = cache;

    // Timeout
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
        const res = await fetch(url, fetchOpts);
        clearTimeout(timer);

        if (!res.ok) {
            // Session expired — redirect to login
            if (res.status === 401) {
                window.location.href = '/auth/login';
                throw new Error('Session expired');
            }
            if (res.status === 403) {
                throw new Error('You do not have permission to perform this action');
            }
            const body = await res.json().catch(() => ({}));
            throw new Error(body.error || `HTTP ${res.status}`);
        }

        const data = await res.json();

        if (cache === true) {
            apiCache.set(url, { data, expiry: Date.now() + 30000 });
        }

        return data;
    } catch (err) {
        clearTimeout(timer);
        if (err.name === 'AbortError') {
            throw new Error('Request timed out');
        }
        throw err;
    }
}

const BarkDialog = (() => {
    let previousFocus = null;
    const overlay = () => document.getElementById('app-dialog-overlay');
    const close = (result = false) => {
        const node = overlay();
        if (!node || node.hidden) return;
        node.hidden = true;
        node.setAttribute('aria-hidden', 'true');
        const inputWrap = node.querySelector('[data-dialog-input-wrap]');
        if (inputWrap) inputWrap.hidden = true;
        const gridWrap = node.querySelector('[data-dialog-grid-wrap]');
        if (gridWrap) gridWrap.hidden = true;
        const resolver = node._resolver;
        node._resolver = null;
        if (previousFocus?.isConnected) previousFocus.focus();
        if (resolver) resolver(result);
    };
    const confirm = ({title, message, confirmLabel = 'Continue', danger = false}) => new Promise((resolve) => {
        const node = overlay();
        if (!node) { resolve(false); return; }
        // Resolve an older dialog before replacing it so callers never retain a
        // pending promise when two controls are activated quickly.
        if (!node.hidden) close(false);
        previousFocus = document.activeElement;
        node.querySelector('[data-dialog-title]').textContent = title;
        node.querySelector('[data-dialog-message]').textContent = message;
        const confirmButton = node.querySelector('[data-dialog-confirm]');
        confirmButton.textContent = confirmLabel;
        confirmButton.classList.toggle('btn-danger', danger);
        confirmButton.classList.toggle('btn-primary', !danger);
        node.hidden = false; node.setAttribute('aria-hidden', 'false'); node._resolver = resolve;
        confirmButton.focus();
    });
    const prompt = ({title, message = '', defaultValue = '', confirmLabel = 'OK', placeholder = ''}) => new Promise((resolve) => {
        const node = overlay();
        if (!node) { resolve(null); return; }
        if (!node.hidden) close(false);
        previousFocus = document.activeElement;
        node.querySelector('[data-dialog-title]').textContent = title;
        node.querySelector('[data-dialog-message]').textContent = message;
        const inputWrap = node.querySelector('[data-dialog-input-wrap]');
        const input = node.querySelector('[data-dialog-input]');
        input.value = defaultValue;
        input.placeholder = placeholder;
        inputWrap.hidden = false;
        const confirmButton = node.querySelector('[data-dialog-confirm]');
        confirmButton.textContent = confirmLabel;
        confirmButton.classList.remove('btn-danger');
        confirmButton.classList.add('btn-primary');
        node._resolver = (confirmed) => {
            inputWrap.hidden = true;
            resolve(confirmed === true ? input.value.trim() : null);
        };
        node.hidden = false; node.setAttribute('aria-hidden', 'false');
        input.focus();
        input.select();
    });
    const pick = ({title, items, message = '', onDelete = null}) => new Promise((resolve) => {
        const node = overlay();
        if (!node) { resolve(null); return; }
        if (!node.hidden) close(false);
        previousFocus = document.activeElement;
        node.querySelector('[data-dialog-title]').textContent = title;
        node.querySelector('[data-dialog-message]').textContent = message;
        const inputWrap = node.querySelector('[data-dialog-input-wrap]');
        inputWrap.hidden = true;
        const gridWrap = node.querySelector('[data-dialog-grid-wrap]');
        const grid = node.querySelector('[data-dialog-grid]');
        grid.innerHTML = '';
        const renderCells = (list) => {
            grid.innerHTML = '';
            list.forEach((item, index) => {
                const cell = document.createElement('div');
                cell.setAttribute('role', 'button');
                cell.tabIndex = 0;
                cell.className = 'dialog-grid-cell';
                cell.setAttribute('aria-label', `Pick ${item.label || item.url}`);
                const img = document.createElement('img');
                img.src = item.url;
                img.alt = item.label || '';
                img.loading = 'lazy';
                cell.appendChild(img);
                const pick = () => {
                    node.hidden = true; node.setAttribute('aria-hidden', 'true');
                    node._resolver = null;
                    gridWrap.hidden = true;
                    if (previousFocus?.isConnected) previousFocus.focus();
                    resolve(item);
                };
                cell.addEventListener('click', pick);
                cell.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        pick();
                    }
                });
                if (onDelete) {
                    const del = document.createElement('button');
                    del.type = 'button';
                    del.className = 'dialog-grid-delete';
                    del.setAttribute('aria-label', `Delete ${item.label || item.url}`);
                    del.textContent = '×';
                    del.addEventListener('click', async (event) => {
                        event.stopPropagation();
                        const ok = await BarkDialog.confirm({title: 'Delete this upload?', message: '', confirmLabel: 'Delete', danger: true});
                        if (!ok) return;
                        try {
                            await onDelete(item);
                            renderCells(list.filter((_, i) => i !== index));
                        } catch (error) {
                            showToast(error.message || 'Delete failed', 'error');
                        }
                    });
                    cell.appendChild(del);
                }
                grid.appendChild(cell);
            });
        };
        renderCells(items);
        gridWrap.hidden = false;
        node.hidden = false; node.setAttribute('aria-hidden', 'false');
        const first = grid.querySelector('.dialog-grid-cell[role="button"]');
        if (first) first.focus();
    });

    document.addEventListener('click', (event) => {
        if (event.target.matches('[data-dialog-cancel], #app-dialog-overlay')) close(false);
        if (event.target.matches('[data-dialog-confirm]')) close(true);
    });
    document.addEventListener('keydown', (event) => {
        const node = overlay();
        if (!node || node.hidden) return;
        if (event.key === 'Escape') { event.preventDefault(); close(false); return; }
        if (event.key === 'Enter' && event.target.matches('[data-dialog-input]')) {
            event.preventDefault();
            close(true);
            return;
        }
        if (event.key === 'Tab') {
            const controls = [...node.querySelectorAll('button:not([disabled]), [href], input:not([disabled])')];
            if (!controls.length) return;
            const first = controls[0], last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
    });
    return {confirm, prompt, pick, close};
})();

// ── Shared Utility Functions ──────────────────────────

function escHtml(t) {
    if (t == null) return '';
    const d = document.createElement('div');
    d.textContent = String(t);
    return d.innerHTML;
}

/**
 * Render Discord-style markdown to safe HTML. The source is HTML-escaped
 * first, so token matches can never inject markup — only the tags we generate.
 * Supports: **bold**, *italic*, __underline__, ~~strike~~, `code`,
 * [text](https://…), #/##/### headings, > quotes, - / 1. lists, and line breaks.
 */
function renderMarkdown(source, escape = escHtml) {
    const text = escape(source == null ? '' : String(source));
    let out = text
        .replace(/```([\s\S]*?)```/g, '<pre class="discord-codeblock">$1</pre>')
        .replace(/`([^`\n]+)`/g, '<code class="discord-code">$1</code>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a class="discord-link" href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
        .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
        .replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>')
        .replace(/__([^_]+)__/g, '<u>$1</u>')
        .replace(/~~([^~]+)~~/g, '<s>$1</s>')
        .replace(/\|\|([^|]+)\|\|/g, '<span class="discord-spoiler">$1</span>')
        .replace(/^### (.+)$/gm, '<h4 class="discord-h4">$1</h4>')
        .replace(/^## (.+)$/gm, '<h3 class="discord-h3">$1</h3>')
        .replace(/^# (.+)$/gm, '<h2 class="discord-h2">$1</h2>')
        .replace(/^&gt; (.+)$/gm, '<blockquote class="discord-quote">$1</blockquote>')
        .replace(/^- (.+)$/gm, '<span class="discord-li">• $1</span>')
        .replace(/^\d+\. (.+)$/gm, '<span class="discord-li">$&</span>');
    return out.replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br>');
}

function safeClassToken(value, fallback = 'item') {
    const token = String(value ?? '').toLowerCase().replace(/[^a-z0-9_-]/g, '');
    return token || fallback;
}

function safeLocalUrl(value, fallback = '#') {
    try {
        const url = new URL(String(value ?? ''), window.location.origin);
        if (url.origin !== window.location.origin || !url.pathname.startsWith('/')) return fallback;
        return `${url.pathname}${url.search}${url.hash}`;
    } catch {
        return fallback;
    }
}

function safeResourceUrl(value, fallback = '') {
    try {
        const url = new URL(String(value ?? ''), window.location.origin);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : fallback;
    } catch {
        return fallback;
    }
}

function showToast(message, type = 'success') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    toast.innerHTML = `<span class="toast-icon">${type === 'error' ? '✕' : '✓'}</span>
                       <span class="toast-msg">${escHtml(message)}</span>`;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('visible'));
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 250);
    }, 3000);
}

function showSkeleton(container, count = 3, type = 'card') {
    let html = '';
    for (let i = 0; i < count; i++) {
        if (type === 'card') {
            html += `<div class="skeleton skeleton-card skeleton-gap-card"></div>`;
        } else if (type === 'text') {
            html += `<div class="skeleton skeleton-text skeleton-gap-text"></div>`;
        } else if (type === 'stat') {
            html += `<div class="skeleton skeleton-stat"></div>`;
        } else if (type === 'avatar-lg') {
            html += `<div class="skeleton skeleton-avatar-lg"></div>`;
        }
    }
    container.innerHTML = html;
}

function timeAgo(iso) {
    if (!iso) return '';
    const timestamp = new Date(iso).getTime();
    if (!Number.isFinite(timestamp)) return '';
    const sec = Math.max(0, (Date.now() - timestamp) / 1000);
    if (sec < 10) return 'just now';
    if (sec < 60) return `${Math.floor(sec)}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 2592000) return `${Math.floor(sec / 86400)}d ago`;
    return new Date(iso).toLocaleDateString();
}

function formatDuration(seconds) {
    if (seconds == null || seconds <= 0) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    const parts = [];
    if (h > 0) parts.push(`${h}h`);
    if (m > 0) parts.push(`${m}m`);
    if (s > 0 || parts.length === 0) parts.push(`${s}s`);
    return parts.join(' ');
}

// ── Shared Data-View Primitives ─────────────────────
// Single source of truth for loading/empty/error states and data tables,
// used by every module workspace and JS-rendered data surface.

function renderStatePanel(kind, title, message, section) {
    const iconName = kind === 'error' ? 'alert-circle' : 'inbox';
    return `
    <div class="state-panel state-${kind}" role="${kind === 'error' ? 'alert' : 'status'}">
      <span class="state-panel-icon" aria-hidden="true">${getIconSvg(iconName, 18)}</span>
      <div><strong>${escHtml(title)}</strong><p>${escHtml(message || '')}</p></div>
      ${section ? `<button type="button" class="btn btn-sm" data-refresh-section="${section}">Retry</button>` : ''}
    </div>`;
}

function renderDataTable(headers, rows, caption) {
    const cap = caption ? `<caption class="sr-only">${escHtml(caption)}</caption>` : '';
    return `<div class="table-scroll"><table class="data-table">${cap}<thead><tr>${headers.map(h => `<th scope="col">${escHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function refreshIcons() {
    if (window.lucide?.createIcons) window.lucide.createIcons();
}

function currentGuildId() {
    return window.location.pathname.match(/\/guild\/(\d+)/)?.[1];
}

// ── Unified Tab Switching ─────────────────────────

function initTabs(container) {
    container = container || document;
    container.querySelectorAll('[role="tablist"], .tabs').forEach((tablist, listIndex) => {
        const tabs = [...tablist.querySelectorAll('[role="tab"], .tab')];
        const scope = tablist.closest('[data-tab-scope]') || tablist.closest('.page-container') || document;
        const activate = (tab, focus = false) => {
            let panelId = tab.getAttribute('aria-controls') || (tab.dataset.tab ? `tab-${tab.dataset.tab}` : '');
            if (!panelId && tab.hash) panelId = tab.hash.slice(1);
            if (!panelId) return;
            tabs.forEach((item) => {
                const selected = item === tab;
                item.classList.toggle('active', selected);
                item.setAttribute('aria-selected', String(selected));
                item.tabIndex = selected ? 0 : -1;
            });
            scope.querySelectorAll('.tab-panel').forEach((panel) => {
                const selected = panel.id === panelId;
                panel.classList.toggle('active', selected);
                panel.hidden = !selected;
            });
            if (focus) tab.focus();
            try { sessionStorage.setItem(`tab:${window.location.pathname}:${listIndex}`, panelId); } catch {}
        };
        tabs.forEach((tab, index) => {
            tab.setAttribute('role', 'tab');
            const panelId = tab.getAttribute('aria-controls') || (tab.dataset.tab ? `tab-${tab.dataset.tab}` : '');
            if (panelId) {
                tab.setAttribute('aria-controls', panelId);
                if (!tab.id) tab.id = `tab-${listIndex}-${index}`;
                const panel = scope.querySelector(`#${CSS.escape(panelId)}`);
                if (panel) { panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id); }
            }
            tab.addEventListener('click', () => activate(tab));
            tab.addEventListener('keydown', (event) => {
                let target;
                if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
                if (event.key === 'ArrowLeft') target = tabs[(index - 1 + tabs.length) % tabs.length];
                if (event.key === 'Home') target = tabs[0];
                if (event.key === 'End') target = tabs[tabs.length - 1];
                if (target) { event.preventDefault(); activate(target, true); }
            });
        });
        let initial = tabs.find((tab) => tab.classList.contains('active')) || tabs[0];
        try {
            const saved = sessionStorage.getItem(`tab:${window.location.pathname}:${listIndex}`);
            initial = tabs.find((tab) => tab.getAttribute('aria-controls') === saved) || initial;
        } catch {}
        if (initial) activate(initial);
    });
}

// ── Unified Data Loader ───────────────────────────

async function loadSection(url, container, renderFn, opts = {}) {
    const { loading = 'Loading...', empty = 'No data found.', error = 'Failed to load.' } = opts;
    if (!container) return;

    // Show skeleton immediately
    const skeletonType = opts.skeleton || 'card';
    showSkeleton(container, opts.skeletonCount || 3, skeletonType);

    try {
        // safeFetch: 401s route to login, 403s give a readable message, and
        // every other failure surfaces the server's error text (raw fetch
        // only produced 'HTTP nnn' and let expired sessions fail silently).
        const res = await safeFetch(url, { cache: 'no-cache' });
        const raw = res;
        const data = raw.data || raw;

        // If renderFn returns false/undefined and items are empty, show empty state
        const result = renderFn(data, container);
        if (result === false || (result === undefined && (!data.items || data.items.length === 0))) {
            container.innerHTML = `<div class="empty-state small"><p>${escHtml(empty)}</p></div>`;
        }
    } catch (e) {
        container.innerHTML = `<div class="empty-state small"><p>${escHtml(error)} ${escHtml(e.message)}</p></div>`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // ── Mobile navigation drawer (slide/gesture menu) ──
    initMobileDrawer();

    // ── Bot connection watchdog ───────────────────────
    // Poll health; show the offline banner while the bot process is up but
    // not connected to Discord (the "0 connected servers" trap).
    const offlineBanner = document.getElementById('bot-offline-banner');
    if (offlineBanner) {
        const checkBotHealth = async () => {
            try {
                const health = await safeFetch('/api/v1/health', {cache: 'no-cache'});
                const bot = health?.data?.bot;
                offlineBanner.hidden = bot?.connected !== false;
            } catch (error) {
                // Instance itself is unreachable — leave the banner alone.
            }
        };
        checkBotHealth();
        const healthTimer = setInterval(checkBotHealth, 30000);
        // Stop polling when the page is cached by bfcache (so the interval
        // doesn't keep firing across restores) and restart on pageshow.
        window.addEventListener('pagehide', () => clearInterval(healthTimer));
    }

    // ── Load Manifest & Build Sidebar ─────────────────
    const navItems = document.getElementById('sidebar-nav-items');
    if (navItems) loadSidebarManifest(navItems);

    // ── Tab switching ────────────────────────────────
    initTabs();

    // ── API-driven select fields (populated from Discord) ──
    initApiSelects();

    // ── Keyboard shortcut hint animation ─────────────
    const hint = document.getElementById('shortcut-hint');
    if (hint) {
        // Fade in hint after 2s
        setTimeout(() => hint.style.opacity = '1', 2000);
    }
});

// ── Mobile Navigation Drawer ────────────────────────────
// The sidebar becomes a slide-out drawer below 769px: closed off-canvas,
// opened by the hamburger (top-left), an edge swipe, or — on open — closed
// by the scrim, the X, a left swipe, Escape, or picking a nav item.

function initMobileDrawer() {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.querySelector('[data-toggle-sidebar]');
    const scrim = document.getElementById('nav-scrim');
    if (!sidebar || !toggle || !scrim) return;

    const mobileQuery = window.matchMedia('(max-width: 768px)');
    const closeTriggers = document.querySelectorAll('[data-close-sidebar]');

    function isMobile() { return mobileQuery.matches; }

    function openDrawer() {
        if (!isMobile()) return;
        sidebar.classList.add('open');
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-label', 'Close navigation menu');
        scrim.classList.add('show');
        scrim.setAttribute('aria-hidden', 'false');
        sidebar.removeAttribute('inert');
        // Focus the drawer so keyboard users land inside it
        sidebar.setAttribute('tabindex', '-1');
        sidebar.focus({ preventScroll: true });
    }

    function closeDrawer() {
        sidebar.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', 'Open navigation menu');
        scrim.classList.remove('show');
        scrim.setAttribute('aria-hidden', 'true');
        if (isMobile()) sidebar.setAttribute('inert', '');
    }

    // Keep the drawer in sync with the viewport (desktop = always open).
    function syncViewport() {
        if (isMobile()) {
            if (!sidebar.classList.contains('open')) sidebar.setAttribute('inert', '');
        } else {
            sidebar.classList.remove('open');
            sidebar.removeAttribute('inert');
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-label', 'Open navigation menu');
            scrim.classList.remove('show');
            scrim.setAttribute('aria-hidden', 'true');
        }
    }

    // Hamburger / X
    toggle.addEventListener('click', () => {
        if (sidebar.classList.contains('open')) closeDrawer();
        else openDrawer();
    });

    // Scrim tap + drawer close buttons (delegated)
    document.addEventListener('click', (event) => {
        if (!closeTriggers.length) return;
        // A dialog on top owns the overlay click — don't yank the drawer
        // closed underneath it at the same time.
        const dialog = document.getElementById('app-dialog-overlay');
        if (dialog && !dialog.hidden) return;
        for (const trigger of closeTriggers) {
            if (trigger.contains(event.target) && sidebar.classList.contains('open')) {
                closeDrawer();
                return;
            }
        }
    });

    // Escape closes the drawer — but ONLY when no dialog is open on top of
    // it (a dialog over the drawer owns Escape; closing both at once was the
    // double-listener bug flagged by the frontend audit).
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape' || !sidebar.classList.contains('open')) return;
        const dialog = document.getElementById('app-dialog-overlay');
        if (dialog && !dialog.hidden) return;
        closeDrawer();
    });

    // Picking a nav item closes the drawer on mobile
    sidebar.addEventListener('click', (event) => {
        const link = event.target.closest('a[href]');
        if (link && isMobile()) closeDrawer();
    });

    // Swipe gestures: right edge-swipe opens; left swipe (open) closes.
    let touchStartX = null;
    let touchStartY = null;
    document.addEventListener('touchstart', (event) => {
        if (event.touches.length !== 1) { touchStartX = null; return; }
        touchStartX = event.touches[0].clientX;
        touchStartY = event.touches[0].clientY;
    }, { passive: true });

    document.addEventListener('touchend', (event) => {
        if (touchStartX === null) return;
        const startX = touchStartX;
        const endX = event.changedTouches[0].clientX;
        const endY = event.changedTouches[0].clientY;
        const dx = endX - startX;
        const dy = endY - touchStartY;
        touchStartX = null;
        touchStartY = null;
        if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy)) return; // not a horizontal swipe
        const isOpen = sidebar.classList.contains('open');
        if (!isOpen && startX < 32 && dx > 0) openDrawer();  // edge swipe right
        if (isOpen && dx < 0) closeDrawer();                 // swipe left to dismiss
    }, { passive: true });

    // Initial state (mobile closed => inert; desktop => inert removed)
    syncViewport();
    mobileQuery.addEventListener('change', syncViewport);
}

// ── API-driven Select Fields ────────────────────────────

async function loadApiSelect(sel) {
    const guildId = currentGuildId();
    if (!guildId || !sel?.dataset.api) return;
    const api = sel.dataset.api.replace('{guild_id}', guildId);
    const valueKey = sel.dataset.valueKey;
    const labelKey = sel.dataset.labelKey;
    const groupKey = sel.dataset.groupKey || '';
    const initialLabel = sel.querySelector('option')?.textContent || 'Select…';
    sel.disabled = true;
    sel.setAttribute('aria-busy', 'true');
    try {
        const data = await safeFetch(api, {cache: 'no-cache'});
        let items = data.data || data;
        if (items?.roles) items = items.roles;
        else if (items?.channels) items = items.channels;
        else if (items?.members) items = items.members;
        else if (!Array.isArray(items)) {
            const arrayValue = Object.values(items || {}).find(value => Array.isArray(value));
            if (arrayValue) items = arrayValue;
        }
        if (!Array.isArray(items)) throw new Error('The server returned an invalid option list');
        const placeholder = sel.dataset.placeholder || initialLabel.replace(/^Loading[^…]*…?$/i, 'Select…');
        sel.innerHTML = `<option value="">${escHtml(placeholder)}</option>`;
        if (groupKey) {
            const groups = {};
            items.forEach(item => { (groups[item[groupKey] || 'Other'] ||= []).push(item); });
            Object.keys(groups).sort().forEach(group => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = group;
                groups[group].forEach(item => {
                    const option = document.createElement('option');
                    option.value = item[valueKey]; option.textContent = item[labelKey]; optgroup.appendChild(option);
                });
                sel.appendChild(optgroup);
            });
        } else {
            items.forEach(item => {
                const option = document.createElement('option');
                option.value = item[valueKey]; option.textContent = item[labelKey]; sel.appendChild(option);
            });
        }
        const savedValue = sel.dataset.value;
        if (savedValue != null && savedValue !== '') sel.value = savedValue;
        sel.dataset.loaded = 'true';
        sel.dispatchEvent(new CustomEvent('api-select:loaded', {bubbles: true}));
    } catch (error) {
        sel.innerHTML = `<option value="">${escHtml(error.message || 'Failed to load options')}</option>`;
        sel.dataset.loaded = 'error';
        sel.dispatchEvent(new CustomEvent('api-select:error', {bubbles: true, detail: {error}}));
    } finally {
        sel.disabled = false;
        sel.removeAttribute('aria-busy');
    }
}

function initApiSelects(container = document) {
    container.querySelectorAll('.api-select').forEach(sel => {
        if (sel.dataset.loaded !== 'true') loadApiSelect(sel);
    });
}

// ── Sidebar Manifest Loader ───────────────────────────

/** Cache key for sessionStorage */
const MANIFEST_CACHE_KEY = 'bark_manifest_cache';

function getCachedManifest(guildId) {
    try {
        const raw = sessionStorage.getItem(`${MANIFEST_CACHE_KEY}_${guildId}`);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        // Expire after 60 seconds
        if (Date.now() - parsed.ts > 60000) {
            sessionStorage.removeItem(`${MANIFEST_CACHE_KEY}_${guildId}`);
            return null;
        }
        return parsed.data;
    } catch { return null; }
}

function setCachedManifest(guildId, data) {
    try {
        sessionStorage.setItem(`${MANIFEST_CACHE_KEY}_${guildId}`, JSON.stringify({ ts: Date.now(), data }));
    } catch { /* quota exceeded, ignore */ }
}

async function loadSidebarManifest(container) {
    const guildId = currentGuildId();
    if (!guildId) return;

    const activePage = getActivePageName();

    // Try cached manifest first for instant render
    const cached = getCachedManifest(guildId);
    if (cached) {
        renderSidebar(container, cached, activePage);
    }

    // Always fetch fresh in background
    try {
        const data = await safeFetch(`/api/v1/guilds/${guildId}/manifest`, { cache: 'no-cache' });
        const payload = data.data || data;
        setCachedManifest(guildId, payload);
        // Avoid replacing identical cached markup (and briefly recreating its icons).
        if (!cached || JSON.stringify(cached) !== JSON.stringify(payload)) {
            renderSidebar(container, payload, activePage);
        }
    } catch (e) {
        if (cached) return; // cached render is good enough
        // Fallback: render basic nav from current URL
        container.innerHTML = `
            <a href="/guild/${guildId}" class="nav-item ${activePage === 'overview' ? 'active' : ''}">
                <span class="nav-icon">${getIconSvg('layout-dashboard', 16)}</span>
                <span>Dashboard</span>
            </a>
            <a href="/guild/${guildId}/members" class="nav-item ${activePage === 'members' ? 'active' : ''}">
                <span class="nav-icon">${getIconSvg('users', 16)}</span>
                <span>Members</span>
            </a>
            <a href="/guild/${guildId}/modules" class="nav-item ${activePage === 'modules' ? 'active' : ''}">
                <span class="nav-icon">${getIconSvg('puzzle', 16)}</span>
                <span>Modules</span>
            </a>
            <a href="/guild/${guildId}/settings" class="nav-item ${activePage === 'settings' ? 'active' : ''}">
                <span class="nav-icon">${getIconSvg('settings', 16)}</span>
                <span>Settings</span>
            </a>`;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

function renderSidebar(container, data, activePage) {
    const categories = data.categories || {};
    const orderedKeys = Object.keys(categories).sort((a, b) => {
        const pa = categories[a].priority ?? 99;
        const pb = categories[b].priority ?? 99;
        return pa - pb;
    });

    let html = '';
    orderedKeys.forEach((catKey) => {
        const cat = categories[catKey];
        const visiblePages = (cat.pages || []).filter((page) => {
            if (!page.module || page.enabled) return true;
            return false;
        }).filter((page) => {
            if (page.label === 'Plugin Catalog' && !location.hostname.includes('bark-dev')) {
                return false;
            }
            return true;
        });
        if (!visiblePages.length) return;

        if (catKey !== '_core') {
            html += `<div class="nav-section-label">${escHtml(cat.label || catKey)}</div>`;
        }

        visiblePages.forEach(p => {
            html += renderNavItem(p, activePage);
        });
    });

    container.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderNavItem(page, activePage) {
    const pageRoute = safeLocalUrl(page.route, '#');
    const activeParts = activePage.split('/');
    const activeBase = activeParts[0];

    // Split the Settings page into its section anchors for active matching.
    const pageRouteBase = pageRoute.split('?')[0];
    const pageSection = (pageRoute.split('?')[1] || '').replace('section=', '');
    const isSettingsSplit = pageRouteBase.endsWith('/settings') && (pageSection === 'instance' || pageSection === 'server');

    // List pages like "Modules" should only highlight on exact match,
    // never when viewing a sub-page like /guild/{id}/modules/moderation
    const isListPage = pageRoute.match(/\/modules$/) && !page.module;

    let isActive = pageRouteBase.endsWith(`/${activePage}`)
        || (!isListPage && activeParts.length === 1 && pageRouteBase.endsWith(`/${activeBase}`))
        || activeBase === 'overview' && pageRouteBase === `/guild/${currentGuildId()}`
        || (!isListPage && activePage.startsWith(pageRouteBase.split('/').pop() + '/'))
        || (!isListPage && activeParts.length > 1 && pageRouteBase.endsWith('/' + activeParts[0]));
    if (isSettingsSplit && activePage === 'settings') {
        isActive = new URLSearchParams(location.search).get('section') === pageSection;
    }

    const isModule = !!page.module;
    const itemClass = isModule ? 'nav-item nav-item-module' : 'nav-item';
    const iconSize = isModule ? 14 : 16;
    const dataModule = isModule ? ` data-module="${escHtml(page.module)}"` : '';

    return `<a href="${pageRoute}" class="${itemClass} ${isActive ? 'active' : ''}"${isActive ? ' aria-current="page"' : ''}${dataModule}>
        <span class="nav-icon">${getIconSvg(page.icon || 'puzzle', iconSize)}</span>
        <span class="${isModule ? 'nav-module-name' : ''}">${escHtml(page.label)}</span>
    </a>`;
}

function getActivePageName() {
    const path = window.location.pathname;
    const parts = path.split('/').filter(Boolean);
    if (parts.length >= 2 && parts[0] === 'guild') {
        return parts.slice(2).join('/') || 'overview';
    }
    return path.split('/').filter(Boolean).join('/') || 'dashboard';
}

function getIconSvg(name, size) {
    const iconName = safeClassToken(name, 'puzzle');
    const parsedSize = Number(size);
    const iconSize = Number.isFinite(parsedSize) ? Math.min(64, Math.max(8, parsedSize)) : 16;
    return `<i data-lucide="${iconName}" width="${iconSize}" height="${iconSize}" stroke-width="1.7"></i>`;
}
