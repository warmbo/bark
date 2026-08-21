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

  function renderActivity(items) {
    var panel = el('panel-activity');
    if (panel === null) return;
    var feed = el('overview-activity-feed');
    if (!feed) { panel.hidden = true; return; }
    // If the user lacks moderation.view, /activity 403s — hide the card silently.
    if (!items || items === 403 || !Array.isArray(items)) { panel.hidden = true; return; }
    if (!items.length) {
      panel.hidden = false;
      feed.innerHTML = '<div class="state-panel state-empty" role="status"><span class="state-panel-icon" aria-hidden="true">' + (typeof getIconSvg === 'function' ? getIconSvg('activity', 18) : '') + '</span><div><strong>No recent activity</strong><p>Notable events will appear here as they happen.</p></div></div>';
      el('activity-total').textContent = '—';
      return;
    }
    panel.hidden = false;
    el('activity-total').textContent = items.length + (items.length === 1 ? ' event' : ' events');
    feed.innerHTML = items.slice(0, 10).map(function (a) {
      var time = a.timestamp ? timeAgo(a.timestamp) : '';
      var tsAttr = a.timestamp ? ' data-activity-timestamp="' + escHtml(a.timestamp).replaceAll('"', '&quot;').replaceAll("'", '&#39;') + '"' : '';
      var reason = a.reason ? '<span class="activity-reason">' + escHtml(a.reason) + '</span>' : '';
      var meta = '';
      if (a.moderator && a.moderator !== a.target && a.moderator !== 'Unknown') {
        meta = '<span class="activity-meta">by ' + escHtml(a.moderator) + '</span>';
      }
      var badge = a.category ? '<span class="activity-category cat-' + safeClassToken(a.category, 'activity') + '">' + escHtml(a.category) + '</span>' : '';
      return '<div class="activity-item type-' + safeClassToken(a.type, 'activity') + '"><span class="activity-icon">' + escHtml(a.icon || '📝') + '</span><span class="activity-desc">' + escHtml(a.description) + meta + '</span>' + reason + badge + '<span class="activity-time"' + tsAttr + '>' + escHtml(time) + '</span></div>';
    }).join('');
  }

  function refreshActivityTimes() {
    document.querySelectorAll('#overview-activity-feed [data-activity-timestamp]').forEach(function (element) {
      element.textContent = timeAgo(element.dataset.activityTimestamp);
    });
  }

  // Show the shared grid container if any live panel or module widget is visible.
  function refreshDashboardVisibility() {
    var wrap = el('dashboard-widgets');
    if (!wrap) return;
    var hasLive = ['panel-online', 'panel-voice', 'panel-emojis', 'panel-activity']
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
        renderEmojis(d.emojis);
        refreshDashboardVisibility();
        if (typeof refreshIcons === 'function') refreshIcons();
      })
      .catch(function () { /* non-fatal; panels stay hidden on error */ });

    // Recent activity — separate call (moderation.view gated; hides if 403).
    safeFetch('/api/v1/guilds/' + GUILD_ID + '/activity', { cache: 'no-cache' })
      .then(function (raw) {
        if (requestToken !== liveRequestToken) return;
        var items = (raw && (raw.data || raw)) || {};
        var list = Array.isArray(items) ? items : (items.activity || []);
        renderActivity(list);
        refreshDashboardVisibility();
      })
      .catch(function (err) {
        if (requestToken !== liveRequestToken) return;
        // safeFetch throws a message on 403 (no status property); treat any
        // permission error as "card hidden" for users without moderation.view.
        if (err && /permission/i.test(err.message || '')) renderActivity(403);
      });
  }

  function init() {
    loadLive();
    setInterval(refreshActivityTimes, 60000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
