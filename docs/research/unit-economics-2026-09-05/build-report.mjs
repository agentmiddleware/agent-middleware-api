// Render the dated report. Uses an existing marked installation; installs nothing.
// node build-report.mjs /absolute/path/to/marked/lib/marked.esm.js
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const { marked } = await import(process.argv[2] ? pathToFileURL(process.argv[2]).href : 'marked');
const assumptions = JSON.parse(fs.readFileSync(path.join(root, 'assumptions.json'), 'utf8'));
let report = fs.readFileSync(path.join(root, 'REPORT.md'), 'utf8');
const tableText = fs.readFileSync(path.join(root, 'calculated-tables.md'), 'utf8');
for (const section of tableText.split(/^## /m).filter(Boolean)) {
  const [key, ...lines] = section.split('\n');
  const body = lines.join('\n').trim();
  report = report.replace(new RegExp('<!-- BEGIN ' + key + ' -->[\\s\\S]*?<!-- END ' + key + ' -->'),
    '<!-- BEGIN ' + key + ' -->\n' + body + '\n<!-- END ' + key + ' -->');
}
if (/\{\{[A-Z_]+\}\}/.test(report)) throw new Error('Unresolved table placeholder');
fs.writeFileSync(path.join(root, 'REPORT.md'), report);
let html = marked.parse(report);
const toc = [];
html = html.replace(/<h2>(.*?)<\/h2>/g, (_, title) => {
  const id = 'section-' + title.split('.')[0];
  toc.push('<a href="#' + id + '">' + title + '</a>');
  return '<h2 id="' + id + '">' + title + '</h2>';
});
html = html.replace(/<table>/g, '<div class="table-scroll"><table>').replace(/<\/table>/g, '</table></div>');
// Codex's :line links remain in Markdown; ordinary file readers need real paths.
html = html.replace(/href="(\/Users\/[^"\n]+?)(?::(\d+))?"/g, (_, local, line) =>
  'href="' + pathToFileURL(local).href + '"' + (line ? ' title="Source line ' + line + '"' : ''));
const inputs = [
  ['n', 'Unique attempts / month', 1000000, 1, 1000],
  ['base', 'Monthly base fee ($)', assumptions.base_monthly_fee, 0, 50],
  ['included', 'Included attempts', assumptions.included_actions, 0, 1000],
  ['overage', 'Overage ($ / attempt)', assumptions.overage_per_action, 0, .0001],
  ['infra', 'Baseline infrastructure ($ / month)', 150, 0, 25],
  ['enterprise', 'Incremental Enterprise allocation ($)', assumptions.enterprise_allocation, 0, 100],
  ['machine', 'Incremental machine cost ($ / attempt)', .0001, 0, .00001],
  ['support', 'Routine delivery hours / month', 3, 0, .5],
  ['wage', 'Loaded labor cost ($ / hour)', 75, 0, 5],
  ['q', 'Exception rate (%)', .005, 0, .001],
  ['escalation', 'Exceptions needing a human (%)', 10, 0, 1],
  ['minutes', 'Minutes per human case', 15, 0, 5],
];
const fields = inputs.map(([id, label, val, min, step]) => '<label for="' + id + '">' + label + '<input type="number" id="' + id + '" value="' + val + '" min="' + min + '" step="' + step + '"' + (id === 'q' || id === 'escalation' ? ' max="100"' : '') + '></label>').join('');
const calc = `<section class="calculator" id="calculator" aria-labelledby="calc-title">
<span class="eyebrow">Editable scenario • no actual customer data</span>
<h2 id="calc-title">How much does one account contribute?</h2>
<p>Start with the base example, then change volume, delivery effort, or Enterprise allocation. This does not edit the saved report or application settings.</p>
<p class="critical"><strong>Enterprise cost is unresolved.</strong> The zero below excludes that cost; it is not a quote. The deployment SOP requires Enterprise.</p>
<form id="inputs">${fields}</form>
<p id="calc-error" role="alert"></p>
<div class="cards" aria-live="polite">
<div><span>Monthly revenue</span><strong id="revenue"></strong></div>
<div><span>Delivery cost</span><strong id="cogs"></strong></div>
<div><span>Contribution</span><strong id="contribution"></strong></div>
<div><span>Contribution margin</span><strong id="margin"></strong></div>
</div>
<p id="floor"></p><p id="labor"></p>
<div class="bar" aria-hidden="true"><span id="cost-bar"></span><span id="profit-bar"></span></div>
<p class="small">Orange = delivery cost; green = remaining contribution. The bar stops at revenue when the account loses money. Assumes one monthly domestic-card payment (2.9% + $0.30), a 1% concession/loss allowance, and a 70% target margin. Incremental machine cost includes assumed replay/control traffic and a representative retention age. Excludes setup, acquisition, shared overhead and upstream resale.</p>
<button id="reset" type="button">Reset base assumptions</button>
</section>`;

