'use strict';
/* StudioOS Books home and Party page (App Flows map). Books home (owner and accounts): what is owed to suppliers, how old it is, bank
   balances, closed months and payments not yet matched to the bank. The Party page: one vendor or client, with amounts shown only to
   roles that may see them. Read-only; every change is still a ticket. No inline styles (strict CSP). Loaded after app.js. */

Object.assign(state, {bk: {home: null, party: null, partyId: null, activePanel: null, billOpts: null, billPrefillVendor: null, dueData: null, dueCompanyId: null, dueFilterVendor: null, journalOpts: null}});

const bkRs = p => inr(Number(p || 0) / 100);
const BK_AGE = {current: '0 to 30 days', days_31_60: '31 to 60 days', days_61_90: '61 to 90 days', over_90: 'Over 90 days'};

function bkLoadHome() { return api('/api/books/home'); }
function bkLoadParty(id) { return api(`/api/books/parties/${Number(id)}`); }

async function bkLoad(view, partyId = null) {
  const book = state.bk;
  if (book.loading?.view === view && book.loading.partyId === partyId) return;
  const request = {view, partyId};
  book.loading = request;
  const current = () => state.bk === book && book.loading === request && state.view === view &&
    (view === 'books' || book.partyId === partyId);
  let result;
  try {
    result = await (view === 'books' ? bkLoadHome() : bkLoadParty(partyId));
  } catch (error) {
    if (!current()) return;
    book.loading = null;
    notify(error.message, true);
    if (view === 'party') {
      book.partyId = null;
      book.party = null;
      switchView('books');
      return;
    }
    book.home = {companies: [], note: ''};
    render();
    return;
  }
  if (!current()) return;
  book.loading = null;
  if (view === 'books') book.home = result;
  else book.party = result;
  render();
}

function bkAgeing(a) {
  return `<div class="v-tiles">${Object.keys(BK_AGE).map(k => `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(a[k]))}</div><div class="v-tile-label">${esc(BK_AGE[k])}</div></div>`).join('')}</div>`;
}

