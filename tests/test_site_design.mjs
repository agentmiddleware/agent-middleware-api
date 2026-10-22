// Usage: node tests/test_site_design.mjs <local URL> [Playwright module path] [screenshot directory]
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a loopback preview");
const { chromium } = await import(process.argv[3] ? pathToFileURL(process.argv[3]).href : "playwright");
const browser = await chromium.launch({ headless: true });
const routes = ["/", "/try/", "/docs/", "/docs/three-minute-quickstart/", "/proof/", "/compare/", "/concept/", "/demo-key/", "/pilot/", "/404.html"];
const docsManifest = JSON.parse(await readFile(new URL("../site/docs-src/nav.json", import.meta.url), "utf8"));
const docsRoutes = docsManifest.sections.flatMap((section) => section.pages.map((entry) => `/docs/${entry.slug}/`));
const contrastPairs = new Map([
  ["/try/", [[".try-page .eyebrow", "#main"], [".try-page .page-intro > p:last-child", "#main"], [".try-page .key-panel", ".try-page .key-panel"], [".try-page .primary-button", ".try-page .primary-button"]]],
  ["/docs/three-minute-quickstart/", [[".docs-content p", "#main"], [".docs-content pre code", ".docs-content pre"]]],
  ["/proof/", [[".proof-page-lead", "#main"], [".proof-live-section pre", ".proof-live-section pre"]]],
  ["/compare/", [[".compare-table tbody td", ".compare-scroll"], [".compare-table caption", ".compare-scroll"]]],
  ["/pilot/", [[".fit-fields input", ".fit-fields input"]]],
  ["/demo-key/", [[".demo-key-panel", ".demo-key-panel"]]],
  ["/concept/", [[".hero-body", "#main"]]],
]);
function luminance(color) {
  const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  assert.equal(channels?.length, 3, `expected RGB color: ${color}`);
  return channels.reduce((sum, value, index) => {
    const normalized = value / 255;
    const linear = normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    return sum + linear * [0.2126, 0.7152, 0.0722][index];
  }, 0);
}
function contrast(foreground, background) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
const errors = [];
let scenarios = 0;
try {
  for (const javaScriptEnabled of [true, false]) {
    for (const width of [320, 390, 768, 1024, 1440]) {
      const context = await browser.newContext({ javaScriptEnabled, viewport: { width, height: 1000 }, reducedMotion: "reduce" });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("response", (response) => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
      let commonNav;
      let commonFooter;
      let commonHeading;
      for (const route of routes) {
        const response = await page.goto(new URL(route, base).href, { waitUntil: "networkidle" });
        assert.equal(response.status(), 200, route);
        await page.evaluate(() => document.fonts.ready);
        const layout = await page.evaluate((route) => {
          const nav = document.querySelector(".site-nav");
          const styles = getComputedStyle(document.body);
          return {
            overflow: document.documentElement.scrollWidth > innerWidth,
            nav: [...nav.querySelectorAll("a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]),
            footer: [...document.querySelectorAll(".site-footer a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]),
            theme: [styles.fontFamily, styles.fontSize, styles.color, styles.backgroundColor, getComputedStyle(document.querySelector("h1")).fontFamily],
            mainBackground: getComputedStyle(document.querySelector("main")).backgroundColor,
            navBackground: getComputedStyle(nav).backgroundColor,
            footerColor: getComputedStyle(document.querySelector(".site-footer")).color,
            footerBackground: route === "/" ? styles.backgroundColor : getComputedStyle(document.querySelector(".site-footer"), "::before").backgroundColor,
            homeSurface: route === "/" ? [
              getComputedStyle(document.querySelector("main")).backgroundColor,
              getComputedStyle(document.querySelector(".hero-v2 h1")).color,
            ] : null,
            navHeight: getComputedStyle(nav).position === "sticky" ? nav.getBoundingClientRect().height : 0,
            scrollPadding: parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop),
          };
        }, route);
        assert(!layout.overflow, `${route} overflows at ${width}px JS=${javaScriptEnabled}`);
        assert(layout.scrollPadding >= layout.navHeight, `${route} sticky nav obscures anchors: ${layout.navHeight} > ${layout.scrollPadding} at ${width}px`);
        commonNav ??= layout.nav;
        commonFooter ??= layout.footer;
        assert.deepEqual(layout.nav, commonNav, `${route} navigation differs`);
        assert.deepEqual(layout.footer, commonFooter, `${route} footer differs`);
        assert.equal(layout.theme[0], '"Public Sans", "Segoe UI", system-ui, sans-serif');
        assert.equal(layout.mainBackground, "rgb(255, 255, 255)", `${route} main is not light`);
        assert.equal(layout.navBackground, "rgb(255, 255, 255)", `${route} navigation is not light`);
        assert.equal(layout.footerColor, "rgb(233, 237, 248)", `${route} dark footer lost readable text`);
        assert.equal(layout.footerBackground, "rgb(11, 16, 32)", `${route} dark footer background differs`);
        if (route === "/") {
          assert.equal(layout.theme[4], '"Public Sans", "Segoe UI", system-ui, sans-serif');
          assert.deepEqual(layout.theme.slice(2, 4), ["rgb(233, 237, 248)", "rgb(11, 16, 32)"]);
          assert.deepEqual(layout.homeSurface, ["rgb(255, 255, 255)", "rgb(17, 17, 17)"]);
          if (!javaScriptEnabled) {
            assert.equal(await page.locator("#home-key-trigger").isVisible(), false);
            assert.equal(await page.locator('noscript a[href="/demo-key/"]').isVisible(), true);
          }
        } else {
          assert.deepEqual(layout.theme.slice(2, 4), ["rgb(17, 17, 17)", "rgb(255, 255, 255)"], `${route} body is not light`);
          commonHeading ??= layout.theme[4];
          assert.equal(layout.theme[4], commonHeading, `${route} heading design token differs`);
        }
        await page.keyboard.press("Tab");
        assert.equal(await page.locator(":focus").getAttribute("class"), "skip-link");
        await page.keyboard.press("Enter");
        assert.equal(new URL(page.url()).hash, "#main");
        if (process.argv[4] && javaScriptEnabled && [390, 1440].includes(width)) {
          await mkdir(process.argv[4], { recursive: true });
          await page.goto(new URL(route, base).href, { waitUntil: "networkidle" });
          await page.screenshot({ path: `${process.argv[4]}/${route.replaceAll("/", "") || "home"}-${width}.png` });
        }
        scenarios++;
      }
      await context.close();
    }
  }
  const page = await browser.newPage({ viewport: { width: 320, height: 1000 }, reducedMotion: "reduce" });
  await page.goto(base.href);
  await page.evaluate(() => localStorage.setItem("amw-a11y", JSON.stringify({ scale: 1.4, contrast: true, spacing: true, motion: true })));
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of routes) {
      const response = await page.goto(new URL(route, base).href, { waitUntil: "networkidle" });
      assert.equal(response.status(), 200, `${route} preview missing during accessibility checks`);
      await page.evaluate(() => document.fonts.ready);
      const result = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth,
        nav: getComputedStyle(document.querySelector(".site-nav")).position === "sticky" ? document.querySelector(".site-nav").getBoundingClientRect().height : 0,
        padding: parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop),
        color: getComputedStyle(document.body).color,
      }));
      assert(!result.overflow, `${route} enlarged high-contrast text overflows`);
      assert(result.padding >= result.nav, `${route} enlarged nav obscures targets: ${result.nav} > ${result.padding}`);
      assert.equal(result.color, "rgb(255, 255, 255)");
      scenarios++;
    }
  }
  const docsPage = await browser.newPage({ viewport: { width: 320, height: 1000 } });
  await docsPage.goto(new URL("/docs/", base).href);
  await docsPage.evaluate(() => localStorage.setItem("amw-a11y", JSON.stringify({ scale: 1.4, contrast: true, spacing: true, motion: true })));
  for (const route of docsRoutes) {
    const response = await docsPage.goto(new URL(route, base).href, { waitUntil: "domcontentloaded" });
    assert.equal(response.status(), 200, `${route} is missing`);
    await docsPage.evaluate(() => document.fonts.ready);
    assert(await docsPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${route} overflows at 320px with enlarged high-contrast text`);
    scenarios++;
  }
  await docsPage.close();
  const contrastPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  for (const [route, pairs] of contrastPairs) {
    await contrastPage.goto(new URL(route, base).href, { waitUntil: "networkidle" });
    for (const [foreground, background] of pairs) {
      const colors = await contrastPage.evaluate(([fg, bg]) => [
        getComputedStyle(document.querySelector(fg)).color,
        getComputedStyle(document.querySelector(bg)).backgroundColor,
      ], [foreground, background]);
      assert(contrast(...colors) >= 4.5, `${route} ${foreground} fails AA against ${background}: ${colors.join(" on ")}`);
      scenarios++;
    }
  }
  await contrastPage.close();
  const keyPage = await browser.newPage({ viewport: { width: 320, height: 1000 } });
  let keyStatus = 500;
  await keyPage.route("https://api.thisisatest.tech/v1/demo/keys", (route) =>
    route.fulfill({ status: keyStatus, body: "", headers: { "Access-Control-Allow-Origin": "*" } }));
  for (const [status, visibleId, hiddenId] of [
    [500, "home-key-retry", "home-key-email"],
    [404, "home-key-email", "home-key-retry"],
  ]) {
    keyStatus = status;
    await keyPage.goto(base.href, { waitUntil: "networkidle" });
    await keyPage.locator("#home-key-trigger").click();
    await keyPage.locator(`#${visibleId}`).waitFor({ state: "visible" });
    assert.equal(await keyPage.locator(`#${hiddenId}`).isVisible(), false);
    assert(await keyPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    scenarios++;
  }
  await keyPage.close();
  // The operator index stays self-contained on its separate API origin.
  // A fresh response must use the API policy: setContent on the marketing
  // document inherits its style-src 'self' and incorrectly blocks this CSS.
  const apiPolicy = JSON.parse(execFileSync("python3", ["-c", `
import ast, json, pathlib, sys
tree = ast.parse(pathlib.Path(sys.argv[1]).read_text())
policy = next(ast.literal_eval(node.value) for node in tree.body
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
    and target.id == "FIRST_PARTY_HTML_CSP" for target in node.targets))
print(json.dumps(policy))
`, fileURLToPath(new URL("../app/middleware/security_headers.py", import.meta.url))], { encoding: "utf8" }));
  const operator = await browser.newPage({ viewport: { width: 320, height: 1000 } });
  operator.on("pageerror", (error) => errors.push(error.message));
  operator.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const operatorURL = new URL("/operator-preview", base).href;
  const operatorHTML = await readFile(new URL("../static/dashboard.html", import.meta.url), "utf8");
  await operator.route(operatorURL, (route) => route.fulfill({
    status: 200, contentType: "text/html", body: operatorHTML,
    headers: { "Content-Security-Policy": apiPolicy },
  }));
  await operator.goto(operatorURL);
  assert.equal(await operator.locator("script").count(), 0);
  assert.equal(await operator.evaluate(() => getComputedStyle(document.body).backgroundColor), "rgb(11, 16, 32)");
  for (const width of [320, 390, 1440]) {
    await operator.setViewportSize({ width, height: 1000 });
    assert(await operator.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `dashboard overflows at ${width}`);
    scenarios++;
  }
  assert.deepEqual(errors, [], "Browser errors or failed assets");
  console.log(`${scenarios} design scenarios passed: shared shell, theme, responsive layout, keyboard, accessibility preferences, and no-JavaScript rendering.`);
} finally {
  await browser.close();
}
