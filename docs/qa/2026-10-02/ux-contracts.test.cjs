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

test('UX-002: operator commands expose a named keyboard focus target', () => {
  const dom = page('static/dashboard.html');
  try {
    const {document} = dom.window;
    const code = document.querySelector('pre');
    assert.equal(code.tabIndex, 0, 'Scrollable commands must join sequential keyboard navigation');
    assert.equal(code.getAttribute('role'), 'region');
    assert.equal(code.getAttribute('aria-label'), 'Authenticated inspection commands');
    code.focus();
    assert.equal(document.activeElement, code);
  } finally {dom.window.close();}
});

test('UX-003: operator runtime links resolve on the served origin', () => {
  const dom = page('static/dashboard.html');
  try {
    const {document} = dom.window;
    const runtimePaths = ['/health/dependencies', '/.well-known/trust-keys.json',
      '/.well-known/agent.json', '/llms.txt'];
    const links = [...document.querySelectorAll('a[href]')];
    for (const pathname of runtimePaths) {
      const matches = links.filter(link => new URL(link.href).pathname === pathname);
      assert(matches.length > 0, `Missing runtime link: ${pathname}`);
      for (const link of matches) {
        for (const origin of ['http://127.0.0.1:8765', 'https://operator.example']) {
          assert.equal(new URL(link.getAttribute('href'), origin).origin, origin,
            `${pathname} must inspect the served runtime`);
        }
      }
    }
    for (const link of links.filter(link => new URL(link.href).pathname === '/proof/')) {
      assert.match(link.textContent, /hosted/i, 'External proof must be labeled as hosted');
    }
  } finally {dom.window.close();}
});

test('UX-003: inspection commands require an explicit API origin', () => {
  const dom = page('static/dashboard.html');
  try {
    const code = dom.window.document.querySelector('pre').textContent;
    assert.match(code, /export API_URL="http:\/\/127\.0\.0\.1:8000"/);
    for (const endpoint of ['permits', 'receipts', 'audit/events']) {
      assert(code.includes('"${API_URL}/v1/me/' + endpoint + '"'));
    }
    assert(!code.includes('https://api.thisisatest.tech'));
  } finally {dom.window.close();}
});