function bkCompanyProjects(projects, label = 'Projects') {
  if (!projects?.length) return '';
  const rows = projects.map(p => '<tr><td><button type="button" class="cx-link" data-project-open="'+Number(p.id)+'">'+esc(p.name)+
    '</button></td><td class="num">'+esc(bkRs(p.budget_paise))+'</td><td class="num">'+esc(bkRs(p.cost_to_date_paise))+'</td></tr>').join('');
  return '<h3 class="w-sub">'+esc(label)+'</h3><div class="w-table-wrap"><table class="w-table">'+
    '<thead><tr><th scope="col">Project</th><th scope="col">Budget</th><th scope="col">Cost to date</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}
function bkHomeView() {
  if (!['admin', 'accounts'].includes(state.user?.role)) return head('Books', 'Books are for the owner and accounts.');
  if (!state.bk.home) {
    bkLoad('books');
    return head('Books', 'What is owed, what is in the bank.') + '<div class="loading">Loading…</div>';
  }
  const h = state.bk.home;
  const cards = h.companies.map(c => {
    const banks = c.banks.map(b => `<tr><td>${esc(b.name)} <span class="muted">${esc(b.masked)}</span></td><td class="num">${esc(bkRs(b.balance_paise))}</td></tr>`).join('');
    const owed = c.owed_by_supplier.map(s => `<tr><td><button type="button" class="cx-link" data-bk="party" data-id="${Number(s.party_id)}">${esc(s.name || 'Supplier ' + s.party_id)}</button></td><td class="num">${esc(bkRs(s.owed_paise))}</td></tr>`).join('');
    return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(c.name)}</div><div class="panel-sub">${Number(c.open_bills)} unpaid bill${c.open_bills === 1 ? '' : 's'} · ${esc(bkRs(c.payable_paise))} owed to suppliers</div></div></div><div class="panel-body">` +
      `<p>Posted expenses <strong>${esc(bkRs(c.posted_expense_paise))}</strong></p>` + bkCompanyProjects(c.projects) +
      `<div class="w-sub">How old the unpaid balances are</div>${bkAgeing(c.ageing)}` +
      `<div class="w-sub">Bank accounts</div>${banks ? `<div class="w-table-wrap"><table class="w-table"><tbody>${banks}</tbody></table></div>` : '<p class="muted">No bank account registered.</p>'}` +
      `<div class="w-sub">Owed, by supplier</div>${owed ? `<div class="w-table-wrap"><table class="w-table"><tbody>${owed}</tbody></table></div>` : '<p class="muted">Nothing owed.</p>'}` +
      `<p class="muted">${Number(c.unmatched_payments.count)} supplier payment${c.unmatched_payments.count === 1 ? '' : 's'} (${esc(bkRs(c.unmatched_payments.paise))}) not yet matched to the bank statement.</p>` +
      `<p class="muted">Closed months: ${c.closed_months.length ? esc(c.closed_months.join(', ')) : 'none yet'}</p></div></section>`;
  }).join('');
  const quickSwitch = `<div class="sense-books-bar" role="navigation" aria-label="Accounts quick switch">` +
    `<button type="button" class="sense-filter-pill active" data-view="books">Overview</button>` +
    `<button type="button" class="sense-filter-pill" data-sense-new="contacts">Contacts (Vendors &amp; Clients)</button>` +
    `<button type="button" class="sense-filter-pill" data-view="sales">Sales &amp; Invoices</button>` +
    `<button type="button" class="sense-filter-pill" data-view="receipts">Receipts &amp; Retainers</button>` +
    `<button type="button" class="sense-filter-pill" data-view="reports">Reports (P&amp;L · GST · TDS)</button>` +
    `<button type="button" class="sense-filter-pill" data-view="chart">Chart of Accounts</button>` +
    `<button type="button" class="sense-filter-pill" data-view="ledger">Banking &amp; Ledger</button>` +
    `<button type="button" class="sense-filter-pill" data-view="bankfeed">Bank feed &amp; controls</button>` +
    `</div>`;
  const off = cards ? '' : ' disabled aria-disabled="true"';   // nothing to act on until a company is set up
  const ap = state.bk.activePanel;
  const addBillBtn = quickSwitch + `<div class="section-gap"><button type="button" class="btn btn-accent" data-sense-new="bill"${off}>+ Supplier bill</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="vendor"${off}>+ New vendor</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="client"${off}>+ New client</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="account"${off}>+ New account</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="due"${off}>Bills due &amp; Pay</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="transfer"${off}>Move money</button> ` +
    `<button type="button" class="btn btn-secondary" data-sense-new="journal"${off}>Manual journal</button></div>` +
    (ap === 'vendor' ? bkVendorFormHtml() : ap === 'bill' ? bkBillFormHtml() : ap === 'due' ? bkBillsDueHtml() : ap === 'transfer' ? bkTransferFormHtml() : ap === 'journal' ? bkManualJournalFormHtml() : '');
  return head('Books', 'What is owed, what is in the bank, and which months are closed.') + addBillBtn + (cards || empty('₹', 'Set up your company first', 'Set up a company and chart of accounts from the Accounting ledger.') + '<div class="section-gap"><button type="button" class="btn btn-primary" data-view="ledger">Open Accounting ledger</button></div>') + bkCompanyProjects(h.projects_without_company, 'Projects waiting for a company') + `<p class="muted">${esc(h.note)}</p>`;
}

function bkDueGroupHtml(title, rows) {
  if (!rows.length) return '';
  const trs = rows.map(r => {
    const late = r.days_late > 0 ? ' ' + pill(`${Number(r.days_late)} days late`, 'critical') : '';
    const due = r.due_date ? `due ${esc(r.due_date)}` : 'no due date';
    const available = Number(r.available_payment_paise ?? r.owed_paise);
    const pending = r.pending_payment_paise ? `<div class="muted">${esc(bkRs(r.pending_payment_paise))} awaiting approval</div>` : '';
    const disabled = available > 0 ? '' : ' disabled';
    const label = `${r.supplier_name || 'Vendor'} ${r.invoice_number}`;
    return `<tr><td><input type="checkbox" name="due_pick" value="${esc(r.kind + ':' + r.bill_id)}" data-entity="${Number(r.entity_id)}" data-owed="${available}" data-available="${available}" aria-label="Select ${esc(label)}"${disabled}></td>` +
      `<td><strong>${esc(r.supplier_name || 'Vendor')}</strong> · ${esc(r.invoice_number)}<div class="muted">${due}${late}</div>${approvalFiles(r)}</td>` +
      `<td class="num">${esc(bkRs(r.owed_paise))}${pending}</td>` +
      `<td><input type="text" class="form-input" name="due_amt_${esc(r.kind + '_' + r.bill_id)}" inputmode="decimal" value="${esc((available / 100).toFixed(2))}" aria-label="Amount to pay in rupees for ${esc(label)}"${disabled}></td></tr>`;
  }).join('');
  return `<div class="w-sub">${esc(title)}</div><div class="w-table-wrap"><table class="w-table"><thead><tr><th></th><th>Bill</th><th>Owed</th><th>Pay now (₹)</th></tr></thead><tbody>${trs}</tbody></table></div>`;
}

function bkUpdateDueSummary(form) {
  if (!form) return;
  const boxes = Array.from(form.querySelectorAll('input[name="due_pick"]'));
  const picked = boxes.filter(cb => cb.checked);
  let total = 0;
  picked.forEach(cb => {
    const [kind, id] = cb.value.split(':');
    const inp = form.querySelector(`[name="due_amt_${kind}_${id}"]`);
    total += bkParsePaise(inp ? inp.value : 0);
  });
  const out = document.getElementById('bkDueSummary');
  if (out) out.textContent = `${picked.length} bill${picked.length === 1 ? '' : 's'} selected · Total ${bkRs(total)}`;
  const allCb = document.getElementById('bkDueSelectAll');
  if (allCb) {
    allCb.checked = boxes.length > 0 && picked.length === boxes.length;
    allCb.indeterminate = picked.length > 0 && picked.length < boxes.length;
  }
}

function bkBillsDueHtml() {
  const d = state.bk.dueData;
  if (!d) return '<section class="panel section-gap"><div class="panel-body"><div class="loading">Loading bills due…</div></div></section>';
  const rawAll = [...(d.overdue || []), ...(d.due_this_week || []), ...(d.due_later || [])];
  if (!rawAll.length) return '<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Bills due</div></div><div class="panel-body"><p class="muted">No unpaid bills right now.</p></div></section>';
  const vendorFilter = state.bk.dueFilterVendor;
  const vendorFiltered = vendorFilter ? rawAll.filter(r => Number(r.supplier_id) === Number(vendorFilter.id) || String(r.supplier_name || '').toLowerCase() === String(vendorFilter.name || '').toLowerCase()) : rawAll;
  const companyIds = [...new Set((vendorFiltered.length ? vendorFiltered : rawAll).map(r => Number(r.entity_id)))];
  if (!companyIds.includes(Number(state.bk.dueCompanyId))) state.bk.dueCompanyId = companyIds[0];
  const entId = Number(state.bk.dueCompanyId);
  const compName = id => (state.bk.home?.companies || []).find(c => Number(c.id) === Number(id))?.name || `Company #${id}`;
  const filterRow = r => Number(r.entity_id) === entId && (!vendorFilter || Number(r.supplier_id) === Number(vendorFilter.id) || String(r.supplier_name || '').toLowerCase() === String(vendorFilter.name || '').toLowerCase());
  const overdue = (d.overdue || []).filter(filterRow);
  const week = (d.due_this_week || []).filter(filterRow);
  const later = (d.due_later || []).filter(filterRow);
  const shownCount = overdue.length + week.length + later.length;
  const accounts = (d.paying_accounts && d.paying_accounts[String(entId)]) || [];
  const accOpts = accounts.map(a => `<option value="${Number(a.id)}">${esc(a.name)}</option>`).join('');
  const companyPicker = companyIds.length > 1
    ? `<label class="g-field"><span>Company</span><select id="bkDueCompany" class="form-input">${companyIds.map(id => `<option value="${id}"${id === entId ? ' selected' : ''}>${esc(compName(id))}</option>`).join('')}</select></label>`
    : '';
  const vendorBanner = vendorFilter
    ? `<div class="row-actions section-gap"><span class="muted">Showing bills for <strong>${esc(vendorFilter.name)}</strong></span> <button type="button" class="btn btn-secondary btn-sm" data-bk="due-clear-vendor">Show all vendors</button></div>`
    : '';
  if (!shownCount) {
    return `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Bills due</div></div><div class="panel-body">${vendorBanner}<p class="muted">No unpaid bills match this filter.</p></div></section>`;
  }
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Bills due</div><div class="panel-sub">Tick the bills to pay together. Each payment becomes an item on one approval request.</div></div></div><div class="panel-body">` +
    vendorBanner +
    `<form id="bkPaySelectedForm" data-entity="${Number(entId)}" data-request-key="${esc(formRequestKey())}">` +
    (companyPicker ? `<div class="g-form section-gap">${companyPicker}</div>` : '') +
    `<div class="row-actions section-gap"><label class="checkbox-row"><input type="checkbox" id="bkDueSelectAll"> <span>Select all (${shownCount})</span></label> ` +
    `<span class="muted" id="bkDueSummary" aria-live="polite">0 bills selected · Total ₹0.00</span></div>` +
    bkDueGroupHtml('Overdue', overdue) + bkDueGroupHtml('Due this week', week) + bkDueGroupHtml('Due later', later) +
    `<div class="g-form section-gap"><label class="g-field"><span>Pay from</span><select name="paid_through_id" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Payment date</span><input type="date" name="payment_date" class="form-input" required value="${esc(d.today || '')}"></label>` +
    `<label class="g-field"><span>Reference (UTR or cheque no.)</span><input name="payment_reference" class="form-input" maxlength="120" required placeholder="UTR / cheque ref"></label></div>` +
    `<div class="section-gap"><button type="submit" class="btn btn-primary">Pay selected</button></div></form></div></section>`;
}

function bkAddDays(iso, days) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
  const d = new Date(iso + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + Math.max(0, Number(days) || 0));
  return d.toISOString().slice(0, 10);
}

function bkVendorFormHtml() {
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New vendor</div><div class="panel-sub">Zoho-style vendor profile with GST treatment, PAN, TDS section, and bank details. Opens an approval ticket.</div></div></div><div class="panel-body">` +
    `<form id="bkVendorForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Vendor name *</span><input name="name" class="form-input" required maxlength="200" placeholder="e.g. Sri Ram Traders"></label>` +
    `<label class="g-field"><span>GST treatment *</span><select name="gst_treatment" class="form-input" required><option value="unregistered">Unregistered Business</option><option value="registered_regular">Registered — Regular</option><option value="registered_composition">Registered — Composition</option><option value="overseas">Overseas</option></select></label>` +
    `<label class="g-field"><span>GSTIN (mandatory if registered)</span><input name="gstin" class="form-input" maxlength="15" placeholder="29ABCDE1234F1Z5"></label>` +
    `<label class="g-field"><span>PAN</span><input name="pan" class="form-input" maxlength="10" placeholder="ABCDE1234F"></label>` +
    `<label class="g-field"><span>State code (2-digit)</span><input name="state_code" class="form-input" maxlength="2" placeholder="29"></label>` +
    `<label class="g-field"><span>Phone (10 digits)</span><input name="phone" class="form-input" maxlength="10" placeholder="9876543210"></label>` +
    `<label class="g-field"><span>Email</span><input name="email" type="email" class="form-input" maxlength="120" placeholder="accounts@vendor.example"></label>` +
    `<label class="g-field"><span>Trade / category</span><input name="trade" class="form-input" maxlength="120" placeholder="Tiles, Carpentry, Electrical"></label>` +
    `<label class="g-field"><span>Payment terms (days)</span><input name="payment_terms_days" type="number" class="form-input" min="0" max="365" value="30"></label>` +
    `<label class="g-field"><span>Default TDS section</span><select name="default_tds_section" class="form-input"><option value="">None</option><option value="194C">194C (Contractor)</option><option value="194J">194J (Professional)</option><option value="194J_TECH">194J Technical (2%)</option><option value="194I">194I (Rent)</option><option value="194H">194H (Commission)</option></select></label>` +
    `<label class="g-field"><span>Billing address</span><input name="billing_address" class="form-input" maxlength="300" placeholder="Street, City, State"></label>` +
    `<label class="g-field"><span>Bank IFSC</span><input name="bank_ifsc" class="form-input" maxlength="11" placeholder="HDFC0001234"></label>` +
    `<label class="g-field"><span>Bank account (masked)</span><input name="bank_masked_number" class="form-input" maxlength="40" placeholder="XXXX1234"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send vendor for approval</button></div></form></div></section>`;
}

function bkBillLineRow(opts, entityId, projectLinked = false) {
  const accs = (opts.accounts || []).filter(a => Number(a.entity_id) === Number(entityId));
  const accOpts = accs.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' · ' + a.name)}</option>`).join('');
  const available = (opts.projects || []).filter(p => p.company_id && (!projectLinked || p.company_id === entityId));
  const projOpts = '<option value="">Office / no project</option>' + available.map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
  return `<div class="g-form bk-bill-line"><label class="g-field"><span>Account (Expense/COGS/Asset)</span><select name="line_account" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="line_project" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>Description</span><input name="line_desc" class="form-input" maxlength="250" placeholder="What was supplied"></label>` +
    `<label class="g-field"><span>Taxable (₹)</span><input name="line_amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>GST %</span><select name="line_gst" class="form-input"><option value="0">0%</option><option value="500">5%</option><option value="1200">12%</option><option value="1800">18%</option><option value="2800">28%</option></select></label>` +
    `<div class="g-field"><span>&nbsp;</span><button type="button" class="btn btn-secondary btn-sm" data-bk="rm-line">Remove</button></div></div>`;
}

