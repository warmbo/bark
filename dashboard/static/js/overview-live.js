/**
 * Overview "live" panels — who's online, in voice, boosts, and the emoji wall.
 * Rendered from the aggregate /dashboard endpoint (presence/voice/boosts/emojis)
 * into the SAME #dashboard-widgets grid as the add-on module widgets, so every
 * box on the front page is a uniform content-card with consistent spacing.
 */
(function () {
  'use strict';

  function el(id) { return document.getElementById(id); }

  function statusLabel(status) {
    return { online: 'Online', idle: 'Idle', dnd: 'Do Not Disturb' }[status] || 'Online';
  }

  function statusDot(status) {
    return '<span class="presence-dot presence-' + (status || 'online') + '" aria-hidden="true"></span>';
  }

  function avatarHtml(member, size) {
    size = size || 28;
    const url = member.avatar_url;
    if (url) {
      return '<img class="member-avatar" src="' + escHtml(url) + '" alt="' + escHtml(member.name) + '" width="' + size + '" height="' + size + '" loading="lazy" data-fallback-src="/static/img/bark-avatar.png">';
    }
    return '<span class="member-avatar member-avatar-fallback">' + escHtml((member.name || '?')[0].toUpperCase()) + '</span>';
  }

  function renderPresence(p) {
    var panel = el('panel-online');
    if (!p || panel === null) { if (panel) panel.hidden = true; return; }
    panel.hidden = false;
    el('live-online-total').textContent = (p.total ?? 0) + ' online';
    var row = el('presence-row');
    var cells = [
      ['online', p.online, 'Online'],
      ['idle', p.idle, 'Idle'],
      ['dnd', p.dnd, 'DND'],
      ['offline', p.offline, 'Offline'],
    ].filter(function (c) { return c[1] > 0; });
    row.innerHTML = cells.map(function (c) {
      return '<span class="presence-count"><span class="presence-dot presence-' + c[0] + '"></span><strong>' + c[1] + '</strong> ' + c[2] + '</span>';
    }).join('') || '<span class="text-tertiary">No members present</span>';

    var members = p.members || [];
    var wrap = el('online-members');
    if (!members.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>Nobody online right now</strong></div></div>';
      return;
    }
    wrap.innerHTML = members.map(function (m) {
      return '<span class="member-tile" title="' + escHtml(m.name) + ' (' + statusLabel(m.status) + ')">' + avatarHtml(m, 30) + statusDot(m.status) + '</span>';
    }).join('');
  }

  function renderVoice(voice) {
    var panel = el('panel-voice');
    if (panel === null) return;
    if (!voice || !voice.length) { panel.hidden = true; return; }
    panel.hidden = false;
    var total = 0;
    (voice || []).forEach(function (c) { total += (c.members || []).length; });
    el('voice-total').textContent = total + (total === 1 ? ' member' : ' members');
    var wrap = el('voice-channels');
    wrap.innerHTML = voice.map(function (ch) {
      var members = ch.members || [];
      return '<div class="voice-channel"><div class="voice-channel-head">' + statusDot('online') + '<strong>' + escHtml(ch.name) + '</strong><span class="text-tertiary">' + members.length + '</span></div>' +
        '<div class="voice-member-list">' + members.map(function (m) {
          return '<span class="voice-member" title="' + escHtml(m.name) + '">' + avatarHtml(m, 24) + '<span>' + escHtml(m.name) + '</span></span>';
        }).join('') + '</div></div>';
    }).join('');
  }

  function renderBoosts(b) {
    var panel = el('panel-boosts');
    if (panel === null) return;
    if (!b) { panel.hidden = true; return; }
    panel.hidden = false;
    el('boosts-label').textContent = (b.tier || 0) + ' · ' + (b.count || 0) + ' boosts';
    var fill = el('boost-bar-fill');
    var meta = el('boost-bar-meta');
    var nt = b.next_tier;
    if (nt) {
      var req = nt.required || 0;
      var pct = req ? Math.min(100, Math.round(((b.count || 0) / req) * 100)) : 0;
      if (fill) fill.style.width = pct + '%';
      meta.innerHTML = '<span>' + (b.count || 0) + ' / ' + req + ' to Tier ' + nt.tier + '</span><span>' + pct + '%</span>';
    } else {
      if (fill) fill.style.width = '100%';
      meta.innerHTML = '<span>Max boost tier reached</span><span>100%</span>';
    }
  }

  function renderEmojis(emojis) {
    var panel = el('panel-emojis');
    if (panel === null) return;
    if (!emojis || !emojis.length) { panel.hidden = true; return; }
    panel.hidden = false;
    el('emoji-total').textContent = emojis.length + (emojis.length === 1 ? ' emoji' : ' emojis');
    var wrap = el('emoji-wall');
    wrap.innerHTML = emojis.map(function (e) {
      return '<span class="emoji-tile" title=":' + escHtml(e.name) + ':" role="img" aria-label="' + escHtml(e.name) + '"><img src="' + escHtml(e.url) + '" alt="' + escHtml(e.name) + '" loading="lazy"></span>';
    }).join('');
  }

  // Show the shared grid container if any live panel or module widget is visible.
  function refreshDashboardVisibility() {
    var wrap = el('dashboard-widgets');
    if (!wrap) return;
    var hasLive = ['panel-online', 'panel-voice', 'panel-boosts', 'panel-emojis']
      .some(function (id) { var p = document.getElementById(id); return p && !p.hidden; });
    var hasWidget = wrap.querySelector('.dashboard-widget[data-widget]') !== null;
    wrap.hidden = !(hasLive || hasWidget);
  }
  window.refreshDashboardVisibility = refreshDashboardVisibility;

  var liveRequestToken = 0;
  function loadLive() {
    var requestToken = ++liveRequestToken;
    safeFetch('/api/v1/guilds/' + GUILD_ID + '/dashboard', { cache: 'no-cache' })
      .then(function (raw) {
        if (requestToken !== liveRequestToken) return;
        var d = (raw && (raw.data || raw)) || {};
        renderPresence(d.presence);
        renderVoice(d.voice);
        renderBoosts(d.boosts);
        renderEmojis(d.emojis);
        refreshDashboardVisibility();
        if (typeof refreshIcons === 'function') refreshIcons();
      })
      .catch(function () { /* non-fatal; panels stay hidden on error */ });
  }

  function init() {
    loadLive();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
