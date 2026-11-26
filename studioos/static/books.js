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
    const historical = c.open_legacy_payables ? ` · ${Number(c.open_legacy_payables)} historical expense balance${c.open_legacy_payables === 1 ? '' : 's'}` : '';
    return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(c.name)}</div><div class="panel-sub">${Number(c.open_bills)} unpaid bill${c.open_bills === 1 ? '' : 's'}${historical} · ${esc(bkRs(c.payable_paise))} owed to suppliers</div></div></div><div class="panel-body">` +
      `<p>Posted expenses <strong>${esc(bkRs(c.posted_expense_paise))}</strong></p>` +
      `<div class="w-sub">How old the unpaid balances are</div>${bkAgeing(c.ageing)}` +
      `<div class="w-sub">Bank accounts</div>${banks ? `<div class="w-table-wrap"><table class="w-table"><tbody>${banks}</tbody></table></div>` : '<p class="muted">No bank account registered.</p>'}` +
      `<div class="w-sub">Owed, by supplier</div>${owed ? `<div class="w-table-wrap"><table class="w-table"><tbody>${owed}</tbody></table></div>` : '<p class="muted">Nothing owed.</p>'}` +
      `<p class="muted">${Number(c.unmatched_payments.count)} supplier payment${c.unmatched_payments.count === 1 ? '' : 's'} (${esc(bkRs(c.unmatched_payments.paise))}) not yet matched to the bank statement.</p>` +
      `<p class="muted">Closed months: ${c.closed_months.length ? esc(c.closed_months.join(', ')) : 'none yet'}</p></div></section>`;
  }).join('');
  const off = cards ? '' : ' disabled aria-disabled="true"';   // nothing to act on until a company is set up
  const ap = state.bk.activePanel;
  const addBillBtn = `<div class="section-gap"><button type="button" class="btn btn-primary" data-bk="toggle-bill"${off}>${ap === 'bill' ? 'Close bill form' : 'Add supplier bill'}</button> ` +
    `<button type="button" class="btn btn-secondary" data-bk="toggle-due"${off}>${ap === 'due' ? 'Hide bills due' : 'Bills due & Pay selected'}</button> ` +
    `<button type="button" class="btn btn-secondary" data-bk="toggle-transfer"${off}>${ap === 'transfer' ? 'Close transfer' : 'Move money'}</button> ` +
    `<button type="button" class="btn btn-secondary" data-bk="toggle-journal"${off}>${ap === 'journal' ? 'Close journal' : 'Manual journal'}</button></div>` +
    (ap === 'bill' ? bkBillFormHtml() : ap === 'due' ? bkBillsDueHtml() : ap === 'transfer' ? bkTransferFormHtml() : ap === 'journal' ? bkManualJournalFormHtml() : '');
  return head('Books', 'What is owed, what is in the bank, and which months are closed.') + addBillBtn + (cards || empty('₹', 'Set up your company first', 'Bills, payments and journals unlock once your company and chart of accounts exist. It takes one short form.') + '<div class="section-gap"><button type="button" class="btn btn-primary" data-view="ledger">Set up your company</button></div>') + `<p class="muted">${esc(h.note)}</p>`;
}

function bkDueGroupHtml(title, rows) {
  if (!rows.length) return '';
  const trs = rows.map(r => {
    const late = r.days_late > 0 ? ' ' + pill(`${Number(r.days_late)} days late`, 'critical') : '';
    const due = r.due_date ? `due ${esc(r.due_date)}` : 'no due date';
    const label = `${r.supplier_name || 'Vendor'} ${r.invoice_number}`;
    return `<tr><td><input type="checkbox" name="due_pick" value="${esc(r.kind + ':' + r.bill_id)}" data-entity="${Number(r.entity_id)}" data-owed="${Number(r.owed_paise)}" aria-label="Select ${esc(label)}"></td>` +
      `<td><strong>${esc(r.supplier_name || 'Vendor')}</strong> · ${esc(r.invoice_number)}<div class="muted">${due}${late}</div>${approvalFiles(r)}</td>` +
      `<td class="num">${esc(bkRs(r.owed_paise))}</td>` +
      `<td><input type="text" class="form-input" name="due_amt_${esc(r.kind + '_' + r.bill_id)}" inputmode="decimal" value="${esc((r.owed_paise / 100).toFixed(2))}" aria-label="Amount to pay in rupees for ${esc(label)}"></td></tr>`;
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

function bkBillLineRow(opts, entityId) {
  const accs = (opts.accounts || []).filter(a => Number(a.entity_id) === Number(entityId));
  const accOpts = accs.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' · ' + a.name)}</option>`).join('');
  const projOpts = '<option value="">Office / no project</option>' + (opts.projects || []).map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
  return `<div class="g-form bk-bill-line"><label class="g-field"><span>Expense account</span><select name="line_account" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="line_project" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>Description</span><input name="line_desc" class="form-input" maxlength="250" placeholder="What was supplied"></label>` +
    `<label class="g-field"><span>Amount (₹)</span><input name="line_amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
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
  const docOpts = '<option value="">No file attached</option>' + opts.documents.map(d => `<option value="${Number(d.id)}">${esc(d.name)}</option>`).join('');
  const today = opts.today || '';
  const due = bkAddDays(today, 30);
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New supplier bill</div><div class="panel-sub">Sends a draft change request for approval. Nothing posts until approved.</div></div></div><div class="panel-body">` +
    `<form id="bkBillForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Vendor</span><select name="supplier_id" class="form-input" required>${vendOpts}</select></label>` +
    `<label class="g-field"><span>Invoice number</span><input name="invoice_number" class="form-input" maxlength="120" required placeholder="INV-2026-001"></label>` +
    `<label class="g-field"><span>Bill date</span><input type="date" name="bill_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Payment terms</span><select name="payment_terms_days" class="form-input" required>${[[0, 'Due on receipt'], [7, 'Net 7'], [15, 'Net 15'], [30, 'Net 30'], [45, 'Net 45'], [60, 'Net 60'], [90, 'Net 90']].map(([d, l]) => `<option value="${d}"${d === 30 ? ' selected' : ''}>${l}</option>`).join('')}</select></label>` +
    `<label class="g-field"><span>Due date</span><input type="date" name="due_date" class="form-input" required value="${esc(due)}"></label>` +
    `<label class="g-field"><span>Attachment (optional)</span><select name="attachment_id" class="form-input">${docOpts}</select></label>` +
    `<label class="g-field"><span>Note (optional)</span><input name="note" class="form-input" maxlength="500" placeholder="Reference or delivery note"></label>` +
    `</div><div class="field files-field"><label for="bkBillFiles">Photos or PDF of the bill (optional)</label><input type="file" class="form-input" id="bkBillFiles" data-upload-files accept="image/jpeg,image/png,application/pdf" multiple>` +
    `<div class="file-previews" aria-live="polite">${filePreviewsHtml()}</div><small class="muted">Up to 5 photos (JPG or PNG) or PDFs, 8 MB each.</small></div>` +
    `<div class="w-sub">Bill lines</div><div id="bkBillLines">${bkBillLineRow(opts, entId)}</div>` +
    `<div class="section-gap"><button type="button" class="btn btn-secondary btn-sm" data-bk="add-line">+ Add line</button> ` +
    `<span class="muted" id="bkBillTotal" aria-live="polite">Total: ₹0.00</span></div>` +
    `<div class="section-gap"><button type="submit" class="btn btn-primary">Send for approval</button></div></form></div></section>`;
}