function bkBillFormHtml() {
  const opts = state.bk.billOpts;
  if (!opts) return '<section class="panel section-gap"><div class="panel-body"><div class="loading">Loading bill form…</div></div></section>';
  if (!opts.companies.length) return '<section class="panel section-gap"><div class="panel-body"><p class="muted">Set up a company first before entering a bill.</p></div></section>';
  const entId = opts.companies[0].id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const prefillVendor = state.bk.billPrefillVendor ? Number(state.bk.billPrefillVendor) : null;
  const vendOpts = '<option value="">Choose a vendor</option>' + opts.vendors.map(v => `<option value="${Number(v.id)}"${prefillVendor === Number(v.id) ? ' selected' : ''}>${esc(v.name)}</option>`).join('');
  const poOpts = '<option value="">None (direct bill)</option>' + (opts.purchase_orders || []).map(p => `<option value="${Number(p.id)}">${esc(p.po_number)} (rem ${esc(bkRs(p.remaining_paise))})</option>`).join('');
  const docOpts = '<option value="">No file attached</option>' + opts.documents.map(d => `<option value="${Number(d.id)}">${esc(d.name)}</option>`).join('');
  const today = opts.today || '';
  const due = bkAddDays(today, 30);
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New supplier bill</div><div class="panel-sub">Supports GST, TDS, Asset/COGS accounts, and partial PO billing. Sends a draft for approval.</div></div></div><div class="panel-body">` +
    `<form id="bkBillForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company *</span><select name="entity_id" class="form-input" required>${compOpts}</select><small class="muted" data-bk-company-source hidden>From the project</small></label>` +
    `<label class="g-field"><span>Vendor *</span><select name="supplier_id" class="form-input" required>${vendOpts}</select></label>` +
    `<label class="g-field"><span>Purchase order (optional)</span><select name="po_id" class="form-input">${poOpts}</select></label>` +
    `<label class="g-field"><span>Invoice number *</span><input name="invoice_number" class="form-input" maxlength="120" required placeholder="INV-2026-001"></label>` +
    `<label class="g-field"><span>Bill date *</span><input type="date" name="bill_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Payment terms (days) *</span><input type="number" name="payment_terms_days" class="form-input" min="0" max="365" required value="30"></label>` +
    `<label class="g-field"><span>Due date *</span><input type="date" name="due_date" class="form-input" required value="${esc(due)}"></label>` +
    `<label class="g-field"><span>Supply type</span><select name="supply_type" class="form-input"><option value="intra">Intra-state (CGST + SGST)</option><option value="inter">Inter-state (IGST)</option></select></label>` +
    `<label class="g-field"><span>TDS section (optional)</span><select name="tds_section" class="form-input"><option value="">None</option><option value="194C">194C (Contractor)</option><option value="194J">194J (Professional)</option><option value="194I">194I (Rent)</option></select></label>` +
    `<label class="g-field"><span>TDS deducted (₹)</span><input name="tds_amount" class="form-input" inputmode="decimal" value="0.00"></label>` +
    `<label class="g-field"><span>Attachment (optional)</span><select name="attachment_id" class="form-input">${docOpts}</select></label>` +
    `<label class="g-field"><span>Note (optional)</span><input name="note" class="form-input" maxlength="500" placeholder="Reference or delivery note"></label>` +
    `</div><div class="field files-field"><label for="bkBillFiles">Photos or PDF of the bill (optional)</label><input type="file" class="form-input" id="bkBillFiles" data-upload-files accept="image/jpeg,image/png,application/pdf" multiple>` +
    `<div class="file-previews" aria-live="polite">${filePreviewsHtml()}</div><small class="muted">Up to 5 photos (JPG or PNG) or PDFs, 8 MB each.</small></div>` +
    `<div class="w-sub">Bill lines</div><div id="bkBillLines">${bkBillLineRow(opts, entId)}</div>` +
    `<div class="section-gap"><button type="button" class="btn btn-secondary btn-sm" data-bk="add-line">+ Add line</button> ` +
    `<span class="muted" id="bkBillTotal" aria-live="polite">Net payable: ₹0.00</span></div>` +
    `<div class="section-gap"><button type="submit" class="btn btn-primary">Send for approval</button></div></form></div></section>`;
}

