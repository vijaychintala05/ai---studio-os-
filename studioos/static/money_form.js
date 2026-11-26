'use strict';
// Structured input for approved money drafts.
Object.assign(state, {moneyEntry: null});
function moneyOptions(options,value) {return options.map(o=>`<option value="${Number(o.id)}" ${String(o.id)===String(value)?'selected':''}>${esc(o.name)}</option>`).join('');}
/* The expense page, laid out the way Zoho Books lays out its New Expense page: a full page, labels on the left (the
   mandatory ones in red), one narrow column of fields, a receipt box on the right and a bar of buttons at the bottom.
   Zoho's help describes the fields and the Billable / mark-up behaviour; the exact look here follows its familiar layout. */
const ZX_NO_RATES = [0, 500, 1200, 1800, 2800];
function zxSplit(amount, bps, mode) {            // [cost before GST, GST] for one typed amount, as the server works it out
  if (mode === 'none' || !bps) return [amount, 0];
  const a = BigInt(amount), b = BigInt(bps);
  if (mode === 'exclusive') return [amount, Number((a * b + 5000n) / 10000n)];
  const net = (a * 10000n + (10000n + b) / 2n) / (10000n + b);
  return [Number(net), Number(a - net)];
}
function zxRows(v) {                              // the lines being typed: from the itemised table, or the one account and amount
  const m = state.moneyEntry;
  if (v.itemize === '1') return (m.items || []).map(i => ({account: i.account, desc: i.desc || '', amount: i.amount || '', bps: Number(i.tax || 0)}));
  return [{account: v.expense_account_id, desc: '', amount: v.amount || '', bps: Number(v.tax_bps || 0)}];
}
function zxPaise(raw) {
  if (typeof rupeesToPaise === 'function') return rupeesToPaise(raw);
  const s = String(raw ?? '').replace(/[₹,\s]/g, '');
  if (!/^\d+(?:\.\d{1,2})?$/.test(s)) return NaN;
  return Math.round(Number(s) * 100);
}
function zxFigures(v, gst) {                      // totals for the screen; null while the amounts are not valid yet
  const rows = zxRows(v).filter(r => String(r.amount || '').trim());
  const anyTax = rows.some(r => r.bps > 0);
  const mode = anyTax ? (v.tax_mode === 'inclusive' ? 'inclusive' : 'exclusive') : 'none';
  let net = 0, tax = 0;
  for (const r of rows) {
    const paise = zxPaise(r.amount);
    if (!Number.isSafeInteger(paise) || paise <= 0) return null;
    const [n, t] = zxSplit(paise, r.bps, mode);
    net += n; tax += t;
  }
  const place = v.place_of_supply || gst.company_state;
  const intra = place === gst.company_state;
  return {net, tax, total: net + tax, mode, place, intra, cgst: intra ? Math.floor(tax / 2) : 0, sgst: intra ? tax - Math.floor(tax / 2) : 0, igst: intra ? 0 : tax, any: anyTax, count: rows.length};
}
function zxTotalsHtml(f) {
  if (!f || !f.count) return '';
  const money = p => esc(inr(p / 100));
  return `<div class="zx-total-row"><span>Sub Total</span><span>${money(f.net)}</span></div>` +
    (f.tax ? (f.intra ? `<div class="zx-total-row"><span>CGST</span><span>${money(f.cgst)}</span></div><div class="zx-total-row"><span>SGST</span><span>${money(f.sgst)}</span></div>`
      : `<div class="zx-total-row"><span>IGST</span><span>${money(f.igst)}</span></div>`) : '') +
    `<div class="zx-total-row zx-grand"><span>Total (₹)</span><span>${money(f.total)}</span></div>`;
}
function zxLinesPayload(values) {                 // null for a plain expense; otherwise the lines the server expects
  const rows = zxRows(values).filter(r => r.account || String(r.amount || '').trim() || r.desc);
  const itemised = values.itemize === '1';
  if (!itemised && !(rows[0] && rows[0].bps > 0)) return null;
  if (!rows.length) throw new Error('Add at least one line.');
  const f = zxFigures(values, (state.moneyEntry.options.recipes.find(x => x.key === 'expense') || {}).gst || {company_state: '29'});
  if (!f) throw new Error('Enter an amount greater than zero on each line.');
  const lines = rows.map((r, n) => {
    const paise = rupeesToPaise(r.amount);
    if (!r.account || !Number.isSafeInteger(paise) || paise <= 0) throw new Error(`Line ${n + 1}: choose the expense account and enter an amount.`);
    return {expense_account_id: Number(r.account), description: String(r.desc || '').trim(), amount_paise: paise, tax_bps: f.any ? r.bps : 0};
  });
  return {lines, mode: f.mode, total: f.total, place: f.any ? f.place : ''};
}