function bkParsePaise(raw) {
  const clean = String(raw || '').replace(/,/g, '').trim();
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return 0;
  const [rs, ps = ''] = clean.split('.');
  return Number(rs) * 100 + Number((ps + '00').slice(0, 2));
}

function bkUpdateBillTotal(form) {
  const total = Array.from(form.querySelectorAll('input[name="line_amount"]')).reduce((s, el) => s + bkParsePaise(el.value), 0);
  const out = document.getElementById('bkBillTotal');
  if (out) out.textContent = 'Total: ' + bkRs(total);
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
  const projOpts = '<option value="">No project</option>' + (opts.projects || []).map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
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
  const historical = (d.legacy_payables || []).map(row => `<tr><td>${esc(row.title)}</td><td>${esc(row.posted_date)}</td><td class="num">${esc(bkRs(row.owed_paise))}</td><td><button type="button" class="btn btn-secondary btn-sm" data-bk="pay-legacy" data-company="${Number(row.entity_id)}" data-journal="${Number(row.journal_id)}">Pay balance</button></td></tr>`).join('');
  const bills = (d.bills || []).map(b => {
    const invoiceDate = b.bill_date ? `Bill date ${esc(b.bill_date)}` : 'Date unknown';
    const terms = b.payment_terms_days === 0 ? 'Due on receipt' : `${Number(b.payment_terms_days)} days`;
    const due = b.due_date ? ` · Due ${esc(b.due_date)}${b.payment_terms_days == null ? '' : ` · ${terms}`}` : '';
    return `<tr><td>${esc(b.invoice_number)}<div class="muted">${invoiceDate}${due}</div></td><td class="num">${esc(bkRs(b.amount_paise))}</td><td class="num">${esc(bkRs(b.paid_paise))}</td><td class="num">${esc(bkRs(b.owed_paise))}</td><td class="num">${Number(b.age_days)} d</td></tr>`;
  }).join('');
  const hasOpenBills = (d.bills || []).some(b => Number(b.owed_paise) > 0);
  const payments = [...(d.payments || []), ...(d.legacy_payments || [])];
  const pays = payments.map(x => `<tr><td>${esc(x.reference)}<div class="muted">${x.payment_date ? esc(x.payment_date) : 'Date unknown'}${x.opening_journal_id ? ' · Historical balance' : ''}</div></td><td class="num">${esc(bkRs(x.amount_paise))}</td><td>${x.kind === 'cash' ? 'Cash' : x.matched ? pill('Matched', 'good') : pill('Not matched', 'warn')}</td></tr>`).join('');
  const projects = d.projects.map(x => `<li>${esc(x.name)}</li>`).join('');
  const backBar = `<div class="row-actions section-gap"><button type="button" class="btn btn-secondary btn-sm" data-bk="back-books">← Back to Books</button>` +
    (d.amounts && p.kind !== 'client' ? ` <button type="button" class="btn btn-primary btn-sm" data-bk="party-add-bill" data-vendor="${Number(p.id)}">Add bill</button>` +
      (hasOpenBills ? ` <button type="button" class="btn btn-secondary btn-sm" data-bk="party-pay-bills" data-vendor="${Number(p.id)}" data-vendor-name="${esc(p.name)}">Pay open bills</button>` : '') : '') +
    `</div>`;
  return head(p.name, [p.kind, p.trade, p.phone].filter(Boolean).join(' · ')) + backBar +
    `<section class="panel"><div class="panel-head"><div class="panel-title">Contact</div></div><div class="panel-body"><p>${esc(p.kind)}${p.trade ? ' · ' + esc(p.trade) : ''}</p>${p.phone ? `<p>Phone ${esc(p.phone)}</p>` : ''}${p.gstin ? `<p>GSTIN ${esc(p.gstin)}</p>` : ''}</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Projects</div></div><div class="panel-body">${projects ? `<ul>${projects}</ul>` : '<p class="muted">Not on any project you can see.</p>'}</div></section>` +
    (d.amounts ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Supplier balances</div><div class="panel-sub">${esc(bkRs(d.owed_paise))} owed${d.unallocated_advance_paise ? ` · ${esc(bkRs(d.unallocated_advance_paise))} unallocated advances` : ''}</div></div><a class="btn btn-secondary btn-sm" href="/api/books/parties/${Number(p.id)}/statement.pdf" target="_blank" rel="noopener">Download statement (PDF)</a></div><div class="panel-body">${bkAgeing(d.ageing)}` +
      (bills ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Invoice</th><th>Bill</th><th>Paid</th><th>Owed</th><th>Age</th></tr></thead><tbody>${bills}</tbody></table></div>` : '<p class="muted">No bills.</p>') +
      (historical ? `<div class="w-sub">Historical expense balances</div><div class="w-table-wrap"><table class="w-table"><thead><tr><th>Expense</th><th>Posted to Books</th><th>Owed</th><th>Action</th></tr></thead><tbody>${historical}</tbody></table></div><div id="bkPayBalance" aria-live="polite"></div>` : '') + '</div></section>' +
      `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Payments</div></div><div class="panel-body">${pays ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Reference</th><th>Amount</th><th>Bank</th></tr></thead><tbody>${pays}</tbody></table></div>` : '<p class="muted">No payments.</p>'}</div></section>` : '');
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
    state.bk.activePanel = state.bk.activePanel === 'due' ? null : 'due';
    state.bk.dueFilterVendor = null;
    if (state.bk.activePanel === 'due') {
      api('/api/books/bills-due').then(r => { state.bk.dueData = r; render(); }).catch(err => notify(err.message, true));
    }
    render();
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
    if (box) box.insertAdjacentHTML('beforeend', bkBillLineRow(state.bk.billOpts, entId));
    return;
  }
  const rmLine = e.target.closest('[data-bk="rm-line"]');
  if (rmLine) {
    const box = document.getElementById('bkBillLines');
    if (box && box.querySelectorAll('.bk-bill-line').length > 1) {
      rmLine.closest('.bk-bill-line')?.remove();
      const form = document.getElementById('bkBillForm');
      if (form) bkUpdateBillTotal(form);
    }
    return;
  }
  const payment = e.target.closest('[data-bk="pay-legacy"]');
  if (payment) {
    const output = document.getElementById('bkPayBalance');
    showVendorPayment(Number(payment.dataset.company), output, Number(payment.dataset.journal))
      .catch(err => notify(err.message, true));
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
  if (e.target.name === 'line_amount') bkUpdateBillTotal(form);
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
      const accOpts = (state.bk.journalOpts.accounts || []).filter(a => Number(a.entity_id) === entId)
        .map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
      jrForm.querySelectorAll('select[name="jr_account"]').forEach(sel => { sel.innerHTML = accOpts; });
      return;
    }
  }
  const form = e.target.closest('#bkBillForm');
  if (!form || e.target.name !== 'entity_id' || !state.bk.billOpts) return;
  const entId = Number(form.entity_id.value);
  const accOpts = (state.bk.billOpts.accounts || []).filter(a => Number(a.entity_id) === entId)
    .map(a => `<option value="${Number(a.id)}">${esc(a.code + ' · ' + a.name)}</option>`).join('');
  form.querySelectorAll('select[name="line_account"]').forEach(sel => { sel.innerHTML = accOpts; });
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
        return {kind, bill_id: Number(id), amount_paise: bkParsePaise(amtInput ? amtInput.value : 0)};
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
      state.bk.dueFilterVendor = null;
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
    const lines = Array.from(form.querySelectorAll('.bk-bill-line')).map(row => ({
      account_id: Number(row.querySelector('[name="line_account"]').value),
      project_id: row.querySelector('[name="line_project"]').value ? Number(row.querySelector('[name="line_project"]').value) : null,
      description: row.querySelector('[name="line_desc"]').value.trim(),
      amount_paise: bkParsePaise(row.querySelector('[name="line_amount"]').value),
    }));
    const amount_paise = lines.reduce((s, ln) => s + ln.amount_paise, 0);
    const body = {
      entity_id: Number(form.entity_id.value),
      supplier_id: Number(form.supplier_id.value),
      invoice_number: form.invoice_number.value.trim(),
      bill_date: form.bill_date.value,
      due_date: form.due_date.value,
      payment_terms_days: Number(form.payment_terms_days.value),
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
    refresh();
  } catch (err) {
    notify(err.message, true);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
});
