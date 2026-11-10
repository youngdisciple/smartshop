// Optional browser verification: NODE_PATH=/path/to/node_modules node tests/browser_phase3.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const today = new Date().toISOString().slice(0, 10);
const suffixes = ['4965', '4970', '4968', '4951'];
const tags = suffixes.map(suffix => 'DE' + '0'.repeat(18) + suffix); // synthetic, never physical EPC evidence
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.SMARTSHOP_CHROMIUM_PATH || undefined});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function goto(path) { await page.goto('http://127.0.0.1:5093' + path); }
  async function click(label) { await page.getByRole('button', {name: label, exact: true}).click(); }
  async function fill(name, value) { await page.locator(`[name="${name}"]`).fill(value); }
  async function card() {
    await page.evaluate(async () => {
      const token = document.querySelector('meta[name="csrf-token"]').content;
      const response = await fetch('/__test/card', {method: 'POST', headers: {'X-CSRF-Token': token}});
      if (!response.ok) throw new Error('Card fixture failed');
    });
  }
  try {
    await goto('/auth/login'); await fill('email', 'admin@example.test'); await fill('password', 'fixture12'); await click('Sign in');
    for (let i = 0; i < 4; i++) {
      await goto('/products/new');
      for (const [name, value] of Object.entries({name: `Development product ${i + 1}`, category: 'Development', producer: 'Fixture', price: '1.25', upc: '000000000000' + i, epc: tags[i]})) await fill(name, value);
      await click('Save product');
      await goto('/inventory/' + (i + 1)); await fill('quantity', '3'); await fill('received_on', today); await click('Receive stock');
    }
    await goto('/products');
    await page.screenshot({path: '/tmp/smartshop-products-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    for (const path of ['/products', '/products/1/edit', '/inventory/1', '/account', '/account/card']) {
      await goto(path);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, path + ' page overflow');
    }
    await goto('/products'); await page.screenshot({path: '/tmp/smartshop-products-mobile.png', fullPage: true});
    await click('Sign out');
    await goto('/auth/signup');
    for (const [name, value] of Object.entries({name: 'Development member', email: 'member@example.test', address: '1 Test', password: 'fixture12', confirm_password: 'fixture12'})) await fill(name, value);
    await click('Create account');
    await goto('/account/card'); await click('Start enrollment'); await card();
    await page.getByRole('button', {name: 'Confirm link', exact: true}).waitFor(); await click('Confirm link');
    await goto('/checkout'); await click('Start a new checkout');
    const cartPath = new URL(page.url()).pathname;
    await click('Start product scan');
    await fill('tags', tags.concat(tags[0]).join(' ')); await click('Queue development scans');
    await page.waitForFunction(() => document.querySelectorAll('#cart-items tr').length === 4);
    assert.equal(await page.locator('#cart-total').textContent(), '5.00 CAD');
    await page.getByRole('button', {name: 'Remove', exact: true}).first().click();
    await page.waitForFunction(() => document.querySelectorAll('#cart-items tr').length === 3);
    await page.screenshot({path: '/tmp/smartshop-cart-mobile.png', fullPage: true});
    await click('Review purchase'); await click('Scan membership card'); await card();
    await page.getByRole('link', {name: 'Refresh membership result', exact: true}).click();
    await click('Confirm membership'); await click('Proceed to simulated payment');
    await click('Simulate failure');
    await click('Proceed to simulated payment'); await click('Simulate success');
    await page.getByRole('heading', {name: 'Receipt', exact: true}).waitFor();
    assert.match(await page.locator('main').textContent(), /Points earned: 3/);
    await page.screenshot({path: '/tmp/smartshop-receipt-mobile.png', fullPage: true});
    await goto('/account'); assert.equal(await page.getByRole('link', {name: 'View receipt'}).count(), 1);
    await page.locator('#language').selectOption('fr'); await click('Apply');
    assert.equal(await page.locator('html').getAttribute('lang'), 'fr');
    assert.equal(await page.getByRole('heading', {name: 'Mon compte'}).count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('Browser flow passed: product reception, enrollment, repeated scans, remove, member payment failure/success, receipt/history, French, desktop/mobile overflow.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
