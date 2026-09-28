// node build-report.mjs /absolute/path/to/marked/lib/marked.esm.js
// Uses the existing dependency runtime; installs nothing.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const {marked}=await import(process.argv[2]?pathToFileURL(process.argv[2]).href:'marked');
const a=JSON.parse(fs.readFileSync(path.join(root,'assumptions.json'),'utf8')).base;
let report=fs.readFileSync(path.join(root,'REPORT.md'),'utf8');
const tables=fs.readFileSync(path.join(root,'calculated-tables.md'),'utf8');
for(const section of tables.split(/^## /m).filter(Boolean)){
 const [key,...lines]=section.split('\n');
 const re=new RegExp('<!-- BEGIN '+key+' -->[\\s\\S]*?<!-- END '+key+' -->');
 if(!re.test(report))throw new Error('Missing table marker '+key);
 report=report.replace(re,'<!-- BEGIN '+key+' -->\n'+lines.join('\n').trim()+'\n<!-- END '+key+' -->');
}
fs.writeFileSync(path.join(root,'REPORT.md'),report);
let html=marked.parse(report);
const toc=[];
html=html.replace(/<h2>(.*?)<\/h2>/g,(_,title)=>{
 const id='section-'+title.split('.')[0];
 toc.push('<a href="#'+id+'">'+title+'</a>');
 return '<h2 id="'+id+'">'+title+'</h2>';
});
html=html.replace(/<table>/g,'<div class="table-scroll"><table>').replace(/<\/table>/g,'</table></div>');
html=html.replace(/href="(\/Users\/[^"\n]+?)(?::(\d+))?"/g,(_,local,line)=>
 'href="'+pathToFileURL(local).href+'"'+(line?' title="Source line '+line+'"':''));
const inputs=[
 ['price','Monthly workflow fee ($)',a.price,1],
 ['n','Unique accepted attempts / month',a.actions,1000],
 ['resource','Monthly resource allowance ($)',a.resource_allowance,5],
 ['other','Other direct delivery allowance ($)',a.other_delivery,5],
 ['support','Routine delivery hours / month',a.support_hours,.25],
 ['wage','Loaded labor cost ($ / hour)',a.hourly_cost,5],
 ['q','Exceptions per accepted attempt (%)',a.exception_rate*100,.001],
 ['escalation','Exceptions needing a human (%)',a.human_fraction*100,1],
 ['minutes','Minutes per human exception',a.hours_per_case*60,5],
];
const fields=inputs.map(([id,label,v,step])=>'<label for="'+id+'">'+label+'<input type="number" id="'+id+'" value="'+v+'" min="0" step="'+step+'"'+(['q','escalation'].includes(id)?' max="100"':'')+'></label>').join('');
const calc='<section class="calculator" id="calculator"><span class="eyebrow">Illustrative customer economics • Editable assumptions</span><h2 id="calc-title">What can one supported workflow contribute?</h2><p>Change the fee, workload, or service effort. These are planning inputs, not measurements from a paying customer.</p><p class="critical">The resource allowance replaces the scenario hosting budget. It is not added to the observed demo bill. Any actual contract commitment needs separate reconciliation; no additional Enterprise increment is included here.</p><form id="inputs">'+fields+'</form><p id="calc-error" role="alert"></p><div class="cards" aria-live="polite"><div><span>Monthly fee</span><strong id="revenue"></strong></div><div><span>Delivery cost</span><strong id="cogs"></strong></div><div><span>Contribution</span><strong id="contribution"></strong></div><div><span>Contribution margin</span><strong id="margin"></strong></div></div><p id="floor"></p><p id="labor"></p><p id="unit"></p><div class="bar" aria-hidden="true"><span id="cost-bar"></span><span id="profit-bar"></span></div><p class="small">Orange is delivery cost; green is remaining contribution. Assumes 2.9% + $0.30 per monthly payment, a 1% planning reserve, and a 70% target margin. Excludes setup, acquisition, shared overhead, and upstream resale. No payment means no fixed collection fee. This calculator does not alter saved assumptions or application pricing.</p><button id="reset" type="button">Reset working illustration</button></section>';
const js=[
 'const initial='+JSON.stringify(inputs.map(([id,,v])=>[id,v]))+';',
 'const cfg='+JSON.stringify({rate:a.payment_rate,fixed:a.payment_fixed,reserve:a.reserve_rate,target:a.target_margin})+';',
 fs.readFileSync(path.join(root,'calculator.js'),'utf8'),
].join('\n');
html=html.replace('<h2 id="section-1">',calc+'<h2 id="section-1">');
const css=fs.readFileSync(path.join(root,'style.css'),'utf8');
const output='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent Middleware API — Economics Reconsidered</title><style>'+css+'</style></head><body><div class="top"><span>Agent Middleware API / Economics Reconsidered</span><span>Finalized 08 September 2026</span></div><div class="layout"><nav aria-label="Report contents"><strong>'+toc.length+' sections · Revised evidence</strong><a href="#calculator">Workflow calculator</a>'+toc.join('')+'</nav><main>'+html+'<div class="footer">Observed demo resource usage and explicitly hypothetical customer economics. Research snapshot September 5–6; finalized September 8, 2026. No application or deployment changes.</div></main></div><script>'+js+'</script></body></html>';
fs.writeFileSync(path.join(root,'report.html'),output);
console.log(JSON.stringify({sections:toc.length,words:report.split(/\s+/).length,html_bytes:Buffer.byteLength(output)}));
