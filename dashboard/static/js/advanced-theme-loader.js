(() => {
  'use strict';

  const THREE_THEMES = new Set([
    'aurora', 'neon', 'ocean', 'sunset', 'forest', 'candy', 'slate',
    'crimson', 'honey', 'deepspace', 'graffiti',
  ]);
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let loading = null;
  let hardwareWebGL = null;

  function canAnimateWithWebGL() {
    if (hardwareWebGL !== null) return hardwareWebGL;
    // Browser automation generally uses SwiftShader; avoid a misleadingly slow
    // software context and keep visual/regression tests deterministic.
    if (navigator.webdriver) return (hardwareWebGL = false);
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2', { powerPreference: 'low-power' })
        || canvas.getContext('webgl', { powerPreference: 'low-power' });
      if (!gl) return (hardwareWebGL = false);
      const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
      const rendererName = debugInfo
        ? String(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL))
        : String(gl.getParameter(gl.RENDERER) || '');
      gl.getExtension('WEBGL_lose_context')?.loseContext();
      hardwareWebGL = !/swiftshader|llvmpipe|software/i.test(rendererName);
    } catch (error) {
      hardwareWebGL = false;
    }
    return hardwareWebGL;
  }

  function maybeLoad() {
    const theme = document.documentElement.getAttribute('data-theme') || 'steel';
    const enabled = THREE_THEMES.has(theme);
    document.documentElement.toggleAttribute('data-advanced-theme', enabled);
    document.documentElement.setAttribute('data-advanced-name', theme);
    if (!enabled) {
      document.documentElement.classList.remove('advanced-theme-fallback');
      delete document.documentElement.dataset.advancedQuality;
      return;
    }
    if (reducedMotion.matches || loading) return;
    if (!canAnimateWithWebGL()) {
      document.documentElement.classList.add('advanced-theme-fallback');
      document.documentElement.dataset.advancedQuality = 'static';
      return;
    }
    loading = import('/static/js/advanced-themes.js?v=7').catch((error) => {
      loading = null;
      document.documentElement.classList.add('advanced-theme-fallback');
      console.error('Advanced theme runtime failed to load', error);
    });
  }

  new MutationObserver(maybeLoad).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  reducedMotion.addEventListener('change', maybeLoad);
  maybeLoad();
})();
