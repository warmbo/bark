/**
 * Bark Command Palette — Ctrl+K quick navigation
 * Fuzzy-search over pages, modules, and actions.
 */

let paletteData = { items: [], selectedIndex: 0, previousFocus: null };

function openPalette() {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');
    if (!overlay || !input) return;
    paletteData.previousFocus = document.activeElement;
    overlay.classList.add('visible');
    overlay.setAttribute('aria-hidden', 'false');
    setTimeout(() => { input.focus(); input.select(); }, 100);
    // Load data if not yet loaded
    if (paletteData.items.length === 0) loadPaletteData();
}

function closePalette(e) {
    if (e?.currentTarget && e.target !== e.currentTarget) return;
    const overlay = document.getElementById('palette-overlay');
    if (!overlay) return;
    overlay.classList.remove('visible');
    overlay.setAttribute('aria-hidden', 'true');
    const focusTarget = paletteData.previousFocus instanceof HTMLElement
        && paletteData.previousFocus !== document.body
        ? paletteData.previousFocus
        : document.querySelector('.sidebar-logo');
    focusTarget?.focus();
}

function loadPaletteData() {
    const guildId = window.location.pathname.match(/\/guild\/(\d+)/)?.[1];
    const results = document.getElementById('palette-results');
    if (!guildId) {
        paletteData.items = [{
            label: 'Your Servers', desc: 'Choose a Discord server',
            url: '/dashboard', icon: 'server', badge: '', type: 'page',
        }];
        filterPalette('');
        return;
    }
    if (results) results.innerHTML = '<div class="palette-empty">Loading navigation…</div>';

    fetch(`/api/v1/guilds/${guildId}/manifest`, { cache: 'no-cache' })
        .then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        })
        .then(raw => {
            const data = raw.data || raw;
            const items = [];

            // Add pages
            (data.pages || []).forEach(p => {
                items.push({
                    label: p.label,
                    desc: p.category ? `Page in ${p.category}` : 'Dashboard page',
                    url: p.route,
                    icon: p.icon || 'layout-dashboard',
                    badge: p.category || '',
                    type: 'page',
                });
            });

            // Add module quick-actions
            (data.actions || []).forEach(a => {
                items.push({
                    label: a.label,
                    desc: `Action — ${a.module}`,
                    url: a.url,
                    icon: 'zap',
                    badge: a.module,
                    type: 'action',
                });
            });

            // Add modules
            (data.modules || []).forEach(m => {
                items.push({
                    label: m.label,
                    desc: `${m.enabled ? 'Enabled' : 'Disabled'} — ${m.description || 'Module'}`,
                    url: m.url,
                    icon: 'puzzle',
                    badge: m.actions_count > 0 ? `${m.actions_count} actions` : '',
                    type: 'module',
                });
            });

            paletteData.items = items;
            filterPalette('');
        })
        .catch(() => {
            if (results) results.innerHTML = '<div class="palette-empty">Navigation could not be loaded. Close and try again.</div>';
        });
}

function filterPalette(query) {
    const results = document.getElementById('palette-results');
    const q = query.toLowerCase().trim();

    if (!q) {
        // Show recent / top items when empty
        const top = paletteData.items.slice(0, 8);
        renderPaletteResults(top, results, q);
        return;
    }

    // Simple fuzzy scoring
    const scored = paletteData.items.map(item => {
        const haystack = (item.label + ' ' + item.desc + ' ' + (item.badge || '')).toLowerCase();
        let score = 0;
        if (haystack === q) score = 100;
        else if (haystack.startsWith(q)) score = 80;
        else if (haystack.includes(q)) score = 50;
        else {
            // Substring matching
            let qi = 0;
            for (let i = 0; i < haystack.length && qi < q.length; i++) {
                if (haystack[i] === q[qi]) qi++;
            }
            if (qi === q.length) score = 30;
        }
        return { item, score };
    });

    const filtered = scored
        .filter(s => s.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 20)
        .map(s => s.item);

    renderPaletteResults(filtered, results, q);
}

function renderPaletteResults(items, container, query) {
    if (!container) return;
    if (items.length === 0) {
        container.innerHTML = '<div class="palette-empty">No results found.</div>';
        return;
    }

    // Group by type
    const groups = {};
    items.forEach(item => {
        const key = item.type === 'page' ? 'Pages'
                  : item.type === 'module' ? 'Modules'
                  : 'Quick Actions';
        if (!groups[key]) groups[key] = [];
        groups[key].push(item);
    });

    let html = '';
    Object.keys(groups).forEach(group => {
        html += `<div class="palette-group-label">${group}</div>`;
        groups[group].forEach((item, i) => {
            const hl = query ? highlightMatch(item.label, query) : paletteEscapeHtml(item.label);
            const itemUrl = safeLocalUrl(item.url, '#');
            html += `<a href="${paletteEscapeHtml(itemUrl)}" class="palette-item" role="option" aria-selected="false" tabindex="-1">
                <span class="palette-item-icon">${getLucideIcon(item.icon)}</span>
                <span class="palette-item-info">
                    <span class="palette-item-label">${hl}</span>
                    <span class="palette-item-desc">${paletteEscapeHtml(item.desc)}</span>
                </span>
                ${item.badge ? `<span class="palette-item-badge">${paletteEscapeHtml(item.badge)}</span>` : ''}
            </a>`;
        });
    });

    container.innerHTML = html;
    paletteData.selectedIndex = 0;
    highlightPaletteItem(container.querySelectorAll('.palette-item'));
    rerenderPaletteIcons();
}

function highlightMatch(text, query) {
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return paletteEscapeHtml(text);
    return paletteEscapeHtml(text.slice(0, idx))
        + '<strong style="color:var(--accent)">' + paletteEscapeHtml(text.slice(idx, idx + query.length)) + '</strong>'
        + paletteEscapeHtml(text.slice(idx + query.length));
}

function paletteEscapeHtml(t) {
    if (t == null) return '';
    const d = document.createElement('div');
    d.textContent = String(t);
    return d.innerHTML;
}

function getLucideIcon(name) {
    // Use Lucide icons via data-lucide attribute — render a placeholder i tag
    return `<i data-lucide="${safeClassToken(name, 'puzzle')}" width="16" height="16" style="stroke-width:1.5"></i>`;
}

// This is called after Lucide re-renders
function rerenderPaletteIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('palette-overlay');
    const input = document.getElementById('palette-input');

    // Keyboard navigation
    input?.addEventListener('keydown', (e) => {
        const results = document.getElementById('palette-results');
        const items = results?.querySelectorAll('.palette-item') || [];

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            paletteData.selectedIndex = Math.min(paletteData.selectedIndex + 1, items.length - 1);
            highlightPaletteItem(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            paletteData.selectedIndex = Math.max(paletteData.selectedIndex - 1, 0);
            highlightPaletteItem(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (items[paletteData.selectedIndex]) {
                window.location.href = items[paletteData.selectedIndex].href;
                closePalette();
            }
        } else if (e.key === 'Escape') {
            closePalette();
        } else if (e.key === 'Tab') {
            e.preventDefault();
            input.focus();
        }
    });

    // Live search
    input?.addEventListener('input', (e) => {
        filterPalette(e.target.value);
    });

    // Close on overlay click
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) closePalette(e);
    });
});

function highlightPaletteItem(items) {
    items.forEach((el, i) => {
        el.classList.toggle('selected', i === paletteData.selectedIndex);
        el.setAttribute('aria-selected', i === paletteData.selectedIndex ? 'true' : 'false');
        if (i === paletteData.selectedIndex) el.scrollIntoView({ block: 'nearest' });
    });
}
