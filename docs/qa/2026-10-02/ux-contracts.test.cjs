// Offline DOM/CSS checks; rendering, keyboard scrolling and axe remain browser tests.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const modules = process.env.QA_NODE_MODULES || '/private/tmp/amw-qa-browser/node_modules';
const {JSDOM} = require(`${modules}/jsdom`);
const root = path.resolve(__dirname, '../../..');

function page(file) {
  // No script execution or subresource loading: the checks cannot contact a host.
  return new JSDOM(fs.readFileSync(path.join(root, file), 'utf8'), {
    url: 'http://127.0.0.1:8765/',
  });
}

function luminance(color) {
  const rgb = color.match(/^rgb\((\d+), (\d+), (\d+)\)$/);
  assert(rgb, `Expected an opaque resolved RGB color, got ${color}`);
  const [r, g, b] = rgb.slice(1).map(value => {
    const channel = Number(value) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

for (const contrast of ['default', 'high']) {
  test(`UX-001: paper and dark fit lists meet 4.5:1 contrast (${contrast})`, () => {
    const dom = page('site/compare/index.html');
    try {
      const {document} = dom.window;
      if (contrast === 'high') document.documentElement.dataset.a11yContrast = 'high';
      const style = document.createElement('style');
      const css = fs.readFileSync(path.join(root, 'site/styles.css'), 'utf8');
      style.textContent = css;
      document.head.append(style);
      const tokens = dom.window.getComputedStyle(document.documentElement);
      // JSDOM preserves var() in computed colors. Resolve the page's root palette
      // before computing the real selectors and cascade; do not substitute colors.
      style.textContent = css.replace(/var\((--[\w-]+)\)/g, (value, token) =>
        tokens.getPropertyValue(token).trim() || value);
      for (const selector of ['.proof-col:not(.replay)', '.proof-col.replay']) {
        const card = document.querySelector(selector);
        const background = luminance(dom.window.getComputedStyle(card).backgroundColor);
        const items = card.querySelectorAll('.fit-list li');
        assert.equal(items.length, 4);
        for (const item of items) {
          const foreground = luminance(dom.window.getComputedStyle(item).color);
          const ratio = (Math.max(background, foreground) + 0.05) /
            (Math.min(background, foreground) + 0.05);
          assert(ratio >= 4.5, `${selector}: contrast ${ratio.toFixed(2)}:1 is below 4.5:1`);
        }
      }
    } finally {dom.window.close();}
  });
}