function zohoExpenseView(m, v, r) {
  const opts = (rows, value, blank) => (blank ? `<option value="">${esc(blank)}</option>` : '') +
    rows.map(([id, title]) => `<option value="${esc(id)}"${String(id) === String(value) ? ' selected' : ''}>${esc(title)}</option>`).join('');
  const row = (name, label, control, {required = false, hint = '', after = '', pair = false} = {}) =>
    `<div class="zx-row${required ? ' req' : ''}"><label class="zx-label" for="zx-${name}">${esc(label)}</label>` +
    `<div class="zx-control">${pair ? `<div class="zx-pair">${control}${after}</div>` : control + after}${hint ? `<small class="muted zx-hint">${hint}</small>` : ''}</div></div>`;
  const select = (name, rows, value, required, blank) =>
    `<select class="form-input" id="zx-${name}" name="${name}"${required ? ' required' : ''}>${opts(rows, value, blank)}</select>`;
  const billable = Boolean(v.billable) && Boolean(v.customer_id);
  const gst = r.gst || {rates_bps: ZX_NO_RATES, company_state: '29', intra_ready: true, inter_ready: true};
  const itemised = v.itemize === '1';
  const accountRows = r.items.map(x => [x.id, (x.code ? x.code + ' · ' : '') + x.name]);
  const rateRows = (gst.rates_bps || ZX_NO_RATES).map(b => [String(b), b === 0 ? 'Non-taxable' : `GST ${b / 100}%`]);
  const items = itemised ? (m.items || (m.items = [{account: '', desc: '', amount: '', tax: '0'}])) : [];
  const figures = zxFigures(v, gst);
  const anyTax = Boolean(figures && figures.any) || (!itemised && Number(v.tax_bps || 0) > 0);
  const states = typeof SALES_STATES !== 'undefined' ? Object.entries(SALES_STATES).sort((a, b) => a[1].localeCompare(b[1])) : [[gst.company_state, 'Your state']];
  const itemTable = `<div class="zx-items" role="group" aria-label="Itemised expense"><div class="zx-items-head" aria-hidden="true"><span>Expense Account</span><span>Description</span><span>Amount</span><span>Tax</span><span></span></div>` +
    items.map((it, i) => `<div class="zx-itemrow" data-i="${i}">` +
      `<label class="zx-item-cell"><span class="zx-m-label">Expense Account</span><select class="form-input zx-item-field" data-k="account" required aria-label="Expense account, line ${i + 1}">${opts(accountRows, it.account, 'Select an account')}</select></label>` +
      `<label class="zx-item-cell"><span class="zx-m-label">Description</span><input class="form-input zx-item-field" data-k="desc" maxlength="250" placeholder="Description" aria-label="Description, line ${i + 1}" value="${esc(it.desc || '')}"></label>` +
      `<label class="zx-item-cell"><span class="zx-m-label">Amount (₹)</span><input class="form-input zx-item-field" data-k="amount" inputmode="decimal" autocomplete="off" placeholder="0.00" required aria-label="Amount, line ${i + 1}" value="${esc(it.amount || '')}"></label>` +
      `<label class="zx-item-cell"><span class="zx-m-label">Tax</span><select class="form-input zx-item-field" data-k="tax" aria-label="Tax, line ${i + 1}">${opts(rateRows, it.tax || '0')}</select></label>` +
      `<button type="button" class="icon-btn zx-item-remove" data-zx="remove-item" data-i="${i}" aria-label="Remove line ${i + 1}"${items.length < 2 ? ' disabled' : ''}>✕</button></div>`).join('') +
    `</div><div class="zx-itemactions"><button type="button" class="zx-link" data-zx="add-item"${items.length >= 10 ? ' disabled' : ''}>+ Add another line</button>` +
    `<button type="button" class="zx-link" data-zx="single">Back to a single account</button></div>`;
  const rows = [
    row('date', 'Date', `<input class="form-input" type="date" id="zx-date" name="date" required value="${esc(v.date || '')}">`, {required: true}),
    itemised ? row('items', 'Itemize', itemTable + '<input type="hidden" name="itemize" value="1">', {required: true}) : row('expense_account_id', 'Expense Account',
      select('expense_account_id', accountRows, v.expense_account_id, true, 'Select an account'), {required: true, pair: true,
        after: '<button type="button" class="zx-link" data-zx="itemize">Itemize</button>'}),
    !itemised && r.categories?.length ? row('category_id', 'Category',
      select('category_id', r.categories.map(c => [c.id, c.name]), v.category_id, false, 'Choose an account manually'),
      {hint: 'An approved category fills in its expense account.'}) : '',
    itemised ? '' : row('amount', 'Amount', `<div class="zx-money"><span class="zx-cur" aria-hidden="true">INR</span>` +
      `<input class="form-input" id="zx-amount" name="amount" inputmode="decimal" autocomplete="off" placeholder="0.00" required aria-describedby="money-entry-amount-echo" value="${esc(v.amount || '')}"></div>`,
      {required: true, after: `<small class="muted amount-echo" id="money-entry-amount-echo" data-amount-for="amount" aria-live="polite">${esc(amountEcho(v.amount || ''))}</small>`}),
    itemised ? '' : row('tax_bps', 'Tax', select('tax_bps', rateRows, v.tax_bps || '0', false, '')),
    anyTax ? row('tax_mode', 'Amount is', `<div class="zx-radios"><label class="zx-inline"><input type="radio" name="tax_mode" value="exclusive"${v.tax_mode === 'inclusive' ? '' : ' checked'}> <span>Tax Exclusive</span></label>` +
      `<label class="zx-inline"><input type="radio" name="tax_mode" value="inclusive"${v.tax_mode === 'inclusive' ? ' checked' : ''}> <span>Tax Inclusive</span></label></div>`,
      {hint: 'Exclusive: GST is added on top of what you type. Inclusive: what you type already contains GST.'}) : '',
    anyTax ? row('place_of_supply', 'Place of Supply', select('place_of_supply', states.map(([code, name]) => [code, `${name} (${code})`]), v.place_of_supply || gst.company_state, false, ''),
      {hint: figures && !figures.intra ? (gst.inter_ready ? 'Another state: IGST is claimed.' : 'Ask Accounts to set up the Input IGST account first.')
        : (gst.intra_ready ? 'Your own state: CGST and SGST are claimed.' : 'Ask Accounts to set up the Input CGST and Input SGST accounts first.')}) : '',
    (itemised || anyTax) ? `<div class="zx-row"><span class="zx-label"></span><div class="zx-control"><div class="zx-totals" data-zx-totals aria-live="polite">${zxTotalsHtml(figures)}</div></div></div>` : '',
    row('paid_through_id', 'Paid Through',
      select('paid_through_id', [...r.paid_through.map(x => [x.id, x.name]), ['personal', 'I paid for this myself']], v.paid_through_id, true, 'Select an account'), {required: true}),
    row('vendor_id', 'Vendor', select('vendor_id', [...r.parties.map(x => [x.id, x.name]), ['none', 'No vendor']], v.vendor_id, true, 'Select a vendor'), {required: true}),
    v.vendor_id === 'none' ? row('no_vendor_name', 'Who was paid?',
      `<input class="form-input" id="zx-no_vendor_name" name="no_vendor_name" maxlength="120" required value="${esc(v.no_vendor_name || '')}">`, {required: true}) : '',
    row('reference', 'Invoice#', `<input class="form-input" id="zx-reference" name="reference" maxlength="80" value="${esc(v.reference || '')}">`),
    row('customer_id', 'Customer Name', select('customer_id', (r.customers || []).map(x => [x.id, x.name]), v.customer_id, false, 'Select or add a customer'),
      {pair: true, after: `<label class="zx-inline"><input type="checkbox" name="billable" value="1"${billable ? ' checked' : ''}${v.customer_id ? '' : ' disabled'}> <span>Billable</span></label>`,
        hint: v.customer_id ? '' : 'Choose a customer to make this expense billable.'}),
    billable ? row('markup', 'Markup', `<div class="zx-pct"><input class="form-input" id="zx-markup" name="markup" type="number" min="0" max="100" step="0.01" inputmode="decimal" placeholder="0" value="${esc(v.markup || '')}"><span aria-hidden="true">%</span></div>`,
      {hint: 'Added to the cost when it is put on the customer’s invoice.'}) : '',
    row('project_id', 'Project', select('project_id', (state.projects || []).map(p => [p.id, p.name]), v.project_id, false, 'Office / common costs')),
    row('note', 'Notes', `<textarea class="form-input" id="zx-note" name="note" rows="3" maxlength="400">${esc(v.note || '')}</textarea>`),
  ].join('');
  const filed = r.receipts.filter(x => String(x.project_id || '') === String(v.project_id || ''));
  const side = `<aside class="zx-side"><div class="zx-drop" data-drop-files><div class="zx-drop-title">Attach Receipt</div>` +
    `<p class="muted">Drag or drop your receipts here, or</p><label class="btn btn-secondary btn-sm" for="moneyFiles">Browse files</label>` +
    `<input type="file" class="zx-file-input" id="moneyFiles" data-upload-files accept="image/jpeg,image/png,application/pdf" multiple>` +
    `<small class="muted">Up to 5 files · JPG, PNG or PDF · 8 MB each</small></div>` +
    `<div class="file-previews" aria-live="polite">${typeof filePreviewsHtml === 'function' ? filePreviewsHtml() : ''}</div>` +
    (filed.length ? `<div class="zx-filed"><label for="zx-receipt_id">Or one already filed with this project</label>${select('receipt_id', filed.map(x => [x.id, x.name]), v.receipt_id, false, 'None')}</div>` : '') + `</aside>`;
  return head('New Expense', 'Opens an approval ticket. Books change only after a person reviews and approves it.') +
    `<form id="moneyEntryForm" class="zx-page"><div class="zx-card"><div class="zx-cardhead"><span class="zx-tab" aria-current="page">Record Expense</span>` +
    `<label class="zx-type"><span class="muted">Entry type</span><select class="form-input" name="recipe" aria-label="Entry type">${opts(m.options.recipes.map(x => [x.key, x.title]), r.key)}</select></label></div>` +
    `<div class="zx-body"><div class="zx-fields">${rows}</div>${side}</div></div>` +
    `<div class="zx-footer"><button class="btn btn-primary" type="submit">Send for approval</button>` +
    `<button class="btn btn-secondary" type="submit" data-next="1">Send and add another</button>` +
    `<button class="btn btn-secondary" type="button" data-money="cancel">Cancel</button></div></form>`;
}

