// Regression coverage for the 2026-10-02 UX findings.
const modules = process.env.QA_NODE_MODULES || '/private/tmp/amw-qa-browser/node_modules';
const {test, expect} = require(`${modules}/@playwright/test`);
const axe = require(`${modules}/axe-core`);

test.beforeEach(async ({context, page}) => {
  await context.route('**/*', route => {
    const host = new URL(route.request().url()).hostname;
    return ['127.0.0.1', 'localhost', '[::1]'].includes(host)
      ? route.continue() : route.abort('blockedbyclient');
  });
  await page.setViewportSize({width: 390, height: 844});
});

test('UX-001: comparison fit text meets minimum contrast', async ({page}) => {
  await page.goto('/compare/');
  await page.addScriptTag({content: axe.source});
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run('.proof-col:not(.replay) .fit-list', {
      runOnly: {type: 'rule', values: ['color-contrast']},
    });
    return result.violations.map(v => v.id);
  });
  expect(violations).toEqual([]);
});

test('UX-002: dashboard scrollable commands have explicit keyboard access', async ({page}) => {
  await page.goto('http://127.0.0.1:8766/dashboard.html');
  const code = page.locator('pre');
  const state = await code.evaluate(element => ({
    scrolls: element.scrollWidth > element.clientWidth,
    keyboardAccessible: element.tabIndex >= 0 || element.querySelector(
      'a[href],button,input,select,textarea,[tabindex="0"]',
    ) !== null,
  }));
  expect(!state.scrolls || state.keyboardAccessible).toBe(true);
  await expect(code).toHaveAccessibleName('Authenticated inspection commands');
  await page.locator('a[href$="/llms.txt"]').focus();
  await page.keyboard.press('Tab');
  await expect(code).toBeFocused();
  expect(await code.evaluate(element => parseFloat(getComputedStyle(element).outlineWidth)))
    .toBeGreaterThan(0);
  if (state.scrolls) {
    // WebKit needs time between keydown and keyup to start native scrolling.
    await page.keyboard.press('ArrowRight', {delay: 100});
    await expect.poll(() => code.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  }
});

test('UX-003: operator runtime links remain on the served origin', async ({page}) => {
  await page.goto('http://127.0.0.1:8766/dashboard.html');
  for (const name of [/Runtime truth/, /Current trust keys/, /Agent manifest/, /llms.txt/]) {
    const links = page.getByRole('link', {name});
    await expect(links.first()).toBeVisible();
    for (const link of await links.all()) {
      const href = await link.getAttribute('href');
      expect(new URL(href, page.url()).origin).toBe(new URL(page.url()).origin);
    }
  }
});