function bkSyncBillCompany(form, options) {
  const selectors = Array.from(form.querySelectorAll('[name="line_project"]'));
  const project = selectors.map(field => options.projects.find(row => Number(row.id) === Number(field.value))).find(Boolean);
  if (project) form.entity_id.value = String(project.company_id);
  const entityId = Number(form.entity_id.value);
  form.entity_id.disabled = Boolean(project);
  form.querySelector('[data-bk-company-source]').hidden = !project;
  const projects = options.projects.filter(row => row.company_id && (!project || row.company_id === entityId));
  const accounts = options.accounts.filter(row => row.entity_id === entityId);
  for (const field of selectors) {
    const selected = field.value;
    field.innerHTML = '<option value="">Office / no project</option>'+projects.map(row=>'<option value="'+Number(row.id)+'">'+esc(row.name)+'</option>').join('');
    if (projects.some(row => String(row.id) === selected)) field.value = selected;
  }
  for (const field of form.querySelectorAll('[name="line_account"]')) {
    const selected = field.value;
    field.innerHTML = '<option value="">Choose an expense account</option>'+accounts.map(row=>'<option value="'+Number(row.id)+'">'+esc(row.code+' · '+row.name)+'</option>').join('');
    if (accounts.some(row => String(row.id) === selected)) field.value = selected;
  }
}
function bkParsePaise(raw) {
  const clean = String(raw || '').replace(/,/g, '').trim();
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return 0;
  const [rs, ps = ''] = clean.split('.');
  return Number(rs) * 100 + Number((ps + '00').slice(0, 2));
}

function bkUpdateBillTotal(form) {
  let taxable = 0, gst = 0;
  for (const row of form.querySelectorAll('.bk-bill-line')) {
    const amt = bkParsePaise(row.querySelector('[name="line_amount"]')?.value);
    const bps = Number(row.querySelector('[name="line_gst"]')?.value || 0);
    taxable += amt;
    gst += Math.floor((amt * bps + 5000) / 10000);
  }
  const tds = bkParsePaise(form.tds_amount?.value);
  const net = Math.max(0, taxable + gst - tds);
  const out = document.getElementById('bkBillTotal');
  if (out) out.textContent = `Taxable ${bkRs(taxable)} + GST ${bkRs(gst)} − TDS ${bkRs(tds)} = Net payable ${bkRs(net)}`;
}

function bkTransferFormHtml() {
  const opts = state.bk.journalOpts;
  if (!opts) return '<section class="panel section-gap"><div class="panel-body"><div class="loading">Loading accounts…</div></div></section>';
  const entId = opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const bankCash = (opts.accounts || []).filter(a => a.entity_id === entId && (a.kind === 'bank' || a.kind === 'cash'));
  const fromOpts = bankCash.map((a, i) => `<option value="${Number(a.id)}"${i === 0 ? ' selected' : ''}>${esc(a.code + ' ' + a.name)}</option>`).join('');
  const toOpts = bankCash.map((a, i) => `<option value="${Number(a.id)}"${i === (bankCash.length > 1 ? 1 : 0) ? ' selected' : ''}>${esc(a.code + ' ' + a.name)}</option>`).join('');
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Move money</div><div class="panel-sub">Transfer between two bank or cash accounts. Sends a draft for approval.</div></div></div><div class="panel-body">` +
    `<form id="bkTransferForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>From account</span><select name="from_account_id" class="form-input" required>${fromOpts}</select></label>` +
    `<label class="g-field"><span>To account</span><select name="to_account_id" class="form-input" required>${toOpts}</select></label>` +
    `<label class="g-field"><span>Amount (₹)</span><input name="amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>Date</span><input type="date" name="transfer_date" class="form-input" required value="${esc(opts.today || '')}"></label>` +
    `<label class="g-field"><span>Reference</span><input name="reference" class="form-input" maxlength="120" placeholder="UTR / slip no."></label>` +
    `<label class="g-field"><span>Note</span><input name="note" class="form-input" maxlength="400" placeholder="Optional note"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send for approval</button></div></form></div></section>`;
}

