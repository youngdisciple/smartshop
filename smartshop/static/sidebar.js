'use strict';
(() => {
  const layout = document.querySelector('.app-layout');
  const sidebar = document.querySelector('.sidebar');
  const toggle = document.querySelector('.sidebar-toggle');
  const content = document.querySelector('#sidebar-content');
  if (!layout || !sidebar || !toggle || !content) return;

  const storageKey = 'smartshop.sidebar.collapsed';
  const mobile = window.matchMedia('(max-width: 700px)');
  let preference = null;
  try { preference = localStorage.getItem(storageKey); } catch (error) { /* Storage may be unavailable. */ }

  function setCollapsed(collapsed) {
    if (collapsed && content.contains(document.activeElement)) toggle.focus();
    layout.classList.toggle('sidebar-collapsed', collapsed);
    content.hidden = collapsed;
    toggle.setAttribute('aria-expanded', String(!collapsed));
    const label = collapsed ? toggle.dataset.expandLabel : toggle.dataset.collapseLabel;
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
  }
  function save(collapsed) {
    preference = String(collapsed);
    try { localStorage.setItem(storageKey, preference); } catch (error) { /* Keep the current page usable. */ }
    setCollapsed(collapsed);
  }

  setCollapsed(preference === null ? mobile.matches : preference === 'true');
  toggle.hidden = false;
  toggle.addEventListener('click', () => save(!content.hidden));
  sidebar.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !content.hidden) {
      event.preventDefault();
      save(true);
      toggle.focus();
    }
  });
  mobile.addEventListener('change', () => {
    if (preference === null) setCollapsed(mobile.matches);
  });
})();
