'use strict';
/* One generic renderer. It never executes metadata or JavaScript obtained from records. */
let uTypes=[],uRelations=[],uSelected=null,uRecords=[],uFinance=null,uNotice='',uEditing=null,uViews=[],uNotifications=[],uCalculations=[],uDocuments=[],uDocPreview=null,uDocHistory=[],uDocProjectId=0;
function clearUniversalSession(){
 uTypes=[];uRelations=[];uSelected=null;uRecords=[];uFinance=null;uNotice='';uEditing=null;
 uViews=[];uNotifications=[];uCalculations=[];uDocuments=[];uDocPreview=null;uDocHistory=[];uDocProjectId=0;
}
const uText=x=>esc(x===null?'':typeof x==='object'?JSON.stringify(x):x);
// Financial output never rounds through IEEE-754 floating point.
function uPaise(n){try{const v=BigInt(n);const a=v<0n?-v:v;return `${v<0n?'-':''}₹${a/100n}.${String(a%100n).padStart(2,'0')}`;}catch{return 'Invalid amount';}}
function uLedgerTable(title,columns,rows){
 const cells = rows.map(row => `<tr>${row.map(value => `<td>${esc(value)}</td>`).join('')}</tr>`).join('');
 return `<h3>${esc(title)}</h3><div class="w-table-wrap"><table class="w-table"><thead><tr>${columns.map(label => `<th scope="col">${esc(label)}</th>`).join('')}</tr></thead><tbody>${cells}</tbody></table></div>`;
}
function uTrialBalanceHtml(report){
 const rows = report.accounts.map(a => [a.code, a.name, uPaise(a.debit_paise), uPaise(a.credit_paise)]);
 rows.push(['', 'Total', uPaise(report.total_debit_paise), uPaise(report.total_credit_paise)]);
 return uLedgerTable('Trial balance',['Code','Account','Debit','Credit'],rows);
}
function uJournalRegisterHtml(journals){
 if (!journals.length) return '<p>No journals posted yet.</p>';
 const rows = journals.flatMap(j => j.lines.map(line => [
   '#' + j.id, j.source_event.toLowerCase().replaceAll('_',' '), '#' + j.ticket_id, '#' + line.account_id,
   line.side === 'debit' ? uPaise(line.amount_paise) : '', line.side === 'credit' ? uPaise(line.amount_paise) : ''
 ]));
 return uLedgerTable('Journal register',['Journal','Entry','Approval','Account','Debit','Credit'],rows);
}
function uAssuranceHtml(r){
 const ok=r.passed===true;
 return `<div class="universal-finance-audit"><h3>Ledger assurance: ${ok?'PASS':'FAIL — review required'}</h3>
 <p class="muted">${esc(r.scope)} · ${Number(r.journal_count)} journals / ${Number(r.line_count)} lines.</p>
 <p>Posted debits ${uPaise(r.total_debit_paise)} · credits ${uPaise(r.total_credit_paise)}</p>
 <p>AP control ${r.ap_control_credit_paise===null?'not configured':uPaise(r.ap_control_credit_paise)} · supplier open ${r.supplier_outstanding_paise===null?'not available':uPaise(r.supplier_outstanding_paise)}</p>
 ${r.findings.length?`<h4>Integrity findings</h4><ul>${r.findings.map(x=>`<li>${esc(x.code)}: ${esc(x.message)}${x.journal_id?' (journal #'+Number(x.journal_id)+')':''}</li>`).join('')}</ul>`:'<p>No anomalies detected within the stated supported scope.</p>'}
 <p class="muted">Not a statutory audit, bank verification, or PostgreSQL concurrency certification. Do not use to establish GST/TDS compliance.</p></div>`;
}
function uGeneralLedgerHtml(r){
 return `<div class="universal-finance-audit"><h3>${esc(r.account_code)} — ${esc(r.account_name)}</h3>
 <p class="muted">Posted journal lines · exact INR · ${esc(r.start_date||'all dates')} to ${esc(r.end_date||'all dates')}</p>
 <p>Opening (signed debit): ${uPaise(r.opening_signed_debit_paise)} · Debits ${uPaise(r.debit_paise)} · Credits ${uPaise(r.credit_paise)} · Closing ${uPaise(r.closing_signed_debit_paise)}</p>
 <div class="universal-doc-table"><table><thead><tr><th>Date</th><th>Journal / event</th><th>Debit</th><th>Credit</th><th>Balance</th><th>Evidence</th></tr></thead><tbody>
 ${r.entries.map(x=>`<tr><td>${esc(x.posted_date_utc)}</td><td>#${Number(x.journal_id)} · ${esc(x.source_event)}</td><td>${x.side==='debit'?uPaise(x.amount_paise):'—'}</td><td>${x.side==='credit'?uPaise(x.amount_paise):'—'}</td><td>${uPaise(x.running_balance_paise)}</td><td>Ticket #${Number(x.ticket_id)} · Source #${Number(x.source_id)}</td></tr>`).join('')}</tbody></table></div>
 <p class="muted">Positive signed balance = debit. Internal bank GL does not prove a completed transfer or bank-statement reconciliation.</p></div>`;
}
function universalView(){
 const tabs=uTypes.map(x=>`<button class="btn btn-secondary btn-sm" data-u="type" data-key="${esc(x.key)}">${esc(x.title)}</button>`).join(' ');
 const sel=uSelected;
 let body=sel?`<section class="panel"><div class="panel-head"><div><h2>${esc(sel.title)}</h2><p class="muted">Approved metadata version ${Number(sel.definition_version)} · One reusable form for every new business type</p>${isAdmin()?'<button class="btn btn-secondary btn-sm" data-u="extend-type">Add optional field(s) by ticket</button>':''}</div></div><div class="panel-body"><form id="uRecordForm" class="universal-form"><label>Related project<select class="form-input" name="u-project"><option value="">Not project-related (authorized staff only)</option>${(state.projects||[]).map(p=>`<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('')}</select></label>${sel.ui_form.fields.map(f=>{
 const key=esc(f.key);const label=esc(f.label);const required=f.required?' required':'';
 if(f.primitive==='boolean')return `<label class="universal-field"><span>${label}</span><select class="form-input" name="u-${key}"><option value="">Unknown</option><option value="true">Yes</option><option value="false">No</option></select></label>`;
 if(f.primitive==='enum')return `<label class="universal-field"><span>${label}</span><select class="form-input" name="u-${key}"${required}><option value="">Select…</option>${f.options.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select></label>`;
 if(f.primitive==='quantity')return `<label class="universal-field"><span>${label} (exact quantity)</span><input class="form-input" inputmode="decimal" name="u-${key}" placeholder="e.g. 12.5000"${required}/><select class="form-input" name="u-unit-${key}">${f.units.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select></label>`;
 const typ=f.primitive==='date'?'date':f.primitive==='datetime'?'datetime-local':f.primitive==='integer'?'number': 'text';
 const hint=f.primitive==='money'?'Exact INR value, e.g. 1200.50':f.primitive==='decimal'?'Exact decimal value':'';
 return `<label class="universal-field"><span>${label} ${f.required?'*':''}</span><input class="form-input" type="${typ}" name="u-${key}" ${typ==='number'?'step="1"':''} placeholder="${hint}" ${required}></label>`;
 }).join('')}<button class="btn btn-primary" type="submit">Create / update approval ticket</button></form></div></section>
 <section class="panel"><div class="panel-head"><div><h3>Records</h3><p class="muted">Saved only after authorized ticket approval</p></div></div><div class="panel-body"><div class="universal-filter"><label>Field<select class="form-input" id="uFilterField"><option value="">All records</option>${sel.ui_form.fields.filter(f=>['text','date','integer','decimal','enum'].includes(f.primitive)).map(f=>`<option value="${esc(f.key)}">${esc(f.label)}</option>`).join('')}</select></label><label>Operator<select id="uFilterOp" class="form-input"><option value="eq">Equals</option><option value="lte">On/before or ≤</option><option value="gte">On/after or ≥</option><option value="contains">Contains</option></select></label><label>Value<input id="uFilterValue" class="form-input" placeholder="Filter value"></label><button class="btn btn-secondary" data-u="filter">Apply filter</button></div><div class="universal-records">${uRecords.length?uRecords.map(r=>`<article class="newtype-card"><strong>#${r.id}</strong> · ${esc(r.type_key)} <button class="btn btn-secondary btn-sm" data-u="edit-record" data-id="${Number(r.id)}">Edit</button> <button class="btn btn-secondary btn-sm" data-u="delete-record" data-id="${Number(r.id)}">Soft delete</button> ${uRelations.some(q=>q.source_type===sel.key)?`<button class="btn btn-secondary btn-sm" data-u="link-record" data-id="${Number(r.id)}">Link related record</button>`:''} <small>Project ${r.project_id??'not specified'}</small><div class="universal-record-values">${Object.entries(r.values||{}).map(([k,v])=>`<div><strong>${esc(k)}:</strong> ${uText(v)}</div>`).join('')}</div></article>`).join(''):'<p class="muted">No records loaded. Use the filter or refresh button.</p>'}</div><button class="btn btn-secondary" data-u="load-records">Refresh records</button> <button class="btn btn-secondary" data-u="dashboard">Count dashboard</button> ${isAdmin()?'<button class="btn btn-secondary" data-u="new-view">Propose saved view</button> <button class="btn btn-secondary" data-u="new-workflow">Propose notification rule</button>':''}</div></section>`:'';
 return head('Universal Business Types','Build new business vocabulary as approved metadata. No per-type code changes or migrations.')+
 `<div class="universal-toolbar"><button class="btn btn-secondary" data-u="load-types">Refresh type catalog</button> ${isAdmin()?'<button class="btn btn-primary" data-u="new-type">Propose a new type</button>':''}</div><div class="universal-tabs">${tabs||'<p>No universal types loaded yet. Refresh the catalog.</p>'}</div><p class="muted" id="uNotice" role="status">${esc(uNotice)}</p>${body}
 <section class="panel"><div class="panel-body"><h3>Approved saved views</h3><button class="btn btn-secondary" data-u="load-views">Load views</button>
 ${uViews.map(v=>`<article class="newtype-card"><strong>${esc(v.title)}</strong> · ${esc(v.type_key)} <button class="btn btn-secondary btn-sm" data-u="run-view" data-key="${esc(v.key)}">Run</button> <a class="btn btn-secondary btn-sm" href="/api/universal/saved-views/${encodeURIComponent(v.key)}/export.csv">Export CSV</a></article>`).join('')}
 <h3>Approved calculations & document templates</h3><p class="muted">Exact decimal results and source-linked document drafts. Issuance requires a separate Admin ticket; it never posts accounting entries.</p>
 <button class="btn btn-secondary" data-u="load-documents">Load documents and formulas</button>
 ${isAdmin()?'<button class="btn btn-secondary" data-u="new-calculation">Propose formula</button> <button class="btn btn-secondary" data-u="new-document">Describe new document type</button>':''}
 <div class="universal-filter"><label>Project for document preview<select id="uDocProject" class="form-input"><option value="">Select project</option>${(state.projects||[]).map(p=>`<option value="${Number(p.id)}" ${Number(p.id)===uDocProjectId?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label></div>
 ${uCalculations.map(c=>`<article class="newtype-card"><strong>${esc(c.title)}</strong> · ${esc(c.type_key)} · ${esc(c.key)} · Admin ticket #${Number(c.approval_ticket_id)}</article>`).join('')}
 ${uDocuments.map(d=>`<article class="newtype-card"><strong>${esc(d.title)}</strong> · ${esc(d.kind.replaceAll('_',' '))} · ${esc(d.type_key)} · Definition v${Number(d.version||1)} <button class="btn btn-secondary btn-sm" data-u="preview-document" data-key="${esc(d.key)}">Preview draft</button> <button class="btn btn-secondary btn-sm" data-u="view-document-html" data-key="${esc(d.key)}">Print view</button> <button class="btn btn-secondary btn-sm" data-u="download-document" data-key="${esc(d.key)}">Draft PDF</button> <button class="btn btn-secondary btn-sm" data-u="history-document" data-key="${esc(d.key)}">Revision history</button> ${isAdmin()?`<button class="btn btn-secondary btn-sm" data-u="revise-document" data-key="${esc(d.key)}">Revise template</button>`:''}</article>`).join('')}
 ${uDocPreview?`<article class="newtype-card universal-doc-preview"><p class="muted"><strong>UNAPPROVED DRAFT</strong> · ${esc(uDocPreview.title)} · Project #${Number(uDocPreview.project_id)}</p><div class="universal-doc-table"><table><thead><tr>${uDocPreview.columns.map(c=>`<th>${esc(c.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${uDocPreview.rows.map(r=>`<tr>${r.cells.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${uDocPreview.total!==null?`<p class="universal-doc-total">Calculated total: ${esc(uDocPreview.total)}</p>`:''}<p class="muted">Review all ${uDocPreview.source_records?.length||0} source records, relationships, figures and terms. This preview is not a posted financial document.</p>${uDocPreview.aggregates?.map(a=>`<div><strong>${esc(a.label)}</strong>: ${esc(a.value)}</div>`).join('')||''}${uDocPreview.sections?.map(a=>`<div class="universal-doc-section"><strong>${esc(a.title)}</strong><p>${esc(a.text)}</p></div>`).join('')||''}${isAdmin()?`<button class="btn btn-primary btn-sm" data-u="issue-document" data-key="${esc(uDocPreview.template_key)}">Propose issuing this reviewed snapshot</button>`:''}</article>`:''}
 ${uDocHistory.length?`<article class="newtype-card"><strong>Document issue / withdrawal history (append-only)</strong>${uDocHistory.map(h=>`<div class="universal-doc-history"><strong>Revision ${Number(h.revision)}</strong> · ${esc(h.state)} · Ticket #${Number(h.ticket_id)} · ${esc(h.template_key)} <a href="/api/universal/documents/issued/${Number(h.id)}.pdf" target="_blank" rel="noopener">Historical PDF</a> ${isAdmin()&&h===uDocHistory[0]&&h.state==='issued'?`<button class="btn btn-secondary btn-sm" data-u="withdraw-document" data-key="${esc(h.template_key)}" data-revision="${Number(h.revision)}">Propose withdrawal</button>`:''}<small>SHA256 ${esc(h.snapshot_hash)}</small></div>`).join('')}</article>`:''}
 <h3>Approved workflow notifications</h3><button class="btn btn-secondary" data-u="load-notices">Load notices</button>
 ${uNotifications.map(n=>`<article class="newtype-card"><strong>${esc(n.workflow_key)}</strong> · Record #${Number(n.record_id)} · ${esc(n.message)}</article>`).join('')}</div></section>`;
}
function ledgerView(){return head('Protected INR ledger','Posted journals only. PO commitments are not payables; bank book is not bank reconciliation.')+
 staffReimbursementPanel()+legacyExpensePreviewPanel()+
 `<section class="panel"><div class="panel-body"><button class="btn btn-secondary" data-u="load-companies">Refresh legal entities</button> ${isAdmin()?'<button class="btn btn-secondary" data-u="finance-po">Propose PO</button> <button class="btn btn-secondary" data-u="finance-bill">Propose supplier bill</button> <button class="btn btn-secondary" data-u="finance-allocate-advance">Allocate advance</button> <button class="btn btn-secondary" data-u="finance-reverse-payment">Reverse payment</button> <button class="btn btn-secondary" data-u="finance-reverse-bill">Reverse bill</button> <button class="btn btn-secondary" data-u="finance-close-period">Close accounting period</button> <button class="btn btn-secondary" data-u="finance-grn">Record goods receipt</button> <button class="btn btn-secondary" data-u="finance-inventory-bill">Post GRNI-matched bill</button> <button class="btn btn-secondary" data-u="finance-issue">Issue project material</button> <button class="btn btn-secondary" data-u="finance-statement">Import bank statement evidence</button> <button class="btn btn-secondary" data-u="finance-reconcile">Approve bank reconciliation</button>':''} ${isAdmin()?'<button class="btn btn-secondary" data-u="setup-finance">Propose initial finance mapping</button> <button class="btn btn-secondary" data-u="finance-enable-advances">Enable supplier advances</button> <button class="btn btn-secondary" data-u="finance-enable-inventory">Enable inventory/GRNI</button>':''}<p class="muted">Every accounting write needs an approved ticket. This is a limited invoice-led INR kernel; GST/TDS and advanced stock costing remain disabled. Inventory and bank reconciliation require separately approved policies, documentary evidence and exact amount checks.</p><div id="uFinanceContent">${uFinance?uFinance.map(c=>`<article class="newtype-card"><h3>${esc(c.name)} (${esc(c.currency)})</h3>${isAdmin()?`<button class="btn btn-secondary" data-u="finance-enable-cash" data-entity="${Number(c.id)}">Set up Cash in Hand</button> <button class="btn btn-secondary" data-u="finance-petty-cash-setup" data-entity="${Number(c.id)}">Assign petty cash</button> <button class="btn btn-secondary" data-u="finance-reverse-petty-cash">Reverse a petty cash top-up</button> <button class="btn btn-secondary" data-u="finance-site-company" data-entity="${Number(c.id)}">Use for site expenses</button> `:''}<button class="btn btn-secondary" data-u="finance-pay-vendor" data-entity="${Number(c.id)}">Pay a supplier bill</button> <button class="btn btn-secondary" data-u="finance-pay-advance" data-entity="${Number(c.id)}">Pay a supplier advance</button> <button class="btn btn-secondary" data-u="finance-expense-categories" data-entity="${Number(c.id)}">Expense categories</button> <button class="btn btn-secondary" data-u="trial" data-entity="${Number(c.id)}">Show trial balance</button> <button class="btn btn-secondary" data-u="integrity" data-entity="${Number(c.id)}">Verify GL / AP integrity</button> <button class="btn btn-secondary" data-u="general-ledger" data-entity="${Number(c.id)}">Trace general ledger</button> <button class="btn btn-secondary" data-u="journals" data-entity="${Number(c.id)}">Journal register</button> <button class="btn btn-secondary" data-u="advances" data-entity="${Number(c.id)}">Supplier advances</button> <button class="btn btn-secondary" data-u="reversals" data-entity="${Number(c.id)}">Reversals</button> <button class="btn btn-secondary" data-u="periods" data-entity="${Number(c.id)}">Closed periods</button></article>`).join(''):'Load legal entities to begin.'}</div><div id="uLedgerOutput" class="universal-report"></div></div></section>`;
}
function staffReimbursementPanel(){
 if(!hasFinance()||!uFinance?.length)return '';
 return `<section class="panel section-gap"><div class="panel-head"><div><h2>Pay staff reimbursements</h2><p class="muted">Propose a payment for an approved out-of-pocket claim.</p></div></div>
  <div class="panel-body"><label for="uStaffCompany">Company</label><select id="uStaffCompany" class="form-input">
   ${uFinance.map(x=>`<option value="${Number(x.id)}">${esc(x.name)}</option>`).join('')}
  </select><button class="btn btn-secondary" data-u="staff-claims">Load claims</button><div id="uStaffClaims"></div></div></section>`;
}
async function showVendorPayment(entity){
 const output=document.getElementById('uLedgerOutput');
 const [payables, options]=await Promise.all([
  api('/api/finance-ledger/payables/'+entity),api('/api/finance-ledger/entry-form/'+entity),
 ]);
 if(!output?.isConnected)return;
 const bills=payables.bills.filter(b=>b.outstanding_paise>0);
 const sources=options.recipes.find(r=>r.key==='expense')?.paid_through||[];
 if(!bills.length){output.textContent='This company has no bills to pay.';return;}
 if(!sources.length){output.textContent='Set up a paying account before recording a payment.';return;}
 output.innerHTML=`<form id="uVendorPayForm" class="form-grid" data-key="${formRequestKey()}">
  <label>Bill<select class="form-input" name="bill_id" required>
   ${bills.map(b=>`<option value="${Number(b.bill_id)}">${esc(b.invoice_number+' · '+uPaise(b.outstanding_paise)+' due')}</option>`).join('')}
  </select></label>
  <label>Paid through<select class="form-input" name="paid_through_id" required><option value="">Choose an account</option>
   ${sources.map(a=>`<option value="${Number(a.id)}">${esc(a.name)}</option>`).join('')}
  </select></label>
  <label>Amount (₹)<input class="form-input" name="amount" inputmode="decimal" required></label>
  <label>Payment date<input class="form-input" type="date" name="payment_date" value="${esc(options.today)}" required></label>
  <label>Payment reference<input class="form-input" name="payment_reference" maxlength="120" required></label>
  <button class="btn btn-primary" type="submit">Send payment for approval</button>
 </form>`;
}
async function showSupplierAdvance(entity){
 const output=document.getElementById('uLedgerOutput');
 const options=await api('/api/finance-ledger/entry-form/'+entity);
 if(!output?.isConnected)return;
 const expense=options.recipes.find(recipe=>recipe.key==='expense');
 const projects=state.projects||[];
 if(!expense?.parties.length||!expense.paid_through.length||!projects.length){
  output.textContent='Set up a vendor, project and paying account before recording an advance.';return;
 }
 const optionsFor=rows=>rows.map(row=>`<option value="${Number(row.id)}">${esc(row.name)}</option>`).join('');
 output.innerHTML=`<form id="uSupplierAdvanceForm" class="form-grid" data-entity="${entity}" data-key="${formRequestKey()}">
  <label>Vendor<select class="form-input" name="supplier_id" required><option value="">Choose a vendor</option>${optionsFor(expense.parties)}</select></label>
  <label>Project<select class="form-input" name="project_id" required><option value="">Choose a project</option>${optionsFor(projects)}</select></label>
  <label>Paid through<select class="form-input" name="paid_through_id" required><option value="">Choose an account</option>${optionsFor(expense.paid_through)}</select></label>
  <label>Amount (₹)<input class="form-input" name="amount" inputmode="decimal" required></label>
  <label>Payment date<input class="form-input" type="date" name="payment_date" value="${esc(options.today)}" required></label>
  <label>Payment reference<input class="form-input" name="payment_reference" maxlength="120" required></label>
  <button class="btn btn-primary" type="submit">Send advance for approval</button>
 </form>`;
}
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uSupplierAdvanceForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 const fields=form.elements,amount=rupeesToPaise(fields.amount.value);
 if(amount===null||amount<=0){notify('Enter the amount paid in rupees.',true);return;}
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_advance',evidence:'Supplier advance entered in Books',
   data:{entity_id:Number(form.dataset.entity),supplier_id:Number(fields.supplier_id.value),
    project_id:Number(fields.project_id.value),paid_through_id:Number(fields.paid_through_id.value),
    amount_paise:amount,payment_date:fields.payment_date.value,payment_reference:fields.payment_reference.value.trim(),
    idempotency_key:form.dataset.key},
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Advance ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
function showSiteCompanyForm(entity){
 const output=document.getElementById('uLedgerOutput');
 const projects=state.projects||[];
 const company=uFinance?.find(c=>Number(c.id)===entity);
 if(!company)return;
 if(!projects.length){output.textContent='Create a project before assigning its company.';return;}
 output.innerHTML=`<form id="uSiteCompanyForm" class="form-grid" data-entity="${entity}">
  <label>Project<select class="form-input" name="project_id" required>
   <option value="">Choose a project</option>
   ${projects.map(p=>`<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('')}
  </select></label>
  <p class="muted">After approval, future site expenses for this project will use ${esc(company.name)}.</p>
  <button class="btn btn-primary" type="submit">Send company choice for approval</button>
 </form>`;
}
function showPettyCashSetup(entity){
 const output=document.getElementById('uLedgerOutput');
 const company=uFinance?.find(c=>Number(c.id)===entity);
 if(!company)return;
 const staff=(state.users||[]).filter(user=>user.active&&user.role!=='viewer');
 if(!staff.length){output.textContent='Add an active staff member first.';return;}
 output.innerHTML=`<form id="uPettyCashSetupForm" class="form-grid" data-entity="${entity}">
  <label>Who will hold petty cash for ${esc(company.name)}?<select class="form-input" name="user_id" required>
   <option value="">Choose a staff member</option>
   ${staff.map(user=>`<option value="${Number(user.id)}">${esc(user.display_name||user.username)}</option>`).join('')}
  </select></label>
  <button class="btn btn-primary" type="submit">Send account setup for approval</button>
 </form>`;
}
async function showExpenseCategorySetup(entity){
 const output=document.getElementById('uLedgerOutput');
 const company=uFinance?.find(c=>Number(c.id)===entity);
 if(!company)return;
 const options=await api('/api/finance-ledger/entry-form/'+entity);
 if(!output?.isConnected)return;
 const expense=options.recipes.find(recipe=>recipe.key==='expense');
 const names=new Map(expense.items.map(account=>[account.id,account.name]));
 const rows=expense.categories.map(category=>[category.name,names.get(category.expense_account_id)||'']);
 output.innerHTML=`${rows.length?uLedgerTable('Approved categories',['Expense category','Default account'],rows):''}
  <form id="uExpenseCategoryForm" class="form-grid" data-entity="${entity}">
   <p>Choose a default expense account for ${esc(company.name)}. Use the same category name to change its default.</p>
   <label>Category name<input class="form-input" name="name" minlength="2" maxlength="120" required></label>
   <label>Default expense account<select class="form-input" name="expense_account_id" required>
    <option value="">Choose an account</option>${expense.items.map(account=>`<option value="${Number(account.id)}">${esc(account.name)}</option>`).join('')}
   </select></label>
   <button class="btn btn-primary" type="submit">Send category for approval</button>
  </form>`;
}
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uExpenseCategoryForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_expense_category',evidence:'Default expense account selected in Books',
   data:{entity_id:Number(form.dataset.entity),name:form.elements.name.value.trim(),
    expense_account_id:Number(form.elements.expense_account_id.value)},
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Category ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uPettyCashSetupForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_open_petty_cash',evidence:'Petty cash custodian selected in Books',
   data:{entity_id:Number(form.dataset.entity),user_id:Number(form.elements.user_id.value)},
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Account setup ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uSiteCompanyForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_project_company',evidence:'Default company selected for site expenses in Books',
   data:{project_id:Number(form.elements.project_id.value),entity_id:Number(form.dataset.entity)},
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Company choice ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uVendorPayForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 const fields=form.elements,amount=rupeesToPaise(fields.amount.value);
 if(amount===null||amount<=0){notify('Enter the amount paid in rupees.',true);return;}
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_payment',evidence:'Supplier payment entered in Books',
   data:{bill_id:Number(fields.bill_id.value),paid_through_id:Number(fields.paid_through_id.value),
    amount_paise:amount,payment_date:fields.payment_date.value,payment_reference:fields.payment_reference.value.trim(),
    idempotency_key:form.dataset.key},
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Payment ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
async function showStaffClaims(){
 const company=document.getElementById('uStaffCompany');
 const entity=Number(company.value);
 const [claims,options]=await Promise.all([
  api('/api/finance-ledger/staff-claims/'+entity),api('/api/finance-ledger/entry-form/'+entity),
 ]);
 if(Number(company.value)!==entity||!company.isConnected)return;
 const content=document.getElementById('uStaffClaims');
 if(!claims.length){content.textContent='This company has no outstanding staff claims.';return;}
 const expense=options.recipes.find(r=>r.key==='expense');
 content.innerHTML=`<form id="uStaffPayForm" class="form-grid" data-key="${formRequestKey()}">
   <label>Claim<select class="form-input" name="claim_id" required>
    ${claims.map(c=>`<option value="${Number(c.id)}" data-paise="${Number(c.amount_paise)}">${esc(c.staff+' · '+c.note+' · '+uPaise(c.amount_paise))}</option>`).join('')}
   </select></label>
   <label>Paid through<select class="form-input" name="paid_through_id" required><option value="">Choose…</option>
    ${expense.paid_through.map(a=>`<option value="${Number(a.id)}">${esc(a.name)}</option>`).join('')}
   </select></label>
   <label>Payment date<input class="form-input" type="date" name="payment_date" value="${esc(options.today)}" required></label>
   <button class="btn btn-primary" type="submit">Send payment for approval</button>
  </form>`;
}
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='uStaffPayForm')return;
 e.preventDefault();
 const button=e.submitter;
 if(button?.disabled)return;
 if(button)button.disabled=true;
 try{
  const claim=form.elements.claim_id.selectedOptions[0];
  const data={claim_id:Number(claim.value),amount_paise:Number(claim.dataset.paise),
   paid_through_id:Number(form.elements.paid_through_id.value),payment_date:form.elements.payment_date.value,
   request_key:form.dataset.key};
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind:'finance_reimburse_staff',data,evidence:'Staff payment selected in Books',
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Payment ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{if(button)button.disabled=false;}
});
function legacyExpensePreviewPanel(){
 if(!['admin','accounts'].includes(state.user?.role)||!uFinance?.length)return '';
 return `<section class="panel section-gap">
  <div class="panel-head"><div><h2>Preview old costs in Books</h2><p class="muted">Review what an old expense would become in the ledger.</p></div></div>
  <div class="panel-body">
   <label for="legacyExpenseCompany">Company</label>
   <select id="legacyExpenseCompany" class="form-input">${uFinance.map(company=>`<option value="${Number(company.id)}">${esc(company.name)}</option>`).join('')}</select>
   <button class="btn btn-secondary" data-u="legacy-expense-options">Open preview form</button>
   <div id="legacyExpensePreviewContent"></div>
   <details><summary>Reverse an approved migration batch</summary>
    <form id="legacyExpenseReverseForm" class="form-grid">
     <label>Migration ticket number<input class="form-input" name="batch_ticket_id" type="number" min="1" step="1" required></label>
     <label>Reason<textarea class="form-input" name="reason" maxlength="400" required></textarea></label>
     <button class="btn btn-secondary" type="submit">Send reversal for approval</button>
    </form>
   </details>
  </div>
 </section>`;
}
const reviewedLegacyBatches=new WeakMap();
async function legacyExpenseOptions(entity){
 const target=document.getElementById('legacyExpensePreviewContent');
 if(!target)return;
 const [form, sources]=await Promise.all([
  api('/api/finance-ledger/entry-form/'+entity),api('/api/finance-ledger/paid-through/'+entity),
 ]);
 if(!target.isConnected||Number(document.getElementById('legacyExpenseCompany')?.value)!==entity)return;
 const expense=form.recipes.find(row=>row.key==='expense');
 const costs=(state.costs||[]).filter(row=>row.kind==='expense'&&row.status==='approved');
 const input=(label,name,choices)=>`<label>${label}<select name="${name}" class="form-input"><option value="">Choose…</option>${choices.map(x=>`<option value="${Number(x.id)}">${esc(x.name)}</option>`).join('')}</select></label>`;
 const row=`<fieldset class="form-grid" data-legacy-entry>
  <legend>Old expense mapping</legend>
  ${input('Old expense','cost_id',costs.map(c=>({id:c.id,name:c.title+' · '+c.project+' · '+inr(c.amount)})))}
  ${input('Vendor','vendor_id',expense.parties)}
  ${input('Paid through','paid_through_id',sources)}
  <div class="form-grid" data-legacy-payments></div>
  ${input('Expense account','expense_account_id',expense.items)}
  <label>Original expense date<input type="date" name="date" class="form-input"></label>
  <button class="btn btn-secondary btn-sm" type="button" data-legacy-remove>Remove expense</button>
 </fieldset>`;
 target.innerHTML=`<form id="legacyExpensePreviewForm" data-entity="${entity}" class="form-grid">
  <div class="form-grid" data-legacy-entries>${row}</div>
  <template data-legacy-template>${row}</template>
  <button class="btn btn-secondary" type="button" data-legacy-add>Add another expense</button>
  <button class="btn btn-primary" type="submit">Preview selected expenses</button>
 </form><div id="legacyExpensePreviewResult" role="status"></div>`;
 syncLegacyPreviewRows(target.querySelector('form'));
}
function syncLegacyPreviewRows(form){
 const rows=[...form.querySelectorAll('[data-legacy-entry]')];
 rows.forEach(row=>row.querySelector('[data-legacy-remove]').hidden=rows.length===1);
 form.querySelector('[data-legacy-add]').disabled=rows.length>=50;
 clearLegacyPreview(form);
}
function clearLegacyPreview(form){
 form.dataset.reviewRevision=String(Number(form.dataset.reviewRevision||0)+1);
 document.getElementById('legacyExpensePreviewResult')?.replaceChildren();
}
async function loadHistoricalPayments(form, select){
 const row=select.closest('[data-legacy-entry]');
 const target=row.querySelector('[data-legacy-payments]');
 const source=row.querySelector('[name="paid_through_id"]');
 const cost=Number(select.value), version=String(Number(row.dataset.paymentRequest||0)+1);
 const current=()=>row.isConnected&&row.dataset.paymentRequest===version;
 row.dataset.paymentRequest=version;
 target.replaceChildren();
 source.closest('label').hidden=false;
 source.disabled=false;
 delete row.dataset.loadingPayments;
 if(!cost)return;
 row.dataset.loadingPayments='true';
 target.textContent='Checking linked payments…';
 try{
  const result=await api('/api/finance-ledger/legacy-expenses/'+Number(form.dataset.entity)+'/preview',{
   method:'POST',body:JSON.stringify({entries:[{cost_id:cost}]}),
  });
  if(!current())return;
  const payments=result.entries[0].payments||[];
  const active=payments.filter(payment=>payment.status==='approved');
  if(!payments.length){target.replaceChildren();return;}
  source.value='';
  source.disabled=true;
  source.closest('label').hidden=true;
  target.innerHTML=active.length?active.map(payment=>`<fieldset class="form-grid" data-legacy-payment="${Number(payment.id)}">
   <legend>Payment #${Number(payment.id)} · ${esc(uPaise(payment.amount_paise))}</legend>
   <label>Paid through<select class="form-input" data-legacy-payment-source>${source.innerHTML}</select></label>
   <label>Original payment date<input type="date" class="form-input" data-legacy-payment-date value="${esc(payment.date||'')}"></label>
  </fieldset>`).join(''):'There are no approved linked payments to map.';
 }catch(err){
  if(current())target.textContent=err.message;
 }finally{
  if(current())delete row.dataset.loadingPayments;
 }
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-legacy-add],[data-legacy-remove]');
 const form=button?.closest('#legacyExpensePreviewForm');
 if(!form)return;
 if(button.hasAttribute('data-legacy-add')){
  form.querySelector('[data-legacy-entries]').append(form.querySelector('template').content.cloneNode(true));
 }else{
  button.closest('[data-legacy-entry]').remove();
 }
 syncLegacyPreviewRows(form);
});
document.addEventListener('submit',async e=>{
 const form=e.target;
 if(form.id!=='legacyExpensePreviewForm')return;
 e.preventDefault();
 const button=e.submitter, target=document.getElementById('legacyExpensePreviewResult');
 const revision=form.dataset.reviewRevision;
 if(button?.disabled)return;
 if(button)button.disabled=true;
 try{
  if(form.querySelector('[data-loading-payments]'))throw new Error('Wait for the linked payments to finish loading.');
  const entries=[...form.querySelectorAll('[data-legacy-entry]')].map(row=>{
   const read=name=>row.querySelector('[name="'+name+'"]').value;
   const payment_mappings=[...row.querySelectorAll('[data-legacy-payment]')].map(payment=>({
    payment_id:Number(payment.dataset.legacyPayment),
    paid_through_id:Number(payment.querySelector('[data-legacy-payment-source]').value)||null,
    date:payment.querySelector('[data-legacy-payment-date]').value||null,
   }));
   return {cost_id:Number(read('cost_id')),vendor_id:Number(read('vendor_id'))||null,
    paid_through_id:Number(read('paid_through_id'))||null,expense_account_id:Number(read('expense_account_id'))||null,
    date:read('date')||null,payment_mappings};
  });
  if(entries.some(entry=>!entry.cost_id))throw new Error('Choose an old expense for each row.');
  if(new Set(entries.map(entry=>entry.cost_id)).size!==entries.length)throw new Error('Choose each old expense only once.');
  const result=await api('/api/finance-ledger/legacy-expenses/'+Number(form.dataset.entity)+'/preview',{
   method:'POST',body:JSON.stringify({entries}),
  });
  if(!form.isConnected||form.dataset.reviewRevision!==revision)return;
  const batch=result.batch;
  const issues=items=>items.length?`<ul>${items.map(issue=>`<li>${esc(issue)}</li>`).join('')}</ul>`:'';
  const comparison=uLedgerTable('Effect on project totals',['Project','Current','If posted','Difference'],
   batch.projects.map(p=>[p.project_name,uPaise(p.current_actual_paise),uPaise(p.projected_actual_paise),uPaise(p.difference_paise)]));
  target.innerHTML=`<p>${batch.ready_for_review?'Ready for accountant review.':'This group needs review.'}</p>
   <p>Debits ${esc(uPaise(batch.total_debit_paise))} · Credits ${esc(uPaise(batch.total_credit_paise))}</p>
   ${issues(batch.issues)}${comparison}
   ${result.entries.map(draft=>draft.ready_for_review
    ?uLedgerTable(draft.title,['Account','Side','Amount'],draft.journal_lines.map(line=>[
      line.account_name,line.side==='debit'?'Debit':'Credit',uPaise(line.amount_paise),
     ]))
    :`<h4>${esc(draft.title||'Historical cost #'+Number(draft.cost_id))}</h4>${issues(draft.issues)}`).join('')}
   ${batch.ready_for_review?`<form id="legacyExpenseSendForm" class="form-grid">
    <label>Accountant sign-off reference<input class="form-input" name="signoff_reference" maxlength="400" required></label>
    <button class="btn btn-primary" type="submit">Send ${entries.length} expenses for approval</button>
   </form>`:''}`;
  const sentForm=target.querySelector('#legacyExpenseSendForm');
  if(sentForm)reviewedLegacyBatches.set(sentForm,{
   entity_id:Number(form.dataset.entity),entries,review_fingerprint:batch.review_fingerprint,
  });
 }catch(err){if(form.isConnected&&form.dataset.reviewRevision===revision)target.textContent=err.message;}
 finally{if(button)button.disabled=false;}
});
document.addEventListener('submit',async e=>{
 const form=e.target;
 const isMigration=form.id==='legacyExpenseSendForm';
 if(!isMigration&&form.id!=='legacyExpenseReverseForm')return;
 e.preventDefault();
 const button=form.querySelector('button[type="submit"]');
 if(button.disabled)return;
 const values=Object.fromEntries(new FormData(form));
 const batch=reviewedLegacyBatches.get(form);
 if(isMigration&&!batch)return;
 const kind=isMigration?'finance_migrate_expenses':'finance_reverse_expense_migration';
 const data=isMigration?{...batch,signoff_reference:values.signoff_reference.trim()}
  :{batch_ticket_id:Number(values.batch_ticket_id),reason:values.reason.trim()};
 button.disabled=true;
 try{
  const result=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
   kind,data,evidence:isMigration?'Accountant review reference entered in Books':'Migration reversal requested in Books',
  })});
  form.replaceWith(Object.assign(document.createElement('p'),{textContent:'Ticket #'+result.ticket_id+' is ready for approval.'}));
 }catch(err){notify(err.message,true);}
 finally{button.disabled=false;}
});
document.addEventListener('change',e=>{
 const legacyMapping=e.target.closest('#legacyExpensePreviewForm');
 if(legacyMapping){
  clearLegacyPreview(legacyMapping);
  if(e.target.name==='cost_id')loadHistoricalPayments(legacyMapping,e.target);
 }
 if(e.target.id==='legacyExpenseCompany')document.getElementById('legacyExpensePreviewContent')?.replaceChildren();
 if(e.target.id==='uStaffCompany')document.getElementById('uStaffClaims')?.replaceChildren();
});
async function uLoadRecords(query=''){
 if(!uSelected)return;
 const r=await api('/api/universal/records/'+encodeURIComponent(uSelected.key)+(query?'?'+query:''));
 uRecords=r.records;uNotice=`${r.total} matching records`;render();
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-u]');if(!b)return;
 const action=b.dataset.u;
 try{
  if(action==='legacy-expense-options'){await legacyExpenseOptions(Number(document.getElementById('legacyExpenseCompany').value));return;}
  if(action==='staff-claims'){await showStaffClaims();return;}
  if(action==='load-documents'){
   [uCalculations,uDocuments]=await Promise.all([api('/api/universal/calculations'),api('/api/universal/documents')]);
   uNotice=`${uCalculations.length} formulas, ${uDocuments.length} approved document templates`;render();return;
  }
  if(action==='new-calculation'){
   if(!uSelected)throw new Error('Select a metadata type first');
   const field=uSelected.ui_form.fields.find(f=>['integer','decimal','money','quantity'].includes(f.primitive));
   if(!field)throw new Error('The selected type needs a numeric field for a calculation');
   const sample={key:'record_total',type_key:uSelected.key,title:'Calculated total',
     expression:{op:'mul',args:[{field:field.key},{constant:'1.00'}]},output:'decimal',currency:null};
   const raw=await askText('Safe formula: only field, constant, add, sub, mul, div, min, max. Exact decimal strings only.',JSON.stringify(sample));
   if(!raw)return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_calculation',
      data:JSON.parse(raw),evidence:'Admin proposes a bounded decimal formula for '+uSelected.key})});
   uNotice=`Formula ticket #${r.ticket_id} awaits Admin approval`;render();return;
  }
  if(action==='new-document'){
   if(!uSelected)throw new Error('Select a business type to ground the document in approved fields');
   const request=await askText('Describe the document/report you need; this is untrusted input and creates only a draft proposal.',
       'Create a reusable report from approved '+uSelected.title+' records.');
   if(!request)return;
   const typeKey=await askText('Unique machine key (lower_snake_case), e.g. inspection_certificate','custom_inspection_report');
   if(!typeKey)return;
   const title=await askText('Document display title','Fictional Business Report');
   if(!title)return;
   const provider=await askText('Template advisor: demo (offline) or configured openai/claude/gemini','demo')||'demo';
   const advice=await api('/api/universal/documents/suggest',{method:'POST',body:JSON.stringify({
     type_key:uSelected.key,key:typeKey,title,request_text:request,provider})});
   const raw=await askText('Review and edit the suggested declarative template. Submission requires an Admin ticket.',JSON.stringify(advice.template,null,2));
   if(!raw)return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_document',
     data:JSON.parse(raw),evidence:'Owner-requested document template: '+request.slice(0,2000)})});
   uNotice=`Document template #${r.ticket_id} pending Admin approval. Advisor ${advice.provider}; not issued.`;
   render();return;
  }
  if(action==='revise-document'){
   const def=await api('/api/universal/documents/'+encodeURIComponent(b.dataset.key)+'/definition');
   const revised={...def.definition};delete revised.version;
   const raw=await askText('Edit the current approved metadata (new version requires Admin ticket).',JSON.stringify(revised,null,2));
   if(!raw)return;
   const result=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({
       kind:'metadata_document_revision',data:{template_key:def.key,expected_version:def.version,definition:JSON.parse(raw)},
       evidence:'Human-reviewed document definition revision requested'})});
   uNotice=`Template revision proposed in ticket #${result.ticket_id}. No current documents changed.`;render();return;
  }
  if(action==='history-document'){
   const sel=document.getElementById('uDocProject');const pid=Number(sel?.value||0);
   if(!pid)throw new Error('Select a project first');
   const report=await api('/api/universal/documents/issued-history?project_id='+pid+'&template_key='+encodeURIComponent(b.dataset.key));
   uDocHistory=report.history;uNotice=`${uDocHistory.length} immutable document event(s) found.`;render();return;
  }
  if(action==='issue-document'){
   const pid=Number(document.getElementById('uDocProject')?.value||0);
   if(!pid)throw new Error('Select a project first');
   const path='/api/universal/documents/'+encodeURIComponent(b.dataset.key);
   const reviewed=await api(path+'/issue-preview?project_id='+pid);
   if(!await askConfirm('Issue EXACT reviewed snapshot of '+reviewed.snapshot.rows.length+' records? This creates a pending Admin ticket; no accounting entry.'))return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_document_issue',
       data:{template_key:b.dataset.key,project_id:pid,expected_revision:reviewed.expected_revision,
             source_digest:reviewed.source_digest},
       evidence:'Human reviewed PDF draft, source record links and calculations before proposing issuance'})});
   uNotice=`Issuance proposed in ticket #${r.ticket_id}. Only after Admin review will it become an issued, frozen document.`;render();return;
  }
  if(action==='withdraw-document'){
   const pid=Number(document.getElementById('uDocProject')?.value||0);
   if(!pid)throw new Error('Select a project first');
   const reason=await askText('Explain why this issued document must be withdrawn (historical PDF remains preserved).');
   if(!reason)return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_document_withdraw',
       data:{template_key:b.dataset.key,project_id:pid,expected_revision:Number(b.dataset.revision),reason},
       evidence:'Owner requested withdrawal with audit-preserved historical copy'})});
   uNotice=`Withdrawal ticket #${r.ticket_id} awaits Admin approval.`;render();return;
  }
  if(action==='preview-document'||action==='download-document'||action==='view-document-html'){
   const selected=document.getElementById('uDocProject');
   const project=selected?Number(selected.value):0;
   if(!Number.isSafeInteger(project)||project<=0)throw new Error('Select a project for the draft document');
   const path='/api/universal/documents/'+encodeURIComponent(b.dataset.key);
   if(action==='download-document'||action==='view-document-html'){
     window.open(path+(action==='download-document'?'/preview.pdf':'/preview.html')+'?project_id='+project,'_blank','noopener');return;
   }
   uDocProjectId=project;uDocHistory=[];uDocPreview=await api(path+'/preview?project_id='+project);
   uNotice=`Unapproved draft with ${uDocPreview.rows.length} approved business records; review before issuing`;
   render();return;
  }
  if(action==='load-views'){uViews=await api('/api/universal/saved-views');render();return;}
  if(action==='load-notices'){const x=await api('/api/universal/workflow-notices');uNotifications=x.notices;render();return;}
  if(action==='run-view'){const x=await api('/api/universal/saved-views/'+encodeURIComponent(b.dataset.key)+'/records');uNotice=`Saved view ${x.title}: ${x.total} visible records`;uRecords=x.records;render();return;}
  if(action==='new-view'){
   if(!uSelected)throw new Error('Select an approved type first');
   const example={key:'upcoming_review',type_key:uSelected.key,title:'Upcoming reviews',filters:[],columns:uSelected.ui_form.fields.slice(0,3).map(f=>f.key)};
   const raw=await askText('Define an approved saved view: allowed metadata fields, structured filters and columns only.',JSON.stringify(example));
   if(!raw)return;
   const t=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_view',data:JSON.parse(raw),evidence:'User requests bounded saved view on '+uSelected.key})});
   uNotice=`View ticket #${t.ticket_id} is awaiting Admin approval`;render();return;
  }
  if(action==='new-workflow'){
   if(!uSelected)throw new Error('Select an approved type first');
   const example={key:'review_new_record',type_key:uSelected.key,event:'record_created',condition:null,message:'Review this new record',action:'notify'};
   const raw=await askText('Approved declarative workflow; only notify action is permitted.',JSON.stringify(example));
   if(!raw)return;
   const t=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_workflow',data:JSON.parse(raw),evidence:'User requests an internal review notification on '+uSelected.key})});
   uNotice=`Notification workflow ticket #${t.ticket_id} awaits Admin approval`;render();return;
  }
  if(action==='load-types'){uTypes=await api('/api/universal/types');uRelations=await api('/api/universal/relationship-types');uNotice=`${uTypes.length} active or retired definitions`;render();return;}
  if(action==='type'){uSelected=await api('/api/universal/types/'+encodeURIComponent(b.dataset.key));uRecords=[];await uLoadRecords();return;}
  if(action==='load-records'){await uLoadRecords();return;}
  if(action==='filter'){
   const name=document.getElementById('uFilterField').value;
   const val=document.getElementById('uFilterValue').value;
   const op=document.getElementById('uFilterOp').value;
   await uLoadRecords(name?new URLSearchParams({filter_field:name,filter_op:op,filter_value:val}).toString():'');return;
  }
  if(action==='dashboard'){
   const r=await api('/api/universal/dashboard/'+encodeURIComponent(uSelected.key));uNotice=`${uSelected.title}: ${r.value} approved records (accessible to you)`;render();return;
  }
  if(action==='extend-type'){
   const raw=await askText('Add optional fields as a JSON array, e.g. [{"name":"asset_tag","type":"text","required":false}]');
   if(!raw)return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_type_extend',
      data:{type_key:uSelected.key,fields:JSON.parse(raw)},evidence:'Owner requested an additive optional-field extension to '+uSelected.key})});
   uNotice=`Extension ticket #${r.ticket_id} requires Admin approval`;render();return;
  }
  if(action==='edit-record'){
   const r=await api(`/api/universal/records/${encodeURIComponent(uSelected.key)}/${Number(b.dataset.id)}`);
   uEditing=r;render();
   const form=document.getElementById('uRecordForm');form.elements['u-project'].value=r.project_id||'';
   for(const f of uSelected.ui_form.fields){
    const input=form.elements['u-'+f.key];const v=r.values[f.key];if(!input||v===undefined)continue;
    input.value=f.primitive==='money'?v.amount:f.primitive==='quantity'?v.value:
       f.primitive==='boolean'?String(v):String(v);
    if(f.primitive==='quantity')form.elements['u-unit-'+f.key].value=v.unit;
   }
   uNotice=`Editing record #${r.id}. Changes still require an approval ticket.`;
   document.getElementById('uRecordForm').scrollIntoView({block:'center'});return;
  }
  if(action==='delete-record'){
   const r=await api(`/api/universal/records/${encodeURIComponent(uSelected.key)}/${Number(b.dataset.id)}`);
   if(!await askConfirm(`Propose soft-deleting record #${r.id}? Related records block deletion.`))return;
   const t=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_record_delete',
     data:{type_key:uSelected.key,record_id:r.id,expected_version:r.current_version},
     evidence:'User requests reversible soft-delete of metadata record '+r.id})});
   uNotice=`Soft deletion is pending approval in ticket #${t.ticket_id}`;render();return;
  }
  if(action==='link-record'){
   const available=uRelations.filter(q=>q.source_type===uSelected.key && q.status==='active');
   if(!available.length)throw new Error('No approved relations for this type');
   const names=available.map(q=>q.key+' → '+q.target_type).join(', ');
   const rel=await askText('Approved relation key ('+names+')',available[0].key);
   if(!rel)return;
   if(!available.some(q=>q.key===rel))throw new Error('Choose an approved relation key');
   const target=await askText('Existing target record / project / supplier numeric ID (verified by backend)');
   if(!target)return;
   if(!/^[1-9]\d*$/.test(target)||!Number.isSafeInteger(Number(target)))throw new Error('Valid target ID required');
   const result=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_edge',
      data:{relation_key:rel,source_id:Number(b.dataset.id),target_id:Number(target)},
      evidence:'Human requests an approved typed relation from existing record '+b.dataset.id})});
   uNotice=`Relation is pending Admin approval in ticket #${result.ticket_id}`;render();notify(uNotice);return;
  }
  if(action==='new-type'){
   const raw=await askText('Define a new type using JSON with key, title and fields. No executable code.\nExample: {"key":"equipment","title":"Equipment","fields":[{"name":"serial_number","type":"text","required":true}]}');
   if(!raw)return;
   const d=JSON.parse(raw);
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'metadata_type',data:d,evidence:'User proposed metadata type '+String(d.title||d.key||'').slice(0,100)})});
   uNotice=`Draft ticket #${r.ticket_id} created; Admin approval required before activation`;render();return;
  }
  if(action==='load-companies'){uFinance=await api('/api/finance-ledger/entities');render();return;}
  if(action==='integrity'){
   const id=Number(b.dataset.entity);if(!Number.isSafeInteger(id)||id<1)throw new Error('Select a legal entity');
   const r=await api('/api/finance-ledger/integrity/'+id);
   document.getElementById('uLedgerOutput').innerHTML=uAssuranceHtml(r);return;
  }
  if(action==='general-ledger'){
   const entity=Number(b.dataset.entity);
   if(!Number.isSafeInteger(entity)||entity<1)throw new Error('Select a legal entity');
   const selected=await askText('Enter the GL account ID (from finance setup), optionally followed by start and end dates YYYY-MM-DD separated by commas. Example: 3,2026-11-01,2026-11-30');
   if(!selected)return;
   const values=selected.split(',').map(x=>x.trim());
   if(values.length<1||values.length>3||!/^[1-9]\d*$/.test(values[0]))throw new Error('GL account ID must be a positive integer');
   if(values.slice(1).some(x=>x&&!/^\d{4}-\d{2}-\d{2}$/.test(x)))throw new Error('Date must be YYYY-MM-DD');
   const q=new URLSearchParams();if(values[1])q.set('start_date',values[1]);if(values[2])q.set('end_date',values[2]);
   const r=await api('/api/finance-ledger/general-ledger/'+entity+'/'+encodeURIComponent(values[0])+(q.toString()?'?'+q.toString():''));
   document.getElementById('uLedgerOutput').innerHTML=uGeneralLedgerHtml(r);return;
  }
  if(['trial','journals','advances','reversals','periods'].includes(action)){
   const r=await api('/api/finance-ledger/'+({'trial':'trial-balance/','journals':'journals/','advances':'advances/','reversals':'reversals/','periods':'closed-periods/'}[action])+encodeURIComponent(b.dataset.entity));
   const output=document.getElementById('uLedgerOutput');
   if(action==='trial')output.innerHTML=uTrialBalanceHtml(r);
   else if(action==='journals')output.innerHTML=uJournalRegisterHtml(r);
   else output.textContent=JSON.stringify(r,null,2);
   return;
  }
  if(action==='finance-enable-cash'){
   const response=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
    kind:'finance_enable_cash',data:{entity_id:Number(b.dataset.entity)},
    evidence:'Cash in Hand requested for this company in Books',
   })});
   notify('Cash in Hand ticket #'+response.ticket_id+' is ready for approval.');return;
  }
  if(action==='finance-pay-vendor'){await showVendorPayment(Number(b.dataset.entity));return;}
  if(action==='finance-pay-advance'){await showSupplierAdvance(Number(b.dataset.entity));return;}
  if(action==='finance-site-company'){showSiteCompanyForm(Number(b.dataset.entity));return;}
  if(action==='finance-petty-cash-setup'){showPettyCashSetup(Number(b.dataset.entity));return;}
  if(action==='finance-expense-categories'){await showExpenseCategorySetup(Number(b.dataset.entity));return;}
  if(action==='finance-reverse-petty-cash'){
   const journal=await askText('Enter the journal number for the petty cash top-up.');
   if(journal===null||!/^\d+$/.test(journal.trim()))return;
   const reason=await askText('Why are you reversing this top-up?');
   if(!reason?.trim())return;
   const response=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({
    kind:'finance_reverse_petty_cash_topup',data:{journal_id:Number(journal),reason:reason.trim()},
    evidence:'Cash return reviewed in Books',
   })});
   notify('Reversal ticket #'+response.ticket_id+' is ready for approval.');return;
  }
  if(['finance-enable-inventory','finance-grn','finance-inventory-bill','finance-issue','finance-statement','finance-reconcile'].includes(action)){
   const names={'finance-enable-inventory':'finance_enable_inventory','finance-grn':'finance_goods_receipt',
     'finance-inventory-bill':'finance_inventory_bill','finance-issue':'finance_material_issue',
     'finance-statement':'finance_bank_statement_line','finance-reconcile':'finance_reconcile_bank'};
   const examples={
     'finance-enable-inventory':{entity_id:1,inventory_code:'1400',grni_code:'2200'},
     'finance-grn':{po_id:1,quantity:100,unit_cost_paise:35000,receipt_reference:'FICTIONAL-GRN-001',idempotency_key:'fictional-grn-001'},   // gitleaks:allow (fictional sample key)
     'finance-inventory-bill':{po_id:1,invoice_number:'FICTIONAL-GRNI-BILL-001',amount_paise:3500000,
       bill_date:'',due_date:'',payment_terms_days:0},
     'finance-issue':{po_id:1,quantity:40,issue_reference:'FICTIONAL-ISSUE-001',idempotency_key:'fictional-issue-001'},
     'finance-statement':{bank_id:1,booking_date:'2026-11-14',statement_reference:'FICTIONAL-STATEMENT-001',signed_amount_paise:-3500000,evidence_document_id:1},
     'finance-reconcile':{statement_line_id:1,journal_id:1}
   };
   const prompt = action === 'finance-inventory-bill'
     ? 'Enter the invoice date and due date as YYYY-MM-DD. Payment terms are the number of days between those dates.'
     : 'Use existing verified IDs, independent bank_statement document evidence and exact integer paise. Approval required.';
   const raw=await askText(prompt,JSON.stringify(examples[action]));
   if(!raw)return;
   const r=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({kind:names[action],data:JSON.parse(raw),
     evidence:'Human requests deterministic '+names[action]+'; supporting documents and GL mapping require verification'})});
   uNotice=`Finance ticket #${r.ticket_id} awaits Admin approval; no bank transfer has occurred.`;
   const target=document.getElementById('uLedgerOutput');if(target)target.textContent=JSON.stringify(r.accounting_preview,null,2);
   notify(uNotice);return;
  }
  if(['finance-enable-advances','finance-allocate-advance','finance-reverse-payment','finance-reverse-bill','finance-close-period'].includes(action)){
   const names={'finance-enable-advances':'finance_enable_advances',
     'finance-allocate-advance':'finance_allocate_advance','finance-reverse-payment':'finance_reverse_payment',
     'finance-reverse-bill':'finance_reverse_bill','finance-close-period':'finance_close_period'};
   const examples={
    'finance-enable-advances':{entity_id:1,advance_code:'1300'},
    'finance-allocate-advance':{advance_id:1,bill_id:1,amount_paise:1000000,idempotency_key:'fictional-allocation-001'},
    'finance-reverse-payment':{payment_id:1,reason:'Correct an erroneous posted entry'},
    'finance-reverse-bill':{bill_id:1,reason:'Correct an erroneous supplier bill'},
    'finance-close-period':{entity_id:1,year_month:'2026-11',reason:'Accounting period closure verified'}
   };
   const prompt=action==='finance-reverse-payment'
    ? 'Enter the payment ID and reason. For cash, use cash_payment_id in place of payment_id.'
    : action==='finance-allocate-advance'
     ? 'Enter the advance ID, bill ID and amount in whole paise. For a cash advance, use cash_advance_id in place of advance_id.'
     : 'Use verified IDs and exact integer paise. A separate Admin ticket is mandatory.';
   const raw=await askText(prompt,JSON.stringify(examples[action]));
   if(!raw)return;
   const response=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({kind:names[action],data:JSON.parse(raw),
     evidence:'Human requests reviewed '+names[action]+'; source evidence and accounting mapping must be verified'})});
   uNotice=`Financial proposal #${response.ticket_id} awaits Admin approval`;
   const target=document.getElementById('uLedgerOutput');if(target)target.textContent=JSON.stringify(response.accounting_preview,null,2);
   notify(uNotice);return;
  }
  if(['finance-po','finance-bill'].includes(action)){
   const kinds={'finance-po':'finance_po','finance-bill':'finance_bill'};
   const examples={
      'finance-po':{entity_id:1,supplier_id:1,project_id:1,po_number:'FICTIONAL-PO-001',amount_paise:5000000},
      'finance-bill':{po_id:1,invoice_number:'FICTIONAL-BILL-001',amount_paise:5000000,
          bill_date:'',due_date:'',payment_terms_days:0}
   };
   const dateHelp = {
     'finance-bill': ' Enter the invoice and due dates as YYYY-MM-DD. Payment terms are the number of days between them.',
   };
   const raw=await askText('Use verified record numbers and amounts in whole paise.' + (dateHelp[action] || ''),JSON.stringify(examples[action]));
   if(!raw)return;
   const d=JSON.parse(raw);
   const response=await api('/api/finance-ledger/proposals',{method:'POST',body:JSON.stringify({kind:kinds[action],
      data:d,evidence:'Human requests review of '+kinds[action]+'; supporting source references must be verified'})});
   uNotice=`Financial proposal #${response.ticket_id} created. Review journal preview and approve separately.`;
   document.getElementById('uLedgerOutput').textContent=JSON.stringify(response.accounting_preview,null,2);
   notify(uNotice);return;
  }
  if(action==='setup-finance'){
   const raw=await askText('Enter an explicit fictional finance setup as JSON: {"entity_name":"Fictional Constructions","expense_code":"5000","ap_code":"2100","bank_code":"1000","bank_name":"ICICI Current (Demo)","bank_masked":"****1234"}');
   if(!raw)return;
   const r=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify({kind:'finance_setup',data:JSON.parse(raw),evidence:'Owner requests an approved deterministic INR finance setup'})});
   uNotice=`Finance setup ticket #${r.ticket_id} submitted for Admin review`;notify(uNotice);return;
  }
 }catch(err){uNotice=err.message;notify(err.message,true);}
});
document.addEventListener('submit',async e=>{
 if(e.target.id!=='uRecordForm')return;e.preventDefault();
 if(!uSelected)return;
 const form=new FormData(e.target),values={};
 try{
  for(const f of uSelected.ui_form.fields){
   const raw=String(form.get('u-'+f.key)??'').trim();
   if(!raw){if(f.required)throw new Error(`${f.label} is required`);continue;}
   if(f.primitive==='integer'){if(!/^-?\d+$/.test(raw))throw new Error('Whole number required');values[f.key]=Number(raw);if(!Number.isSafeInteger(values[f.key]))throw new Error('Integer is out of range');}
   else if(f.primitive==='boolean')values[f.key]=raw==='true';
   else if(f.primitive==='money')values[f.key]={amount:raw,currency:'INR'};
   else if(f.primitive==='quantity')values[f.key]={value:raw,unit:form.get('u-unit-'+f.key)};
   else if(f.primitive==='datetime')values[f.key]=new Date(raw).toISOString();
   else values[f.key]=raw;
  }
  const project=form.get('u-project');
  const kind=uEditing?'metadata_record_update':'metadata_record';
  const data={type_key:uSelected.key,project_id:project?Number(project):null,values};
  if(uEditing){data.record_id=uEditing.id;data.expected_version=uEditing.current_version;}
  const proposal={kind,data,evidence:'Human submitted typed record to existing approved business type '+uSelected.key};
  const result=await api('/api/universal/proposals',{method:'POST',body:JSON.stringify(proposal)});
  uEditing=null;uNotice=`Record is NOT saved yet. Review approval ticket #${result.ticket_id}`;render();notify(uNotice);
 }catch(err){notify(err.message,true);}
});

// Preserve selected project while document preview/history causes a UI re-render.
document.addEventListener('change',e=>{if(e.target?.id==='uDocProject')uDocProjectId=Number(e.target.value)||0;});