function moneyEntryView() {
  const m=state.moneyEntry,v=m.values,r=m.options.recipes.find(x=>x.key===v.recipe);
  if(r.key==='expense')return zohoExpenseView(m,v,r);
  const sel=(name,label,options,value,required=false)=>`<div class="field"><label>${label}<select class="form-input" name="${name}" ${required?'required':''}>${options.map(([id,title])=>`<option value="${esc(id)}" ${String(id)===String(value)?'selected':''}>${esc(title)}</option>`).join('')}</select></label></div>`;
  const input=(name,label,type='text',required=false)=>`<div class="field"><label>${label}<input class="form-input" name="${name}" type="${type}" value="${esc(v[name]||'')}" ${required?'required':''}></label></div>`;
  const tax=['purchase','client_invoice'].includes(r.key);
  const settlements=r.key==='client_invoice'?[['credit','On credit']]:[['bank','Bank / UPI'],['cash','Cash']].concat(r.key==='purchase'?[['credit','On credit']]:[]);
  return head('New money entry','Opens an approval ticket. Books change only after a person reviews and approves it.')+`<section class="panel"><form class="panel-body" id="moneyEntryForm"><div class="form-grid">
    ${sel('recipe','What happened',m.options.recipes.map(x=>[x.key,x.title]),r.key)}
    ${sel('project_id','Project',[['','Office / common costs'],...(state.projects||[]).filter(p=>p.company_id).map(p=>[p.id,p.name])],v.project_id)}
    <label class="field"><span>Company${v.project_id?' · From the project':''}</span><input class="form-input" value="${esc(m.options.company_name)}" readonly></label>
    ${moneyAmountField('money-entry', 'Amount (₹)', v.amount)}${input('date','Date','date',true)}
    ${input('reference','Bill / receipt reference')+`
    ${r.items.length?`<div class="field"><label>Material, service or income category<select class="form-input" name="item_id" required><option value="">Choose…</option>${moneyOptions(r.items,v.item_id)}</select></label></div>${input('description','Description (optional)')}`:''}
    ${r.parties.length?`<div class="field"><label>${r.key==='purchase'||r.key==='vendor_payment'?'Supplier / contractor':'Client'}<select class="form-input" name="party_id" required><option value="">Choose…</option>${moneyOptions(r.parties,v.party_id)}</select></label></div>`:input('party','Payee (optional)')}
    ${sel('settlement','Payment',settlements,v.settlement)}
    <div class="field"><label>Bank account<select class="form-input" name="bank_id">${moneyOptions(r.banks,v.bank_id)}</select></label></div>
    ${tax?sel('gst_rate','GST rate',[['0','No GST'],['5','5%'],['12','12%'],['18','18%'],['28','28%']],v.gst_rate)+sel('gst_mode','GST included or added',[['none','No GST'],['extra','Add GST to amount'],['included','Amount includes GST']],v.gst_mode)+sel('gst_type','GST location',[['intra','Within state (CGST + SGST)'],['inter','Other state (IGST)']],v.gst_type):''}`}
    </div><div class="g-actions"><button class="btn btn-primary" type="submit">Propose entry</button><button class="btn btn-secondary" type="button" data-money="cancel">Cancel</button></div></form></section>`;
}
const _moneyRender=render;
render=function(){if(state.view==='chart'&&state.moneyEntry){updateIdentity();$('mainContent').innerHTML=moneyEntryView();$('breadcrumb').textContent=state.moneyEntry.values.recipe==='expense'?'New Expense':'New money entry';return;}_moneyRender();};
async function openBooksExpense(){
  try{
    if(!state.coaEntity)await coaLoad();
    if(!state.coaEntity)throw new Error('Set up a company in Books before recording an expense.');
    const options=await api('/api/finance-ledger/entry-form/'+state.coaEntity);
    const recipe=options.recipes.find(r=>r.key==='expense')||options.recipes[0];
    state.formFiles=[];                     // photos of an earlier entry never carry over
    state.moneyEntry={options,originalCompanyId:options.entity_id,idempotencyKey:formRequestKey(),values:{recipe:recipe.key,date:options.today,settlement:recipe.default_settlement,gst_rate:'0',gst_mode:'none',gst_type:'intra'}};
    if(state.view!=='chart')state.moneyReturn=state.view;           // come back to the screen it was opened from
    state.view='chart';render();
  }catch(err){notify(err.message,true);}
}
document.addEventListener('click',async e=>{
  const newButton=e.target.closest('[data-action=coa-new-entry]');
  if(newButton){e.stopImmediatePropagation();await openBooksExpense();return;}
  if(e.target.closest('[data-money=cancel]')){state.moneyEntry=null;if(state.moneyReturn){state.view=state.moneyReturn;state.moneyReturn=null;}render();}
},true);
async function switchMoneyProject(m, form, v, previousProject) {
  const project = (state.projects || []).find(row => String(row.id) === v.project_id);
  const companyId = project?.company_id ?? m.originalCompanyId;
  const request = {};
  m.companyRequest = request;
  form.querySelector('button[type="submit"]').disabled = true;
  try {
    const options = companyId === m.options.entity_id ? m.options : await api('/api/finance-ledger/entry-form/'+companyId);
    if (state.moneyEntry !== m || m.companyRequest !== request || !form.isConnected) return;
    const values = Object.fromEntries(new FormData(form));
    const recipe = options.recipes.find(row => row.key === values.recipe);
    if (!recipe) throw new Error('Set up this entry type for the project’s company first.');
    if (companyId !== m.options.entity_id) {
      for (const name of ['expense_account_id','paid_through_id','category_id','item_id','party_id','bank_id']) values[name] = '';
    }
    values.receipt_id = '';
    m.options = options;
    m.projectId = v.project_id;
    m.values = values;
    render();
    document.querySelector('#moneyEntryForm [name="project_id"]')?.focus();
  } catch (error) {
    if (state.moneyEntry !== m || m.companyRequest !== request || !form.isConnected) return;
    form.elements.project_id.value = previousProject;
    m.values = Object.fromEntries(new FormData(form));
    form.querySelector('button[type="submit"]').disabled = false;
    notify(error.message, true);
  } finally {
    if (m.companyRequest === request) m.companyRequest = null;
  }
}
function moneyRenderKeepFocus(target){
  const el=target||document.activeElement;
  const form=el&&el.closest&&el.closest('#moneyEntryForm');
  const snap=form?{
    id:el.id||'',
    name:el.name||'',
    itemIdx:el.closest&&el.closest('[data-i]')?el.closest('[data-i]').dataset.i:null,
    itemKey:el.dataset&&el.dataset.k||null,
    zx:el.dataset&&el.dataset.zx||null,
  }:null;
  render();
  if(!snap)return;
  const nextForm=document.querySelector('#moneyEntryForm');
  if(!nextForm)return;
  let next=null;
  if(snap.id)next=nextForm.querySelector('#'+CSS.escape(snap.id));
  if(!next&&snap.itemIdx!==null&&snap.itemKey)next=nextForm.querySelector(`[data-i="${snap.itemIdx}"] [data-k="${snap.itemKey}"]`);
  if(!next&&snap.name)next=nextForm.querySelector(`[name="${CSS.escape(snap.name)}"]`);
  if(!next&&snap.zx)next=nextForm.querySelector(`[data-zx="${CSS.escape(snap.zx)}"]`);
  if(next&&typeof next.focus==='function')next.focus();
}
document.addEventListener('change',e=>{
  if(!e.target.closest('#moneyEntryForm')||!['recipe','gst_rate','project_id','vendor_id','category_id','expense_account_id','customer_id','billable','tax_bps'].includes(e.target.name))return;
  const m=state.moneyEntry;
  const v=Object.fromEntries(new FormData(e.target.form));
  if(e.target.name==='project_id'){
    switchMoneyProject(m,e.target.form,v,m.projectId||'');
    return;
  }
  if(m.companyRequest)return;
  m.values=v;
  if(e.target.name==='recipe'){
    const r=state.moneyEntry.options.recipes.find(x=>x.key===v.recipe);
    v.settlement=r.default_settlement;v.item_id='';v.party_id='';
  }else if(e.target.name==='customer_id'){
    if(!v.customer_id){v.billable='';v.markup='';}
  }else if(e.target.name==='category_id'){
    const r=state.moneyEntry.options.recipes.find(x=>x.key===v.recipe);
    const category=r.categories.find(c=>String(c.id)===v.category_id);
    if(category)v.expense_account_id=String(category.expense_account_id);
  }else if(e.target.name==='expense_account_id'){
    v.category_id='';
  }else if(e.target.name==='gst_rate'){
    if(v.gst_rate==='0')v.gst_mode='none';else if(v.gst_mode==='none')v.gst_mode='extra';
  }
  moneyRenderKeepFocus(e.target);
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='moneyEntryForm')return;e.preventDefault();
  const button=e.submitter;if(button?.disabled)return;if(button)button.disabled=true;
  const m=state.moneyEntry,v=Object.fromEntries(new FormData(e.target)),r=m.options.recipes.find(x=>x.key===v.recipe);
  try {
    const direct=r.key==='expense';
    const data=direct?directExpenseData(v,m.idempotencyKey):recipeEntryData(v,r,m.idempotencyKey,m.options.entity_id);
    const draft=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
      kind:direct?'finance_expense':'finance_text_entry',data,evidence:'Money form completed by a person',
    })});
    const another=Boolean(e.submitter?.dataset.next);
    state.moneyEntry=null;state.coa=null;if(state.moneyReturn){state.view=state.moneyReturn;state.moneyReturn=null;}render();notify('Ticket #'+draft.ticket_id+' opened. Review it before posting.');
    if(another)await openBooksExpense();
  }catch(err){if(button)button.disabled=false;notify(err.message,true);}
});

