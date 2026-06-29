/*
 * Bark Dashboard — Main JavaScript
 * Lightweight interactivity, HTMX-free
 */

document.addEventListener('DOMContentLoaded', () => {
    // Tab switching
    document.querySelectorAll('[role="tablist"]').forEach(tablist => {
        const tabs = tablist.querySelectorAll('[role="tab"]');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const panelId = tab.getAttribute('aria-controls') || `tab-${tab.dataset.tab}`;
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                tablist.closest('.page-container')?.querySelectorAll('.tab-panel').forEach(p => {
                    p.classList.remove('active');
                });
                const panel = document.getElementById(panelId);
                if (panel) panel.classList.add('active');
            });
        });
    });

    // Module toggle buttons
    document.querySelectorAll('.module-toggle').forEach(toggle => {
        toggle.addEventListener('change', async (e) => {
            const moduleName = e.target.dataset.module;
            const enabled = e.target.checked;
            const guildId = new URLSearchParams(window.location.search).get('guild_id')
                || window.location.pathname.match(/\/guild\/(\d+)/)?.[1];

            if (!guildId) return;

            try {
                const res = await fetch(`/api/v1/guilds/${guildId}/modules/${moduleName}/toggle`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled })
                });
                const data = await res.json();
                if (!data.success) {
                    e.target.checked = !enabled;
                    console.error('Toggle failed:', data);
                }
            } catch (err) {
                e.target.checked = !enabled;
                console.error('Toggle error:', err);
            }
        });
    });

    // Auto-submitting forms via fetch
    document.querySelectorAll('.settings-form').forEach(form => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());

            const guildId = window.location.pathname.match(/\/guild\/(\d+)/)?.[1];
            if (!guildId) return;

            // Determine endpoint from form context
            const tabPanel = form.closest('.tab-panel');
            let endpoint = 'general';
            if (tabPanel?.id === 'tab-logging') endpoint = 'logging';
            if (tabPanel?.id === 'tab-automod') endpoint = 'automod';

            try {
                const res = await fetch(`/api/v1/guilds/${guildId}/settings/${endpoint}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                if (result.success) {
                    showToast('Settings saved successfully');
                } else {
                    showToast('Failed to save settings', 'error');
                }
            } catch (err) {
                showToast('Network error saving settings', 'error');
                console.error(err);
            }
        });
    });
});

// ── Toast Notification ──────────────────────────────

function showToast(message, type = 'success') {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    Object.assign(toast.style, {
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        padding: '12px 20px',
        borderRadius: '8px',
        fontSize: '13px',
        fontWeight: '500',
        background: type === 'error' ? 'var(--red-muted)' : 'var(--green-muted)',
        color: type === 'error' ? 'var(--red)' : 'var(--green)',
        border: `1px solid ${type === 'error' ? 'var(--red-muted)' : 'var(--green-muted)'}`,
        zIndex: '9999',
        opacity: '0',
        transform: 'translateY(8px)',
        transition: 'all 200ms ease',
    });

    document.body.appendChild(toast);
    requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateY(0)';
    });

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(8px)';
        setTimeout(() => toast.remove(), 200);
    }, 2500);
}
