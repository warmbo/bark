/** Reputation workspace — leaderboard, thanks log, and tier management. */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace[data-module-name="reputation"]');
  if (!root) return;

  const guildId = root.dataset.guildId;
  const api = (path) => `/api/v1/guilds/${guildId}/modules/reputation/${path}`;
  const byId = (id) => document.getElementById(id);
  const loading = (container, count = 2) => { if (container) showSkeleton(container, count, 'card'); };
  const statePanel = renderStatePanel;
  const formatDate = (value) => value ? new Date(value).toLocaleString() : '—';

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

  // ── Tiers ───────────────────────────────────────────

  async function loadTiers() {
    const container = byId('rep-tiers-content');
    if (!container) return;
    loading(container);
    try {
      const [tiersRes, rolesRes] = await Promise.all([
        safeFetch(api('tiers'), {cache: 'no-cache'}),
        safeFetch(`/api/v1/guilds/${guildId}/roles`, {cache: 'no-cache'}),
      ]);
      const tiers = (tiersRes.data || tiersRes).tiers || [];
      const roles = (rolesRes.data || rolesRes).roles || [];
      window.__repTierRoles = roles;
      if (!tiers.length) {
        container.innerHTML = statePanel('empty', 'No tiers configured', 'Tiers will be created automatically for this guild.', 'tiers');
        refreshIcons(); return;
      }
      const roleOptions = (selectedId) => ['<option value="">— no role —</option>']
        .concat(roles.map(r => `<option value="${escHtml(r.id)}"${String(r.id) === String(selectedId) ? ' selected' : ''}>${escHtml(r.name)}</option>`))
        .join('');
      const rows = tiers.map((t) => `<tr>
        <td><input class="form-input form-input-sm tier-symbol" value="${escHtml(t.symbol)}" aria-label="Tier symbol" size="3"></td>
        <td><input class="form-input form-input-sm tier-name" value="${escHtml(t.name)}" aria-label="Tier name"></td>
        <td><input type="number" min="0" class="form-input form-input-sm tier-level" value="${Number(t.min_level)}" aria-label="Min level"></td>
        <td><input type="number" min="0" step="0.5" class="form-input form-input-sm tier-score" value="${Number(t.min_score)}" aria-label="Min score"></td>
        <td><input type="text" class="form-input form-input-sm tier-color" value="${escHtml(t.color_hex)}" aria-label="Tier color" size="8"></td>
        <td><select class="form-select form-select-sm tier-role" aria-label="Linked role">${roleOptions(t.role_id)}</select></td>
        <td><input type="checkbox" class="tier-assign" ${t.assign_role ? 'checked' : ''} aria-label="Auto-assign role on level-up" title="Auto-assign: grant this role automatically when a member reaches this tier's level"></td>
        <td><button type="button" class="btn btn-sm tier-save" data-name="${escHtml(t.name)}">Save</button>
            <button type="button" class="btn btn-sm btn-danger tier-delete" data-name="${escHtml(t.name)}" aria-label="Delete tier">Delete</button></td>
      </tr>`).join('');
      container.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr>
        <th>Symbol</th><th>Name</th><th>Min Level</th><th>Min Score</th><th>Color</th><th>Linked Role</th><th>Auto</th><th></th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
      refreshIcons();
    } catch (error) {
      container.innerHTML = statePanel('error', 'Tiers unavailable', error.message || 'Could not load tiers.', 'tiers');
      refreshIcons();
    }
  }

  function addTierRow() {
    const container = byId('rep-tiers-content');
    if (!container) return;
    const tbody = container.querySelector('tbody');
    const roles = window.__repTierRoles || [];
    const roleOptions = (selectedId) => ['<option value="">— no role —</option>']
      .concat(roles.map(r => `<option value="${escHtml(r.id)}"${String(r.id) === String(selectedId) ? ' selected' : ''}>${escHtml(r.name)}</option>`))
      .join('');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class="form-input form-input-sm tier-symbol" value="⭐" aria-label="Tier symbol" size="3"></td>
      <td><input class="form-input form-input-sm tier-name" value="" placeholder="New tier name" aria-label="Tier name"></td>
      <td><input type="number" min="0" class="form-input form-input-sm tier-level" value="0" aria-label="Min level"></td>
      <td><input type="number" min="0" step="0.5" class="form-input form-input-sm tier-score" value="0" aria-label="Min score"></td>
      <td><input type="text" class="form-input form-input-sm tier-color" value="#99aab5" aria-label="Tier color" size="8"></td>
      <td><select class="form-select form-select-sm tier-role" aria-label="Linked role">${roleOptions(null)}</select></td>
      <td><input type="checkbox" class="tier-assign" aria-label="Auto-assign role on level-up" title="Auto-assign: grant this role automatically when a member reaches this tier's level"></td>
      <td><button type="button" class="btn btn-sm btn-primary tier-save" data-new="true">Save</button></td>`;
    if (tbody) tbody.appendChild(tr);
    tr.querySelector('.tier-name').focus();
  }

  async function saveTier(row) {
    const isNew = row.querySelector('.tier-save').dataset.new === 'true';
    const originalName = row.querySelector('.tier-save').dataset.name || '';
    const payload = {
      name: row.querySelector('.tier-name').value.trim(),
      symbol: row.querySelector('.tier-symbol').value,
      min_level: Number(row.querySelector('.tier-level').value || 0),
      min_score: Number(row.querySelector('.tier-score').value || 0),
      color_hex: row.querySelector('.tier-color').value,
      role_id: row.querySelector('.tier-role').value || null,
      assign_role: row.querySelector('.tier-assign').checked,
    };
    if (!payload.name) { showToast('Tier name is required', 'error'); return; }
    try {
      const result = await safeFetch(api(`tiers${isNew ? '' : `/${encodeURIComponent(originalName)}`}`), {
        method: isNew ? 'POST' : 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (result.success === false) throw new Error(result.error || 'Save failed');
      showToast(`Tier ${payload.name} ${isNew ? 'created' : 'saved'}`, 'success');
      loadTiers();
    } catch (error) {
      showToast(error.message || 'Unable to save tier', 'error');
    }
  }

  async function deleteTier(name) {
    const ok = await BarkDialog.confirm({
      title: `Delete tier "${name}"?`,
      message: 'Members who reached this tier keep their role; profiles that referenced it are re-tiered, and rewards gated on it are cleared. This cannot be undone from the dashboard.',
      confirmLabel: 'Delete tier',
      danger: true,
    });
    if (!ok) return;
    try {
      const result = await safeFetch(api(`tiers/${encodeURIComponent(name)}`), { method: 'DELETE' });
      if (result.success === false) throw new Error(result.error || 'Delete failed');
      showToast(`Tier ${name} deleted`, 'success');
      loadTiers();
    } catch (error) {
      showToast(error.message || 'Unable to delete tier', 'error');
    }
  }

  async function generateTierRoles() {
    const ok = await BarkDialog.confirm({
      title: 'Generate Discord roles for tiers?',
      message: 'The bot creates one role per tier that has none linked, names it after the tier, colors it with the tier color, and links it with auto-assign turned on. The bot needs the Manage Roles permission.',
      confirmLabel: 'Generate roles',
      danger: false,
    });
    if (!ok) return;
    try {
      const result = await safeFetch(api('tiers/generate-roles'), { method: 'POST' });
      if (result.success === false) throw new Error(result.error || 'Generation failed');
      const data = result.data || {};
      const created = (data.created || []).length;
      const skipped = (data.skipped || []).length;
      showToast(`Created ${created} role(s)${skipped ? `, skipped ${skipped}` : ''}`, created ? 'success' : 'info');
      loadTiers();
    } catch (error) {
      showToast(error.message || 'Unable to generate roles', 'error');
    }
  }

  // ── Event wiring ──────────────────────────────────────

  const loaders = { leaderboard: loadLeaderboard, thanks: loadThanks, tiers: loadTiers };

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target)) return;
    if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
    if (target.dataset.generateTierRoles !== undefined) generateTierRoles();
    if (target.dataset.addTier !== undefined) addTierRow();
    if (target.classList.contains('tier-save')) saveTier(target.closest('tr'));
    if (target.classList.contains('tier-delete')) deleteTier(target.dataset.name);
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
