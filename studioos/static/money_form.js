'use strict';
// Structured input for approved money drafts.
Object.assign(state, {moneyEntry: null});
function moneyOptions(options,value) {return options.map(o=>`<option value="${Number(o.id)}" ${String(o.id)===String(value)?'selected':''}>${esc(o.name)}</option>`).join('');}
function moneyEntryView() {
  const m=state.moneyEntry,v=m.values,r=m.options.recipes.find(x=>x.key===v.recipe);
  const sel=(name,label,options,value,required=false)=>`<div class="field"><label>${label}<select class="form-input" name="${name}" ${required?'required':''}>${options.map(([id,title])=>`<option value="${esc(id)}" ${String(id)===String(value)?'selected':''}>${esc(title)}</option>`).join('')}</select></label></div>`;
  const input=(name,label,type='text',required=false)=>`<div class="field"><label>${label}<input class="form-input" name="${name}" type="${type}" value="${esc(v[name]||'')}" ${required?'required':''}></label></div>`;
  const tax=['purchase','client_invoice'].includes(r.key);
  const settlements=r.key==='client_invoice'?[['credit','On credit']]:[['bank','Bank / UPI'],['cash','Cash']].concat(r.key==='purchase'?[['credit','On credit']]:[]);
  const expenseFields=r.key==='expense'?[
    r.categories?.length?sel('category_id','Expense category',[['','Choose an account manually'],...r.categories.map(c=>[c.id,c.name])],v.category_id):'',
    sel('expense_account_id','Expense account',[['','Choose an account'],...r.items.map(x=>[x.id,x.name])],v.expense_account_id,true),
    sel('vendor_id','Vendor',[['','Choose a vendor'],...r.parties.map(x=>[x.id,x.name]),['none','No vendor']],v.vendor_id,true),
    v.vendor_id==='none'?'<div class="field"><label>Who was paid?<input class="form-input" name="no_vendor_name" maxlength="120" required value="'+esc(v.no_vendor_name||'')+'"></label></div>':'',
    sel('paid_through_id','Paid through',[['','Choose an account'],...r.paid_through.map(x=>[x.id,x.name]),['personal','I paid for this myself']],v.paid_through_id,true),
    sel('receipt_id','Receipt',[['','No receipt attached'],...r.receipts.filter(x=>String(x.project_id||'')===String(v.project_id||'')).map(x=>[x.id,x.name])],v.receipt_id),
    input('note','Note (optional)'),
  ].join(''):'';
  return head('New money entry','Opens an approval ticket. Books change only after a person reviews and approves it.')+`<section class="panel"><form class="panel-body" id="moneyEntryForm"><div class="form-grid">
    ${sel('recipe','What happened',m.options.recipes.map(x=>[x.key,x.title]),r.key)}
    ${sel('project_id','Project',[['','Office / common costs'],...(state.projects||[]).map(p=>[p.id,p.name])],v.project_id)}
    ${moneyAmountField('money-entry', 'Amount (₹)', v.amount)}${input('date','Date','date',true)}
    ${r.key==='expense'?expenseFields:input('reference','Bill / receipt reference')+`
    ${r.items.length?`<div class="field"><label>Material, service or income category<select class="form-input" name="item_id" required><option value="">Choose…</option>${moneyOptions(r.items,v.item_id)}</select></label></div>${input('description','Description (optional)')}`:''}
    ${r.parties.length?`<div class="field"><label>${r.key==='purchase'||r.key==='vendor_payment'?'Supplier / contractor':'Client'}<select class="form-input" name="party_id" required><option value="">Choose…</option>${moneyOptions(r.parties,v.party_id)}</select></label></div>`:input('party','Payee (optional)')}
    ${sel('settlement','Payment',settlements,v.settlement)}
    <div class="field"><label>Bank account<select class="form-input" name="bank_id">${moneyOptions(r.banks,v.bank_id)}</select></label></div>
    ${tax?sel('gst_rate','GST rate',[['0','No GST'],['5','5%'],['12','12%'],['18','18%'],['28','28%']],v.gst_rate)+sel('gst_mode','GST included or added',[['none','No GST'],['extra','Add GST to amount'],['included','Amount includes GST']],v.gst_mode)+sel('gst_type','GST location',[['intra','Within state (CGST + SGST)'],['inter','Other state (IGST)']],v.gst_type):''}`}
    </div><div class="g-actions"><button class="btn btn-primary" type="submit">Propose entry</button><button class="btn btn-secondary" type="button" data-money="cancel">Cancel</button></div></form></section>`;
}
const _moneyRender=render;
render=function(){if(state.view==='chart'&&state.moneyEntry){updateIdentity();$('mainContent').innerHTML=moneyEntryView();$('breadcrumb').textContent='New money entry';return;}_moneyRender();};
document.addEventListener('click',async e=>{
  const newButton=e.target.closest('[data-action=coa-new-entry]');
  if(newButton){e.stopImmediatePropagation();try{
    if(!state.coaEntity)await coaLoad();
    if(!state.coaEntity)throw new Error('Set up a company in Books before recording an expense.');
    const options=await api('/api/finance-ledger/entry-form/'+state.coaEntity);
    const recipe=options.recipes.find(r=>r.key==='expense')||options.recipes[0];
    state.moneyEntry={options,idempotencyKey:formRequestKey(),values:{recipe:recipe.key,date:options.today,settlement:recipe.default_settlement,gst_rate:'0',gst_mode:'none',gst_type:'intra'}};render();
  }catch(err){notify(err.message,true);}return;}
  if(e.target.closest('[data-money=cancel]')){state.moneyEntry=null;render();}
},true);
document.addEventListener('change',e=>{
  if(!e.target.closest('#moneyEntryForm')||!['recipe','gst_rate','project_id','vendor_id','category_id','expense_account_id'].includes(e.target.name))return;
  const v=Object.fromEntries(new FormData(e.target.form));state.moneyEntry.values=v;
  if(e.target.name==='recipe'){
    const r=state.moneyEntry.options.recipes.find(x=>x.key===v.recipe);
    v.settlement=r.default_settlement;v.item_id='';v.party_id='';
  }else if(e.target.name==='project_id'){
    if(v.recipe!=='expense')return;
    v.receipt_id='';
  }else if(e.target.name==='category_id'){
    const r=state.moneyEntry.options.recipes.find(x=>x.key===v.recipe);
    const category=r.categories.find(c=>String(c.id)===v.category_id);
    if(category)v.expense_account_id=String(category.expense_account_id);
  }else if(e.target.name==='expense_account_id'){
    v.category_id='';
  }else if(e.target.name==='gst_rate'){
    if(v.gst_rate==='0')v.gst_mode='none';else if(v.gst_mode==='none')v.gst_mode='extra';
  }
  render();
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='moneyEntryForm')return;e.preventDefault();
  const button=e.submitter;if(button?.disabled)return;if(button)button.disabled=true;
  const m=state.moneyEntry,v=Object.fromEntries(new FormData(e.target)),r=m.options.recipes.find(x=>x.key===v.recipe);
  try {
    const direct=r.key==='expense';
    const data=direct?directExpenseData(v,m.idempotencyKey):recipeEntryData(v,r,m.idempotencyKey);
    const draft=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
      kind:direct?'finance_expense':'finance_text_entry',data,evidence:'Money form completed by a person',
    })});
    state.moneyEntry=null;state.coa=null;render();notify('Ticket #'+draft.ticket_id+' opened. Review it before posting.');
  }catch(err){if(button)button.disabled=false;notify(err.message,true);}
});

