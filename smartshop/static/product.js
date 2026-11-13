'use strict';
const statusNode = document.querySelector('#scanner-status');
const headers = {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content};
const captureButton = document.querySelector('#capture-epc');
let active = false;
let generation = 0;
let pollTimer = null;
function stopPolling() {
  active = false;
  generation += 1;
  window.clearTimeout(pollTimer);
  pollTimer = null;
  captureButton.disabled = false;
}
async function call(url) {
  try {
    const response = await fetch(url, {method: 'POST', headers});
    const data = await response.json();
    if (!response.ok) return {error: data.error};
    return data;
  } catch (error) {
    return {error: statusNode.dataset.connection};
  }
}
document.querySelector('#lookup-upc').addEventListener('click', async () => {
  const input = document.querySelector('#upc');
  const value = input.value.trim();
  if (!value) {
    input.focus();
    statusNode.textContent = statusNode.dataset.upcPrompt;
    return;
  }
  const response = await fetch('/products/lookup?upc=' + encodeURIComponent(value));
  const data = await response.json(); statusNode.textContent = data.error || data.name + ' · ' + (data.price_cents / 100).toFixed(2) + ' CAD';
});
document.querySelector('#upc').addEventListener('keydown', event => {
  if (event.key === 'Enter') { event.preventDefault(); document.querySelector('#epc').focus(); }
});
async function poll(scanGeneration) {
  if (!active || scanGeneration !== generation) return;
  const data = await call('/reader/product/result');
  if (!active || scanGeneration !== generation) return;
  if (data.error) {
    stopPolling();
    statusNode.textContent = data.error;
    return;
  }
  if (data.tags.length === 1) {
    document.querySelector('#epc').value = data.tags[0];
    statusNode.textContent = data.tags[0];
  } else if (data.tags.length > 1) {
    document.querySelector('#epc').value = '';
    statusNode.textContent = statusNode.dataset.multiple;
  } else {
    statusNode.textContent = statusNode.dataset.waiting;
  }
  pollTimer = window.setTimeout(() => poll(scanGeneration), 1000);
}
captureButton.addEventListener('click', async () => {
  if (active) return;
  active = true;
  captureButton.disabled = true;
  const scanGeneration = ++generation;
  statusNode.textContent = statusNode.dataset.starting;
  const data = await call('/reader/product/start');
  if (!active || scanGeneration !== generation) return;
  if (data.error) {
    stopPolling();
    statusNode.textContent = data.error;
    return;
  }
  statusNode.textContent = statusNode.dataset.waiting;
  poll(scanGeneration);
});
document.querySelector('#cancel-capture').addEventListener('click', async () => {
  stopPolling();
  // Keep Start disabled until the cancellation reaches the server.
  captureButton.disabled = true;
  const stoppedGeneration = generation;
  const data = await call('/reader/product/cancel');
  if (stoppedGeneration !== generation) return;
  captureButton.disabled = false;
  statusNode.textContent = data.error || data.message;
});
window.addEventListener('pagehide', stopPolling);
