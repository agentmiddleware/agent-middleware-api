/* Local-only exploratory UX evidence. No product code is modified. */
process.env.PLAYWRIGHT_BROWSERS_PATH = '/private/tmp/amw-qa-playwright-browsers';
const { chromium } = require('/private/tmp/amw-qa-browser/node_modules/playwright');
const axe = require('/private/tmp/amw-qa-browser/node_modules/axe-core');
const fs = require('node:fs');
const path = require('node:path');
const out = path.join(__dirname, 'artifacts');
const report = { started: new Date().toISOString(), axeVersion: axe.version, pages: [], interactions: {}, outboundBlocked: [] };

async function layout(page) {
  return page.evaluate(() => ({
    viewport: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(e => ({tag: e.tagName, text: e.textContent.trim()})),
    landmarks: Array.from(document.querySelectorAll('main,nav,header,footer')).map(e => ({tag: e.tagName, name: e.getAttribute('aria-label')})),
    overflow: Array.from(document.querySelectorAll('main,nav,button,input,a,h1,h2,h3,pre,table')).filter(e => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.right > window.innerWidth + 1 || r.left < -1);
    }).map(e => ({tag: e.tagName, id: e.id, cls: e.className, text: e.textContent.trim().slice(0,80), width: e.getBoundingClientRect().width})),
  }));
}

async function scan(page, label) {
  await page.addScriptTag({content: axe.source});
  const result = await page.evaluate(async () => window.axe.run(document, {
    runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']},
  }));
  fs.writeFileSync(path.join(out, `ux-axe-${label}.json`), JSON.stringify(result, null, 2));
  return {violations: result.violations.map(v => ({id:v.id,impact:v.impact,help:v.help,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})), passes:result.passes.length, incomplete:result.incomplete.length};
}

async function main() {
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (['127.0.0.1','localhost','[::1]'].includes(url.hostname)) return route.continue();
    report.outboundBlocked.push({host:url.hostname,type:route.request().resourceType()});
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  const pages = [
    ['home','http://127.0.0.1:8765/'],
    ['proof','http://127.0.0.1:8765/proof/'],
    ['compare','http://127.0.0.1:8765/compare/'],
    ['concept','http://127.0.0.1:8765/concept/'],
    ['404','http://127.0.0.1:8765/404.html'],
    ['dashboard','http://127.0.0.1:8766/dashboard.html'],
  ];
  for (const [label,url] of pages) {
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(url,{waitUntil:'networkidle'});
    const item = {label,url,title:await page.title(),desktop:await layout(page),axe:await scan(page,label)};
    fs.writeFileSync(path.join(out, `ux-semantics-${label}.yml`), await page.locator('body').ariaSnapshot());
    await page.screenshot({path:path.join(out,`ux-${label}-desktop.png`),fullPage:false});
    await page.keyboard.press('Tab');
    item.firstTab = await page.evaluate(()=>({tag:document.activeElement.tagName,text:document.activeElement.textContent.trim(),href:document.activeElement.getAttribute('href')}));
    await page.keyboard.press('Enter');
    item.skipTarget = await page.evaluate(()=>({hash:location.hash,active:document.activeElement.tagName,id:document.activeElement.id,scrollY:window.scrollY}));
    await page.setViewportSize({width:390,height:844});
    await page.goto(url,{waitUntil:'networkidle'});
    item.mobile = await layout(page);
    await page.screenshot({path:path.join(out,`ux-${label}-mobile.png`),fullPage:label !== 'home' && label !== 'compare'});
    await page.setViewportSize({width:320,height:900});
    item.reflow320 = await layout(page);
    report.pages.push(item);
  }
  await page.setViewportSize({width:390,height:844});
  await page.goto(pages[0][1],{waitUntil:'networkidle'});
  const calculator = page.locator('.pilot-fit');
  await calculator.scrollIntoViewIfNeeded();
  report.interactions.calculatorEmpty = await calculator.innerText();
  await calculator.screenshot({path:path.join(out,'ux-calculator-empty.png')});
  await page.locator('#fit-actions').fill('-1');
  report.interactions.calculatorInvalid = {text:await calculator.innerText(),fields:await calculator.locator('input').evaluateAll(es=>es.map(e=>({id:e.id,invalid:e.getAttribute('aria-invalid'),description:e.getAttribute('aria-describedby')})))};
  await calculator.screenshot({path:path.join(out,'ux-calculator-invalid.png')});
  for (const [id,value] of [['fit-actions','100000'],['fit-rate','0.1'],['fit-loss','50'],['fit-reduction','80'],['fit-cost','2800']]) await page.locator(`#${id}`).fill(value);
  report.interactions.calculatorValid = await calculator.innerText();
  await calculator.screenshot({path:path.join(out,'ux-calculator-valid.png')});
  report.interactions.calculatorAxe = await scan(page,'calculator-valid');
  const toggle = page.getByRole('button',{name:'Accessibility options',exact:true});
  await toggle.focus();
  await page.keyboard.press('Enter');
  report.interactions.accessibilityOpen = {focus:await page.evaluate(()=>document.activeElement.outerHTML.slice(0,300)),snapshot:await page.getByRole('dialog').ariaSnapshot()};
  report.interactions.accessibilityAxe = await scan(page,'accessibility-dialog');
  await page.getByRole('dialog').screenshot({path:path.join(out,'ux-accessibility-panel-mobile.png')});
  await page.keyboard.press('Escape');
  report.interactions.accessibilityEscape = {focus:await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),hidden:await page.getByRole('dialog').count() === 0};
  await toggle.click();
  for (let i=0;i<10;i++) await page.getByRole('button',{name:'Increase text size',exact:true}).click();
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:320,height:900});
  await page.evaluate(()=>scrollTo(0,0));
  report.interactions.enlargedText320 = await layout(page);
  report.interactions.enlargedText320.scale = await page.evaluate(()=>getComputedStyle(document.documentElement).fontSize);
  await page.screenshot({path:path.join(out,'ux-enlarged-text-320.png'),fullPage:false});
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(out,'ux-browser-report.json'),JSON.stringify(report,null,2));
  await browser.close();
  console.log(JSON.stringify({pages:report.pages.map(p=>({label:p.label,violations:p.axe.violations,desktopWidth:p.desktop.documentWidth,mobileWidth:p.mobile.documentWidth,reflowWidth:p.reflow320.documentWidth,firstTab:p.firstTab,skipTarget:p.skipTarget})),calculatorAxe:report.interactions.calculatorAxe,accessibilityAxe:report.interactions.accessibilityAxe,enlargedText320:report.interactions.enlargedText320,outboundBlocked:report.outboundBlocked},null,2));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
