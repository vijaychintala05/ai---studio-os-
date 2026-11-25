'use strict';
/* StudioOS Books home and Party page (App Flows map). Books home (owner and accounts): what is owed to suppliers, how old it is, bank
   balances, closed months and payments not yet matched to the bank. The Party page: one vendor or client, with amounts shown only to
   roles that may see them. Read-only; every change is still a ticket. No inline styles (strict CSP). Loaded after app.js. */

Object.assign(state, {bk: {home: null, party: null, partyId: null, billOpen: false, billOpts: null}});

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
  const addBillBtn = `<div class="section-gap"><button type="button" class="btn btn-primary" data-bk="toggle-bill">${state.bk.billOpen ? 'Close bill form' : 'Add supplier bill'}</button></div>` + (state.bk.billOpen ? bkBillFormHtml() : '');
  return head('Books', 'What is owed, what is in the bank, and which months are closed.') + addBillBtn + (cards || empty('₹', 'No company set up', 'A company with a chart of accounts is set up from the books flow.')) + `<p class="muted">${esc(h.note)}</p>`;
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
  const vendOpts = '<option value="">Choose a vendor</option>' + opts.vendors.map(v => `<option value="${Number(v.id)}">${esc(v.name)}</option>`).join('');
  const docOpts = '<option value="">No file attached</option>' + opts.documents.map(d => `<option value="${Number(d.id)}">${esc(d.name)}</option>`).join('');
  const today = opts.today || '';
  const due = bkAddDays(today, 30);
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New supplier bill</div><div class="panel-sub">Sends a draft change request for approval. Nothing posts until approved.</div></div></div><div class="panel-body">` +
    `<form id="bkBillForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Vendor</span><select name="supplier_id" class="form-input" required>${vendOpts}</select></label>` +
    `<label class="g-field"><span>Invoice number</span><input name="invoice_number" class="form-input" maxlength="120" required placeholder="INV-2026-001"></label>` +
    `<label class="g-field"><span>Bill date</span><input type="date" name="bill_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Payment terms (days)</span><input type="number" name="payment_terms_days" class="form-input" min="0" max="365" required value="30"></label>` +
    `<label class="g-field"><span>Due date</span><input type="date" name="due_date" class="form-input" required value="${esc(due)}"></label>` +
    `<label class="g-field"><span>Attachment (optional)</span><select name="attachment_id" class="form-input">${docOpts}</select></label>` +
    `<label class="g-field"><span>Note (optional)</span><input name="note" class="form-input" maxlength="500" placeholder="Reference or delivery note"></label>` +
    `</div><div class="w-sub">Bill lines</div><div id="bkBillLines">${bkBillLineRow(opts, entId)}</div>` +
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
  const payments = [...(d.payments || []), ...(d.legacy_payments || [])];
  const pays = payments.map(x => `<tr><td>${esc(x.reference)}<div class="muted">${x.payment_date ? esc(x.payment_date) : 'Date unknown'}${x.opening_journal_id ? ' · Historical balance' : ''}</div></td><td class="num">${esc(bkRs(x.amount_paise))}</td><td>${x.kind === 'cash' ? 'Cash' : x.matched ? pill('Matched', 'good') : pill('Not matched', 'warn')}</td></tr>`).join('');
  const projects = d.projects.map(x => `<li>${esc(x.name)}</li>`).join('');
  return head(p.name, [p.kind, p.trade, p.phone].filter(Boolean).join(' · ')) +
    `<section class="panel"><div class="panel-head"><div class="panel-title">Contact</div></div><div class="panel-body"><p>${esc(p.kind)}${p.trade ? ' · ' + esc(p.trade) : ''}</p>${p.phone ? `<p>Phone ${esc(p.phone)}</p>` : ''}${p.gstin ? `<p>GSTIN ${esc(p.gstin)}</p>` : ''}</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Projects</div></div><div class="panel-body">${projects ? `<ul>${projects}</ul>` : '<p class="muted">Not on any project you can see.</p>'}</div></section>` +
    (d.amounts ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Supplier balances</div><div class="panel-sub">${esc(bkRs(d.owed_paise))} owed</div></div></div><div class="panel-body">${bkAgeing(d.ageing)}` +
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
  const toggle = e.target.closest('[data-bk="toggle-bill"]');
  if (toggle) {
    state.bk.billOpen = !state.bk.billOpen;
    if (state.bk.billOpen && !state.bk.billOpts) {
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
  const form = e.target.closest('#bkBillForm');
  if (!form) return;
  if (e.target.name === 'line_amount') bkUpdateBillTotal(form);
  if (e.target.name === 'bill_date' || e.target.name === 'payment_terms_days') {
    const computed = bkAddDays(form.bill_date.value, form.payment_terms_days.value);
    if (computed) form.due_date.value = computed;
  }
});

document.addEventListener('change', e => {
  const form = e.target.closest('#bkBillForm');
  if (!form || e.target.name !== 'entity_id' || !state.bk.billOpts) return;
  const box = document.getElementById('bkBillLines');
  if (box) {
    box.innerHTML = bkBillLineRow(state.bk.billOpts, Number(form.entity_id.value));
    bkUpdateBillTotal(form);
  }
});

document.addEventListener('submit', async e => {
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
      request_key: form.dataset.requestKey || formRequestKey(),
    };
    const res = await api('/api/books/bills', {method: 'POST', body: JSON.stringify(body)});
    notify(`Bill draft #${res.ticket_id} sent for approval.`);
    state.bk.billOpen = false;
    state.bk.home = null;
    refresh();
  } catch (err) {
    notify(err.message, true);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
});
