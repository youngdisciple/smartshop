'use strict';
const statusNode = document.querySelector('#membership-status');
async function poll() {
  try {
    const response = await fetch(statusNode.dataset.url);
    const data = await response.json();
    statusNode.textContent = data.message;
    if (data.ready) { window.location.reload(); return; }
    if (!response.ok) return;
  } catch (error) { return; }
  window.setTimeout(poll, 1200);
}
if (statusNode) poll();
