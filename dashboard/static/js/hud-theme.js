/**
 * Bark Dashboard — HUD theme interaction.
 *
 * Adds the mouse-tracked 3D card tilt + cursor-follow glow for the "hud"
 * accent theme. Only active while <html data-theme="hud"> is set (watched via
 * MutationObserver so picking the theme live enables it without a refresh).
 *
 * It writes --hud-tilt-x / --hud-tilt-y (0..1) CSS custom properties on the
 * card under the pointer; the HUD CSS computes the perspective tilt and the
 * radial highlight from those. Respects prefers-reduced-motion (no tilt).
 */
(function () {
  'use strict';

  var CARD_SELECTOR =
    '.content-card, .guild-card, .module-card, .dashboard-widget, .stat-card, ' +
    '.server-profile, .workspace-data-card, .action-card, .feature-item';

  var reducedMotion =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var enabled = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
  var lastEl = null;

  // Keep --hud-tilt defaults on every card so the base transform is neutral.
  function seed(el) {
    if (!el.style.getPropertyValue('--hud-tilt-x')) {
      el.style.setProperty('--hud-tilt-x', '0.5');
      el.style.setProperty('--hud-tilt-y', '0.5');
    }
  }

  function applyTilt(el, clientX, clientY) {
    var r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    var px = (clientX - r.left) / r.width;
    var py = (clientY - r.top) / r.height;
    px = Math.max(0, Math.min(1, px));
    py = Math.max(0, Math.min(1, py));
    el.style.setProperty('--hud-tilt-x', px.toFixed(3));
    el.style.setProperty('--hud-tilt-y', py.toFixed(3));
  }

  function resetTilt(el) {
    if (!el) return;
    el.style.setProperty('--hud-tilt-x', '0.5');
    el.style.setProperty('--hud-tilt-y', '0.5');
  }

  document.addEventListener('mousemove', function (e) {
    if (!enabled) return;
    var t = e.target && e.target.closest ? e.target.closest(CARD_SELECTOR) : null;
    if (t === lastEl) {
      if (t) applyTilt(t, e.clientX, e.clientY);
      return;
    }
    if (lastEl) resetTilt(lastEl);
    lastEl = t;
    if (t) {
      seed(t);
      applyTilt(t, e.clientX, e.clientY);
    }
  });

  document.addEventListener('mouseout', function (e) {
    if (!enabled) return;
    var t = e.target && e.target.closest ? e.target.closest(CARD_SELECTOR) : null;
    var related = e.relatedTarget;
    // Leaving a card to a non-card area (or out of the window) resets it.
    if (t && !(related && related.closest && related.closest(CARD_SELECTOR))) {
      resetTilt(t);
      if (lastEl === t) lastEl = null;
    }
  }, true);

  // Watch for the theme changing live (e.g. selecting HUD in Settings).
  if (window.MutationObserver) {
    var mo = new MutationObserver(function () {
      var now = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
      if (now !== enabled) {
        enabled = now;
        if (!enabled && lastEl) {
          resetTilt(lastEl);
          lastEl = null;
        }
      }
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  }

  // Recompute reduced-motion if the OS preference changes.
  if (window.matchMedia) {
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', function (m) {
      reducedMotion = m.matches;
      enabled = document.documentElement.getAttribute('data-theme') === 'hud' && !reducedMotion;
      if (!enabled && lastEl) {
        resetTilt(lastEl);
        lastEl = null;
      }
    });
  }
})();
