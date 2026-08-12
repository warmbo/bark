/**
 * Collapsible sidebar sections.
 *
 * The sidebar nav is rendered by main.js (loadSidebarManifest → renderSidebar),
 * which rebuilds #sidebar-nav-items.innerHTML on every manifest refresh. We
 * must not edit main.js, so this file observes the container and re-applies
 * the collapsible wrapper after each render.
 *
 * Behavior:
 *  - Every "nav section label" (Community, Modules, Add-on Modules, Settings)
 *    becomes a toggle button with a chevron.
 *  - Clicking it collapses/expands the links beneath it.
 *  - Collapsed state persists per guild (keyed by section label) in localStorage.
 */
(() => {
  'use strict';

  const root = document.getElementById('sidebar-nav-items');
  if (!root) return;

  // Collapse state keyed by guild id → { sectionLabel: bool }
  const storageKey = () => {
    const m = window.location.pathname.match(/\/guild\/(\d+)/);
    const guildId = m ? m[1] : 'global';
    return `bark:sidebar:collapsed:${guildId}`;
  };

  const readState = () => {
    try { return JSON.parse(localStorage.getItem(storageKey()) || '{}'); }
    catch { return {}; }
  };
  const writeState = (state) => {
    try { localStorage.setItem(storageKey(), JSON.stringify(state)); }
    catch { /* storage unavailable — session-only behavior */ }
  };

  function findSectionLabels() {
    return Array.from(root.querySelectorAll('.nav-section-label'));
  }

  function applyCollapsible() {
    const labels = findSectionLabels();
    const state = readState();

    labels.forEach((label) => {
      if (label.dataset.sectionCollapsible === 'true') return;

      const sectionKey = (label.textContent || '').trim();
      if (!sectionKey) return;

      // Collect the nav items that follow this label (until the next section
      // label or the end of the nav).
      const items = [];
      let node = label.nextElementSibling;
      while (node) {
        if (node.classList && node.classList.contains('nav-section-label')) break;
        items.push(node);
        node = node.nextElementSibling;
      }
      if (!items.length) return;

      label.dataset.sectionCollapsible = 'true';

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
        const next = readState();
        if (collapsed) delete next[sectionKey];
        else next[sectionKey] = true;
        writeState(next);
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

      // Default expanded unless this section was explicitly collapsed before.
      applyState(Boolean(state[sectionKey]));
    });
  }

  applyCollapsible();

  // main.js re-renders the nav on manifest refreshes; re-apply after each.
  const observer = new MutationObserver(() => applyCollapsible());
  observer.observe(root, { childList: true, subtree: true });
})();
