/**
 * Overview "live" panels — who's online, in voice, boosts, emoji wall, role
 * spotlight, and quick commands. Rendered from the aggregate /dashboard
 * endpoint (presence/voice/boosts/emojis/roles/commands fields).
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
    if (!p) return;
    el('live-online-total').textContent = (p.total ?? 0) + ' online';
    const row = el('presence-row');
    const cells = [
      ['online', p.online, 'Online'],
      ['idle', p.idle, 'Idle'],
      ['dnd', p.dnd, 'DND'],
      ['offline', p.offline, 'Offline'],
    ].filter(function (c) { return c[1] > 0; });
    row.innerHTML = cells.map(function (c) {
      return '<span class="presence-count"><span class="presence-dot presence-' + c[0] + '"></span><strong>' + c[1] + '</strong> ' + c[2] + '</span>';
    }).join('') || '<span class="text-tertiary">No members present</span>';

    const members = p.members || [];
    const wrap = el('online-members');
    if (!members.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>Nobody online right now</strong></div></div>';
      return;
    }
    wrap.innerHTML = '<div class="member-avatar-grid">' + members.map(function (m) {
      return '<span class="member-tile" title="' + escHtml(m.name) + ' (' + statusLabel(m.status) + ')">' + avatarHtml(m, 30) + statusDot(m.status) + '</span>';
    }).join('') + '</div>';
  }

  function renderVoice(voice) {
    if (!voice) return;
    let total = 0;
    (voice || []).forEach(function (c) { total += (c.members || []).length; });
    el('voice-total').textContent = total + (total === 1 ? ' member' : ' members');
    const wrap = el('voice-channels');
    if (!voice || !voice.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No one in voice</strong><p>When members join a voice channel they\'ll show up here.</p></div></div>';
      return;
    }
    wrap.innerHTML = voice.map(function (ch) {
      const members = ch.members || [];
      return '<div class="voice-channel"><div class="voice-channel-head">' + statusDot('online') + '<strong>' + escHtml(ch.name) + '</strong><span class="text-tertiary">' + members.length + '</span></div>' +
        '<div class="voice-member-list">' + members.map(function (m) {
          return '<span class="voice-member" title="' + escHtml(m.name) + '">' + avatarHtml(m, 24) + '<span>' + escHtml(m.name) + '</span></span>';
        }).join('') + '</div></div>';
    }).join('');
  }

  function renderBoosts(b) {
    if (!b) return;
    el('boosts-label').textContent = (b.tier || 0) + ' · ' + (b.count || 0) + ' boosts';
    const fill = el('boost-bar-fill');
    const meta = el('boost-bar-meta');
    const nt = b.next_tier;
    if (nt) {
      const req = nt.required || 0;
      const pct = req ? Math.min(100, Math.round(((b.count || 0) / req) * 100)) : 0;
      if (fill) fill.style.width = pct + '%';
      meta.innerHTML = '<span>' + (b.count || 0) + ' / ' + req + ' to Tier ' + nt.tier + '</span><span>' + pct + '%</span>';
    } else {
      if (fill) fill.style.width = '100%';
      meta.innerHTML = '<span>Max boost tier reached</span><span>100%</span>';
    }
  }

  function renderEmojis(emojis) {
    if (!emojis) return;
    el('emoji-total').textContent = emojis.length + (emojis.length === 1 ? ' emoji' : ' emojis');
    const wrap = el('emoji-wall');
    if (!emojis.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No custom emojis</strong></div></div>';
      return;
    }
    wrap.innerHTML = emojis.map(function (e) {
      return '<span class="emoji-tile" title=":' + escHtml(e.name) + ':" role="img" aria-label="' + escHtml(e.name) + '"><img src="' + escHtml(e.url) + '" alt="' + escHtml(e.name) + '" loading="lazy"></span>';
    }).join('');
  }

  function roleColor(c) {
    // role.color is a decimal int; render as a hex for the dot.
    if (!c) return '';
    let hex = Number(c).toString(16).padStart(6, '0');
    return '#' + hex;
  }

  function renderRoles(roles) {
    if (!roles) return;
    const wrap = el('role-spotlight');
    if (!roles.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No spotlight roles</strong><p>Hoisted roles appear here.</p></div></div>';
      return;
    }
    wrap.innerHTML = roles.map(function (r) {
      const color = roleColor(r.color);
      return '<div class="role-row"><span class="role-dot"' + (color ? ' style="background:' + color + '"' : '') + '></span><span class="role-name">' + escHtml(r.name) + '</span><span class="role-count">' + r.count + '</span></div>';
    }).join('');
  }

  var allCommands = [];

  function renderCommands(commands) {
    if (!commands) return;
    allCommands = commands || [];
    filterCommands('');
  }

  function commandRow(c) {
    const full = '/' + c.name;
    return '<div class="command-row"><div class="command-name">' + statusDot('online') + '<code>' + escHtml(full) + '</code><span class="command-module">' + escHtml(c.module || '') + '</span></div>' +
      '<div class="command-desc">' + escHtml(c.description || '') + '</div>' +
      '<button type="button" class="btn btn-xs btn-accent command-copy" data-cmd="' + escHtml(full) + '" title="Copy to clipboard" aria-label="Copy ' + escHtml(full) + '">' + (typeof getIconSvg === 'function' ? getIconSvg('copy', 12) : '') + ' Copy</button></div>';
  }

  function filterCommands(q) {
    const wrap = el('command-list');
    if (!wrap) return;
    q = (q || '').toLowerCase().trim();
    const list = allCommands.filter(function (c) {
      if (!q) return true;
      return (c.name + ' ' + (c.module || '')).toLowerCase().indexOf(q) !== -1;
    });
    if (!list.length) {
      wrap.innerHTML = '<div class="state-panel state-empty" role="status"><div><strong>No matching commands</strong></div></div>';
      return;
    }
    wrap.innerHTML = list.map(commandRow).join('');
  }

  var liveRequestToken = 0;
  function loadLive() {
    var requestToken = ++liveRequestToken;
    safeFetch('/api/v1/guilds/' + GUILD_ID + '/dashboard', { cache: 'no-cache' })
      .then(function (raw) {
        if (requestToken !== liveRequestToken) return;
        var d = (raw && (raw.data || raw)) || {};
        var hasLive = d.presence || d.voice || d.boosts || d.emojis || d.roles || d.commands;
        var wrap = el('live-panels');
        if (!wrap) return;
        if (!hasLive) { wrap.hidden = true; return; }
        wrap.hidden = false;
        renderPresence(d.presence);
        renderVoice(d.voice);
        renderBoosts(d.boosts);
        renderEmojis(d.emojis);
        renderRoles(d.roles);
        renderCommands(d.commands);
        if (typeof refreshIcons === 'function') refreshIcons();
      })
      .catch(function () { /* non-fatal; panels just stay hidden on error */ });
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        if (typeof showToast === 'function') showToast('Copied ' + text, 'success');
      }).catch(function () { /* ignore */ });
    } else if (typeof showToast === 'function') {
      showToast('Press Ctrl+C to copy ' + text, 'info');
    }
  }

  function init() {
    var search = el('command-search');
    if (search) {
      search.addEventListener('input', function () { filterCommands(search.value); });
    }
    var list = el('command-list');
    if (list) {
      list.addEventListener('click', function (e) {
        var btn = e.target.closest('.command-copy');
        if (btn) copyText(btn.dataset.cmd);
      });
    }
    loadLive();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
