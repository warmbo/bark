/** Logging workspace — recent audit-log reader. Loaded only on the logging
 * module detail page (see pages/module_detail.html). Renders Bark's own
 * recorded events (message edits/deletes/links, joins/leaves, voice state)
 * from the shared audit_logs table via /modules/logging/logs.
 */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace[data-module-name="logging"]');
  if (!root) return;

  const guildId = root.dataset.guildId;
  const api = (path) => `/api/v1/guilds/${guildId}/modules/logging/${path}`;
  const byId = (id) => document.getElementById(id);
  const loading = (container, count = 2) => { if (container) showSkeleton(container, count, 'card'); };
  const state = renderStatePanel;
  const table = renderDataTable;
  const formatDate = (value, withTime = false) => value ? new Date(value)[withTime ? 'toLocaleString' : 'toLocaleDateString']() : '—';

  const ACTION_ICONS = {
    message_edit: '✏️', message_delete: '🗑️', link_posted: '🔗',
    member_join: '👋', member_leave: '🚪', voice_state: '🎙️',
    file_upload: '📎', warn: '⚠️', kick: '👢', ban: '🔨', timeout: '⏱',
  };

  async function loadLogs() {
    const container = byId('logging-logs-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('logs?limit=50'), {cache: 'no-cache'});
      const data = raw.data || raw;
      const items = data.entries || [];
      if (!items.length) {
        container.innerHTML = state('empty', 'No logs yet', 'Events will appear here as the module records them.', 'logs');
        refreshIcons(); return;
      }
      const rows = items.map(e => {
        const detail = e.details || {};
        let extra = '';
        if (e.action === 'message_edit' && (detail.before !== undefined || detail.after !== undefined)) {
          extra = `<small>${escHtml((detail.before || '') || '')} → ${escHtml((detail.after || '') || '')}</small>`;
        } else if (e.action === 'message_delete' && detail.before) {
          extra = `<small>${escHtml(detail.before)}</small>`;
        } else if (e.action === 'link_posted' && Array.isArray(detail.links)) {
          extra = `<small>${escHtml(detail.links.slice(0, 3).join(' · '))}</small>`;
        } else if (e.action === 'voice_state' && detail.before_channel) {
          extra = `<small>${escHtml(detail.before_channel)} → ${escHtml(detail.after_channel || 'left')}</small>`;
        } else if (e.channel) {
          extra = `<small>${escHtml(e.channel)}</small>`;
        }
        return `<tr>
          <td><span class="badge badge-muted">${escHtml(ACTION_ICONS[e.action] || '📝')} ${escHtml(String(e.action || '').replace(/_/g, ' '))}</span></td>
          <td>${escHtml(e.actor || 'Unknown')}</td>
          <td>${escHtml(e.target || '—')}</td>
          <td class="cell-truncate" title="${escHtml(String(e.details?.before || e.details?.after || e.channel || ''))}">${extra || '—'}</td>
          <td class="timestamp">${formatDate(e.created_at, true)}</td>
        </tr>`;
      }).join('');
      container.innerHTML = table(['Event', 'Actor', 'Target', 'Details', 'When'], rows);
      refreshIcons();
    } catch (error) {
      container.innerHTML = state('error', 'Logs unavailable', error.message || 'The log could not be loaded.', 'logs');
      refreshIcons();
    }
  }

  const loaders = { logs: loadLogs };

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target)) return;
    if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
  });

  Object.entries(loaders).forEach(([name, loader]) => {
    byId(`workspace-tab-${name}`)?.addEventListener('click', () => loader());
  });

  // Initial load for the active tab
  const activeTab = root.querySelector('.tab-panel:not([hidden])');
  if (activeTab) {
    const section = activeTab.querySelector('[data-section]')?.dataset.section;
    if (section && loaders[section]) loaders[section]();
  } else {
    Object.values(loaders).forEach(loader => loader());
  }
})();
