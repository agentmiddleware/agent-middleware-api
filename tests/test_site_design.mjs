// Usage: node tests/test_site_design.mjs <local URL> [Playwright module path] [screenshot directory]
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const base = new URL(process.argv[2] || "http://127.0.0.1:8765");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a loopback preview");
const { chromium } = await import(process.argv[3] ? pathToFileURL(process.argv[3]).href : "playwright");
const browser = await chromium.launch({ headless: true });
const routes = ["/", "/proof/", "/compare/", "/concept/", "/404.html"];
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
      let commonStyle;
      for (const route of routes) {
        const response = await page.goto(new URL(route, base).href, { waitUntil: "networkidle" });
        assert.equal(response.status(), 200, route);
        await page.evaluate(() => document.fonts.ready);
        const layout = await page.evaluate(() => {
          const nav = document.querySelector(".site-nav");
          const styles = getComputedStyle(document.body);
          return {
            overflow: document.documentElement.scrollWidth > innerWidth,
            nav: [...nav.querySelectorAll("a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]),
            footer: [...document.querySelectorAll(".site-footer a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]),
            theme: [styles.fontFamily, styles.fontSize, styles.color, styles.backgroundColor, getComputedStyle(document.querySelector("h1")).fontFamily],
            navHeight: getComputedStyle(nav).position === "sticky" ? nav.getBoundingClientRect().height : 0,
            scrollPadding: parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop),
          };
        });
        assert(!layout.overflow, `${route} overflows at ${width}px JS=${javaScriptEnabled}`);
        assert(layout.scrollPadding >= layout.navHeight, `${route} sticky nav obscures anchors: ${layout.navHeight} > ${layout.scrollPadding} at ${width}px`);
        commonNav ??= layout.nav;
        commonFooter ??= layout.footer;
        commonStyle ??= layout.theme;
        assert.deepEqual(layout.nav, commonNav, `${route} navigation differs`);
        assert.deepEqual(layout.footer, commonFooter, `${route} footer differs`);
        assert.deepEqual(layout.theme, commonStyle, `${route} design tokens differ`);
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
