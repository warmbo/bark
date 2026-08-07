/**
 * Collapsible "Add-on Modules" sidebar section.
 *
 * The sidebar nav is rendered by main.js (loadSidebarManifest → renderSidebar),
 * which rebuilds #sidebar-nav-items.innerHTML on every manifest refresh. We
 * must not edit main.js, so this file observes the container and re-applies
 * the collapsible wrapper after each render.
 *
 * Behavior:
 *  - The "Add-on Modules" section label becomes a toggle button with a chevron.
 *  - Clicking it collapses/expands the module links beneath it.
 *  - Collapsed state persists per guild in localStorage.
 */
(() => {
  'use strict';

  const STORAGE_KEY = 'bark:sidebar:addons-collapsed';
  const SECTION_LABEL = 'Add-on Modules';

  const root = document.getElementById('sidebar-nav-items');
  if (!root) return;

  const isCollapsed = () => {
    try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }
  };
  const setCollapsed = (collapsed) => {
    try {
      if (collapsed) localStorage.setItem(STORAGE_KEY, '1');
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* storage unavailable — session-only behavior */ }
  };

  function findAddonsGroup() {
    const labels = root.querySelectorAll('.nav-section-label');
    for (const label of labels) {
      if ((label.textContent || '').trim() === SECTION_LABEL) {
        return label;
      }
    }
    return null;
  }

  function applyCollapsible() {
    // Skip if we already wrapped this exact label (avoids double-wrapping
    // when the observer fires during our own DOM edits).
    const label = findAddonsGroup();
    if (!label || label.dataset.addonsCollapsible === 'true') return;

    // Collect the module nav items that follow this label (until the next
    // section label or the end of the nav).
    const items = [];
    let node = label.nextElementSibling;
    while (node) {
      if (node.classList && node.classList.contains('nav-section-label')) break;
      items.push(node);
      node = node.nextElementSibling;
    }
    if (!items.length) return;

    label.dataset.addonsCollapsible = 'true';

    // Build the chevron button on the label itself.
    const chevron = document.createElement('span');
    chevron.className = 'nav-collapse-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.innerHTML = '<i data-lucide="chevron-down" width="13" height="13"></i>';

    label.classList.add('nav-collapse-toggle');
    label.appendChild(chevron);
    label.setAttribute('role', 'button');
    label.setAttribute('tabindex', '0');
    label.setAttribute('aria-expanded', 'true');

    const group = document.createElement('div');
    group.className = 'nav-collapse-group';
    items.forEach((item) => group.appendChild(item));
    label.after(group);

    const applyState = (collapsed) => {
      group.hidden = collapsed;
      label.setAttribute('aria-expanded', String(!collapsed));
      label.classList.toggle('is-collapsed', collapsed);
      if (typeof lucide !== 'undefined') lucide.createIcons();
    };

    const toggle = () => {
      const collapsed = group.hidden;
      applyState(!collapsed);
      setCollapsed(!collapsed);
    };

    label.addEventListener('click', (e) => {
      // Ignore clicks that land on nested interactive content (there is none
      // today, but keep the guard for future label children).
      if (e.target.closest('a, button')) return;
      toggle();
    });
    label.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    });

    applyState(isCollapsed());
  }

  applyCollapsible();

  // main.js re-renders the nav on manifest refreshes; re-apply after each.
  const observer = new MutationObserver(() => applyCollapsible());
  observer.observe(root, { childList: true, subtree: true });
})();
