/** Reputation workspace — leaderboard, thanks log, and tier management. */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace[data-module-name="reputation"]');
  if (!root) return;

  const guildId = root.dataset.guildId;
  const api = (path) => `/api/v1/guilds/${guildId}/modules/reputation/${path}`;
  const byId = (id) => document.getElementById(id);
  const icon = (name, size = 13) => typeof getIconSvg === 'function' ? getIconSvg(name, size) : '';
  const loading = (container, count = 2) => { if (container) showSkeleton(container, count, 'card'); };
  const statePanel = (kind, title, message, section) => `
    <div class="state-panel state-${kind}" role="${kind === 'error' ? 'alert' : 'status'}">
      <span class="state-panel-icon" aria-hidden="true">${icon(kind === 'error' ? 'alert-circle' : 'inbox', 18)}</span>
      <div><strong>${escHtml(title)}</strong><p>${escHtml(message || '')}</p></div>
      ${section ? `<button type="button" class="btn btn-sm" data-refresh-section="${section}">Retry</button>` : ''}
    </div>`;
  const formatDate = (value) => value ? new Date(value).toLocaleString() : '—';
  const refreshIcons = () => { if (window.lucide?.createIcons) window.lucide.createIcons(); };

  // ── Leaderboard ───────────────────────────────────────

  async function loadLeaderboard() {
    const container = byId('rep-leaderboard-content');
    if (!container) return;
    const limitSelect = byId('rep-leaderboard-limit');
    const limit = limitSelect ? Number(limitSelect.value) : 25;
    loading(container);
    try {
      const raw = await safeFetch(api(`leaderboard?limit=${limit}`), {cache: 'no-cache'});
      const data = raw.data || raw;
      const items = data.leaderboard || [];
      if (!items.length) {
        container.innerHTML = statePanel('empty', 'No rankings yet', 'Members will appear here as they earn reputation.', 'leaderboard');
        refreshIcons(); return;
      }
      const rows = items.map(m => `<tr>
        <td><strong>#${m.rank}</strong></td>
        <td><span class="rank-symbol" style="color:${escHtml(m.color_hex || '#99aab5')}">${escHtml(m.symbol || '⬜')}</span></td>
        <td><div class="member-info">${m.avatar ? `<span class="member-avatar-sm"><img src="${escHtml(m.avatar)}" alt="" class="avatar-sm"></span>` : ''}<strong>${escHtml(m.tag)}</strong></div></td>
        <td>Level ${m.level}</td>
        <td>${m.tier}</td>
        <td><strong>${Number(m.total_score).toLocaleString()}</strong></td>
      </tr>`).join('');
      container.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr>
        <th>#</th><th></th><th>Member</th><th>Level</th><th>Tier</th><th>Score</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
      refreshIcons();
    } catch (error) {
      container.innerHTML = statePanel('error', 'Leaderboard unavailable', error.message || 'Could not load rankings.', 'leaderboard');
      refreshIcons();
    }
  }

  // ── Thanks Log ────────────────────────────────────────

  let thanksData = [];
  async function loadThanks() {
    const container = byId('rep-thanks-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('thanks?limit=100'), {cache: 'no-cache'});
      const data = raw.data || raw;
      thanksData = data.thanks || [];
      renderThanks('');
    } catch (error) {
      container.innerHTML = statePanel('error', 'Thanks log unavailable', error.message || 'Could not load thanks.', 'thanks');
      refreshIcons();
    }
  }

  function renderThanks(filter) {
    const container = byId('rep-thanks-content');
    if (!container) return;
    const needle = filter.toLowerCase();
    const filtered = needle ? thanksData.filter(t =>
      (t.actor_id || '').includes(needle) || (t.target_id || '').includes(needle)
    ) : thanksData;
    if (!filtered.length) {
      container.innerHTML = statePanel('empty', 'No thanks yet', needle ? 'No matching entries found.' : 'Thanks will appear here as members use the /thanks command.', 'thanks');
      refreshIcons(); return;
    }
    const rows = filtered.map(t => `<tr>
      <td>${escHtml(t.event_type === 'thanks' ? '🙏 Received' : '🤝 Given')}</td>
      <td><code>${escHtml(t.actor_id || '—')}</code></td>
      <td><code>${escHtml(t.target_id || '—')}</code></td>
      <td><strong>+${Number(t.points)}</strong></td>
      <td class="cell-truncate" title="${escHtml(t.reason || '')}">${escHtml(t.reason || '—')}</td>
      <td class="timestamp">${formatDate(t.created_at)}</td>
    </tr>`).join('');
    container.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr>
      <th>Type</th><th>From</th><th>To</th><th>Points</th><th>Reason</th><th>Date</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`;
    refreshIcons();
  }

  // ── Event wiring ──────────────────────────────────────

  const loaders = { leaderboard: loadLeaderboard, thanks: loadThanks };

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target)) return;
    if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
  });

  document.addEventListener('change', (event) => {
    if (event.target.id === 'rep-leaderboard-limit') loadLeaderboard();
  });

  byId('rep-thanks-search')?.addEventListener('input', (event) => {
    renderThanks(event.target.value);
  });

  // Load data when tabs become visible
  Object.entries(loaders).forEach(([name, loader]) => {
    byId(`workspace-tab-${name}`)?.addEventListener('click', () => loader());
  });

  // Initial load for the active tab
  const activeTab = root.querySelector('.tab-panel:not([hidden])');
  if (activeTab) {
    const section = activeTab.querySelector('[data-section]')?.dataset.section;
    if (section && loaders[section]) loaders[section]();
  } else {
    // Load all on first visit
    Object.values(loaders).forEach(loader => loader());
  }
})();