function directExpenseData(values,requestKey) {
  const parts=/^(\d+|\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+)(?:\.(\d{1,2}))?$/.exec(values.amount.trim());
  const paise=parts?Number(parts[1].replace(/,/g,''))*100+Number((parts[2]||'').padEnd(2,'0')):0;
  if(!Number.isSafeInteger(paise)||paise<=0||paise>=1e14)throw new Error('Enter an amount in rupees with up to two decimal places.');
  return {date:values.date,amount_paise:paise,vendor_id:Number(values.vendor_id)||null,no_vendor:values.vendor_id==='none',
    ...(values.vendor_id==='none'?{no_vendor_name:values.no_vendor_name.trim()}:{}),
    ...(values.category_id?{category_id:Number(values.category_id)}:{}),
    expense_account_id:Number(values.expense_account_id)||null,paid_through_id:Number(values.paid_through_id)||null,
    personal_payment:values.paid_through_id==='personal',
    project_id:Number(values.project_id)||null,receipt_id:Number(values.receipt_id)||null,note:values.note,request_key:requestKey};
}

function recipeEntryData(v,r,requestKey) {
  const item=r.items.find(x=>String(x.id)===v.item_id),party=r.parties.find(x=>String(x.id)===v.party_id),accounts={};
  const slots={amount:v.amount,date:v.date,reference:v.reference,settlement:v.settlement,gst_rate:v.gst_rate||'0',gst_mode:v.gst_mode||'none',gst_type:v.gst_type||'intra'};
  if(item){accounts.item=item.id;slots.item=v.description||item.name;}
  if(party){slots[r.party_word+'_party']=party.name;if(r.key!=='purchase'||v.settlement==='credit')accounts.party=party.id;}
  else if(v.party)slots[r.party_word+'_party']=v.party;
  if(v.settlement==='bank')accounts.bank=Number(v.bank_id);
  return {entity_id:state.coaEntity,recipe:r.key,project_id:Number(v.project_id)||null,slots,accounts,idempotency_key:requestKey};
}

document.addEventListener('input',e=>{
  if(e.target.closest('#moneyEntryForm')&&state.moneyEntry)state.moneyEntry.values=Object.fromEntries(new FormData(e.target.form));
});
