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

      renderChart('lineChart', 'chart-growth', growth, { label: 'Member count', valueLabel: 'Members' });
      renderChart('barChart', 'chart-channels', channels, { label: 'Messages today' });
      renderChart('barChart', 'chart-channels-7d', channels7d, { label: 'Messages (7d)' });
      renderChart('barChart', 'chart-channels-30d', channels30d, { label: 'Messages (30d)' });
      renderChart('barChart', 'chart-emojis-all', emojisAll, { label: 'All-time reactions' });
      renderChart('barChart', 'chart-emojis', emojis, { label: 'Reactions today' });
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