function bkJournalLineRow(opts, entId, side = 'debit', canRemove = false) {
  const accs = (opts.accounts || []).filter(a => Number(a.entity_id) === Number(entId));
  const accOpts = accs.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
  const projOpts = '<option value="">No project</option>' + (opts.projects || []).filter(p => p.company_id === entId).map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
  return `<div class="g-form bk-jr-line">` +
    `<label class="g-field"><span>Account</span><select name="jr_account" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Side</span><select name="jr_side" class="form-input"><option value="debit"${side === 'debit' ? ' selected' : ''}>Debit</option><option value="credit"${side === 'credit' ? ' selected' : ''}>Credit</option></select></label>` +
    `<label class="g-field"><span>Amount (₹)</span><input name="jr_amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="jr_project" class="form-input">${projOpts}</select></label>` +
    `<div class="g-field"><span>&nbsp;</span><button type="button" class="btn btn-secondary btn-sm" data-bk="rm-jr-line"${canRemove ? '' : ' disabled'}>Remove</button></div></div>`;
}

function bkUpdateJournalBalance(form) {
  if (!form) return;
  let dr = 0, cr = 0;
  form.querySelectorAll('.bk-jr-line').forEach(row => {
    const amt = bkParsePaise(row.querySelector('[name="jr_amount"]')?.value);
    if (row.querySelector('[name="jr_side"]')?.value === 'credit') cr += amt;
    else dr += amt;
  });
  const diff = Math.abs(dr - cr);
  const out = document.getElementById('bkJournalBalance');
  if (out) {
    const status = dr === cr && dr > 0 ? 'Balanced ✓' : diff > 0 ? `Difference: ${bkRs(diff)} (must match)` : 'Enter debit and credit amounts';
    out.textContent = `Debits: ${bkRs(dr)} · Credits: ${bkRs(cr)} · ${status}`;
  }
  const rows = form.querySelectorAll('.bk-jr-line');
  rows.forEach(row => {
    const rm = row.querySelector('[data-bk="rm-jr-line"]');
    if (rm) rm.disabled = rows.length <= 2;
  });
}

function bkManualJournalFormHtml() {
  const opts = state.bk.journalOpts;
  if (!opts) return '<section class="panel section-gap"><div class="panel-body"><div class="loading">Loading accounts…</div></div></section>';
  const entId = opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Manual journal</div><div class="panel-sub">Owner / accountant adjustment. Debits and credits must match.</div></div></div><div class="panel-body">` +
    `<form id="bkJournalForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Date</span><input type="date" name="entry_date" class="form-input" required value="${esc(opts.today || '')}"></label>` +
    `<label class="g-field"><span>Reference</span><input name="reference" class="form-input" maxlength="120" placeholder="JV-001"></label>` +
    `<label class="g-field"><span>Narration</span><input name="narration" class="form-input" maxlength="400" required placeholder="Reason for entry"></label>` +
    `</div><div id="bkJournalLines">${bkJournalLineRow(opts, entId, 'debit', false)}${bkJournalLineRow(opts, entId, 'credit', false)}</div>` +
    `<div class="muted section-gap" id="bkJournalBalance" aria-live="polite">Debits: ₹0.00 · Credits: ₹0.00 · Enter debit and credit amounts</div>` +
    `<div class="section-gap"><button type="button" class="btn btn-secondary btn-sm" data-bk="add-jr-line">+ Add line</button> ` +
    `<button type="submit" class="btn btn-primary">Send for approval</button></div></form></div></section>`;
}

