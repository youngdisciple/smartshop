'use strict';
const statusNode = document.querySelector('#scanner-status');
const headers = {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content};
let active = false;
async function call(url) {
  const response = await fetch(url, {method: 'POST', headers});
  const data = await response.json();
  if (!response.ok) { statusNode.textContent = data.error; return null; }
  return data;
}
document.querySelector('#lookup-upc').addEventListener('click', async () => {
  const response = await fetch('/products/lookup?upc=' + encodeURIComponent(document.querySelector('#upc').value));
  const data = await response.json(); statusNode.textContent = data.error || data.name + ' · ' + (data.price_cents / 100).toFixed(2) + ' CAD';
});
document.querySelector('#upc').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); document.querySelector('#epc').focus(); }
});
async function poll() {
  if (!active) return;
  const data = await call('/reader/product/result');
  if (!data) { active = false; return; }
  if (data.tags.length === 1) {
    document.querySelector('#epc').value = data.tags[0]; statusNode.textContent = data.tags[0];
  } else if (data.tags.length > 1) statusNode.textContent = statusNode.dataset.multiple;
  window.setTimeout(poll, 1000);
}
document.querySelector('#capture-epc').addEventListener('click', async () => {
  if (await call('/reader/product/start')) { active = true; poll(); }
});
document.querySelector('#cancel-capture').addEventListener('click', async () => {
  active = false; const data = await call('/reader/product/cancel'); if (data) statusNode.textContent = data.message;
});
