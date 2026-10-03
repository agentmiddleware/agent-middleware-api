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
  for (const contrast of ['default', 'high']) {
    const violations = await page.evaluate(async contrast => {
      document.documentElement.dataset.a11yContrast = contrast;
      const result = await window.axe.run('.fit-list', {
        runOnly: {type: 'rule', values: ['color-contrast']},
      });
      return result.violations.map(v => v.id);
    }, contrast);
    expect(violations, `${contrast} contrast on both paper and dark cards`).toEqual([]);
  }
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
    // WebKit needs a held key to start smooth keyboard scrolling.
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

for (const width of [360, 768, 1280, 1920]) {
  test(`TC-FE-004: navigation and footer touch targets at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 1000});
    for (const route of ['/', '/proof/', '/compare/', '/concept/', '/404.html',
      'http://127.0.0.1:8766/dashboard.html']) {
      await page.goto(route);
      await page.evaluate(() => document.fonts.ready);
      const layout = await page.evaluate(() => {
        // Standalone navigation and footer links have touch targets; inline
        // prose links retain text flow and are outside this regression's scope.
        const targets = [...document.querySelectorAll('.site-nav a, .site-footer a, body > header a, body > footer a')];
        const small = targets.filter(element => {
          const bounds = element.getBoundingClientRect();
          return bounds.width < 44 || bounds.height < 44;
        }).map(element => ({text: element.textContent.trim(),
          width: element.getBoundingClientRect().width,
          height: element.getBoundingClientRect().height}));
        const controls = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex="0"]')]
          .filter(element => getComputedStyle(element).visibility !== 'hidden');
        const overlaps = [];
        for (let i = 0; i < controls.length; i++) {
          for (let j = i + 1; j < controls.length; j++) {
            const a = controls[i], b = controls[j];
            if (a.contains(b) || b.contains(a)) continue;
            // A wrapped inline link's bounding box includes empty line space;
            // compare its actual rendered fragments to avoid false collisions.
            const intersects = [...a.getClientRects()].some(x => [...b.getClientRects()].some(y =>
              Math.min(x.right, y.right) - Math.max(x.left, y.left) > 2 &&
              Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 2));
            if (intersects) overlaps.push([a.textContent.trim(), b.textContent.trim()]);
          }
        }
        return {targetCount: targets.length, small, overlaps,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth};
      });
      expect(layout.targetCount, route).toBeGreaterThan(0);
      expect(layout.small, `${route} at ${width}px`).toEqual([]);
      expect(layout.horizontalOverflow, `${route} at ${width}px`).toBe(false);
      expect(layout.overlaps, `${route} at ${width}px`).toEqual([]);
    }
  });
}
