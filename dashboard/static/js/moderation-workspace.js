/** Moderation CRUD workspace. See docs/moderation-workflows.md. */
(() => {
  'use strict';
  const root = document.querySelector('.module-workspace[data-module-name="moderation"]');
  if (!root) return;

  const guildId = root.dataset.guildId;
  const canManage = root.dataset.canManage === 'true';
  const canModerate = canManage;
  const canAdmin = canManage;
  const api = (path) => `/api/v1/guilds/${guildId}/${path}`;
  const byId = (id) => document.getElementById(id);
  const icon = (name, size = 13) => typeof getIconSvg === 'function' ? getIconSvg(name, size) : '';
  const busy = (button, active, label) => {
    if (!button) return;
    if (active) {
      button.dataset.idleHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      if (label) button.textContent = label;
    } else {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (button.dataset.idleHtml) button.innerHTML = button.dataset.idleHtml;
      delete button.dataset.idleHtml;
    }
  };
  const loading = (container, count = 2) => { if (container) showSkeleton(container, count, 'card'); };
  const state = renderStatePanel;
  const table = renderDataTable;
  const formatDate = (value, withTime = false) => value ? new Date(value)[withTime ? 'toLocaleString' : 'toLocaleDateString']() : '—';

  // Cases -----------------------------------------------------------------
  let casesPage = 0;
  const casesPerPage = 25;
  async function loadCases(page = casesPage) {
    casesPage = Math.max(0, page);
    const container = byId('mod-cases-content');
    if (!container) return;
    loading(container);
    const pagination = byId('mod-cases-pagination');
    if (pagination) pagination.hidden = true;
    try {
      const raw = await safeFetch(api(`moderation/cases?page=${casesPage}&limit=${casesPerPage}`), {cache: 'no-cache'});
      const data = raw.data || raw;
      const items = data.items || data.cases || [];
      if (!items.length) {
        container.innerHTML = state('empty', casesPage ? 'No cases on this page' : 'No active cases', casesPage ? 'Go back to the previous page.' : 'New moderation actions will appear here.', 'cases');
        if (casesPage) { casesPage -= 1; await loadCases(casesPage); }
        return;
      }
      const rows = items.map(c => {
        const type = String(c.action_type || 'unknown');
        return `<tr>
          <td><strong>#${Number(c.case_number)}</strong></td><td><span class="badge badge-${type.replace(/[^a-z0-9_-]/gi, '')}">${escHtml(type)}</span></td>
          <td>${escHtml(c.target_tag || c.target_id || 'Unknown')}</td><td>${escHtml(c.moderator_tag || 'Unknown')}</td>
          <td class="cell-truncate" title="${escHtml(c.reason || 'No reason')}">${escHtml(c.reason || 'No reason')}</td><td class="timestamp">${formatDate(c.created_at)}</td>
          <td class="table-actions"><button type="button" class="btn btn-sm" data-view-case="${Number(c.case_number)}" aria-expanded="false">${icon('eye')} View</button>${canAdmin ? `<button type="button" class="btn btn-sm btn-danger" data-delete-case="${Number(c.case_number)}" aria-label="Delete case ${Number(c.case_number)}">${icon('trash-2')}</button>` : ''}</td>
        </tr><tr class="case-detail-row" data-case-detail="${Number(c.case_number)}" hidden><td colspan="7"><div class="case-detail-content"></div></td></tr>`;
      }).join('');
      container.innerHTML = table(['Case', 'Type', 'Target', 'Moderator', 'Reason', 'Date', 'Actions'], rows);
      const total = Number(data.total || items.length);
      const pages = Math.max(1, Number(data.pages || Math.ceil(total / casesPerPage)));
      if (pagination) pagination.hidden = pages <= 1;
      byId('mod-cases-prev').disabled = casesPage <= 0;
      byId('mod-cases-next').disabled = casesPage >= pages - 1;
      byId('mod-cases-info').textContent = `Page ${casesPage + 1} of ${pages} · ${total} total`;
      refreshIcons();
    } catch (error) {
      container.innerHTML = state('error', 'Cases unavailable', error.message || 'The case list could not be loaded.', 'cases');
      refreshIcons();
    }
  }

  async function viewCase(button) {
    const number = button.dataset.viewCase;
    const row = button.closest('tbody')?.querySelector(`tr[data-case-detail="${number}"]`);
    if (!row) return;
    if (!row.hidden) { row.hidden = true; button.setAttribute('aria-expanded', 'false'); return; }
    row.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    const content = row.querySelector('.case-detail-content');
    content.innerHTML = '<span class="text-secondary">Loading case details…</span>';
    busy(button, true, 'Loading…');
    try {
      const raw = await safeFetch(api(`moderation/cases/${number}`), {cache: 'no-cache'});
      const c = raw.data || raw;
      content.innerHTML = `<dl class="case-detail-grid"><div><dt>Target ID</dt><dd><code>${escHtml(c.target_id || '—')}</code></dd></div><div><dt>Moderator ID</dt><dd><code>${escHtml(c.moderator_id || '—')}</code></dd></div><div><dt>Duration</dt><dd>${c.duration == null ? '—' : `${escHtml(c.duration)} minutes`}</dd></div><div><dt>Status</dt><dd>${c.resolved ? 'Resolved' : 'Active'}</dd></div><div class="case-detail-reason"><dt>Reason</dt><dd>${escHtml(c.reason || 'No reason provided')}</dd></div></dl>`;
    } catch (error) {
      content.innerHTML = state('error', 'Case details unavailable', error.message, 'cases');
    } finally { busy(button, false); refreshIcons(); }
  }

  async function deleteCase(button) {
    const number = button.dataset.deleteCase;
    const confirmed = await BarkDialog.confirm({title: `Delete case #${number}?`, message: 'This removes the case from active views by marking it resolved. This cannot be undone from the dashboard.', confirmLabel: 'Delete case', danger: true});
    if (!confirmed) return;
    busy(button, true, 'Deleting…');
    try { await safeFetch(api(`moderation/cases/${number}`), {method: 'DELETE'}); showToast(`Case #${number} deleted`, 'success'); await loadCases(casesPage); }
    catch (error) { showToast(error.message || 'Unable to delete case', 'error'); busy(button, false); }
  }

  // Warnings --------------------------------------------------------------
  async function loadWarnings() {
    const container = byId('mod-warnings-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('moderation/warnings'), {cache: 'no-cache'});
      const warnings = raw.data?.warnings || raw.warnings || [];
      if (!warnings.length) { container.innerHTML = state('empty', 'No active warnings', 'Cleared and expired warnings are not shown here.', 'warnings'); refreshIcons(); return; }
      const rows = warnings.map(w => `<tr><td><strong>#${Number(w.id)}</strong></td><td><a class="member-link" href="${guildUrl('/members/' + encodeURIComponent(w.user_id))}"><code>${escHtml(w.user_id)}</code></a></td><td><code>${escHtml(w.moderator_id || '—')}</code></td><td class="cell-truncate" title="${escHtml(w.reason || 'No reason')}">${escHtml(w.reason || 'No reason')}</td><td class="timestamp">${formatDate(w.created_at)}</td><td>${canModerate ? `<button type="button" class="btn btn-sm btn-danger" data-clear-warning="${Number(w.id)}">${icon('x')} Clear</button>` : '<span class="badge badge-warn">Active</span>'}</td></tr>`).join('');
      container.innerHTML = table(['ID', 'Member', 'Moderator', 'Reason', 'Date', 'Action'], rows);
      refreshIcons();
    } catch (error) { container.innerHTML = state('error', 'Warnings unavailable', error.message || 'The warning list could not be loaded.', 'warnings'); refreshIcons(); }
  }

  async function clearWarning(button) {
    const id = button.dataset.clearWarning;
    if (!await BarkDialog.confirm({title: `Clear warning #${id}?`, message: 'The warning becomes inactive. Its associated moderation case remains available for audit.', confirmLabel: 'Clear warning', danger: true})) return;
    busy(button, true, 'Clearing…');
    try { await safeFetch(api(`moderation/warnings/${id}`), {method: 'DELETE'}); showToast(`Warning #${id} cleared`, 'success'); await loadWarnings(); }
    catch (error) { showToast(error.message || 'Unable to clear warning', 'error'); busy(button, false); }
  }

  // Notes -----------------------------------------------------------------
  let notes = [];
  const noteForm = byId('mod-note-form');
  function closeNoteForm() {
    if (!noteForm) return;
    noteForm.reset(); byId('mod-note-id').value = ''; byId('mod-note-user').disabled = false; noteForm.hidden = true;
    busy(byId('mod-note-save'), false);
    byId('mod-note-save').innerHTML = `${icon('save', 14)} Save note`; refreshIcons();
  }
  function openNoteForm(note = null) {
    if (!noteForm) return;
    noteForm.hidden = false;
    byId('mod-note-id').value = note?.id || '';
    byId('mod-note-user').value = note?.user_id || '';
    byId('mod-note-user').disabled = Boolean(note);
    byId('mod-note-text').value = note?.content || '';
    byId('mod-note-save').innerHTML = `${icon('save', 14)} ${note ? 'Save changes' : 'Save note'}`;
    byId(note ? 'mod-note-text' : 'mod-note-user').focus(); refreshIcons();
  }
  async function loadNotes() {
    const container = byId('mod-notes-content');
    if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('notes'), {cache: 'no-cache'});
      notes = raw.data?.notes || raw.notes || [];
      if (!notes.length) { container.innerHTML = state('empty', 'No notes yet', canModerate ? 'Add private context for the moderation team.' : 'Notes created by moderators will appear here.', 'notes'); refreshIcons(); return; }
      container.innerHTML = `<div class="notes-list">${notes.map(n => `<article class="note-item"><div class="note-item-header"><div class="note-meta">Member <a href="${guildUrl('/members/' + encodeURIComponent(n.user_id))}"><code>${escHtml(n.user_id)}</code></a> · by <code>${escHtml(n.author_id || 'dashboard')}</code> · ${formatDate(n.created_at, true)}</div>${canModerate ? `<div class="table-actions"><button type="button" class="btn btn-sm" data-edit-note="${Number(n.id)}">${icon('edit-3')} Edit</button><button type="button" class="btn btn-sm btn-danger" data-delete-note="${Number(n.id)}">${icon('trash-2')} Delete</button></div>` : ''}</div><div class="note-content">${escHtml(n.content)}</div></article>`).join('')}</div>`;
      refreshIcons();
    } catch (error) { container.innerHTML = state('error', 'Notes unavailable', error.message || 'The notes list could not be loaded.', 'notes'); refreshIcons(); }
  }
  async function saveNote(event) {
    event.preventDefault();
    if (!noteForm.reportValidity()) return;
    const id = byId('mod-note-id').value;
    const userId = byId('mod-note-user').value.trim();
    const content = byId('mod-note-text').value.trim();
    if ((!id && !userId) || !content) { showToast('Member and note content are required', 'error'); return; }
    const button = byId('mod-note-save'); busy(button, true, 'Saving…');
    try {
      await safeFetch(api(id ? `notes/${id}` : 'notes'), {method: id ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(id ? {content} : {user_id: userId, author_id: 'dashboard', content})});
      showToast(id ? 'Note updated' : 'Note created', 'success'); closeNoteForm(); await loadNotes();
    } catch (error) { showToast(error.message || 'Unable to save note', 'error'); busy(button, false); }
  }
  async function deleteNote(button) {
    const id = button.dataset.deleteNote;
    if (!await BarkDialog.confirm({title: 'Delete this note?', message: 'This permanently removes the private note. This action cannot be undone.', confirmLabel: 'Delete note', danger: true})) return;
    busy(button, true, 'Deleting…');
    try { await safeFetch(api(`notes/${id}`), {method: 'DELETE'}); showToast('Note deleted', 'success'); await loadNotes(); }
    catch (error) { showToast(error.message || 'Unable to delete note', 'error'); busy(button, false); }
  }

  // Rulesets --------------------------------------------------------------
  let rulesets = [];
  let wordlists = [];
  const normalizeEntries = (value) => {
    if (Array.isArray(value)) return value.map(String);
    if (!value) return [];
    try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed.map(String) : []; } catch { return String(value).split(/\r?\n/).filter(Boolean); }
  };
  async function fetchWordlists() {
    const raw = await safeFetch(api('wordlists'), {cache: 'no-cache'});
    wordlists = (raw.data?.wordlists || raw.wordlists || []).map(w => ({...w, entries: normalizeEntries(w.entries)}));
    return wordlists;
  }
  const triggerSummary = (config = {}) => [config.threshold ? `≥${config.threshold}` : '', config.window_seconds ? `${config.window_seconds}s` : '', config.pattern ? `/${config.pattern}/` : '', config.word_list_id ? (wordlists.find(w => String(w.id) === String(config.word_list_id))?.name || `list #${config.word_list_id}`) : ''].filter(Boolean).join(' · ');
  const triggerNames = {
    message_spam: 'Rapid messages (spam)', mass_mention: 'Excessive @mentions', invite_link: 'Discord invite link',
    banned_words: 'Banned words list', banned_domains: 'Banned domains list', scam_link: 'Known scam pattern',
    regex_match: 'Custom regex', duplicate_message: 'Repeated content', all_caps: 'Excessive caps',
    attachment_spam: 'Rapid file uploads', any_link: 'Any URL/link',
  };
  const effectDescriptions = {
    warn: 'Warning DM + delete', delete: 'Delete silently', timeout: 'Timeout / mute',
    kick: 'Kick', ban: 'Ban', alert: 'Alert channel', delete_multiple: 'Delete recent messages',
  };
  const fmtDur = (m) => { if (!m) return ''; if (m >= 1440) return `${m/1440}d`; if (m >= 60) return `${m/60}h`; return `${m}m`; };
  const conditionBadges = (sc) => {
    const tags = [];
    if (sc?.account_age_minutes_max > 0) tags.push(`<span class="badge badge-cond">Account < ${fmtDur(sc.account_age_minutes_max)}</span>`);
    if (sc?.account_age_minutes_min > 0) tags.push(`<span class="badge badge-cond">Account > ${fmtDur(sc.account_age_minutes_min)}</span>`);
    if (sc?.member_duration_minutes_max > 0) tags.push(`<span class="badge badge-cond">Joined < ${fmtDur(sc.member_duration_minutes_max)}</span>`);
    if (sc?.member_duration_minutes_min > 0) tags.push(`<span class="badge badge-cond">Joined > ${fmtDur(sc.member_duration_minutes_min)}</span>`);
    if (sc?.only_bots) tags.push(`<span class="badge badge-bot">Bots only</span>`);
    else if (sc?.ignore_bots === false) tags.push(`<span class="badge badge-cond">Includes bots</span>`);
    if (sc?.active_channels?.length) tags.push(`<span class="badge badge-cond">${sc.active_channels.length} channel(s)</span>`);
    if (sc?.active_categories?.length) tags.push(`<span class="badge badge-cond">${sc.active_categories.length} categor(ies)</span>`);
    if (sc?.ignored_roles?.length) tags.push(`<span class="badge badge-cond">${sc.ignored_roles.length} role(s) ignored</span>`);
    if (sc?.require_roles?.length) tags.push(`<span class="badge badge-cond">Requires ${sc.require_roles.length} role(s)</span>`);
    return tags.length ? `<div class="rs-condition-tags">${tags.join(' ')}</div>` : '';
  };
  async function loadRulesets() {
    const container = byId('rs-list-content'); if (!container) return;
    loading(container);
    try {
      const [raw] = await Promise.all([safeFetch(api('rulesets'), {cache: 'no-cache'}), fetchWordlists().catch(() => [])]);
      rulesets = raw.data?.rulesets || raw.rulesets || [];
      renderRulesets();
    } catch (error) { container.innerHTML = state('error', 'Rulesets unavailable', error.message || 'AutoMod policies could not be loaded.', 'rulesets'); refreshIcons(); }
  }
  function renderRulesets() {
    const container = byId('rs-list-content');
    if (!rulesets.length) { container.innerHTML = state('empty', 'No rulesets configured', canAdmin ? 'Create a ruleset or choose a quick setup preset.' : 'An administrator can create AutoMod policies here.', 'rulesets'); refreshIcons(); return; }
    container.innerHTML = `<div class="ruleset-list">${rulesets.map((rs, index) => `<section class="ruleset-card" data-ruleset-id="${Number(rs.id)}"><header class="ruleset-header"><div class="ruleset-heading">${canAdmin ? `<label class="toggle-switch" aria-label="Enable ${escHtml(rs.name)}"><input type="checkbox" data-toggle-ruleset="${Number(rs.id)}" ${rs.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>` : `<span class="status-indicator ${rs.enabled ? 'status-success' : ''}"></span>`}<div><h3>${escHtml(rs.name)}</h3><p>${(rs.rules || []).length} rule${(rs.rules || []).length === 1 ? '' : 's'} · priority ${Number(rs.priority ?? 100)} · ${rs.enabled ? 'enabled' : 'paused'}</p>${conditionBadges(rs.scoped_conditions)}</div></div>${canAdmin ? `<div class="card-header-actions"><button type="button" class="btn btn-sm" data-rename-ruleset="${Number(rs.id)}">${icon('edit-3')} Rename</button><button type="button" class="btn btn-sm" data-add-rule="${Number(rs.id)}">${icon('plus')} Add rule</button><button type="button" class="btn btn-sm btn-danger" data-delete-ruleset="${Number(rs.id)}">${icon('trash-2')} Delete</button></div>` : ''}</header>${(rs.rules || []).length ? table(['#', 'Trigger', 'Effect', 'Conditions', 'Action'], rs.rules.map((rule, ruleIndex) => `<tr><td>${ruleIndex + 1}</td><td><code>${escHtml(triggerNames[rule.trigger_type] || rule.trigger_type)}</code><small>${escHtml(triggerSummary(rule.trigger_config))}</small></td><td><span class="badge badge-${String(rule.effect_type).replace(/[^a-z0-9_-]/gi, '')}">${escHtml(effectDescriptions[rule.effect_type] || rule.effect_type)}</span>${rule.effect_config?.duration_minutes ? `<small>${Number(rule.effect_config.duration_minutes)}m</small>` : ''}</td><td>${Object.keys(rule.conditions || {}).length ? `${Object.keys(rule.conditions).length} rule condition(s)` : 'Ruleset defaults'}</td><td>${canAdmin ? `<button type="button" class="btn btn-sm" data-edit-rule="${Number(rule.id)}" data-ruleset-index="${index}">${icon('edit-3')} Edit</button>` : '—'}</td></tr>`).join('')) : state('empty', 'No rules in this ruleset', canAdmin ? 'Add a rule to start evaluating messages.' : 'This ruleset does not evaluate any messages.')}</section>`).join('')}</div>`;
    refreshIcons();
  }

  function openModal(id) { const modal = byId(id); if (!modal) return; modal.hidden = false; modal.setAttribute('aria-hidden', 'false'); modal.querySelector('input:not([type="hidden"]), select, button')?.focus(); }
  function closeModal(id) {
    const modal = byId(id); if (!modal) return;
    modal.querySelectorAll('[aria-busy="true"]').forEach(button => busy(button, false));
    modal.hidden = true; modal.setAttribute('aria-hidden', 'true');
  }
  function openRulesetName(rs = null) {
    byId('rs-name-id').value = rs?.id || ''; byId('rs-name-input').value = rs?.name || '';
    byId('rs-name-title').textContent = rs ? 'Rename ruleset' : 'New ruleset'; byId('rs-name-submit').textContent = rs ? 'Save name' : 'Create ruleset';
    openModal('rs-name-modal'); byId('rs-name-input').focus(); byId('rs-name-input').select();
  }
  async function saveRulesetName(event) {
    event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return;
    const id = byId('rs-name-id').value, name = byId('rs-name-input').value.trim(), button = byId('rs-name-submit');
    busy(button, true, 'Saving…');
    try { await safeFetch(api(id ? `rulesets/${id}` : 'rulesets'), {method: id ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(id ? {name} : {name, enabled: true, priority: 100})}); showToast(id ? 'Ruleset renamed' : 'Ruleset created', 'success'); closeModal('rs-name-modal'); await loadRulesets(); }
    catch (error) { showToast(error.message || 'Unable to save ruleset', 'error'); busy(button, false); }
  }
  async function toggleRuleset(input) {
    const enabled = input.checked; input.disabled = true;
    try { await safeFetch(api(`rulesets/${input.dataset.toggleRuleset}`), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled})}); showToast(`Ruleset ${enabled ? 'enabled' : 'paused'}`, 'success'); await loadRulesets(); }
    catch (error) { input.checked = !enabled; input.disabled = false; showToast(error.message || 'Unable to update ruleset', 'error'); }
  }
  async function deleteRuleset(button) {
    const rs = rulesets.find(item => String(item.id) === button.dataset.deleteRuleset);
    if (!await BarkDialog.confirm({title: `Delete “${rs?.name || 'this ruleset'}”?`, message: 'Every rule in this ruleset will be permanently deleted.', confirmLabel: 'Delete ruleset', danger: true})) return;
    busy(button, true, 'Deleting…');
    try { await safeFetch(api(`rulesets/${button.dataset.deleteRuleset}`), {method: 'DELETE'}); showToast('Ruleset deleted', 'success'); await loadRulesets(); }
    catch (error) { showToast(error.message || 'Unable to delete ruleset', 'error'); busy(button, false); }
  }

  const ruleEditor = byId('rs-editor-overlay');
  function syncRuleFields(selectedWordList = '') {
    const trigger = byId('rs-editor-trigger')?.value;
    const listTrigger = ['banned_words', 'banned_domains'].includes(trigger);
    byId('rs-editor-regex-box').hidden = trigger !== 'regex_match';
    byId('rs-editor-wordlist-box').hidden = !listTrigger;
    byId('rs-editor-duration-box').hidden = byId('rs-editor-effect').value !== 'timeout';
    const select = byId('rs-editor-wordlist');
    if (select && listTrigger) {
      const type = trigger === 'banned_domains' ? 'domain' : 'word';
      select.innerHTML = `<option value="">Select a ${type} list…</option>` + wordlists.filter(w => w.list_type === type).map(w => `<option value="${Number(w.id)}">${escHtml(w.name)} (${w.entries.length})</option>`).join('');
      select.value = String(selectedWordList || select.dataset.selected || '');
    }
  }
  function openRuleEditor(rulesetId, rule = null, rs = null) {
    if (!ruleEditor) return;
    byId('rs-editor-rsid').value = rulesetId; byId('rs-editor-ruleid').value = rule?.id || '';
    byId('rs-editor-title').textContent = rule ? 'Edit rule' : 'Add rule'; byId('rs-editor-trigger').value = rule?.trigger_type || 'message_spam'; byId('rs-editor-effect').value = rule?.effect_type || 'warn';
    byId('rs-editor-threshold').value = rule?.trigger_config?.threshold ?? 5; byId('rs-editor-window').value = rule?.trigger_config?.window_seconds ?? 10; byId('rs-editor-duration').value = rule?.effect_config?.duration_minutes ?? 10; byId('rs-editor-regex').value = rule?.trigger_config?.pattern || '';
    byId('rs-editor-wordlist').dataset.selected = rule?.trigger_config?.word_list_id || '';
    const age = Number(rs?.scoped_conditions?.account_age_minutes_max || 0); let unit = 'minutes', value = age;
    if (age && age % 1440 === 0) { unit = 'days'; value = age / 1440; } else if (age && age % 60 === 0) { unit = 'hours'; value = age / 60; }
    byId('rs-editor-ageval').value = value; byId('rs-editor-ageunit').value = unit; byId('rs-editor-ignorebots').value = rs?.scoped_conditions?.ignore_bots === false ? 'false' : 'true'; byId('rs-editor-del').hidden = !rule;
    syncRuleFields(rule?.trigger_config?.word_list_id || ''); ruleEditor.hidden = false; ruleEditor.setAttribute('aria-hidden', 'false'); byId('rs-editor-trigger').focus();
  }
  function closeRuleEditor() {
    if (!ruleEditor) return;
    ruleEditor.querySelectorAll('[aria-busy="true"]').forEach(button => busy(button, false));
    ruleEditor.hidden = true; ruleEditor.setAttribute('aria-hidden', 'true');
  }
  async function saveRule(event) {
    event.preventDefault(); if (!event.currentTarget.reportValidity()) return;
    const rsid = byId('rs-editor-rsid').value, ruleid = byId('rs-editor-ruleid').value, trigger = byId('rs-editor-trigger').value, effect = byId('rs-editor-effect').value;
    const threshold = Number(byId('rs-editor-threshold').value), windowSeconds = Number(byId('rs-editor-window').value), pattern = byId('rs-editor-regex').value.trim(), wordListId = byId('rs-editor-wordlist').value;
    if (trigger === 'regex_match') { if (!pattern) { showToast('A regular expression is required', 'error'); byId('rs-editor-regex').focus(); return; } try { new RegExp(pattern); } catch (error) { showToast(`Invalid regular expression: ${error.message}`, 'error'); byId('rs-editor-regex').focus(); return; } }
    if (['banned_words', 'banned_domains'].includes(trigger) && !wordListId) { showToast('Select a matching word list', 'error'); byId('rs-editor-wordlist').focus(); return; }
    const triggerConfig = {threshold, window_seconds: windowSeconds}; if (pattern && trigger === 'regex_match') triggerConfig.pattern = pattern; if (wordListId && ['banned_words', 'banned_domains'].includes(trigger)) triggerConfig.word_list_id = Number(wordListId);
    const effectConfig = effect === 'timeout' ? {duration_minutes: Number(byId('rs-editor-duration').value)} : {};
    const ageMultipliers = {minutes: 1, hours: 60, days: 1440}; const age = Number(byId('rs-editor-ageval').value) * ageMultipliers[byId('rs-editor-ageunit').value];
    const button = byId('rs-editor-save'); busy(button, true, 'Saving…');
    try {
      await safeFetch(api(ruleid ? `rulesets/${rsid}/rules/${ruleid}` : `rulesets/${rsid}/rules`), {method: ruleid ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({trigger_type: trigger, effect_type: effect, trigger_config: triggerConfig, effect_config: effectConfig, conditions: {}})});
      await safeFetch(api(`rulesets/${rsid}`), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({account_age_minutes_max: age, ignore_bots: byId('rs-editor-ignorebots').value === 'true'})});
      showToast(ruleid ? 'Rule updated' : 'Rule created', 'success'); closeRuleEditor(); await loadRulesets();
    } catch (error) { showToast(error.message || 'Unable to save rule', 'error'); busy(button, false); }
  }
  async function deleteRule(button) {
    const rsid = byId('rs-editor-rsid').value, ruleid = byId('rs-editor-ruleid').value; if (!ruleid) return;
    if (!await BarkDialog.confirm({title: 'Delete this rule?', message: 'Messages will no longer be evaluated by this trigger.', confirmLabel: 'Delete rule', danger: true})) return;
    busy(button, true, 'Deleting…');
    try { await safeFetch(api(`rulesets/${rsid}/rules/${ruleid}`), {method: 'DELETE'}); showToast('Rule deleted', 'success'); closeRuleEditor(); await loadRulesets(); }
    catch (error) { showToast(error.message || 'Unable to delete rule', 'error'); busy(button, false); }
  }
  const presets = {
    'new-account': {name: 'New Account Shield', conditions: {account_age_minutes_max: 2880}, rules: [{trigger_type: 'any_link', trigger_config: {threshold: 1}, effect_type: 'warn', effect_config: {}}, {trigger_type: 'scam_link', trigger_config: {}, effect_type: 'ban', effect_config: {}}]},
    scam: {name: 'Scam Protection', conditions: {}, rules: [{trigger_type: 'scam_link', trigger_config: {}, effect_type: 'ban', effect_config: {}}, {trigger_type: 'invite_link', trigger_config: {threshold: 1}, effect_type: 'warn', effect_config: {}}]},
    raid: {name: 'Raid Protection', conditions: {account_age_minutes_max: 1440}, rules: [{trigger_type: 'message_spam', trigger_config: {threshold: 5, window_seconds: 10}, effect_type: 'kick', effect_config: {}}, {trigger_type: 'mass_mention', trigger_config: {threshold: 10}, effect_type: 'ban', effect_config: {}}]},
  };
  async function createPreset(button) {
    const preset = presets[button.dataset.rulesetPreset]; if (!preset) return;
    let createdRulesetId = null;
    busy(button, true, 'Creating…');
    try {
      const created = await safeFetch(api('rulesets'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: preset.name, enabled: true, priority: 100})});
      createdRulesetId = created.data?.id || created.id;
      if (!createdRulesetId) throw new Error('The new ruleset ID was not returned');
      if (Object.keys(preset.conditions).length) await safeFetch(api(`rulesets/${createdRulesetId}`), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(preset.conditions)});
      for (const rule of preset.rules) await safeFetch(api(`rulesets/${createdRulesetId}/rules`), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...rule, conditions: {}})});
      showToast(`${preset.name} created`, 'success');
      await loadRulesets();
    } catch (error) {
      let cleanupFailed = false;
      if (createdRulesetId) {
        try {
          await safeFetch(api(`rulesets/${createdRulesetId}`), {method: 'DELETE'});
        } catch (cleanupError) {
          cleanupFailed = true;
          console.error('Preset cleanup failed', cleanupError);
        }
      }
      showToast(cleanupFailed ? `Preset partially created and cleanup failed: ${error.message}` : `Preset failed: ${error.message}`, 'error');
      await loadRulesets();
    } finally {
      busy(button, false);
    }
  }

  // Word lists ------------------------------------------------------------
  async function loadWordlists() {
    const container = byId('wl-list-content'); if (!container) return;
    loading(container);
    try { await fetchWordlists(); renderWordlists(); }
    catch (error) { container.innerHTML = state('error', 'Word lists unavailable', error.message || 'Reusable lists could not be loaded.', 'wordlists'); refreshIcons(); }
  }
  function renderWordlists() {
    const container = byId('wl-list-content');
    if (!wordlists.length) { container.innerHTML = state('empty', 'No word lists configured', canAdmin ? 'Create a list, then add one word, phrase, or domain per line.' : 'An administrator can create reusable AutoMod lists here.', 'wordlists'); refreshIcons(); return; }
    const rows = wordlists.map(w => `<tr class="wordlist-summary"><td><strong>${escHtml(w.name)}</strong></td><td><span class="badge">${w.list_type === 'domain' ? 'Domains' : 'Words'}</span></td><td>${w.entries.length}</td><td>${canAdmin ? `<div class="table-actions"><button type="button" class="btn btn-sm" data-edit-wordlist="${Number(w.id)}" aria-expanded="false">${icon('edit-3')} Edit</button><button type="button" class="btn btn-sm btn-danger" data-delete-wordlist="${Number(w.id)}">${icon('trash-2')} Delete</button></div>` : '—'}</td></tr><tr id="wordlist-editor-${Number(w.id)}" class="wordlist-editor-row" hidden><td colspan="4"><form data-wordlist-form="${Number(w.id)}"><div class="form-grid form-grid-2"><div class="form-group"><label class="form-label" for="wordlist-name-${Number(w.id)}">List name</label><input class="form-input" id="wordlist-name-${Number(w.id)}" value="${escHtml(w.name)}" maxlength="100" required></div><div class="form-group"><label class="form-label" for="wordlist-entries-${Number(w.id)}">Entries (one per line)</label><textarea class="form-input" id="wordlist-entries-${Number(w.id)}" rows="8" spellcheck="false" required>${escHtml(w.entries.join('\n'))}</textarea></div></div><div class="form-actions form-actions-static"><button type="button" class="btn" data-cancel-wordlist="${Number(w.id)}">Cancel</button><button type="submit" class="btn btn-primary">${icon('save')} Save list</button></div></form></td></tr>`).join('');
    container.innerHTML = table(['Name', 'Type', 'Entries', 'Actions'], rows); refreshIcons();
  }
  function toggleWordlistEditor(button) {
    const id = button.dataset.editWordlist, row = byId(`wordlist-editor-${id}`), opening = row.hidden;
    document.querySelectorAll('.wordlist-editor-row:not([hidden])').forEach(item => { item.hidden = true; }); document.querySelectorAll('[data-edit-wordlist]').forEach(item => item.setAttribute('aria-expanded', 'false'));
    row.hidden = !opening; button.setAttribute('aria-expanded', String(opening)); if (opening) byId(`wordlist-name-${id}`).focus();
  }
  async function saveWordlist(event) {
    event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return;
    const id = form.dataset.wordlistForm, button = form.querySelector('[type="submit"]'), name = byId(`wordlist-name-${id}`).value.trim(), entries = byId(`wordlist-entries-${id}`).value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
    busy(button, true, 'Saving…');
    try { await safeFetch(api(`wordlists/${id}`), {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, entries})}); showToast('Word list updated', 'success'); await loadWordlists(); }
    catch (error) { showToast(error.message || 'Unable to update word list', 'error'); busy(button, false); }
  }
  async function createWordlist(event) {
    event.preventDefault(); if (!event.currentTarget.reportValidity()) return;
    const button = byId('wl-modal-submit'), name = byId('wl-modal-name').value.trim(), listType = byId('wl-modal-type').value; busy(button, true, 'Creating…');
    try { await safeFetch(api('wordlists'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, list_type: listType, entries: []})}); showToast('Word list created', 'success'); closeModal('wl-modal'); event.currentTarget.reset(); await loadWordlists(); }
    catch (error) { showToast(error.message || 'Unable to create word list', 'error'); busy(button, false); }
  }
  async function deleteWordlist(button) {
    const list = wordlists.find(w => String(w.id) === button.dataset.deleteWordlist);
    if (!await BarkDialog.confirm({title: `Delete “${list?.name || 'this list'}”?`, message: 'Rules that reference this list may stop matching. The list and all entries will be permanently deleted.', confirmLabel: 'Delete list', danger: true})) return;
    busy(button, true, 'Deleting…');
    try { await safeFetch(api(`wordlists/${button.dataset.deleteWordlist}`), {method: 'DELETE'}); showToast('Word list deleted', 'success'); await Promise.all([loadWordlists(), loadRulesets()]); }
    catch (error) { showToast(error.message || 'Unable to delete word list', 'error'); busy(button, false); }
  }

  // Voice -----------------------------------------------------------------
  async function loadVoice() {
    const container = byId('mod-voice-content'); if (!container) return;
    loading(container);
    try {
      const raw = await safeFetch(api('moderation/voice-history?limit=50'), {cache: 'no-cache'}); const sessions = raw.data?.sessions || raw.sessions || [];
      if (!sessions.length) { container.innerHTML = state('empty', 'No voice history yet', 'Voice joins and leaves will appear after the module records them.', 'voice'); refreshIcons(); return; }
      const rows = sessions.map(s => `<tr><td><a class="member-link" href="${guildUrl('/members/' + encodeURIComponent(s.user_id))}">${escHtml(s.username || s.user_tag || s.user_id)}</a></td><td>${escHtml(s.channel_name || s.channel_id || 'Unknown')}</td><td class="timestamp">${formatDate(s.joined_at, true)}</td><td class="timestamp">${s.left_at ? formatDate(s.left_at, true) : '<span class="badge badge-ok">Active now</span>'}</td><td>${s.duration_seconds == null ? '—' : formatDuration(s.duration_seconds)}</td></tr>`).join('');
      container.innerHTML = table(['Member', 'Channel', 'Joined', 'Left', 'Duration'], rows); refreshIcons();
    } catch (error) { container.innerHTML = state('error', 'Voice history unavailable', error.message || 'Voice sessions could not be loaded.', 'voice'); refreshIcons(); }
  }
  async function purgeData(button) {
    const label = button.dataset.purgeLabel;
    if (!await BarkDialog.confirm({title: `Clear all ${label}?`, message: `Every ${label} record for this server will be permanently deleted. This cannot be undone.`, confirmLabel: 'Permanently clear', danger: true})) return;
    busy(button, true, 'Clearing…');
    try { const raw = await safeFetch(api(`moderation/${button.dataset.purge}`), {method: 'DELETE'}); showToast(`${raw.data?.deleted ?? 0} ${label} record(s) deleted`, 'success'); busy(button, false); await loadVoice(); }
    catch (error) { showToast(error.message || `Unable to clear ${label}`, 'error'); busy(button, false); }
  }

  const loaders = {cases: loadCases, warnings: loadWarnings, notes: loadNotes, rulesets: loadRulesets, wordlists: loadWordlists, voice: loadVoice};

  // Recent Activity feed (relocated from the dashboard overview to moderation).
  const activityFeedEl = byId('moderation-activity-feed');
  const activityMoreWrap = byId('moderation-activity-more');
  const activityLoadMore = byId('moderation-activity-load-more');
  const ACTIVITY_PAGE_SIZE = 10;
  let activityItems = [];
  let activityPage = 0;

  function refreshActivityTimes() {
    document.querySelectorAll('#moderation-activity-feed [data-activity-timestamp]').forEach(element => {
      element.textContent = timeAgo(element.dataset.activityTimestamp);
    });
  }
  function renderActivityItem(a) {
    const time = a.timestamp ? timeAgo(a.timestamp) : '';
    const timestampAttr = a.timestamp ? ` data-activity-timestamp="${escHtml(a.timestamp).replaceAll('"', '&quot;').replaceAll("'", '&#39;')}"` : '';
    let reasonHtml = '';
    if (a.reason) reasonHtml = `<span class="activity-reason">${escHtml(a.reason)}</span>`;
    let metaHtml = '';
    if (a.moderator && a.moderator !== a.target && a.moderator !== 'Unknown') {
      metaHtml = `<span class="activity-meta">by ${escHtml(a.moderator)}</span>`;
    }
    const badge = a.category ? `<span class="activity-category cat-${safeClassToken(a.category, 'activity')}">${escHtml(a.category)}</span>` : '';
    return `<div class="activity-item type-${safeClassToken(a.type, 'activity')}"><span class="activity-icon">${escHtml(a.icon || '📝')}</span><span class="activity-desc">${escHtml(a.description)}${metaHtml}</span>${reasonHtml}${badge}<span class="activity-time"${timestampAttr}>${escHtml(time)}</span></div>`;
  }
  function renderActivityPage() {
    const visible = activityItems.slice(0, (activityPage + 1) * ACTIVITY_PAGE_SIZE);
    activityFeedEl.innerHTML = visible.map(renderActivityItem).join('');
    const hasMore = visible.length !== activityItems.length;
    activityFeedEl.classList.toggle('is-masked', hasMore);
    if (activityMoreWrap) activityMoreWrap.hidden = !hasMore;
    refreshIcons();
  }
  async function loadActivity() {
    if (!activityFeedEl) return;
    try {
      const raw = await safeFetch(api('activity'), {cache: 'no-cache'});
      activityItems = raw?.data?.activity || raw?.activity || [];
      activityPage = 0;
      if (activityItems.length === 0) {
        activityFeedEl.innerHTML = `<div class="state-panel state-empty" role="status"><span class="state-panel-icon" aria-hidden="true">${typeof getIconSvg === 'function' ? getIconSvg('activity', 18) : ''}</span><div><strong>No recent activity</strong><p>Notable events will appear here as they happen.</p></div></div>`;
        activityFeedEl.classList.remove('is-masked');
        if (activityMoreWrap) activityMoreWrap.hidden = true;
        return;
      }
      renderActivityPage();
    } catch (error) {
      activityFeedEl.innerHTML = `<div class="state-panel state-error" role="alert"><div><strong>Activity unavailable</strong><p>${escHtml(error.message || 'Activity could not be loaded.')}</p></div></div>`;
    }
  }
  activityLoadMore?.addEventListener('click', () => { activityPage += 1; renderActivityPage(); });
  if (activityFeedEl) {
    loadActivity();
    let timesTimer = setInterval(refreshActivityTimes, 60000);
    // bfcache lifecycle: stop when cached, restart on restore (audit 2026-08-24).
    window.addEventListener('pagehide', () => clearInterval(timesTimer));
    window.addEventListener('pageshow', (event) => {
      if (!event.persisted) return;
      refreshActivityTimes();
      timesTimer = setInterval(refreshActivityTimes, 60000);
    });
  }

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button'); if (!target || !root.contains(target) && !target.closest('.workspace-modal, .workspace-drawer-overlay')) return;
    if (target.dataset.refreshSection) loaders[target.dataset.refreshSection]?.();
    else if (target.dataset.viewCase) viewCase(target); else if (target.dataset.deleteCase) deleteCase(target); else if (target.dataset.clearWarning) clearWarning(target);
    else if (target.id === 'mod-note-new-btn') openNoteForm(); else if (target.id === 'mod-note-cancel') closeNoteForm(); else if (target.dataset.editNote) openNoteForm(notes.find(n => String(n.id) === target.dataset.editNote)); else if (target.dataset.deleteNote) deleteNote(target);
    else if (target.id === 'rs-new-btn') openRulesetName(); else if (target.dataset.renameRuleset) openRulesetName(rulesets.find(rs => String(rs.id) === target.dataset.renameRuleset)); else if (target.dataset.deleteRuleset) deleteRuleset(target); else if (target.dataset.addRule) { const rs = rulesets.find(item => String(item.id) === target.dataset.addRule); openRuleEditor(target.dataset.addRule, null, rs); } else if (target.dataset.editRule) { const rs = rulesets[Number(target.dataset.rulesetIndex)]; const rule = rs?.rules?.find(item => String(item.id) === target.dataset.editRule); openRuleEditor(rs.id, rule, rs); } else if (target.dataset.closeRuleEditor !== undefined) closeRuleEditor(); else if (target.id === 'rs-editor-del') deleteRule(target); else if (target.dataset.rulesetPreset) createPreset(target);
    else if (target.id === 'wl-new-btn') openModal('wl-modal'); else if (target.dataset.editWordlist) toggleWordlistEditor(target); else if (target.dataset.cancelWordlist) renderWordlists(); else if (target.dataset.deleteWordlist) deleteWordlist(target);
    else if (target.dataset.closeModal) closeModal(target.dataset.closeModal); else if (target.dataset.purge) purgeData(target);
  });
  document.addEventListener('change', (event) => { if (event.target.matches('[data-toggle-ruleset]')) toggleRuleset(event.target); if (event.target.id === 'rs-editor-trigger' || event.target.id === 'rs-editor-effect') syncRuleFields(); });
  document.addEventListener('submit', (event) => { if (event.target === noteForm) saveNote(event); else if (event.target.id === 'rs-name-form') saveRulesetName(event); else if (event.target.id === 'rs-editor') saveRule(event); else if (event.target.id === 'wl-form') createWordlist(event); else if (event.target.matches('[data-wordlist-form]')) saveWordlist(event); });
  document.addEventListener('keydown', (event) => { if (event.key !== 'Escape') return; document.querySelectorAll('.workspace-modal:not([hidden])').forEach(modal => closeModal(modal.id)); if (ruleEditor && !ruleEditor.hidden) closeRuleEditor(); });
  Object.entries(loaders).forEach(([name, loader]) => byId(`workspace-tab-${name}`)?.addEventListener('click', () => loader()));
  byId('mod-cases-prev')?.addEventListener('click', () => casesPage > 0 && loadCases(casesPage - 1));
  byId('mod-cases-next')?.addEventListener('click', () => loadCases(casesPage + 1));

  window.addEventListener('bark:module-action-complete', (event) => {
    if (event.detail?.moduleName === 'moderation') Promise.all([loadCases(), loadWarnings(), loadNotes()]);
  });

  // Initial load: only the ACTIVE tab's section fetches at boot. Tab clicks
  // lazy-load the rest — previously all six loaders fired on page load AND
  // again on the first tab click (doubled API traffic per module page visit).
  const activeTab = root.querySelector('.workspace-tab.active');
  const activeName = activeTab?.id?.replace('workspace-tab-', '');
  if (activeName && loaders[activeName]) loaders[activeName]();
  else Object.values(loaders)[0]?.();
})();
