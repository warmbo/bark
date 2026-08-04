/** Role manager workspace — rules CRUD and assignment log. */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace[data-module-name="role_manager"]');
  if (!root) return;

  const guildId = root.dataset.guildId;
  const canManage = root.dataset.canManage === 'true';
  const api = (path) => `/api/v1/guilds/${guildId}/modules/role_manager/${path}`;
  const byId = (id) => document.getElementById(id);
  const icon = (name, size = 13) => typeof getIconSvg === 'function' ? getIconSvg(name, size) : '';
  const loading = (container, count = 2) => { if (container) showSkeleton(container, count, 'card'); };
  const formatDate = (value) => value ? new Date(value).toLocaleString() : '—';
  const state = renderStatePanel;

  const RULE_LABELS = {
    welcome: 'Welcome', tenure: 'Tenure', voice: 'Voice', stream: 'Stream', reaction: 'Reaction',
  };
  const RULE_ORDER = ['welcome', 'tenure', 'voice', 'stream', 'reaction'];

  // Rules -----------------------------------------------------------------
  let rules = [];
  const ruleForm = byId('rm-rule-form');

  function closeRuleForm() {
    if (!ruleForm) return;
    ruleForm.reset();
    byId('rm-rule-id').value = '';
    byId('rm-rule-form').hidden = true;
    byId('rm-rule-save').innerHTML = `${icon('save', 14)} Save rule`;
    refreshIcons();
  }
  function openRuleForm(rule = null) {
    if (!ruleForm) return;
    ruleForm.hidden = false;
    byId('rm-rule-id').value = rule?.id || '';
    byId('rm-rule-name').value = rule?.name || '';
    byId('rm-rule-type').value = rule?.rule_type || 'welcome';
    byId('rm-rule-role').value = rule?.role_id || '';
    byId('rm-rule-enabled').checked = rule ? rule.enabled !== false : true;
    byId('rm-rule-remove').checked = rule ? rule.remove_when_inactive !== false : true;
    const cfg = rule?.trigger_config || {};
    byId('rm-tenure-days').value = cfg.days_required || 30;
    byId('rm-reaction-channel').value = cfg.channel_id || '';
    byId('rm-reaction-message').value = cfg.message_id || '';
    byId('rm-reaction-emoji').value = cfg.emoji || '';
    syncRuleFields();
    const saveBtn = byId('rm-rule-save');
    saveBtn.disabled = false;
    saveBtn.innerHTML = `${icon('save', 14)} ${rule ? 'Save changes' : 'Save rule'}`;
    byId('rm-rule-name').focus();
    refreshIcons();
  }
  function syncRuleFields() {
    const type = byId('rm-rule-type').value;
    const isReaction = type === 'reaction';
    byId('rm-tenure-days-group').hidden = type !== 'tenure';
    byId('rm-reaction-channel-group').hidden = !isReaction;
    byId('rm-reaction-message-group').hidden = !isReaction;
    byId('rm-reaction-emoji-group').hidden = !isReaction;
    // "Remove when inactive" only applies to conditional triggers.
    const removeRelevant = ['voice', 'stream', 'reaction'].includes(type);
    byId('rm-rule-remove-group').hidden = !removeRelevant;
    ['rm-tenure-days', 'rm-reaction-channel', 'rm-reaction-message', 'rm-reaction-emoji', 'rm-rule-remove'].forEach(id => {
      byId(id).disabled = byId(id).closest('.form-group').hidden;
    });
  }

  async function loadRules() {
    const container = byId('rm-rules-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('rules'), {cache: 'no-cache'});
      rules = raw.data?.rules || raw.rules || [];
      if (!rules.length) {
        container.innerHTML = state('empty', 'No role rules', canManage ? 'Create a rule to start managing roles automatically.' : 'An administrator can create role rules here.', 'rules');
        refreshIcons(); return;
      }
      const rows = rules.map(r => renderRuleRow(r)).join('');
      container.innerHTML = renderDataTable(['Rule', 'Trigger', 'Role', 'Behavior', 'Release', 'Status', 'Actions'], rows);
      refreshIcons();
    } catch (error) {
      container.innerHTML = state('error', 'Rules unavailable', error.message || 'Could not load role rules.', 'rules');
      refreshIcons();
    }
  }
  function renderRuleRow(r) {
    const type = String(r.rule_type).replace(/[^a-z0-9_-]/gi, '');
    const cfg = r.trigger_config || {};
    const paused = r.enabled === false;
    const behavior = ruleBehavior(r, cfg);
    const remove = ['welcome', 'tenure'].includes(r.rule_type)
      ? 'Not applicable'
      : (r.remove_when_inactive !== false ? 'Removed when condition ends' : 'Add only');
    const status = paused
      ? '<span class="status-badge status-warning"><span class="status-indicator" aria-hidden="true"></span>Paused</span>'
      : '<span class="status-badge status-success"><span class="status-indicator" aria-hidden="true"></span>Enabled</span>';
    const actions = canManage
      ? `<div class="table-actions"><button type="button" class="btn btn-sm" data-edit-rule="${Number(r.id)}">${icon('edit-3')} Edit</button><button type="button" class="btn btn-sm btn-danger" data-delete-rule="${Number(r.id)}" aria-label="Delete rule ${escHtml(r.name)}">${icon('trash-2')}</button></div>`
      : '—';
    return `<tr>
      <td><strong>${escHtml(r.name)}</strong></td>
      <td><span class="badge badge-sm">${escHtml(RULE_LABELS[r.rule_type] || r.rule_type)}</span></td>
      <td><code>${escHtml(r.role_id)}</code></td>
      <td class="cell-truncate" title="${escHtml(String(behavior).replace(/<[^>]*>/g, ''))}">${behavior}</td>
      <td>${escHtml(remove)}</td>
      <td>${status}</td>
      <td>${actions}</td>
    </tr>`;
  }
  function ruleBehavior(r, cfg) {
    if (r.rule_type === 'tenure') return `Add after <strong>${cfg.days_required || 30} days</strong> in the server`;
    if (r.rule_type === 'reaction') {
      const emoji = escHtml(cfg.emoji || '⭐');
      const msg = cfg.message_id ? ` on message <code>${escHtml(cfg.message_id)}</code>` : '';
      return `React ${emoji} in channel <code>${escHtml(cfg.channel_id || '?')}</code>${msg}`;
    }
    if (r.rule_type === 'voice') return 'Add while connected to a voice channel';
    if (r.rule_type === 'stream') return 'Add while live on Twitch (linked account)';
    return 'Add immediately when a member joins';
  }

  async function saveRule(event) {
    event.preventDefault();
    if (!ruleForm.reportValidity()) return;
    const id = byId('rm-rule-id').value;
    const type = byId('rm-rule-type').value;
    const payload = {
      name: byId('rm-rule-name').value.trim(),
      rule_type: type,
      role_id: byId('rm-rule-role').value,
      enabled: byId('rm-rule-enabled').checked,
      remove_when_inactive: byId('rm-rule-remove').checked,
      trigger_config: {},
    };
    if (type === 'tenure') payload.trigger_config.days_required = Number(byId('rm-tenure-days').value) || 30;
    if (type === 'reaction') {
      payload.trigger_config.channel_id = byId('rm-reaction-channel').value;
      payload.trigger_config.message_id = byId('rm-reaction-message').value.trim();
      payload.trigger_config.emoji = byId('rm-reaction-emoji').value.trim();
      if (!payload.trigger_config.channel_id || !payload.trigger_config.emoji) {
        showToast('Reaction channel and emoji are required', 'error'); return;
      }
    }
    const button = byId('rm-rule-save');
    const idle = button.innerHTML;
    button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = 'Saving…';
    try {
      await safeFetch(api(id ? `rules/${id}` : 'rules'), {method: id ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      showToast(id ? 'Rule updated' : 'Rule created', 'success');
      closeRuleForm(); await loadRules();
    } catch (error) {
      showToast(error.message || 'Unable to save rule', 'error');
    } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = idle; }
  }
  async function deleteRule(button) {
    const rule = rules.find(r => String(r.id) === button.dataset.deleteRule);
    if (!await BarkDialog.confirm({title: `Delete “${rule?.name || 'this rule'}”?`, message: 'The role will no longer be managed automatically. This cannot be undone.', confirmLabel: 'Delete rule', danger: true})) return;
    const idle = button.innerHTML; button.disabled = true; button.setAttribute('aria-busy', 'true');
    try {
      await safeFetch(api(`rules/${button.dataset.deleteRule}`), {method: 'DELETE'});
      showToast('Rule deleted', 'success'); await loadRules();
    } catch (error) { showToast(error.message || 'Unable to delete rule', 'error'); }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); button.innerHTML = idle; }
  }

  // Assignments -----------------------------------------------------------
  async function loadAssignments() {
    const container = byId('rm-assignments-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('assignments?limit=100'), {cache: 'no-cache'});
      const items = raw.data?.assignments || raw.assignments || [];
      if (!items.length) {
        container.innerHTML = state('empty', 'No assignments yet', 'Role changes made by the module will appear here.', 'assignments');
        refreshIcons(); return;
      }
      const rows = items.map(a => `<tr>
        <td>${escHtml(a.user_name || a.user_id)}${a.user_name && a.user_name !== a.user_id ? `<code class="cell-muted">${escHtml(a.user_id)}</code>` : ''}</td>
        <td>${escHtml(a.role_name || a.role_id)}${a.role_name && a.role_name !== a.role_id ? `<code class="cell-muted">${escHtml(a.role_id)}</code>` : ''}</td>
        <td><span class="badge ${a.action === 'add' ? 'badge-ok' : 'badge-warn'}">${a.action === 'add' ? 'Added' : 'Removed'}</span></td>
        <td class="cell-truncate" title="${escHtml(a.reason || '')}">${escHtml(a.reason || (a.rule_name ? a.rule_name : '—'))}</td>
        <td class="timestamp">${formatDate(a.created_at)}</td>
      </tr>`).join('');
      container.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr><th>User</th><th>Role</th><th>Action</th><th>Reason</th><th>When</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      refreshIcons();
    } catch (error) {
      container.innerHTML = state('error', 'Assignments unavailable', error.message || 'Could not load assignment log.', 'assignments');
      refreshIcons();
    }
  }

  const loaders = { rules: loadRules, assignments: loadAssignments };

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target || !root.contains(target)) return;
    if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
    else if (target.id === 'rm-new-rule-btn') openRuleForm();
    else if (target.id === 'rm-rule-cancel') closeRuleForm();
    else if (target.dataset.editRule) openRuleForm(rules.find(r => String(r.id) === target.dataset.editRule));
    else if (target.dataset.deleteRule) deleteRule(target);
  });
  document.addEventListener('change', (event) => {
    if (event.target.id === 'rm-rule-type') syncRuleFields();
  });
  document.addEventListener('submit', (event) => {
    if (event.target === ruleForm) saveRule(event);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && ruleForm && !ruleForm.hidden) closeRuleForm();
  });
  Object.entries(loaders).forEach(([name, loader]) => {
    byId(`workspace-tab-${name}`)?.addEventListener('click', () => loader());
  });

  // Initial loads
  Object.values(loaders).forEach(loader => loader());
})();