function bkPartyView() {
  if (!state.bk.partyId) return head('Contact', 'Choose a contact.') + empty('☎', 'No contact chosen', 'Open one from Books or from search.');
  if (!state.bk.party || state.bk.party.party.id !== state.bk.partyId) {
    bkLoad('party', state.bk.partyId);
    return head('Contact', 'Loading…') + '<div class="loading">Loading…</div>';
  }
  const d = state.bk.party, p = d.party;
  const bills = (d.bills || []).map(b => {
    const invoiceDate = b.bill_date ? `Bill date ${esc(b.bill_date)}` : 'Date unknown';
    const terms = b.payment_terms_days === 0 ? 'Due on receipt' : `${Number(b.payment_terms_days)} days`;
    const due = b.due_date ? ` · Due ${esc(b.due_date)}${b.payment_terms_days == null ? '' : ` · ${terms}`}` : '';
    const pdf = b.id ? `<a class="btn btn-secondary btn-sm" href="/api/books/bills/${Number(b.id)}/pdf" target="_blank" rel="noopener">PDF</a>` : '';
    return `<tr><td><span class="code-mono">${esc(b.invoice_number)}</span><div class="muted">${invoiceDate}${due}</div></td><td class="num">${esc(bkRs(b.amount_paise))}</td><td class="num">${esc(bkRs(b.paid_paise))}</td><td class="num">${esc(bkRs(b.owed_paise))}</td><td class="num">${Number(b.age_days)} d</td><td>${pdf}</td></tr>`;
  }).join('');
  const hasOpenBills = (d.bills || []).some(b => Number(b.owed_paise) > 0);
  const payments = d.payments || [];
  const pays = payments.map(x => {
    const vPdf = x.id ? `<a class="btn btn-secondary btn-sm" href="/api/books/payments/${Number(x.id)}/voucher.pdf" target="_blank" rel="noopener">Voucher PDF</a>` : '';
    return `<tr><td><span class="code-mono">${esc(x.reference)}</span><div class="muted">${x.payment_date ? esc(x.payment_date) : 'Date unknown'}</div></td><td class="num">${esc(bkRs(x.amount_paise))}</td><td>${x.kind === 'cash' ? 'Cash' : x.matched ? pill('Matched', 'good') : pill('Not matched', 'warn')}</td><td>${vPdf}</td></tr>`;
  }).join('');
  const projects = d.projects.map(x => {
    const roles = (x.roles || []).map(role => pill(role[0].toUpperCase() + role.slice(1), 'gray')).join(' ');
    const amounts = d.amounts ? [x.spending_paise ? `Spent ${bkRs(x.spending_paise)}` : '',
      x.billed_paise ? `Billed ${bkRs(x.billed_paise)}` : ''].filter(Boolean).join(' · ') : '';
    return `<li><button type="button" class="cx-link" data-project-open="${Number(x.id)}">${esc(x.name)}</button> ${roles}${amounts ? `<div class="muted">${esc(amounts)}</div>` : ''}</li>`;
  }).join('');
  const backBar = `<div class="row-actions section-gap"><button type="button" class="btn btn-secondary btn-sm" data-bk="back-books">← Back to Books</button>` +
    (d.amounts && p.kind !== 'client' ? ` <button type="button" class="btn btn-primary btn-sm" data-bk="party-add-bill" data-vendor="${Number(p.id)}">Add bill</button>` +
      (hasOpenBills ? ` <button type="button" class="btn btn-secondary btn-sm" data-bk="party-pay-bills" data-vendor="${Number(p.id)}" data-vendor-name="${esc(p.name)}">Pay open bills</button>` : '') : '') +
    `</div>`;
  return head(p.name, [p.kind, p.trade, p.phone].filter(Boolean).join(' · ')) + backBar +
    `<section class="panel"><div class="panel-head"><div class="panel-title">Contact</div></div><div class="panel-body"><p>${esc(p.kind)}${p.trade ? ' · ' + esc(p.trade) : ''}</p>${p.phone ? `<p>Phone ${esc(p.phone)}</p>` : ''}${p.gstin ? `<p>GSTIN ${esc(p.gstin)}</p>` : ''}</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Projects</div></div><div class="panel-body">${projects ? `<ul>${projects}</ul>` : '<p class="muted">Not on any project you can see.</p>'}</div></section>` +
    (d.amounts ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Supplier balances</div><div class="panel-sub">${esc(bkRs(d.owed_paise))} owed${d.unallocated_advance_paise ? ` · ${esc(bkRs(d.unallocated_advance_paise))} unallocated advances` : ''}</div></div><a class="btn btn-secondary btn-sm" href="/api/books/parties/${Number(p.id)}/statement.pdf" target="_blank" rel="noopener">Download statement (PDF)</a></div><div class="panel-body">${bkAgeing(d.ageing)}` +
      (bills ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Invoice</th><th>Bill</th><th>Paid</th><th>Owed</th><th>Age</th><th></th></tr></thead><tbody>${bills}</tbody></table></div>` : '<p class="muted">No bills.</p>') +
      '</div></section>' +
      `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Payments</div></div><div class="panel-body">${pays ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Reference</th><th>Amount</th><th>Bank</th><th></th></tr></thead><tbody>${pays}</tbody></table></div>` : '<p class="muted">No payments.</p>'}</div></section>` : '');
}

const BK_VIEWS = {books: ['Books', bkHomeView], party: ['Contact', bkPartyView]};
const _bkRender = render;
render = function () {
  const v = BK_VIEWS[state.view];
  if (!v) { _bkRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = v[1]().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / ' + v[0].toUpperCase());
  $('breadcrumb').textContent = state.view === 'party' && state.bk.party ? state.bk.party.party.name : v[0];
  document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === 'books'));
};

function openParty(id) { state.bk.partyId = Number(id); state.bk.party = null; state.bk.loading = null; switchView('party'); }

async function openBooksDue() {
  const session = state.session;
  state.bk.dueOpen = true;
  if (state.view === 'books') render();
  else switchView('books');
  try {
    const data = await api('/api/books/bills-due');
    if (state.session !== session) return;
    state.bk.dueData = data;
    if (state.view === 'books') render();
  } catch (error) { notify(error.message, true); }
}

const _bkSwitchView = switchView;
switchView = function (view) {
  if (view === 'books') {
    state.bk.home = null;
    state.bk.loading = null;
  }
  return _bkSwitchView(view);
};

document.addEventListener('click', e => {
  if (e.target.closest('[data-bk="back-books"]')) {
    switchView('books');
    return;
  }
  const partyAddBill = e.target.closest('[data-bk="party-add-bill"]');
  if (partyAddBill) {
    state.bk.activePanel = 'bill';
    state.bk.billPrefillVendor = Number(partyAddBill.dataset.vendor) || null;
    state.formFiles = [];
    if (!state.bk.billOpts) {
      api('/api/books/bill-options').then(r => { state.bk.billOpts = r; render(); }).catch(err => notify(err.message, true));
    }
    switchView('books');
    return;
  }
  const partyPayBills = e.target.closest('[data-bk="party-pay-bills"]');
  if (partyPayBills) {
    state.bk.activePanel = 'due';
    state.bk.dueFilterVendor = {id: Number(partyPayBills.dataset.vendor) || 0, name: partyPayBills.dataset.vendorName || 'Vendor'};
    state.bk.dueData = null;
    api('/api/books/bills-due').then(r => { state.bk.dueData = r; render(); }).catch(err => notify(err.message, true));
    switchView('books');
    return;
  }
  if (e.target.closest('[data-bk="due-clear-vendor"]')) {
    state.bk.dueFilterVendor = null;
    render();
    return;
  }
  const toggleVendor = e.target.closest('[data-bk="toggle-vendor"]');
  if (toggleVendor) {
    state.bk.activePanel = state.bk.activePanel === 'vendor' ? null : 'vendor';
    render();
    return;
  }
  const toggleTransfer = e.target.closest('[data-bk="toggle-transfer"]');
  if (toggleTransfer) {
    state.bk.activePanel = state.bk.activePanel === 'transfer' ? null : 'transfer';
    if (state.bk.activePanel === 'transfer' && !state.bk.journalOpts) {
      api('/api/books/journal-options').then(r => { state.bk.journalOpts = r; render(); }).catch(err => notify(err.message, true));
    }
    render();
    return;
  }
  const toggleJournal = e.target.closest('[data-bk="toggle-journal"]');
  if (toggleJournal) {
    state.bk.activePanel = state.bk.activePanel === 'journal' ? null : 'journal';
    if (state.bk.activePanel === 'journal' && !state.bk.journalOpts) {
      api('/api/books/journal-options').then(r => { state.bk.journalOpts = r; render(); }).catch(err => notify(err.message, true));
    }
    render();
    return;
  }
  const addJrLine = e.target.closest('[data-bk="add-jr-line"]');
  if (addJrLine && state.bk.journalOpts) {
    const form = document.getElementById('bkJournalForm');
    const entId = form ? Number(form.entity_id.value) : state.bk.journalOpts.companies[0]?.id;
    const box = document.getElementById('bkJournalLines');
    if (box) {
      box.insertAdjacentHTML('beforeend', bkJournalLineRow(state.bk.journalOpts, entId, 'debit', true));
      bkUpdateJournalBalance(form);
    }
    return;
  }
  const rmJrLine = e.target.closest('[data-bk="rm-jr-line"]');
  if (rmJrLine) {
    const form = document.getElementById('bkJournalForm');
    const box = document.getElementById('bkJournalLines');
    if (box && box.querySelectorAll('.bk-jr-line').length > 2) {
      rmJrLine.closest('.bk-jr-line')?.remove();
      bkUpdateJournalBalance(form);
    }
    return;
  }
  const toggleDue = e.target.closest('[data-bk="toggle-due"]');
  if (toggleDue) {
    state.bk.dueFilterVendor = null;
    if (state.bk.activePanel === 'due') { state.bk.activePanel = null; render(); }
    else { state.bk.activePanel = 'due'; openBooksDue(); }
    return;
  }
  const toggle = e.target.closest('[data-bk="toggle-bill"]');
  if (toggle) {
    state.bk.activePanel = state.bk.activePanel === 'bill' ? null : 'bill';
    state.bk.billPrefillVendor = null;
    state.formFiles = [];                       // photos of an earlier bill never carry over
    if (state.bk.activePanel === 'bill' && !state.bk.billOpts) {
      api('/api/books/bill-options').then(r => { state.bk.billOpts = r; render(); }).catch(err => notify(err.message, true));
    }
    render();
    return;
  }
  const addLine = e.target.closest('[data-bk="add-line"]');
  if (addLine && state.bk.billOpts) {
    const form = document.getElementById('bkBillForm');
    const entId = form ? Number(form.entity_id.value) : state.bk.billOpts.companies[0]?.id;
    const box = document.getElementById('bkBillLines');
    if (box) box.insertAdjacentHTML('beforeend', bkBillLineRow(state.bk.billOpts, entId, form.entity_id.disabled));
    return;
  }
  const rmLine = e.target.closest('[data-bk="rm-line"]');
  if (rmLine) {
    const box = document.getElementById('bkBillLines');
    if (box && box.querySelectorAll('.bk-bill-line').length > 1) {
      rmLine.closest('.bk-bill-line')?.remove();
      const form = document.getElementById('bkBillForm');
      if (form) { bkSyncBillCompany(form, state.bk.billOpts); bkUpdateBillTotal(form); }
    }
    return;
  }
  const b = e.target.closest('[data-bk="party"]');
  if (b) openParty(b.dataset.id);
});

document.addEventListener('input', e => {
  const jrForm = e.target.closest('#bkJournalForm');
  if (jrForm && e.target.name === 'jr_amount') { bkUpdateJournalBalance(jrForm); return; }
  const payForm = e.target.closest('#bkPaySelectedForm');
  if (payForm && e.target.name && e.target.name.startsWith('due_amt_')) { bkUpdateDueSummary(payForm); return; }
  const form = e.target.closest('#bkBillForm');
  if (!form) return;
  if (e.target.name === 'line_amount' || e.target.name === 'tds_amount') bkUpdateBillTotal(form);
  if (e.target.name === 'bill_date' || e.target.name === 'payment_terms_days') {
    const computed = bkAddDays(form.bill_date.value, form.payment_terms_days.value);
    if (computed) form.due_date.value = computed;
  }
});

document.addEventListener('change', e => {
  if (e.target.id === 'bkDueCompany') {
    state.bk.dueCompanyId = Number(e.target.value);
    render();
    return;
  }
  const payForm = e.target.closest('#bkPaySelectedForm');
  if (payForm) {
    if (e.target.id === 'bkDueSelectAll') {
      payForm.querySelectorAll('input[name="due_pick"]').forEach(cb => { cb.checked = e.target.checked; });
      bkUpdateDueSummary(payForm);
      return;
    }
    if (e.target.name === 'due_pick') { bkUpdateDueSummary(payForm); return; }
  }
  const trForm = e.target.closest('#bkTransferForm');
  if (trForm && e.target.name === 'entity_id' && state.bk.journalOpts) {
    const entId = Number(trForm.entity_id.value);
    const bankCash = (state.bk.journalOpts.accounts || []).filter(a => Number(a.entity_id) === entId && (a.kind === 'bank' || a.kind === 'cash'));
    const fromSel = trForm.querySelector('select[name="from_account_id"]');
    const toSel = trForm.querySelector('select[name="to_account_id"]');
    if (fromSel) fromSel.innerHTML = bankCash.map((a, i) => `<option value="${Number(a.id)}"${i === 0 ? ' selected' : ''}>${esc(a.code + ' ' + a.name)}</option>`).join('');
    if (toSel) toSel.innerHTML = bankCash.map((a, i) => `<option value="${Number(a.id)}"${i === (bankCash.length > 1 ? 1 : 0) ? ' selected' : ''}>${esc(a.code + ' ' + a.name)}</option>`).join('');
    return;
  }
  const jrForm = e.target.closest('#bkJournalForm');
  if (jrForm) {
    if (e.target.name === 'jr_side') { bkUpdateJournalBalance(jrForm); return; }
    if (e.target.name === 'entity_id' && state.bk.journalOpts) {
      const entId = Number(jrForm.entity_id.value);
      const accounts = (state.bk.journalOpts.accounts || []).filter(a => Number(a.entity_id) === entId);
      const projects = (state.bk.journalOpts.projects || []).filter(p => Number(p.company_id) === entId);
      const accOpts = '<option value="">Choose an account</option>' + accounts.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
      const projOpts = '<option value="">No project</option>' + projects.map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
      jrForm.querySelectorAll('[name="jr_account"]').forEach(sel => { sel.innerHTML = accOpts; });
      jrForm.querySelectorAll('[name="jr_project"]').forEach(sel => { sel.innerHTML = projOpts; });
      return;
    }
  }
  const form = e.target.closest('#bkBillForm');
  if (!form) return;
  if (e.target.name === 'line_gst') { bkUpdateBillTotal(form); return; }
  if (!['entity_id', 'line_project'].includes(e.target.name) || !state.bk.billOpts) return;
  bkSyncBillCompany(form, state.bk.billOpts);
});

document.addEventListener('submit', async e => {
  const trForm = e.target.closest('#bkTransferForm');
  if (trForm) {
    e.preventDefault();
    const btn = trForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/transfers', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(trForm.entity_id.value),
          from_account_id: Number(trForm.from_account_id.value),
          to_account_id: Number(trForm.to_account_id.value),
          amount_paise: bkParsePaise(trForm.amount.value),
          transfer_date: trForm.transfer_date.value,
          reference: trForm.reference.value.trim(),
          note: trForm.note.value.trim(),
          request_key: trForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Transfer draft #${res.ticket_id} sent for approval.`);
      state.bk.activePanel = null;
      if (typeof senseOfferImmediateReview === 'function') await senseOfferImmediateReview(res.ticket_id, 'Transfer draft ready');
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }
  const jrForm = e.target.closest('#bkJournalForm');
  if (jrForm) {
    e.preventDefault();
    const lines = Array.from(jrForm.querySelectorAll('.bk-jr-line')).map(row => ({
      account_id: Number(row.querySelector('[name="jr_account"]').value),
      side: row.querySelector('[name="jr_side"]').value,
      amount_paise: bkParsePaise(row.querySelector('[name="jr_amount"]').value),
      project_id: row.querySelector('[name="jr_project"]').value ? Number(row.querySelector('[name="jr_project"]').value) : null,
    }));
    const dr = lines.filter(l => l.side === 'debit').reduce((s, l) => s + l.amount_paise, 0);
    const cr = lines.filter(l => l.side === 'credit').reduce((s, l) => s + l.amount_paise, 0);
    if (dr <= 0 || dr !== cr) {
      notify('Debits and credits must be greater than zero and match before sending for approval.', true);
      return;
    }
    const btn = jrForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/manual-journals', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(jrForm.entity_id.value),
          entry_date: jrForm.entry_date.value,
          reference: jrForm.reference.value.trim(),
          narration: jrForm.narration.value.trim(),
          lines,
          request_key: jrForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Manual journal draft #${res.ticket_id} sent for approval.`);
      state.bk.activePanel = null;
      if (typeof senseOfferImmediateReview === 'function') await senseOfferImmediateReview(res.ticket_id, 'Journal draft ready');
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }
  const payForm = e.target.closest('#bkPaySelectedForm');
  if (payForm) {
    e.preventDefault();
    const picked = Array.from(payForm.querySelectorAll('input[name="due_pick"]:checked'));
    if (!picked.length) { notify('Tick at least one bill to pay.', true); return; }
    const entities = new Set(picked.map(cb => Number(cb.dataset.entity)));
    if (entities.size > 1) { notify('Select bills from one company at a time.', true); return; }
    const btn = payForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const items = picked.map(cb => {
        const [kind, id] = cb.value.split(':');
        const amtInput = payForm.querySelector(`[name="due_amt_${kind}_${id}"]`);
        const amount = bkParsePaise(amtInput?.value);
        if (amount <= 0 || amount > Number(cb.dataset.available)) throw new Error('Enter a payment up to the available amount for each selected bill.');
        return {kind, bill_id: Number(id), amount_paise: amount};
      });
      const res = await api('/api/books/pay-selected', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(payForm.dataset.entity),
          paid_through_id: Number(payForm.paid_through_id.value),
          payment_date: payForm.payment_date.value,
          payment_reference: payForm.payment_reference.value.trim(),
          items,
          request_key: payForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`${res.item_count} payment${res.item_count === 1 ? '' : 's'} sent for approval (ticket #${res.ticket_id}).`);
      state.bk.activePanel = null;
      state.bk.dueData = null;
      if (typeof senseOfferImmediateReview === 'function') await senseOfferImmediateReview(res.ticket_id, 'Payment batch ready');
      state.bk.dueFilterVendor = null;
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }
  const vForm = e.target.closest('#bkVendorForm');
  if (vForm) {
    e.preventDefault();
    const btn = vForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/vendors', {
        method: 'POST',
        body: JSON.stringify({
          name: vForm.name.value.trim(),
          gst_treatment: vForm.gst_treatment.value,
          gstin: vForm.gstin.value.trim(),
          pan: vForm.pan.value.trim(),
          state_code: vForm.state_code.value.trim(),
          phone: vForm.phone.value.trim(),
          email: vForm.email.value.trim(),
          trade: vForm.trade.value.trim(),
          payment_terms_days: Number(vForm.payment_terms_days.value || 30),
          default_tds_section: vForm.default_tds_section.value,
          billing_address: vForm.billing_address.value.trim(),
          bank_ifsc: vForm.bank_ifsc.value.trim(),
          bank_masked_number: vForm.bank_masked_number.value.trim(),
          request_key: vForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Vendor draft #${res.ticket_id} sent for approval.`);
      state.bk.activePanel = null;
      state.bk.billOpts = null;
      if (typeof senseOfferImmediateReview === 'function') await senseOfferImmediateReview(res.ticket_id, 'Vendor draft ready');
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }
  const form = e.target.closest('#bkBillForm');
  if (!form) return;
  e.preventDefault();
  const submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;
  try {
    let taxable = 0, gstTotal = 0;
    const lines = Array.from(form.querySelectorAll('.bk-bill-line')).map(row => {
      const amount_paise = bkParsePaise(row.querySelector('[name="line_amount"]').value);
      const tax_rate_bps = Number(row.querySelector('[name="line_gst"]')?.value || 0);
      taxable += amount_paise;
      gstTotal += Math.floor((amount_paise * tax_rate_bps + 5000) / 10000);
      return {
        account_id: Number(row.querySelector('[name="line_account"]').value),
        project_id: row.querySelector('[name="line_project"]').value ? Number(row.querySelector('[name="line_project"]').value) : null,
        description: row.querySelector('[name="line_desc"]').value.trim(),
        amount_paise,
        tax_rate_bps,
      };
    });
    const tds_paise = bkParsePaise(form.tds_amount?.value);
    const amount_paise = taxable + gstTotal - tds_paise;
    const body = {
      entity_id: Number(form.entity_id.value),
      supplier_id: Number(form.supplier_id.value),
      po_id: form.po_id?.value ? Number(form.po_id.value) : null,
      invoice_number: form.invoice_number.value.trim(),
      bill_date: form.bill_date.value,
      due_date: form.due_date.value,
      payment_terms_days: Number(form.payment_terms_days.value),
      supply_type: form.supply_type?.value || 'intra',
      tds_section: form.tds_section?.value || '',
      tds_paise,
      amount_paise,
      lines,
      note: form.note.value.trim(),
      attachment_id: form.attachment_id.value ? Number(form.attachment_id.value) : null,
      receipt_ids: (state.formFiles || []).map(f => Number(f.id)),
      request_key: form.dataset.requestKey || formRequestKey(),
    };
    const res = await api('/api/books/bills', {method: 'POST', body: JSON.stringify(body)});
    notify(`Bill draft #${res.ticket_id} sent for approval.`);
    state.bk.activePanel = null;
    state.bk.billPrefillVendor = null;
    state.formFiles = [];
    state.bk.home = null;
    if (typeof senseOfferImmediateReview === 'function') await senseOfferImmediateReview(res.ticket_id, 'Supplier bill draft ready');
    refresh();
  } catch (err) {
    notify(err.message, true);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
});
