// Verify the local report and export PDF using an existing Playwright runtime.
// node check-export.mjs /absolute/path/to/playwright/index.js
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const playwrightModule = await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : 'playwright');
const { chromium } = playwrightModule.default ?? playwrightModule;
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.goto(pathToFileURL(path.join(root,'report.html')).href);
assert.equal(await page.locator('main h2').count(),29);
assert.equal(await page.locator('#revenue').textContent(),'$2,400.00');
assert.equal(await page.locator('#cogs').textContent(),'$662.65');
assert.equal(await page.locator('#contribution').textContent(),'$1,737.35');
assert.equal(await page.locator('#margin').textContent(),'72.4%');
await page.locator('#enterprise').fill('1000');
assert.equal(await page.locator('#contribution').textContent(),'$737.35');
assert.equal(await page.locator('#margin').textContent(),'30.7%');
await page.locator('#enterprise').fill('2000');
assert.equal(await page.locator('#contribution').textContent(),'-$262.65');
assert.equal(await page.locator('#margin').textContent(),'-10.9%');
await page.locator('#n').fill('0');
assert.ok((await page.locator('#calc-error').textContent()).length>0);
assert.equal(await page.locator('#contribution').textContent(),'—');
await page.locator('#reset').click();
const a=JSON.parse(fs.readFileSync(path.join(root,'assumptions.json'),'utf8'));
const results=JSON.parse(fs.readFileSync(path.join(root,'model-results.json'),'utf8')).accounts;
const currency=x=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x);
for(let i=0;i<a.scenarios.length;i++){
  const s=a.scenarios[i];
  const values={n:s.actions,infra:s.infra_fixed,machine:s.machine_per_action,support:s.support_hours,wage:s.hourly_cost,q:s.exception_rate*100,escalation:s.human_fraction*100,minutes:s.hours_per_case*60};
  for(const [id,value] of Object.entries(values)) await page.locator('#'+id).fill(String(value));
  assert.equal(await page.locator('#cogs').textContent(),currency(results[i].cogs));
  assert.equal(await page.locator('#contribution').textContent(),currency(results[i].contribution));
}
await page.locator('#reset').click();
await page.locator('#base').fill('0');
await page.locator('#overage').fill('0');
assert.equal(await page.locator('#margin').textContent(),'Undefined');
await page.locator('#reset').click();
await page.evaluate(()=>window.scrollTo(0,0));
await page.screenshot({path:'/tmp/amw-unit-economics-desktop.png'});
await page.setViewportSize({width:390,height:844});
await page.evaluate(()=>window.scrollTo(0,0));
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
await page.screenshot({path:'/tmp/amw-unit-economics-mobile.png'});
await page.setViewportSize({width:1440,height:1050});
await page.emulateMedia({media:'print'});
await page.pdf({path:path.join(root,'report.pdf'),format:'A4',printBackground:true,displayHeaderFooter:true,
 headerTemplate:'<div style="font-size:8px;width:100%;text-align:center;color:#60706f">AGENT MIDDLEWARE API · UNIT ECONOMICS · WORKING DRAFT</div>',
 footerTemplate:'<div style="font-size:8px;width:100%;text-align:center;color:#60706f">September 5, 2026 · Assumptions, not financial actuals · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
 preferCSSPageSize:true});
assert.deepEqual(errors,[]);
await browser.close();
console.log(JSON.stringify({browser_checks:'passed',scenarios_verified:4,enterprise_sensitivities:2,zero_volume:'guarded',zero_revenue:'guarded',mobile_overflow:false,javascript_errors:errors,pdf:'report.pdf'}));
