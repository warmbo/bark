/** Bark keyboard shortcuts — shared, focus-safe global bindings. */
document.addEventListener('keydown', (event) => {
    const tag = event.target.tagName;
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target.isContentEditable;
    if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        // On the server dashboard, Ctrl/Cmd+K focuses the server search — the
        // search bar advertises `Ctrl K` and that's the page's primary action.
        // On any other page (or when the search input is absent) it opens the
        // global command palette.
        const serverSearch = document.getElementById('server-search');
        if (serverSearch) {
            serverSearch.focus();
            serverSearch.select();
            return;
        }
        const overlay = document.getElementById('palette-overlay');
        if (overlay?.classList.contains('visible')) closePalette(); else openPalette();
        return;
    }
    if (event.key === 'Escape') {
        const palette = document.getElementById('palette-overlay');
        if (palette?.classList.contains('visible')) { closePalette(); return; }
        document.querySelectorAll('.context-menu.visible, .overflow-dropdown.open').forEach((node) => node.classList.remove('visible', 'open'));
        return;
    }
    if (event.key === '?' && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        BarkDialog.confirm({
            title: 'Keyboard shortcuts',
            message: 'Ctrl or Command + K: command palette. Arrow keys, Home, and End: move through tabs. Escape: close the current overlay. Question mark: show this help.',
            confirmLabel: 'Close'
        });
    }
});

document.addEventListener('click', (event) => {
    if (event.target.closest('[data-open-palette]')) openPalette();
});
