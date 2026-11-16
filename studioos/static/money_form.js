'use strict';
// Structured input to the same approved text-book recipes used by chat.
Object.assign(state, {moneyEntry: null});
function moneyOptions(options,value) {return options.map(o=>`<option value="${Number(o.id)}" ${String(o.id)===String(value)?'selected':''}>${esc(o.name)}</option>`).join('');}
function moneyEntryView() {
  const m=state.moneyEntry,v=m.values,r=m.options.recipes.find(x=>x.key===v.recipe);
  const sel=(name,label,options,value)=>`<div class="field"><label>${label}<select class="form-input" name="${name}">${options.map(([id,title])=>`<option value="${esc(id)}" ${String(id)===String(value)?'selected':''}>${esc(title)}</option>`).join('')}</select></label></div>`;
  const input=(name,label,type='text',required=false)=>`<div class="field"><label>${label}<input class="form-input" name="${name}" type="${type}" value="${esc(v[name]||'')}" ${required?'required':''} ${name==='amount'?'inputmode="decimal" placeholder="e.g. 1,250.50"':''}></label></div>`;
  const tax=['purchase','expense','client_invoice'].includes(r.key);
  const settlements=r.key==='client_invoice'?[['credit','On credit']]:[['bank','Bank / UPI'],['cash','Cash']].concat(r.key==='purchase'?[['credit','On credit']]:[]);
  return head('New money entry','Opens an approval ticket. Books change only after a person reviews and approves it.')+`<section class="panel"><form class="panel-body" id="moneyEntryForm"><div class="form-grid">
    ${sel('recipe','What happened',m.options.recipes.map(x=>[x.key,x.title]),r.key)}
    ${sel('project_id','Project',[['','Office / common costs'],...(state.projects||[]).map(p=>[p.id,p.name])],v.project_id)}
    ${input('amount','Amount (₹)','text',true)}${input('date','Date','date',true)}${input('reference','Bill / receipt reference')}
    ${r.items.length?`<div class="field"><label>Material, service or income category<select class="form-input" name="item_id" required><option value="">Choose…</option>${moneyOptions(r.items,v.item_id)}</select></label></div>${input('description','Description (optional)')}`:''}
    ${r.parties.length?`<div class="field"><label>${r.key==='purchase'||r.key==='vendor_payment'?'Supplier / contractor':'Client'}<select class="form-input" name="party_id" required><option value="">Choose…</option>${moneyOptions(r.parties,v.party_id)}</select></label></div>`:input('party','Payee (optional)')}
    ${sel('settlement','Payment',settlements,v.settlement)}
    <div class="field"><label>Bank account<select class="form-input" name="bank_id">${moneyOptions(r.banks,v.bank_id)}</select></label></div>
    ${tax?sel('gst_rate','GST rate',[['0','No GST'],['5','5%'],['12','12%'],['18','18%'],['28','28%']],v.gst_rate)+sel('gst_mode','GST included or added',[['none','No GST'],['extra','Add GST to amount'],['included','Amount includes GST']],v.gst_mode)+sel('gst_type','GST location',[['intra','Within state (CGST + SGST)'],['inter','Other state (IGST)']],v.gst_type):''}
    </div><div class="g-actions"><button class="btn btn-primary" type="submit">Propose entry</button><button class="btn btn-secondary" type="button" data-money="cancel">Cancel</button></div></form></section>`;
}
const _moneyRender=render;
render=function(){if(state.view==='chart'&&state.moneyEntry){updateIdentity();$('mainContent').innerHTML=moneyEntryView();$('breadcrumb').textContent='New money entry';return;}_moneyRender();};
document.addEventListener('click',async e=>{
  const newButton=e.target.closest('[data-action=coa-new-entry]');
  if(newButton){e.stopImmediatePropagation();try{
    if(!state.coaEntity)await coaLoad();
    const options=await api('/api/finance-ledger/entry-form/'+state.coaEntity);
    if(!options.recipes.length)throw new Error('Install an approved chart of accounts first.');
    const recipe=options.recipes.find(r=>r.key==='purchase')||options.recipes[0];
    state.moneyEntry={options,idempotencyKey:'form:'+crypto.randomUUID(),values:{recipe:recipe.key,date:options.today,settlement:recipe.default_settlement,gst_rate:'0',gst_mode:'none',gst_type:'intra'}};render();
  }catch(err){notify(err.message,true);}return;}
  if(e.target.closest('[data-money=cancel]')){state.moneyEntry=null;render();}
},true);
document.addEventListener('change',e=>{
  if(!e.target.closest('#moneyEntryForm')||!['recipe','gst_rate'].includes(e.target.name))return;
  const v=Object.fromEntries(new FormData(e.target.form));state.moneyEntry.values=v;
  if(e.target.name==='recipe'){
    const r=state.moneyEntry.options.recipes.find(x=>x.key===v.recipe);
    v.settlement=r.default_settlement;v.item_id='';v.party_id='';
  }else if(v.gst_rate==='0')v.gst_mode='none';else if(v.gst_mode==='none')v.gst_mode='extra';
  render();
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='moneyEntryForm')return;e.preventDefault();
  const button=e.submitter;if(button?.disabled)return;if(button)button.disabled=true;
  const m=state.moneyEntry,v=Object.fromEntries(new FormData(e.target)),r=m.options.recipes.find(x=>x.key===v.recipe);
  const item=r.items.find(x=>String(x.id)===v.item_id),party=r.parties.find(x=>String(x.id)===v.party_id),accounts={};
  const slots={amount:v.amount,date:v.date,reference:v.reference,settlement:v.settlement,gst_rate:v.gst_rate||'0',gst_mode:v.gst_mode||'none',gst_type:v.gst_type||'intra'};
  if(item){accounts.item=item.id;slots.item=v.description||item.name;}
  if(party){slots[r.party_word+'_party']=party.name;if(r.key!=='purchase'||v.settlement==='credit')accounts.party=party.id;}
  else if(v.party)slots[r.party_word+'_party']=v.party;
  if(v.settlement==='bank')accounts.bank=Number(v.bank_id);
  const data={entity_id:state.coaEntity,recipe:r.key,project_id:Number(v.project_id)||null,slots,accounts,idempotency_key:m.idempotencyKey};
  try{const draft=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({kind:'finance_text_entry',data,evidence:'Structured money form entered and checked by a person'})});
    state.moneyEntry=null;state.coa=null;render();notify('Ticket #'+draft.ticket_id+' opened. Review it before posting.');
  }catch(err){if(button)button.disabled=false;notify(err.message,true);}
});

document.addEventListener('input',e=>{
  if(e.target.closest('#moneyEntryForm')&&state.moneyEntry)state.moneyEntry.values=Object.fromEntries(new FormData(e.target.form));
});
