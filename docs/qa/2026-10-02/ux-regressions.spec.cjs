// Known issues are expected failures until the corresponding product fix lands.
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
  test.fail(true, 'UX-001: paper card inherits dark-surface text color (2.13:1).');
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
  test.fail(true, 'UX-002: scrollable pre has neither tabindex nor focusable content.');
  await page.goto('http://127.0.0.1:8766/dashboard.html');
  const code = page.locator('pre');
  const state = await code.evaluate(element => ({
    scrolls: element.scrollWidth > element.clientWidth,
    keyboardAccessible: element.tabIndex >= 0 || element.querySelector(
      'a[href],button,input,select,textarea,[tabindex="0"]',
    ) !== null,
  }));
  expect(!state.scrolls || state.keyboardAccessible).toBe(true);
});

test('UX-003: operator runtime links remain on the served origin', async ({page}) => {
  test.fail(true, 'UX-003: runtime links target a fixed production origin from local dashboard.');
  await page.goto('http://127.0.0.1:8766/dashboard.html');
  const href = await page.getByRole('link', {name: /Runtime truth/}).first().getAttribute('href');
  expect(new URL(href, page.url()).origin).toBe(new URL(page.url()).origin);
});