function billableMarkup(text) {   // "12.5" (a percentage) -> 1250 basis points
  const percent=Number(String(text||'0').trim()||0);
  if(!Number.isFinite(percent)||percent<0||percent>100)throw new Error('The mark-up is a percentage from 0 to 100.');
  return Math.round(percent*100);
}

function directExpenseData(values,requestKey) {
  const itemised=zxLinesPayload(values);          // several accounts and/or GST; null for a plain expense
  const parts=itemised?null:/^(\d+|\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+)(?:\.(\d{1,2}))?$/.exec(String(values.amount||'').trim());
  const paise=itemised?itemised.total:(parts?Number(parts[1].replace(/,/g,''))*100+Number((parts[2]||'').padEnd(2,'0')):0);
  if(!Number.isSafeInteger(paise)||paise<=0||paise>=1e14)throw new Error('Enter an amount in rupees with up to two decimal places.');
  return {date:values.date,amount_paise:paise,vendor_id:Number(values.vendor_id)||null,no_vendor:values.vendor_id==='none',
    ...(values.vendor_id==='none'?{no_vendor_name:values.no_vendor_name.trim()}:{}),
    ...(values.category_id?{category_id:Number(values.category_id)}:{}),
    ...(values.customer_id?{customer_id:Number(values.customer_id)}:{}),
    ...(values.billable&&values.customer_id?{billable:true,markup_bps:billableMarkup(values.markup)}:{}),
    ...(String(values.reference||'').trim()?{reference_number:String(values.reference).trim()}:{}),
    ...((state.formFiles||[]).length?{receipt_ids:state.formFiles.map(f=>Number(f.id))}:{}),
    expense_account_id:itemised?itemised.lines[0].expense_account_id:(Number(values.expense_account_id)||null),paid_through_id:Number(values.paid_through_id)||null,
    ...(itemised?{lines:itemised.lines,tax_mode:itemised.mode,...(itemised.place?{place_of_supply:itemised.place}:{})}:{}),
    personal_payment:values.paid_through_id==='personal',
    project_id:Number(values.project_id)||null,receipt_id:Number(values.receipt_id)||null,note:values.note,request_key:requestKey};
}

