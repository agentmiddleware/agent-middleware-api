// node check-export.mjs /absolute/path/to/playwright/index.js
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const mod=await import(process.argv[2]?pathToFileURL(process.argv[2]).href:'playwright');
const {chromium}=mod.default??mod;
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050}});
const errors=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.goto(pathToFileURL(path.join(root,'report.html')).href);
assert.equal(await page.locator('main h2').count(),27);
assert.equal(await page.locator('#revenue').textContent(),'$999.00');
assert.equal(await page.locator('#cogs').textContent(),'$343.64');
assert.equal(await page.locator('#contribution').textContent(),'$655.36');
assert.equal(await page.locator('#margin').textContent(),'65.6%');
const {scenarios,results}=JSON.parse(fs.readFileSync(path.join(root,'model-results.json'),'utf8'));
const numeric=s=>Number(s.replace(/[^0-9.-]/g,''));
for(let i=0;i<scenarios.length;i++){
 const s=scenarios[i],r=results[i];
 const values={price:s.price,n:s.actions,resource:s.resource_allowance,other:s.other_delivery,support:s.support_hours,wage:s.hourly_cost,q:s.exception_rate*100,escalation:s.human_fraction*100,minutes:s.hours_per_case*60};
 for(const [id,value] of Object.entries(values))await page.locator('#'+id).fill(String(value));
 for(const [id,key] of [['cogs','delivery'],['contribution','contribution']]){
  const actual=numeric(await page.locator('#'+id).textContent());
  assert.ok(Math.abs(actual-r[key])<.0051,'Scenario '+i+' '+key+' differs');
 }
 assert.equal(await page.locator('#margin').textContent(),(r.margin*100).toFixed(1)+'%');
}
await page.locator('#reset').click();
await page.locator('#resource').fill('1000');
assert.equal(await page.locator('#contribution').textContent(),'-$294.64');
await page.locator('#reset').click();
await page.locator('#n').fill('0');
assert.ok((await page.locator('#unit').textContent()).includes('Undefined'));
assert.equal(await page.locator('#calc-error').textContent(),'');
await page.locator('#price').fill('0');
assert.equal(await page.locator('#margin').textContent(),'Undefined');
assert.equal(await page.locator('#cogs').textContent(),'$295.00');
await page.locator('#reset').click();
await page.locator('#support').fill('-1');
assert.equal(await page.locator('#contribution').textContent(),'—');
await page.locator('#reset').click();
await page.locator('#escalation').fill('101');
assert.equal(await page.locator('#contribution').textContent(),'—');
await page.locator('#reset').click();
await page.locator('#price').fill('');
assert.equal(await page.locator('#contribution').textContent(),'—');
await page.locator('#reset').click();
const brokenAnchors=await page.evaluate(()=>[...document.querySelectorAll('nav a')].map(a=>a.getAttribute('href')).filter(h=>!document.querySelector(h)));
assert.deepEqual(brokenAnchors,[]);
await page.evaluate(()=>window.scrollTo(0,0));
await page.screenshot({path:'/tmp/amw-reconsidered-desktop.png'});
await page.setViewportSize({width:390,height:844});
await page.evaluate(()=>window.scrollTo(0,0));
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile page overflow');
await page.screenshot({path:'/tmp/amw-reconsidered-mobile.png'});
await page.setViewportSize({width:1440,height:1050});
await page.emulateMedia({media:'print'});
await page.pdf({path:path.join(root,'report.pdf'),format:'A4',printBackground:true,displayHeaderFooter:true,
 headerTemplate:'<div style="font-size:8px;width:100%;text-align:center;color:#60706f">AGENT MIDDLEWARE API · ECONOMICS RECONSIDERED</div>',
 footerTemplate:'<div style="font-size:8px;width:100%;text-align:center;color:#60706f">Finalized September 8, 2026 · Dated observations and explicit scenarios · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
 preferCSSPageSize:true});
assert.deepEqual(errors,[]);
await browser.close();
const outcome={browser_checks:'passed',python_js_scenarios:5,negative_contribution:'passed',zero_revenue:'passed',zero_volume:'passed',invalid_inputs:'passed',reset:'passed',broken_navigation:brokenAnchors,mobile_overflow:false,javascript_errors:errors,pdf:'report.pdf'};
fs.writeFileSync(path.join(root,'browser-validation.json'),JSON.stringify(outcome,null,2)+'\n');
console.log(JSON.stringify(outcome));
