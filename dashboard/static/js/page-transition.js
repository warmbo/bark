/**
 * Bark Dashboard — soft fade page transitions.
 *
 * Two halves:
 *   1. FADE-IN: on every page load, <body> animates from a translucent veil to
 *      opaque (pure CSS, .page-fade-in). Only plays for fresh navigations —
 *      the first paint is already opaque when the theme is applied from
 *      localStorage before paint.
 *   2. FADE-OUT: clicking any internal navigation <a> adds .page-leaving to
 *      <body>, which fades the page out over ~150ms; the browser then starts
 *      the next navigation. Modifier-key / target=_blank / external clicks are
 *      left alone.
 *
 * It is deliberately tiny and dependency-free, and works under every accent
 * theme (it does not read theme state). Respects prefers-reduced-motion.
 */
(function () {
  'use strict';

  var reducedMotion =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reducedMotion) return;

  var FADE_MS = 150;

  function isInternal(href, base) {
    if (!href) return false;
    try {
      var target = new URL(href, base);
      if (target.origin !== window.location.origin) return false;
      return true;
    } catch (e) {
      // Relative href — internal.
      return true;
    }
  }

  function isPlainClick(e) {
    if (e.defaultPrevented) return false;
    if (e.button !== 0) return false;          // left click only
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
    if (e.target && e.target.hasAttribute && e.target.hasAttribute('download')) return false;
    return true;
  }

  // Fade-out on internal link click.
  document.addEventListener('click', function (e) {
    if (!isPlainClick(e)) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    if (a.target === '_blank' || a.target === '_top') return;
    if (a.hasAttribute('download')) return;
    if (!isInternal(a.getAttribute('href'), a.baseURI || document.baseURI)) return;
    // Don't fade for in-page anchors.
    var href = a.getAttribute('href') || '';
    if (href.charAt(0) === '#') return;

    document.body.classList.add('page-leaving');
  }, true);

  // Reset the leaving state if the navigation is aborted (e.g. blocked, or the
  // user presses stop) so the page is never left stuck faded out.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      document.body.classList.remove('page-leaving');
    }
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') {
      document.body.classList.remove('page-leaving');
    }
  });
})();
