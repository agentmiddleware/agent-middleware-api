const money=x=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(x);
function update(){
 const v=Object.fromEntries(initial.map(([id])=>[id,Number(document.getElementById(id).value)]));
 const invalid=initial.some(([id])=>{const el=document.getElementById(id);return el.value===''||!Number.isFinite(v[id])||v[id]<0;})||v.q>100||v.escalation>100;
 document.getElementById('calc-error').textContent=invalid?'Enter nonnegative finite values and percentages between 0 and 100.':'';
 if(invalid){
  for(const id of ['revenue','cogs','contribution','margin'])document.getElementById(id).textContent='—';
  for(const id of ['floor','labor','unit'])document.getElementById(id).textContent='';
  for(const id of ['cost-bar','profit-bar'])document.getElementById(id).style.width='0%';
  return;
 }
 const eh=v.n*(v.q/100)*(v.escalation/100)*(v.minutes/60);
 const base=v.resource+v.other+(v.support+eh)*v.wage;
 const c=base+v.price*(cfg.rate+cfg.reserve)+(v.price>0?cfg.fixed:0);
 const contribution=v.price-c;
 const floor=(base+cfg.fixed)/(1-cfg.rate-cfg.reserve-cfg.target);
 document.getElementById('revenue').textContent=money(v.price);
 document.getElementById('cogs').textContent=money(c);
 document.getElementById('contribution').textContent=money(contribution);
 document.getElementById('contribution').style.color=contribution<0?'#a13c22':'#19796a';
 document.getElementById('margin').textContent=v.price>0?(100*contribution/v.price).toFixed(1)+'%':'Undefined';
 document.getElementById('floor').textContent='Monthly fee for 70% contribution margin: '+money(floor)+'.';
 document.getElementById('labor').textContent='Delivery hours: '+v.support.toFixed(3)+' routine + '+eh.toFixed(3)+' exception. Both use the stated loaded labor cost.';
 document.getElementById('unit').textContent='Delivery cost per 1,000 accepted attempts: '+(v.n>0?money(c/v.n*1000):'Undefined (no accepted attempts)')+'.';
 const costShare=v.price>0?Math.min(100,c/v.price*100):100;
 document.getElementById('cost-bar').style.width=costShare+'%';
 document.getElementById('profit-bar').style.width=(100-costShare)+'%';
}
document.getElementById('inputs').addEventListener('input',update);
document.getElementById('inputs').addEventListener('submit',e=>e.preventDefault());
document.getElementById('reset').addEventListener('click',()=>{for(const [id,v] of initial)document.getElementById(id).value=v;update();});
update();
