// Run with: node --test tests/product_reader_ui.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function fixture() {
  const nodes = new Map();
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      content: 'csrf', value: '', textContent: '', disabled: false,
      dataset: {starting: 'Starting', waiting: 'Waiting', multiple: 'Multiple', connection: 'Offline', upcPrompt: 'Scan or enter a UPC first'},
      focus() { this.focused = true; },
      handlers: {}, addEventListener(event, callback) { this.handlers[event] = callback; }
    });
    return nodes.get(selector);
  }
  const window = {
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); }, addEventListener() {}
  };
  vm.runInNewContext(fs.readFileSync('smartshop/static/product.js', 'utf8'), {
    document: {querySelector: node}, window,
    fetch(url) { return new Promise(resolve => requests.push({url, resolve})); }
  });
  async function respond(index, data, ok = true) {
    requests[index].resolve({ok, json: async () => data});
    await new Promise(resolve => setImmediate(resolve));
  }
  return {node, requests, timers, respond};
}

test('empty UPC lookup focuses input without requesting validation', async () => {
  const f = fixture();
  assert.equal(f.requests.length, 0);
  for (const value of ['', '   ']) {
    f.node('#upc').value = value;
    await f.node('#lookup-upc').handlers.click();
    assert.equal(f.requests.length, 0);
    assert.equal(f.node('#upc').focused, true);
    assert.equal(f.node('#scanner-status').textContent, 'Scan or enter a UPC first');
  }
});

test('populated UPC lookup preserves leading zeros', async () => {
  const f = fixture();
  f.node('#upc').value = ' 001234567890 ';
  const lookup = f.node('#lookup-upc').handlers.click();
  assert.equal(f.requests[0].url, '/products/lookup?upc=001234567890');
  await f.respond(0, {name: 'Test product', price_cents: 125});
  await lookup;
  assert.equal(f.node('#scanner-status').textContent, 'Test product · 1.25 CAD');
});

test('repeated capture clicks start only one polling loop and show waiting/captured states', async () => {
  const f = fixture();
  const button = f.node('#capture-epc');
  const started = button.handlers.click();
  button.handlers.click();
  assert.equal(f.requests.length, 1);
  assert.equal(button.disabled, true);
  await f.respond(0, {operation_id: 'one'});
  await started;
  assert.equal(f.requests[1].url, '/reader/product/result');
  await f.respond(1, {tags: []});
  assert.equal(f.node('#scanner-status').textContent, 'Waiting');
  assert.equal(f.timers.size, 1);
  const [id, callback] = [...f.timers][0];
  f.timers.delete(id);
  callback();
  await f.respond(2, {tags: ['0000ABCD']});
  assert.equal(f.node('#epc').value, '0000ABCD');
  assert.equal(f.timers.size, 1);
});

test('cancellation ignores a stale in-flight result', async () => {
  const f = fixture();
  f.node('#capture-epc').handlers.click();
  await f.respond(0, {operation_id: 'one'});
  const cancelled = f.node('#cancel-capture').handlers.click();
  await f.respond(1, {tags: ['00AA']});
  assert.equal(f.node('#epc').value, '');
  assert.equal(f.timers.size, 0);
  await f.respond(2, {message: 'Cancelled'});
  await cancelled;
  assert.equal(f.node('#scanner-status').textContent, 'Cancelled');
  assert.equal(f.node('#capture-epc').disabled, false);
});

test('multiple tags clear an ambiguous field; reader errors allow retry', async () => {
  const f = fixture();
  f.node('#epc').value = '00AA';
  f.node('#capture-epc').handlers.click();
  await f.respond(0, {operation_id: 'one'});
  await f.respond(1, {tags: ['00AA', '00BB']});
  assert.equal(f.node('#epc').value, '');
  assert.equal(f.node('#scanner-status').textContent, 'Multiple');
  const [id, callback] = [...f.timers][0];
  f.timers.delete(id);
  callback();
  await f.respond(2, {error: 'Expired'}, false);
  assert.equal(f.node('#scanner-status').textContent, 'Expired');
  assert.equal(f.node('#capture-epc').disabled, false);
  assert.equal(f.timers.size, 0);
});