function recipeEntryData(v,r,requestKey,companyId=state.coaEntity) {
  const item=r.items.find(x=>String(x.id)===v.item_id),party=r.parties.find(x=>String(x.id)===v.party_id),accounts={};
  const slots={amount:v.amount,date:v.date,reference:v.reference,settlement:v.settlement,gst_rate:v.gst_rate||'0',gst_mode:v.gst_mode||'none',gst_type:v.gst_type||'intra'};
  if(item){accounts.item=item.id;slots.item=v.description||item.name;}
  if(party){slots[r.party_word+'_party']=party.name;if(r.key!=='purchase'||v.settlement==='credit')accounts.party=party.id;}
  else if(v.party)slots[r.party_word+'_party']=v.party;
  if(v.settlement==='bank')accounts.bank=Number(v.bank_id);
  return {entity_id:companyId,recipe:r.key,project_id:Number(v.project_id)||null,slots,accounts,idempotency_key:requestKey};
}

document.addEventListener('input',e=>{
  if(e.target.closest('#moneyEntryForm')&&state.moneyEntry)state.moneyEntry.values=Object.fromEntries(new FormData(e.target.form));
});


/* Zoho Books "Itemize": split one expense across several expense accounts, each with its own amount and GST rate. */
function zxGst() { return (state.moneyEntry.options.recipes.find(x => x.key === 'expense') || {}).gst || {company_state: '29'}; }
function zxRefreshTotals(form) {
  const box = form.querySelector('[data-zx-totals]');
  if (box) box.innerHTML = zxTotalsHtml(zxFigures(Object.fromEntries(new FormData(form)), zxGst()));
}
document.addEventListener('click', async e => {
  const b = e.target.closest && e.target.closest('#moneyEntryForm [data-zx]');
  if (!b || !state.moneyEntry) return;
  const m = state.moneyEntry, v = m.values = Object.fromEntries(new FormData(b.form || document.querySelector('#moneyEntryForm')));
  const action = b.dataset.zx;
  if (action === 'itemize') {
    m.items = [{account: v.expense_account_id || '', desc: '', amount: v.amount || '', tax: v.tax_bps || '0'}, {account: '', desc: '', amount: '', tax: v.tax_bps || '0'}];
    v.itemize = '1';
    render();
    document.querySelector('#moneyEntryForm [data-i="0"] [data-k="account"]')?.focus();
    return;
  } else if (action === 'add-item') {
    if ((m.items || []).length < 10) m.items.push({account: '', desc: '', amount: '', tax: '0'});
    render();
    const lastIdx = (m.items || []).length - 1;
    document.querySelector(`#moneyEntryForm [data-i="${lastIdx}"] [data-k="account"]`)?.focus();
    return;
  } else if (action === 'remove-item') {
    if ((m.items || []).length > 1) m.items.splice(Number(b.dataset.i), 1);
    moneyRenderKeepFocus(b);
    return;
  } else if (action === 'single') {
    const extraHasData = (m.items || []).slice(1).some(it => it.account || String(it.amount || '').trim() || String(it.desc || '').trim());
    if (extraHasData && typeof askConfirm === 'function') {
      const ok = await askConfirm('Switching back to a single account will discard lines 2 and onward. Continue?');
      if (!ok) return;
    }
    const first = (m.items || [])[0] || {};
    v.expense_account_id = first.account || ''; v.amount = first.amount || ''; v.tax_bps = first.tax || '0';
    delete v.itemize; m.items = null;
    render();
    document.querySelector('#zx-expense_account_id')?.focus();
    return;
  }
  render();
});
document.addEventListener('input', e => {
  const f = e.target.closest && e.target.closest('#moneyEntryForm .zx-item-field');
  if (f && state.moneyEntry) {
    const i = Number(f.closest('[data-i]').dataset.i);
    state.moneyEntry.items[i][f.dataset.k] = f.value;
  }
  const form = e.target.closest && e.target.closest('#moneyEntryForm');
  if (form && state.moneyEntry && (f || ['amount', 'tax_mode', 'place_of_supply'].includes(e.target.name))) zxRefreshTotals(form);
});
document.addEventListener('change', e => {
  const form = e.target.closest && e.target.closest('#moneyEntryForm');
  if (!form || !state.moneyEntry) return;
  const f = e.target.closest('.zx-item-field');
  if (f) {
    state.moneyEntry.items[Number(f.closest('[data-i]').dataset.i)][f.dataset.k] = f.value;
    if (f.dataset.k === 'tax') {                      // a line with GST shows the GST rows: draw the page again
      state.moneyEntry.values = Object.fromEntries(new FormData(form));
      moneyRenderKeepFocus(f);
    } else zxRefreshTotals(form);
  } else if (['tax_mode', 'place_of_supply'].includes(e.target.name)) {
    state.moneyEntry.values = Object.fromEntries(new FormData(form));
    zxRefreshTotals(form);
  }
});
