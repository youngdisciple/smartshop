'use strict';
const statusNode = document.querySelector('#cart-status');
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const itemsNode = document.querySelector('#cart-items');
let fingerprint = '';
async function poll() {
  try {
    const response = await fetch(statusNode.dataset.poll, {method: 'POST', headers: {'X-CSRF-Token': csrf}});
    if (!response.ok) throw new Error(response.status);
    const data = await response.json();
    statusNode.textContent = data.messages.join(' · ');
    const next = JSON.stringify(data.items);
    if (statusNode.dataset.scanning === 'yes' && next !== fingerprint) {
      fingerprint = next;
      itemsNode.replaceChildren();
      for (const item of data.items) {
        const row = document.createElement('tr');
        const labels = JSON.parse(itemsNode.dataset.labels);
        for (const [index, text] of [item.name, '1', (item.unit_cents / 100).toFixed(2) + ' CAD', (item.unit_cents / 100).toFixed(2) + ' CAD'].entries()) {
          const cell = document.createElement('td'); cell.textContent = text; cell.dataset.label = labels[index]; row.append(cell);
        }
        const cell = document.createElement('td');
        const form = document.createElement('form'); form.method = 'post';
        for (const [name, value] of [['csrf_token', csrf], ['product_id', item.product_id]]) {
          const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; form.append(input);
        }
        const button = document.createElement('button'); button.name = 'action'; button.value = 'remove'; button.textContent = itemsNode.dataset.remove;
        form.append(button); cell.append(form); row.append(cell); itemsNode.append(row);
      }
      document.querySelector('#cart-total').textContent = (data.total_cents / 100).toFixed(2) + ' CAD';
    }
  } catch (error) { statusNode.textContent = document.documentElement.lang === 'fr' ? 'Connexion interrompue' : 'Connection interrupted'; }
  window.setTimeout(poll, 1200);
}
if (statusNode) poll();
const fake = document.querySelector('#fake-tags');
if (fake) fake.addEventListener('submit', async event => {
  event.preventDefault();
  const response = await fetch(fake.action, {method: 'POST', body: new FormData(fake)});
  const data = await response.json(); statusNode.textContent = data.message || response.status;
});
