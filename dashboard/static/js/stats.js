/**
 * Bark Dashboard — Statistics page controller.
 *
 * Fetches the server overview from /api/v1/guilds/{id}/dashboard (the same
 * aggregate the overview page uses) and populates the metrics list + the SVG
 * charts rendered by charts.js. Pure progressive enhancement: a failed fetch
 * leaves the static skeleton in place rather than crashing the page.
 */
(function () {
  'use strict';

  const GUILD_ID = window.BARK_GUILD_ID;

  function setStat(id, val, fallback) {
    const el = document.getElementById(id);
    if (el) el.textContent = val != null && val !== '' ? String(val) : (fallback || '—');
  }

  function renderChart(name, id, data, opts) {
    const el = document.getElementById(id);
    if (!el) return;
    if (window.BarkCharts && typeof window.BarkCharts[name] === 'function') {
      window.BarkCharts[name](el, data || [], opts);
    } else {
      el.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>Chart unavailable</strong></div></div>';
    }
  }

  let statsRequestToken = 0;
  async function loadStats() {
    const requestToken = ++statsRequestToken;
    try {
      const raw = await safeFetch(`/api/v1/guilds/${GUILD_ID}/stats`, { cache: 'no-cache' });
      if (requestToken !== statsRequestToken) return; // a newer reload started
      const d = (raw && (raw.data || raw)) || {};

      setStat('stat-members', d.members);
      const onlinePct = d.members && d.members_online != null
        ? Math.round((d.members_online / d.members) * 100) + '% online'
        : null;
      setStat('stat-online', onlinePct);
      setStat('stat-tier', d.boost_tier ? 'Tier ' + d.boost_tier : null);
      setStat('stat-boosts', d.boosts != null ? d.boosts + ' boosting' : null);
      setStat('stat-channels', d.channels);
      if (d.text_channels != null && d.voice_channels != null) {
        setStat('stat-channel-split', d.text_channels + ' text · ' + d.voice_channels + ' voice');
      }
      setStat('stat-roles', d.roles);
      setStat('stat-voice', d.in_voice);
      const g = d.growth_30d;
      setStat('stat-growth', g != null ? (g > 0 ? '+' + g : g) : null);
      setStat('stat-messages', d.messages_today);
      const topCh = (d.top_channels_today || [])[0];
      const topEm = (d.top_emojis_today || [])[0];
      setStat('stat-top-channel', topCh ? '#' + topCh.name : null);
      setStat('stat-top-channel-count', topCh && topCh.count != null ? topCh.count + ' msgs' : '—');
      setStat('stat-top-emoji', topEm && topEm.name ? topEm.name : null);
      setStat('stat-top-emoji-count', topEm && topEm.count != null ? topEm.count + ' uses' : '—');

      const growth = (d.growth_series || []).map(p => ({ label: (p.date || '').slice(5), value: p.members }));
      const channels = (d.top_channels_today || []).map(c => ({ label: '#' + c.name, value: c.count }));
      const channels7d = (d.top_channels_7d || []).map(c => ({ label: '#' + c.name, value: c.count }));
      const channels30d = (d.top_channels_30d || []).map(c => ({ label: '#' + c.name, value: c.count }));
      const emojisAll = (d.top_emojis_all_time || []).map(e => ({ label: e.name, value: e.count }));
      const emojis = (d.top_emojis_today || []).map(e => ({ label: e.name, value: e.count }));
      // New engagement/activity series (data that accumulates over time).
      const newMembers = (d.new_members_series || []).map(p => ({ label: (p.date || '').slice(5), value: p.count }));
      const reputation = (d.reputation_series || []).map(p => ({ label: (p.date || '').slice(5), value: p.count }));
      const audit = (d.audit_series || []).map(p => ({ label: (p.date || '').slice(5), value: p.count }));
      const voice = (d.voice_series || []).map(p => ({ label: (p.date || '').slice(5), value: p.count }));
      const reputationTypes = (d.reputation_by_type || []).map(e => ({ label: e.name, value: e.count }));
      const games = (d.popular_games || []).map(g => ({ label: g.name, value: g.count }));
      const voiceUsers = (d.top_voice_users || []).map(u => ({ label: u.name, value: u.count, sub: u.sessions }));
      const topReputation = (d.top_reputation || []).map(r => ({ label: r.name, value: r.count }));

      renderChart('lineChart', 'chart-growth', growth, { label: 'Member count', valueLabel: 'Members' });
      renderChart('lineChart', 'chart-new-members', newMembers, { label: 'New members', valueLabel: 'Members' });
      renderChart('lineChart', 'chart-reputation', reputation, { label: 'Reputation events', valueLabel: 'Events' });
      renderChart('pieChart', 'chart-reputation-types', reputationTypes, { label: 'Reputation' });
      renderChart('lineChart', 'chart-voice', voice, { label: 'Voice sessions', valueLabel: 'Sessions' });
      renderChart('barChart', 'chart-voice-users', voiceUsers, { label: 'Voice minutes', emptyTitle: 'No voice time yet', emptyHint: 'Appears once members spend time in voice channels.' });
      renderChart('lineChart', 'chart-audit', audit, { label: 'Moderation events', valueLabel: 'Events' });
      renderChart('barChart', 'chart-games', games, { label: 'Games', emptyTitle: 'No games detected yet', emptyHint: 'Appears when members play games in temporary voice channels.' });
      renderChart('barChart', 'chart-reputation-top', topReputation, { label: 'Reputation', emptyTitle: 'No reputation yet', emptyHint: 'Appears as members earn reputation points.' });
      renderChart('barChart', 'chart-channels', channels, { label: 'Messages today', emptyTitle: 'No messages today', emptyHint: 'Appears once members post in channels.' });
      renderChart('barChart', 'chart-channels-7d', channels7d, { label: 'Messages (7d)', emptyTitle: 'No messages in 7 days', emptyHint: 'Appears once members post in channels.' });
      renderChart('barChart', 'chart-channels-30d', channels30d, { label: 'Messages (30d)', emptyTitle: 'No messages in 30 days', emptyHint: 'Appears once members post in channels.' });
      renderChart('barChart', 'chart-emojis-all', emojisAll, { label: 'All-time reactions', emptyTitle: 'No reactions yet', emptyHint: 'Appears once members react to messages.' });
      renderChart('barChart', 'chart-emojis', emojis, { label: 'Reactions today', emptyTitle: 'No reactions today', emptyHint: 'Appears once members react to messages.' });
    } catch (e) {
      if (requestToken !== statsRequestToken) return; // a newer reload started
      setStat('stat-members', 'Unavailable');
      const err = document.getElementById('chart-growth');
      const msg = (window.BarkCharts && window.BarkCharts.esc)
        ? window.BarkCharts.esc(e && e.message ? e.message : 'Could not load statistics.')
        : 'Could not load statistics.';
      if (err) {
        err.innerHTML = `<div class="state-panel state-error" role="alert"><div><strong>Statistics unavailable</strong><p>${msg}</p></div><button type="button" class="btn btn-sm" id="stats-retry">Retry</button></div>`;
        const btn = document.getElementById('stats-retry');
        if (btn) btn.addEventListener('click', loadStats);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadStats();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) loadStats();
    });
  });
})();
