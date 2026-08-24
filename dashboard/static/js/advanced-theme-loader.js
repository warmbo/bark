(() => {
  'use strict';

  const THREE_THEMES = new Set([
    'aurora', 'neon', 'ocean', 'sunset', 'forest', 'candy', 'slate',
    'crimson', 'honey', 'deepspace', 'graffiti',
  ]);
  let loading = null;

  function maybeLoad() {
    const theme = document.documentElement.getAttribute('data-theme') || 'steel';
    if (!THREE_THEMES.has(theme) || loading) return;
    loading = import('/static/js/advanced-themes.js?v=2').catch((error) => {
      loading = null;
      document.documentElement.classList.add('advanced-theme-fallback');
      console.error('Advanced theme runtime failed to load', error);
    });
  }

  new MutationObserver(maybeLoad).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  maybeLoad();
})();
