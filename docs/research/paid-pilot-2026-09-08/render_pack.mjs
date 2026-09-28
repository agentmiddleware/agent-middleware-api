// Render the pilot memo with the existing bundled marked and Playwright modules.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const {marked}=await import(pathToFileURL(process.argv[2]).href);
const mod=await import(pathToFileURL(process.argv[3]).href);
const {chromium}=mod.default??mod;
let body=marked.parse(fs.readFileSync(path.join(root,'PILOT_PACKAGE.md'),'utf8'));
body=body.replace(/<td>(A\d{2})<\/td>/g,'<td style="white-space:nowrap;min-width:34px">$1</td>');
body=body.replace(/href="(\/Users\/[^"\n]+?)(?::(\d+))?"/g,(_,p)=>'href="'+pathToFileURL(p).href+'"');
const css='*{box-sizing:border-box}body{margin:0;color:#15343e;font:16px/1.65 Georgia,serif;background:#f1f6f4}main{max-width:1050px;margin:30px auto;padding:48px;background:white;overflow-wrap:anywhere}h1,h2{font-family:Arial,sans-serif;line-height:1.2}h1{font-size:38px}h2{font-size:25px;border-top:2px solid #d6e2df;padding-top:20px;margin-top:40px}a{color:#19796a;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font:12px/1.45 Arial,sans-serif}th{background:#15343e;color:white;text-align:left}th,td{padding:10px;border-bottom:1px solid #d6e2df;vertical-align:top}tbody tr:nth-child(even){background:#f1f6f4}blockquote{border-left:3px solid #19796a;margin:20px 0;padding:8px 20px}li{margin:8px 0}.table-scroll{overflow-x:auto}@media(max-width:600px){main{padding:20px;margin:0}table{min-width:550px}h1{font-size:30px}}@page{size:A4;margin:18mm 16mm}@media print{body{background:white;font-size:10.5pt;line-height:1.5}main{padding:0;margin:0}h1{font-size:27pt}h2{font-size:17pt;break-after:avoid;margin-top:22pt}table{font-size:8pt;min-width:0}th,td{padding:7pt}thead{display:table-header-group}tr{break-inside:avoid}p{orphans:3;widows:3}.table-scroll{overflow:visible}a{text-decoration:none}}';
body=body.replace(/<table>/g,'<div class="table-scroll"><table>').replace(/<\/table>/g,'</table></div>');
const html='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>One-tool paid-pilot package</title><style>'+css+'</style></head><body><main>'+body+'</main></body></html>';
fs.writeFileSync(path.join(root,'pilot-package.html'),html);
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1280,height:1000}});
await page.goto(pathToFileURL(path.join(root,'pilot-package.html')).href);
await page.emulateMedia({media:'print'});
await page.pdf({path:path.join(root,'pilot-package.pdf'),format:'A4',printBackground:true,displayHeaderFooter:true,
headerTemplate:'<div style="font-size:8px;text-align:center;width:100%;color:#536a70">AGENT MIDDLEWARE API · PAID-PILOT PROPOSAL DRAFT</div>',
footerTemplate:'<div style="font-size:8px;text-align:center;width:100%;color:#536a70">September 8, 2026 · No accepted order · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
preferCSSPageSize:true});
await page.setViewportSize({width:390,height:844});await page.emulateMedia({media:'screen'});
if(!(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)))throw new Error('Mobile overflow');
await browser.close();
console.log('Pilot memo exported; mobile layout passed');
