/**
 * Bark Dashboard — HUD theme interaction.
 *
 * Mouse-tracked 3D card tilt for the "hud" accent theme. Unlike a per-card
 * hover tilt (only the card under the cursor reacts), this treats the whole
 * page as a single blanket: EVERY card is aware of the mouse at all times and
 * tilts according to its position relative to the cursor, like a weight rolling
 * across a cloth. Cards near the cursor depress strongly; distant cards sit
 * nearly flat; cards off to one side lean toward the weight. The depression
 * follows the cursor smoothly as it moves.
 *
 * Only active while <html data-theme="hud"> is set (watched via MutationObserver
 * so picking the theme live enables it without a refresh). It writes
 * --hud-tilt-x / --hud-tilt-y (0..1) CSS custom properties on every card; the
 * HUD CSS computes the perspective tilt and radial highlight from those.
 * Respects prefers-reduced-motion (no tilt).
 */
(function () {
  'use strict';

  var CARD_SELECTOR =
    '.content-card, .guild-card, .module-card, .dashboard-widget, .stat-card, ' +
    '.server-profile, .workspace-data-card, .action-card, .feature-item';

  // Influence radius (px) and how strongly the "weight" depresses the nearest
  // card. Beyond ~2x the radius a card is essentially flat.
  var RADIUS = 480;
  var STRENGTH = 0.34;

  var reducedMotion =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var enabled = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
  var cards = [];

  function collectCards() {
    cards = [];
    var els = document.querySelectorAll(CARD_SELECTOR);
    for (var i = 0; i < els.length; i++) {
      if (els[i].getBoundingClientRect().width) cards.push(els[i]);
    }
  }

  // Seed the default so a card shows no tilt until the cursor moves.
  function seed(el) {
    if (!el.style.getPropertyValue('--hud-tilt-x')) {
      el.style.setProperty('--hud-tilt-x', '0.5');
      el.style.setProperty('--hud-tilt-y', '0.5');
    }
  }

  function resetAll() {
    for (var i = 0; i < cards.length; i++) {
      cards[i].style.setProperty('--hud-tilt-x', '0.5');
      cards[i].style.setProperty('--hud-tilt-y', '0.5');
    }
  }

  function applyBlanket(clientX, clientY) {
    for (var i = 0; i < cards.length; i++) {
      var el = cards[i];
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;

      // Vector from the card's center to the cursor.
      var cx = r.left + r.width / 2;
      var cy = r.top + r.height / 2;
      var dx = clientX - cx;
      var dy = clientY - cy;

      // Falloff: 1 when the cursor is on the card, ~0 beyond RADIUS.
      var dist = Math.sqrt(dx * dx + dy * dy);
      var falloff = Math.max(0, 1 - dist / RADIUS);
      falloff = falloff * falloff; // smooth the depression edge

      // Normalize the offset relative to the card's own size so a large card
      // and a small card depress proportionally. tx/ty are 0..1 with 0.5 flat.
      // Sign: a cursor on the RIGHT (nx>0) recedes the right edge (tx>0.5) and
      // a cursor BELOW (ny>0) recedes the bottom edge (ty>0.5) — the "weight"
      // depresses the edge nearest it, producing a concave dip under the mouse.
      var nx = r.width ? dx / (r.width / 2) : 0;
      var ny = r.height ? dy / (r.height / 2) : 0;
      var tx = 0.5 + nx * falloff * STRENGTH;
      var ty = 0.5 + ny * falloff * STRENGTH;

      // Clamp so the tilt never over-rotates the card.
      tx = Math.max(0.08, Math.min(0.92, tx));
      ty = Math.max(0.08, Math.min(0.92, ty));

      el.style.setProperty('--hud-tilt-x', tx.toFixed(3));
      el.style.setProperty('--hud-tilt-y', ty.toFixed(3));
    }
  }

  // Throttle rect-reads to the animation frame.
  var rafPending = false;
  var lastX = 0;
  var lastY = 0;
  function onMove(clientX, clientY) {
    lastX = clientX;
    lastY = clientY;
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () {
      rafPending = false;
      if (!enabled) return;
      applyBlanket(lastX, lastY);
    });
  }

  document.addEventListener('mousemove', function (e) {
    if (!enabled) return;
    onMove(e.clientX, e.clientY);
  });

  // Keep the tilt in sync with layout changes (scroll/resize) using the last
  // cursor position, so a scrolled-into-view card is already aware.
  document.addEventListener('scroll', function () {
    if (!enabled || rafPending) return;
    onMove(lastX, lastY);
  }, true);
  window.addEventListener('resize', function () {
    if (!enabled) return;
    onMove(lastX, lastY);
  });

  collectCards();

  // Re-collect cards and re-seed defaults as the DOM changes.
  if (window.MutationObserver) {
    var mo = new MutationObserver(function () {
      collectCards();
      for (var i = 0; i < cards.length; i++) seed(cards[i]);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  // Watch for the theme changing live (e.g. selecting HUD in Settings).
  if (window.MutationObserver) {
    var themeMo = new MutationObserver(function () {
      var now = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
      if (now !== enabled) {
        enabled = now;
        if (enabled) {
          collectCards();
        } else {
          resetAll();
        }
      }
    });
    themeMo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  }

  // Recompute reduced-motion if the OS preference changes.
  if (window.matchMedia) {
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', function (m) {
      reducedMotion = m.matches;
      enabled = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
      if (!enabled) resetAll();
    });
  }
})();