const css = `
:root{--ink:#172e36;--muted:#52656a;--navy:#0f3039;--teal:#19796a;--line:#d7e1df;--paper:#fff;--wash:#f3f6f4;--orange:#b86b32}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--wash);font:16px/1.68 Georgia,serif}
.top{background:var(--navy);color:#fff;padding:22px 32px;font:600 12px/1.5 Arial,sans-serif;letter-spacing:.13em;text-transform:uppercase;display:flex;justify-content:space-between;gap:20px}
.layout{max-width:1480px;margin:auto;display:grid;grid-template-columns:270px minmax(0,1fr);gap:32px;padding:36px 28px}
nav{font:12px/1.5 Arial,sans-serif;position:sticky;top:20px;align-self:start;max-height:94vh;overflow:auto;padding:8px 0}nav strong{display:block;margin-bottom:12px;letter-spacing:.1em;font-size:11px}nav a{display:block;color:var(--muted);padding:7px 10px;border-left:2px solid var(--line);text-decoration:none}nav a:hover{color:var(--teal);border-color:var(--teal)}
main{background:var(--paper);padding:48px 54px;min-width:0;box-shadow:0 8px 35px #17323809}h1{font:600 46px/1.12 Arial,sans-serif;letter-spacing:-1.4px;margin:0 0 28px;max-width:830px}h2{font:600 26px/1.25 Arial,sans-serif;margin:56px 0 20px;padding-top:20px;border-top:2px solid var(--line);scroll-margin-top:24px;letter-spacing:-.5px}h3{font:600 20px/1.3 Arial,sans-serif}p{margin:0 0 18px}a{color:#176c62;text-underline-offset:3px;overflow-wrap:anywhere}li{padding-left:4px;margin:8px 0}strong{font-weight:700}code{font:12px/1.5 Menlo,monospace;background:#edf2f0;padding:2px 4px;overflow-wrap:anywhere}pre{background:#edf2f0;border-left:3px solid var(--teal);padding:18px 20px;white-space:pre-wrap;overflow-wrap:anywhere}pre code{background:none;padding:0;font-size:12px}.table-scroll{overflow-x:auto;margin:24px 0}table{border-collapse:collapse;width:100%;font:12px/1.5 Arial,sans-serif}th{text-align:left;background:var(--navy);color:white;padding:12px 10px;vertical-align:top}td{border-bottom:1px solid var(--line);padding:11px 10px;vertical-align:top}tbody tr:nth-child(even){background:#f6f8f6}td:first-child{font-weight:600}blockquote{border-left:3px solid var(--teal);margin:18px 0;padding-left:20px}
.calculator{border:1px solid #b9d1c9;background:#f2f7f3;padding:28px;margin:36px 0 46px;font-family:Arial,sans-serif}.calculator h2{border:0;margin:10px 0 18px;padding:0}.eyebrow{font:700 10px/1.5 Arial,sans-serif;text-transform:uppercase;letter-spacing:.11em}.critical{border-left:3px solid var(--orange);padding:10px 14px;background:#fff5e8;font-size:13px}form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 20px}label{display:block;font-size:11px;font-weight:600;line-height:1.4}input{display:block;width:100%;font:15px Arial,sans-serif;padding:10px;border:1px solid #becdc7;border-radius:2px;margin-top:6px;background:#fff;color:#135ba2}input:focus{outline:2px solid var(--teal);outline-offset:1px}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:26px 0 18px}.cards>div{background:#fff;border:1px solid var(--line);padding:14px}.cards span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.cards strong{display:block;font-size:27px;font-weight:500;margin-top:6px}.small,#floor,#labor{font-size:12px;line-height:1.6}.bar{display:flex;height:10px;margin:20px 0 10px;background:#dbe5df}.bar span{display:block;height:10px}#cost-bar{background:var(--orange)}#profit-bar{background:var(--teal)}button{background:var(--navy);color:white;border:0;padding:11px 18px;cursor:pointer;font:12px Arial,sans-serif}#calc-error{color:#a13c22;font-size:13px;margin:15px 0}.footer{font:12px/1.6 Arial,sans-serif;padding:30px 0 0;border-top:1px solid var(--line);color:var(--muted)}
@media(max-width:1000px){.layout{display:block;padding:18px}nav{display:none}main{padding:30px}h1{font-size:37px}}
@media(max-width:560px){.layout{padding:0}main{padding:26px 18px}h1{font-size:32px}h2{font-size:23px}.top{padding:15px 18px;font-size:10px}.top span:last-child{display:none}.calculator{padding:18px}form{grid-template-columns:1fr}.cards strong{font-size:23px}table{min-width:530px}}
@page{size:A4;margin:19mm 16mm 19mm} @media print{html{scroll-behavior:auto}body{background:white;font-size:10.4pt;line-height:1.55}.top,nav,.calculator{display:none}.layout{display:block;padding:0}main{padding:0;box-shadow:none}h1{font-size:30pt;margin-bottom:18pt}h2{font-size:18pt;margin-top:25pt;padding-top:12pt;break-after:avoid}h3{break-after:avoid}p{orphans:3;widows:3;margin-bottom:10pt}table{font-size:8pt;line-height:1.35;min-width:0!important}th,td{padding:7pt 6pt}thead{display:table-header-group}tr{break-inside:avoid}.table-scroll{overflow:visible;margin:12pt 0}pre{font-size:8pt;break-inside:avoid}pre code,code{font-size:8pt}a{color:#176c62;text-decoration:none}li{margin:5pt 0}.footer{font-size:8pt}}
`;
const js = `
const initial = ${JSON.stringify(inputs.map(([id,,v]) => [id,v]))};
const cfg = ${JSON.stringify({card:assumptions.card_percent,fixed:assumptions.card_fixed,reserve:assumptions.reserve_percent,target:assumptions.target_margin})};
const money = x => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x);
function update(){
 const v=Object.fromEntries(initial.map(([id])=>[id,Number(document.getElementById(id).value)]));
 const invalid=initial.some(([id])=>{const el=document.getElementById(id);return el.value===''||!Number.isFinite(v[id])||v[id]<0;})||v.n<1||v.q>100||v.escalation>100;
 document.getElementById('calc-error').textContent=invalid?'Use nonnegative finite inputs, at least one attempt, and percentages between 0 and 100.':'';
 if(invalid){for(const id of ['revenue','cogs','contribution','margin'])document.getElementById(id).textContent='—';document.getElementById('floor').textContent='';document.getElementById('labor').textContent='';document.getElementById('cost-bar').style.width='0%';document.getElementById('profit-bar').style.width='0%';return;}
 const r=v.base+Math.max(0,v.n-v.included)*v.overage;
 const eh=v.n*(v.q/100)*(v.escalation/100)*(v.minutes/60);
 const fixed=v.infra+v.enterprise+v.n*v.machine+(v.support+eh)*v.wage;
 const c=fixed+r*(cfg.card+cfg.reserve)+cfg.fixed;
 const contribution=r-c;
 const floor=(fixed+cfg.fixed)/(1-cfg.card-cfg.reserve-cfg.target);
 document.getElementById('revenue').textContent=money(r);
 document.getElementById('cogs').textContent=money(c);
 document.getElementById('contribution').textContent=money(contribution);
 document.getElementById('contribution').style.color=contribution<0?'#a13c22':'#19796a';
 document.getElementById('margin').textContent=r>0?(100*contribution/r).toFixed(1)+'%':'Undefined';
 document.getElementById('floor').textContent='Revenue required for 70% margin at these costs: '+money(floor)+'/month.';
 document.getElementById('labor').textContent='Monthly labor: '+v.support.toFixed(2)+' routine hours + '+eh.toFixed(2)+' exception hours. Enterprise allocation: '+money(v.enterprise)+'.';
 const costShare=r>0?Math.min(100,c/r*100):100;
 document.getElementById('cost-bar').style.width=costShare+'%';
 document.getElementById('profit-bar').style.width=(100-costShare)+'%';
}
document.getElementById('inputs').addEventListener('input',update);
document.getElementById('inputs').addEventListener('submit',e=>e.preventDefault());
document.getElementById('reset').addEventListener('click',()=>{for(const [id,v] of initial)document.getElementById(id).value=v;update();});
update();
`;
// Keep the document title and scope ahead of the optional calculator.
html = html.replace('<h2 id="section-1">', calc + '<h2 id="section-1">');
const output = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent Middleware API — Unit Economics</title><style>${css}</style></head><body><div class="top"><span>Agent Middleware API / Economics</span><span>Working draft • 05 September 2026</span></div><div class="layout"><nav aria-label="Report contents"><strong>28 sections · Scenario model</strong><a href="#calculator">Account calculator</a>${toc.join('')}</nav><main>${html}<div class="footer">Source inspection and scenario analysis. All actual financial results remain unverified. No application or deployment changes.</div></main></div><script>${js}</script></body></html>`;
fs.writeFileSync(path.join(root, 'report.html'), output);
console.log(JSON.stringify({sections:toc.length,words:report.split(/\s+/).length,html_bytes:Buffer.byteLength(output)}));
