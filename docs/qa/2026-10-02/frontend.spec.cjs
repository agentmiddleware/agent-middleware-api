// QA regression coverage. This suite cannot contact non-loopback hosts.
const {test, expect} = require(process.env.QA_NODE_MODULES
  ? `${process.env.QA_NODE_MODULES}/@playwright/test` : '/private/tmp/amw-qa-browser/node_modules/@playwright/test');
test.beforeEach(async ({context}) => {
  await context.route('**/*', route => ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort('blockedbyclient'));
});

test('main public pages load without browser or resource errors', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);});
  for (const route of ['/', '/proof/', '/compare/', '/concept/', '/404.html']) {
    expect((await page.goto(route, {waitUntil: 'networkidle'})).status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
    expect(await page.locator('body').innerText()).not.toContain('@@PUBLIC_');
  }
  expect(errors).toEqual([]);
});

test('calculator valid, boundary, invalid and cleared states stay local', async ({page}) => {
  await page.goto('/');
  const fields = ['actions', 'rate', 'loss', 'reduction', 'cost'].map(name => page.locator(`#fit-${name}`));
  const summary = page.locator('[data-fit-summary]');
  const guidance = page.locator('[data-fit-guidance]');
  const requests = [];
  await page.waitForLoadState('networkidle');
  page.on('request', request => requests.push(request.url()));
  async function fill(values) {for (let i = 0; i < values.length; i++) await fields[i].fill(String(values[i]));}
  await expect(summary).toContainText('Enter the four');
  await fill([100000, 0.1, 50, 80, 2800]);
  await expect(summary).toContainText('$4,000.00');
  await expect(guidance).toContainText('exceeds');
  await expect(page.locator('[data-fit-next]')).toBeVisible();
  await fill([0, 100, 50, 100, 0]);
  await expect(guidance).toContainText('no avoided duplicates');
  await fill([1, 101, 50, 100, 0]);
  await expect(summary).toContainText('Check your inputs');
  await expect(fields[1]).toHaveAttribute('aria-invalid', 'true');
  await fill([1, 100, 1.005, 100, 1]);
  await expect(summary).toContainText('$1.01');
  await expect(guidance).toContainText('$0.01');
  await fields[2].fill('');
  await expect(summary).toContainText('Enter the four');
  expect(requests).toEqual([]);
});

test('receipt evidence loads without claiming cryptographic verification', async ({page}) => {
  await page.goto('/proof/');
  await expect(page.locator('[data-proof-status]').first()).toHaveText('artifacts loaded');
  await expect(page.locator('[data-proof-message]').first()).toContainText('Run the offline verifier');
});

test('receipt load failure removes published data and verification claims', async ({page}) => {
  await page.route('http://127.0.0.1:8765/proof/receipt.json', route => route.fulfill({status: 503, contentType: 'application/json', body: '{}'}));
  await page.goto('/proof/');
  await expect(page.locator('[data-proof-status]').first()).toHaveText('not published');
  await expect(page.locator('[data-proof-message]').first()).toContainText('No verification claim');
  for (const field of await page.locator('[data-proof-field]').all()) await expect(field).toHaveText('not published');
});

test('malformed receipt payload fails closed', async ({page}) => {
  await page.route('http://127.0.0.1:8765/proof/receipt.json', route => route.fulfill({status: 200, contentType: 'application/json', body: '{"signing_input":"not json"}'}));
  await page.goto('/proof/');
  await expect(page.locator('[data-proof-status]').first()).toHaveText('not published');
});

test('mobile pages do not overflow', async ({page}) => {
  await page.setViewportSize({width: 320, height: 844});
  for (const route of ['/', '/proof/', '/compare/', '/concept/', '/404.html']) {
    await page.goto(route, {waitUntil: 'networkidle'});
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), route).toBe(true);
  }
});

test('operator index is static and does not ask for credentials', async ({page}) => {
  await page.goto('http://127.0.0.1:8766/dashboard.html');
  await expect(page.locator('h1')).toContainText('Inspect the trust plane');
  expect(await page.locator('script, input, form').count()).toBe(0);
  await expect(page.locator('.notice')).toContainText('does not request API keys');
});

test('no JavaScript retains the pilot and proof entry path', async ({browser}) => {
  const context = await browser.newContext({javaScriptEnabled: false, serviceWorkers: 'block'});
  await context.route('**/*', route => ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort('blockedbyclient'));
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8765');
  await expect(page.locator('#pilot')).toContainText('Who owns the budget');
  await expect(page.locator('[data-fit-inputs]')).toBeHidden();
  expect(await page.locator('a[href="/proof/"]').count()).toBeGreaterThan(0);
  await context.close();
});
