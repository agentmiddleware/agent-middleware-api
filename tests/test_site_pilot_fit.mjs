// Usage: node tests/test_site_pilot_fit.mjs <local URL> [Playwright module path] [screenshot directory]
// Uses a real browser for number-input validity, live results, and mobile layout.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const baseURL = new URL(process.argv[2] || "http://127.0.0.1:8765");
assert(["127.0.0.1", "localhost", "[::1]"].includes(baseURL.hostname), "Use a loopback preview, not production");
const playwright = await import(process.argv[3] ? pathToFileURL(process.argv[3]).href : "playwright");
const browser = await playwright.chromium.launch({ headless: true });
const errors = [];
let scenarios = 0;
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  page.on("pageerror", (error) => errors.push(error.message));
  const response = await page.goto(baseURL.href, { waitUntil: "networkidle" });
  assert.equal(response.status(), 200, "Build site/dist before running the browser checks");
  const panel = page.locator("#economic-fit");
  const summary = panel.locator("[data-fit-summary]");
  const guidance = panel.locator("[data-fit-guidance]");
  const next = panel.locator("[data-fit-next]");
  const alternative = panel.locator("[data-fit-alternative]");
  const inputs = ["actions", "rate", "loss", "reduction", "cost"].map((name) => page.locator("#fit-" + name));
  async function fill(values) {
    for (let index = 0; index < values.length; index++) await inputs[index].fill(String(values[index]));
    scenarios++;
  }
  assert.match(await summary.innerText(), /Enter the four/);
  for (const input of inputs) assert.equal(await input.inputValue(), "");
  const storageBefore = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));

  await fill([100000, 0.1, 50, 80, 2800]);
  assert.match(await summary.innerText(), /\$4,000.00/);
  assert.match(await guidance.innerText(), /exceeds.*\$1,200.00.*duplicate: \$35.00/);
  assert.equal(await next.isVisible(), true);
  assert.equal(await alternative.isVisible(), false);
  await fill([100000, 0.01, 50, 80, 2800]);
  assert.match(await summary.innerText(), /\$400.00/);
  assert.match(await guidance.innerText(), /does not exceed.*duplicate: \$350.00/);
  assert.equal(await next.isVisible(), false);
  assert.equal(await alternative.isVisible(), true);
  await fill([100000, 0.1, 50, 80, 4000]);
  assert.match(await guidance.innerText(), /does not exceed/);
  // Displayed monetary amounts must govern fit, including binary rounding noise.
  for (const values of [[3, 10, 100, 10, 3], [3, 10, 100, 10, 2.999], [1, 100, 1.004, 100, 1]]) {
    await fill(values);
    assert.match(await guidance.innerText(), /does not exceed/);
    assert.equal(await next.isVisible(), false);
  }
  for (const cost of [1, 1.004]) {
    await fill([1, 100, 1.005, 100, cost]);
    assert.match(await summary.innerText(), /\$1.01/);
    assert.match(await guidance.innerText(), /exceeds.*\$0.01/);
    assert.equal(await next.isVisible(), true);
  }
  await fill([100000, 0.1, 50, 80, ""]);
  assert.match(await guidance.innerText(), /fit is still unknown/);
  assert.equal(await next.isVisible(), false);
  await fill([100000, 0.1, 50, 80, 0]);
  assert.match(await guidance.innerText(), /duplicate: \$0.00/);
  for (const index of [0, 1, 3]) {
    const values = [100000, 0.1, 50, 80, 2800];
    values[index] = 0;
    await fill(values);
    assert.match(await guidance.innerText(), /no avoided duplicates/);
    assert.doesNotMatch(await panel.innerText(), /Infinity|NaN/);
    assert.equal(await next.isVisible(), false);
  }
  await fill([100000, 0.1, 0, 80, 2800]);
  assert.match(await summary.innerText(), /\$0.00/);
  assert.match(await guidance.innerText(), /does not exceed/);
  for (const [index, value] of [[0, -1], [0, 0.5], [1, -0.1], [1, 101], [2, -1], [3, 101], [4, -1]]) {
    const values = [100000, 0.1, 50, 80, 2800];
    values[index] = value;
    await fill(values);
    assert.match(await summary.innerText(), /Check your inputs/);
    assert.equal(await inputs[index].getAttribute("aria-invalid"), "true");
    assert.equal(await next.isVisible(), false);
    assert.equal(await guidance.innerText(), "");
  }
  await fill([100000, 0.1, 1e308, 80, 2800]);
  assert.match(await summary.innerText(), /too large/);
  await fill([100000, 0.1, "", 80, 2800]);
  assert.match(await summary.innerText(), /Enter the four/);
  assert.equal(await next.isVisible(), false);
  await inputs[2].pressSequentially("e");
  assert.match(await summary.innerText(), /Check your inputs/);
  await fill([100000, 100, 50, 100, 2800]);
  assert.match(await summary.innerText(), /\$5,000,000.00/);
  await fill([100000, 0.1, 50, 80, 2800]);
  await inputs[0].focus();
  await page.keyboard.press("Tab");
  assert.equal(await inputs[1].evaluate((input) => input === document.activeElement), true);
  assert.equal(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage])), storageBefore);
  assert.deepEqual(requests, [], "Editing assumptions must not transmit values or load remote assets");

  const pilotLink = page.locator('#pilot a[aria-label="Start a pilot by email (opens your mail app)"]');
  const draft = new URL(await pilotLink.getAttribute("href"));
  assert.match(draft.searchParams.get("body"), /4\. Cost of one duplicate/);
  assert.match(draft.searchParams.get("body"), /5\. Budget owner and target decision date/);
  assert.doesNotMatch(draft.searchParams.get("body"), /100000|2800/);
  if (process.argv[4]) {
    await mkdir(process.argv[4], { recursive: true });
    await panel.screenshot({ path: process.argv[4] + "/pilot-fit-desktop.png" });
  }
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await panel.scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow at ${width}px`);
    for (const input of inputs) {
      const box = await input.boundingBox();
      assert(box.x >= 0 && box.x + box.width <= width && box.height >= 44);
    }
  }
  if (process.argv[4]) await panel.screenshot({ path: process.argv[4] + "/pilot-fit-mobile.png" });
  await page.evaluate(() => document.documentElement.setAttribute("data-a11y-contrast", "high"));
  assert.equal(await inputs[0].isVisible(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  const noJS = await browser.newPage({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  await noJS.goto(baseURL.href);
  assert.equal(await noJS.locator("[data-fit-inputs]").isVisible(), false);
  assert.equal(await noJS.locator("#economic-fit summary").isVisible(), true);
  await noJS.locator("#economic-fit summary").click();
  assert.match(await noJS.locator("#economic-fit").innerText(), /threshold rises to \$350/);
  assert.match(await noJS.locator("#pilot").innerText(), /Who owns the budget/);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, calculatorScenarios: scenarios, viewports: [1440, 390, 320], noJavaScript: true, inputPrivacy: true, browserErrors: errors }));
} finally {
  await browser.close();
}
