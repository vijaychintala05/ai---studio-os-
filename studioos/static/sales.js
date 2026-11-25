'use strict';
/* StudioOS M3 Sales & Receipts screens (Quotes, Client Tax Invoices + PDF, Credit Notes,
   Client Receipts with optional TDS, Client Retainers/Advances, and Customer Statements).
   Strict CSP: zero inline styles or handlers. Every change sends an approval draft ticket. */

Object.assign(state, {
  sl: {
    opts: null, quotes: [], invoices: [], loading: false,
    tab: 'quotes', formOpen: '', prefillQuote: null,
    stmtClientId: null, stmt: null,
  },
});

const SL_ROLES = ['admin', 'accounts', 'manager'];

function slFindAcc(accounts, entId, predicate) {
  const entAccs = (accounts || []).filter(a => a.entity_id === entId);
  return entAccs.find(predicate) || entAccs[0] || null;
}

function slAutoAccounts(opts, entId) {
  const accs = (opts && opts.accounts) || [];
  const has = (a, ...words) => words.some(w => (a.name || '').toLowerCase().includes(w));
  return {
    ar: slFindAcc(accs, entId, a => has(a, 'receivable', 'debtor') || a.code === '1100'),
    income: slFindAcc(accs, entId, a => a.kind === 'income' || a.kind === 'revenue'),
    cgst: slFindAcc(accs, entId, a => has(a, 'output cgst', 'cgst')),
    sgst: slFindAcc(accs, entId, a => has(a, 'output sgst', 'sgst')),
    igst: slFindAcc(accs, entId, a => has(a, 'output igst', 'igst')),
    rounding: slFindAcc(accs, entId, a => has(a, 'rounding')),
    tds: slFindAcc(accs, entId, a => has(a, 'tds receivable', 'tds')),
    advance: slFindAcc(accs, entId, a => has(a, 'client advance', 'retainer', 'advance')),
    ap: slFindAcc(accs, entId, a => a.kind === 'payable' || has(a, 'payable')),
    expense: slFindAcc(accs, entId, a => a.kind === 'expense'),
    bankCash: accs.filter(a => a.entity_id === entId && (a.kind === 'bank' || a.kind === 'cash')),
  };
}

async function slLoadAll() {
  if (state.sl.loading) return;
  state.sl.loading = true;
  try {
    const [opts, qRes, iRes] = await Promise.all([
      api('/api/sales/options'),
      api('/api/sales/quotes'),
      api('/api/sales/invoices'),
    ]);
    state.sl.opts = opts;
    state.sl.quotes = qRes.quotes || [];
    state.sl.invoices = iRes.invoices || [];
  } catch (err) {
    notify(err.message, true);
  } finally {
    state.sl.loading = false;
    render();
  }
}

function slLineRowHtml(opts, entId, isInvoice, preset = {}) {
  const accs = (opts.accounts || []).filter(a => a.entity_id === entId && (a.kind === 'income' || a.kind === 'revenue'));
  const accField = isInvoice
    ? `<label class="g-field"><span>Income account</span><select name="sl_inc" class="form-input" required>${
        (accs.length ? accs : (opts.accounts || []).filter(a => a.entity_id === entId))
          .map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('')
      }</select></label>`
    : '';
  return `<div class="g-form sl-line">` + accField +
    `<label class="g-field"><span>Description</span><input name="sl_desc" class="form-input" required maxlength="250" value="${esc(preset.description || '')}" placeholder="Design fee / turnkey milestone"></label>` +
    `<label class="g-field"><span>SAC / HSN</span><input name="sl_sac" class="form-input" maxlength="20" value="${esc(preset.sac_hsn || '998391')}"></label>` +
    `<label class="g-field"><span>Qty</span><input type="number" name="sl_qty" class="form-input" min="1" required value="${Number(preset.quantity || 1)}"></label>` +
    `<label class="g-field"><span>Rate (₹)</span><input name="sl_rate" class="form-input" inputmode="decimal" required value="${preset.rate_paise ? esc((preset.rate_paise / 100).toFixed(2)) : ''}" placeholder="0.00"></label>` +
    `<label class="g-field"><span>GST %</span><select name="sl_gst" class="form-input">` +
    [1800, 1200, 500, 2800, 0].map(bps => `<option value="${bps}"${Number(preset.tax_rate_bps ?? 1800) === bps ? ' selected' : ''}>${bps / 100}%</option>`).join('') +
    `</select></label></div>`;
}

function slQuoteFormHtml(opts) {
  const entId = opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const cliOpts = opts.clients.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const projOpts = '<option value="">No project</option>' + opts.projects.map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
  const today = opts.today || '';
  const valid = bkAddDays(today, 30);
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New client quote</div><div class="panel-sub">Quotes are versioned and never post to the ledger until invoiced.</div></div></div><div class="panel-body">` +
    `<form id="slQuoteForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Client</span><select name="client_id" class="form-input" required>${cliOpts}</select></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="project_id" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>Quote number</span><input name="quote_number" class="form-input" required maxlength="80" placeholder="QT-2026-001"></label>` +
    `<label class="g-field"><span>Quote date</span><input type="date" name="quote_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Valid until</span><input type="date" name="valid_until" class="form-input" required value="${esc(valid)}"></label>` +
    `<label class="g-field"><span>Note</span><input name="note" class="form-input" maxlength="400" placeholder="Payment schedule or scope note"></label>` +
    `</div><div class="w-sub">Quote lines</div><div id="slQuoteLines">${slLineRowHtml(opts, entId, false)}</div>` +
    `<div class="section-gap"><button type="button" class="btn btn-secondary btn-sm" data-sl="add-q-line">+ Add line</button> ` +
    `<button type="submit" class="btn btn-primary">Send quote for approval</button></div></form></div></section>`;
}

function slInvoiceFormHtml(opts) {
  const pre = state.sl.prefillQuote;
  const entId = pre ? pre.entity_id : opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}"${c.id === entId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const cliOpts = opts.clients.map(c => `<option value="${Number(c.id)}"${pre && c.id === pre.client_id ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const projOpts = '<option value="">No project</option>' + opts.projects.map(p => `<option value="${Number(p.id)}"${pre && p.id === pre.project_id ? ' selected' : ''}>${esc(p.name)}</option>`).join('');
  const today = opts.today || '';
  const due = bkAddDays(today, 30);
  const linesHtml = pre && pre.lines && pre.lines.length
    ? pre.lines.map(l => slLineRowHtml(opts, entId, true, l)).join('')
    : slLineRowHtml(opts, entId, true);
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New GST tax invoice</div><div class="panel-sub">Accounts Receivable, GST, and CGST §170 nearest-₹1 rounding are wired automatically.</div></div></div><div class="panel-body">` +
    `<form id="slInvoiceForm" data-quote-id="${pre ? Number(pre.id) : ''}" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Client</span><select name="client_id" class="form-input" required>${cliOpts}</select></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="project_id" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>Invoice number</span><input name="invoice_number" class="form-input" required maxlength="80" placeholder="INV-2026-001"></label>` +
    `<label class="g-field"><span>Invoice date</span><input type="date" name="invoice_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Due date</span><input type="date" name="due_date" class="form-input" required value="${esc(due)}"></label>` +
    `<label class="g-field"><span>Place of supply</span><input name="place_of_supply" class="form-input" value="Karnataka (29)" maxlength="40"></label>` +
    `<label class="g-field"><span>GST type</span><select name="supply_type" class="form-input"><option value="intra">Intra-state (CGST + SGST)</option><option value="inter">Inter-state (IGST)</option></select></label>` +
    `</div><div class="w-sub">Invoice lines</div><div id="slInvLines">${linesHtml}</div>` +
    `<div class="section-gap"><button type="button" class="btn btn-secondary btn-sm" data-sl="add-i-line">+ Add line</button> ` +
    `<button type="submit" class="btn btn-primary">Send invoice for approval</button></div></form></div></section>`;
}

function slCreditNoteFormHtml(opts) {
  const entId = opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const cliOpts = opts.clients.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const today = opts.today || '';
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New client credit note</div><div class="panel-sub">Reduces client receivable and reverses revenue/GST cleanly on approval.</div></div></div><div class="panel-body">` +
    `<form id="slCreditNoteForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Client</span><select name="client_id" class="form-input" required>${cliOpts}</select></label>` +
    `<label class="g-field"><span>Credit note #</span><input name="note_number" class="form-input" required maxlength="80" placeholder="CN-2026-001"></label>` +
    `<label class="g-field"><span>Date</span><input type="date" name="note_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Taxable amount (₹)</span><input name="taxable" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>GST amount (₹)</span><input name="tax" class="form-input" inputmode="decimal" value="0.00"></label>` +
    `<label class="g-field"><span>Reason</span><input name="reason" class="form-input" required maxlength="300" placeholder="Agreed discount / scope reduction"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send credit note for approval</button></div></form></div></section>`;
}

function slSalesView() {
  if (!SL_ROLES.includes(state.user?.role)) return head('Sales', 'Sales screens are for the owner, accounts, and managers.');
  if (!state.sl.opts) {
    slLoadAll();
    return head('Sales', 'Quotes, client tax invoices, and credit notes.') + '<div class="loading">Loading…</div>';
  }
  const opts = state.sl.opts;
  const openQuotes = state.sl.quotes.filter(q => !q.accepted);
  const activeInvs = state.sl.invoices.filter(i => !i.reversed);
  const tiles = `<div class="v-tiles">` +
    `<div class="v-tile"><div class="v-tile-value">${openQuotes.length}</div><div class="v-tile-label">Open Quotes</div></div>` +
    `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(openQuotes.reduce((s, q) => s + q.total_paise, 0)))}</div><div class="v-tile-label">Quoted Value</div></div>` +
    `<div class="v-tile"><div class="v-tile-value">${activeInvs.length}</div><div class="v-tile-label">Posted Invoices</div></div>` +
    `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(activeInvs.reduce((s, i) => s + i.total_paise, 0)))}</div><div class="v-tile-label">Invoiced Total</div></div></div>`;

  const actions = `<div class="section-gap">` +
    `<button type="button" class="btn btn-primary" data-sl="toggle-form" data-form="quote">${state.sl.formOpen === 'quote' ? 'Close quote form' : '+ New Quote'}</button> ` +
    `<button type="button" class="btn btn-secondary" data-sl="toggle-form" data-form="invoice">${state.sl.formOpen === 'invoice' ? 'Close invoice form' : '+ New Tax Invoice'}</button> ` +
    `<button type="button" class="btn btn-secondary" data-sl="toggle-form" data-form="credit">${state.sl.formOpen === 'credit' ? 'Close credit note' : '+ Credit Note'}</button></div>`;

  let formHtml = '';
  if (state.sl.formOpen === 'quote') formHtml = slQuoteFormHtml(opts);
  else if (state.sl.formOpen === 'invoice') formHtml = slInvoiceFormHtml(opts);
  else if (state.sl.formOpen === 'credit') formHtml = slCreditNoteFormHtml(opts);

  const clientMap = Object.fromEntries((opts.clients || []).map(c => [c.id, c.name]));
  const qRows = state.sl.quotes.map(q => `<tr><td><strong>${esc(q.quote_number)}</strong> <span class="muted">v${Number(q.version)}</span></td>` +
    `<td>${esc(clientMap[q.client_id] || 'Client #' + q.client_id)}</td><td>${esc(q.valid_until)}</td>` +
    `<td class="num">${esc(bkRs(q.total_paise))}</td><td>${q.accepted ? pill('Accepted', 'good') : pill('Draft', 'warn')}</td>` +
    `<td>${q.accepted
      ? `<button type="button" class="btn btn-secondary btn-sm" data-sl="quote-to-inv" data-id="${Number(q.id)}">Turn into Invoice →</button>`
      : `<button type="button" class="btn btn-secondary btn-sm" data-sl="accept-quote" data-id="${Number(q.id)}">Mark Accepted</button>`
    }</td></tr>`).join('');

  const iRows = state.sl.invoices.map(i => `<tr><td><strong>${esc(i.invoice_number)}</strong></td>` +
    `<td>${esc(i.client_name || 'Client #' + i.client_id)}</td><td>${esc(i.invoice_date)}</td><td>${esc(i.due_date)}</td>` +
    `<td class="num">${esc(bkRs(i.total_paise))}</td><td>${i.reversed ? pill('Reversed', 'critical') : pill('Posted', 'good')}</td>` +
    `<td><a class="btn btn-secondary btn-sm" href="/api/sales/invoices/${Number(i.id)}/pdf" target="_blank" rel="noopener">Download PDF</a></td></tr>`).join('');

  return head('Sales', 'Quotes, GST tax invoices, and credit notes.') + tiles + actions + formHtml +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Client quotes</div></div><div class="panel-body">` +
    (qRows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Quote</th><th>Client</th><th>Valid until</th><th>Total</th><th>Status</th><th>Action</th></tr></thead><tbody>${qRows}</tbody></table></div>` : '<p class="muted">No quotes yet.</p>') +
    `</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Client tax invoices</div></div><div class="panel-body">` +
    (iRows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Invoice</th><th>Client</th><th>Date</th><th>Due</th><th>Total</th><th>Status</th><th>PDF</th></tr></thead><tbody>${iRows}</tbody></table></div>` : '<p class="muted">No invoices yet.</p>') +
    `</div></section>`;
}

function slReceiptsView() {
  if (!SL_ROLES.includes(state.user?.role)) return head('Receipts & Retainers', 'For owner, accounts, and managers.');
  if (!state.sl.opts) {
    slLoadAll();
    return head('Receipts & Retainers', 'Client payments, TDS, retainers, and customer statements.') + '<div class="loading">Loading…</div>';
  }
  const opts = state.sl.opts;
  const entId = opts.companies[0]?.id;
  const auto = slAutoAccounts(opts, entId);
  const bankOpts = auto.bankCash.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
  const invOpts = state.sl.invoices.filter(i => !i.reversed).map(i => `<option value="${Number(i.id)}">${esc(i.invoice_number + ' · ' + i.client_name + ' (' + bkRs(i.total_paise) + ')')}</option>`).join('');
  const cliOpts = opts.clients.map(c => `<option value="${Number(c.id)}"${state.sl.stmtClientId === c.id ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const projOpts = '<option value="">No project</option>' + opts.projects.map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('');
  const today = opts.today || '';

  const stmt = state.sl.stmt;
  const stmtHtml = stmt
    ? `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(bkRs(stmt.receivable_paise))}</div><div class="v-tile-label">Open Receivable</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(stmt.unallocated_advance_paise))}</div><div class="v-tile-label">Unallocated Retainers</div></div></div>` +
      `<div class="w-sub">Invoices</div>` +
      (stmt.invoices.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Owed</th></tr></thead><tbody>${
        stmt.invoices.map(x => `<tr><td>${esc(x.invoice_number)}</td><td>${esc(x.invoice_date)}</td><td class="num">${esc(bkRs(x.total_paise))}</td><td class="num">${esc(bkRs(x.owed_paise))}</td></tr>`).join('')
      }</tbody></table></div>` : '<p class="muted">No invoices for this client.</p>') +
      `<div class="w-sub">Retainers / Advances</div>` +
      (stmt.advances.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Reference</th><th>Date</th><th>Received</th><th>Unallocated</th></tr></thead><tbody>${
        stmt.advances.map(x => `<tr><td>${esc(x.reference)}</td><td>${esc(x.receipt_date)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td><td class="num">${esc(bkRs(x.remaining_paise))}</td></tr>`).join('')
      }</tbody></table></div>` : '<p class="muted">No retainers for this client.</p>')
    : '<p class="muted">Pick a client above to view their statement.</p>';

  return head('Receipts & Retainers', 'Record client payments (with TDS), retainers, and view customer statements.') +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Record client payment against invoice</div></div><div class="panel-body">` +
    `<form id="slReceiptForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Invoice</span><select name="invoice_id" class="form-input" required>${invOpts}</select></label>` +
    `<label class="g-field"><span>Deposit into</span><select name="deposit_account_id" class="form-input" required>${bankOpts}</select></label>` +
    `<label class="g-field"><span>Received in bank (₹)</span><input name="amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>TDS deducted by client (₹)</span><input name="tds" class="form-input" inputmode="decimal" value="0.00"></label>` +
    `<label class="g-field"><span>Date</span><input type="date" name="receipt_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Reference / UTR</span><input name="reference" class="form-input" required maxlength="120" placeholder="NEFT / UPI ref"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send receipt for approval</button></div></form></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Record client retainer / advance</div></div><div class="panel-body">` +
    `<form id="slAdvanceForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Client</span><select name="client_id" class="form-input" required>${cliOpts}</select></label>` +
    `<label class="g-field"><span>Project (optional)</span><select name="project_id" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>Deposit into</span><select name="deposit_account_id" class="form-input" required>${bankOpts}</select></label>` +
    `<label class="g-field"><span>Amount (₹)</span><input name="amount" class="form-input" inputmode="decimal" required placeholder="0.00"></label>` +
    `<label class="g-field"><span>Date</span><input type="date" name="receipt_date" class="form-input" required value="${esc(today)}"></label>` +
    `<label class="g-field"><span>Reference</span><input name="reference" class="form-input" required maxlength="120" placeholder="Retainer UTR"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send retainer for approval</button></div></form></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Customer statement</div></div><div class="panel-body">` +
    `<div class="g-form"><label class="g-field"><span>Select client</span><select id="slStmtClient" class="form-input"><option value="">Choose client…</option>${cliOpts}</select></label></div>` +
    `<div class="section-gap">${stmtHtml}</div></div></section>`;
}

const SL_VIEWS = {sales: ['Sales', slSalesView], receipts: ['Receipts & Retainers', slReceiptsView]};
const _slRender = render;
render = function () {
  const v = SL_VIEWS[state.view];
  if (!v) { _slRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = v[1]().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / ' + v[0].toUpperCase());
  $('breadcrumb').textContent = v[0];
};

document.addEventListener('click', async e => {
  const tf = e.target.closest('[data-sl="toggle-form"]');
  if (tf) {
    const f = tf.dataset.form;
    state.sl.prefillQuote = null;
    state.sl.formOpen = state.sl.formOpen === f ? '' : f;
    render();
    return;
  }
  const addQ = e.target.closest('[data-sl="add-q-line"]');
  if (addQ && state.sl.opts) {
    const form = document.getElementById('slQuoteForm');
    const entId = form ? Number(form.entity_id.value) : state.sl.opts.companies[0]?.id;
    document.getElementById('slQuoteLines')?.insertAdjacentHTML('beforeend', slLineRowHtml(state.sl.opts, entId, false));
    return;
  }
  const addI = e.target.closest('[data-sl="add-i-line"]');
  if (addI && state.sl.opts) {
    const form = document.getElementById('slInvoiceForm');
    const entId = form ? Number(form.entity_id.value) : state.sl.opts.companies[0]?.id;
    document.getElementById('slInvLines')?.insertAdjacentHTML('beforeend', slLineRowHtml(state.sl.opts, entId, true));
    return;
  }
  const accQ = e.target.closest('[data-sl="accept-quote"]');
  if (accQ) {
    try {
      const res = await api(`/api/sales/quotes/${Number(accQ.dataset.id)}/accept`, {
        method: 'POST',
        body: JSON.stringify({accepted_date: state.sl.opts?.today || new Date().toISOString().slice(0, 10), note: 'Accepted in Sales UI'}),
      });
      notify(`Quote acceptance draft #${res.ticket_id} sent for approval.`);
      slLoadAll();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const q2i = e.target.closest('[data-sl="quote-to-inv"]');
  if (q2i) {
    const q = state.sl.quotes.find(x => x.id === Number(q2i.dataset.id));
    if (q) {
      state.sl.prefillQuote = q;
      state.sl.formOpen = 'invoice';
      render();
    }
  }
});

document.addEventListener('change', async e => {
  if (e.target.id === 'slStmtClient') {
    const cid = Number(e.target.value);
    state.sl.stmtClientId = cid || null;
    state.sl.stmt = null;
    if (cid) {
      try { state.sl.stmt = await api(`/api/sales/clients/${cid}/statement`); }
      catch (err) { notify(err.message, true); }
    }
    render();
  }
});

document.addEventListener('submit', async e => {
  const qf = e.target.closest('#slQuoteForm');
  if (qf) {
    e.preventDefault();
    try {
      const lines = Array.from(qf.querySelectorAll('.sl-line')).map(r => ({
        description: r.querySelector('[name="sl_desc"]').value.trim(),
        sac_hsn: r.querySelector('[name="sl_sac"]').value.trim(),
        quantity: Number(r.querySelector('[name="sl_qty"]').value),
        rate_paise: bkParsePaise(r.querySelector('[name="sl_rate"]').value),
        tax_rate_bps: Number(r.querySelector('[name="sl_gst"]').value),
      }));
      const res = await api('/api/sales/quotes', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(qf.entity_id.value), client_id: Number(qf.client_id.value),
          project_id: qf.project_id.value ? Number(qf.project_id.value) : null,
          quote_number: qf.quote_number.value.trim(), quote_date: qf.quote_date.value,
          valid_until: qf.valid_until.value, lines, note: qf.note.value.trim(),
          request_key: qf.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Quote draft #${res.ticket_id} sent for approval.`);
      state.sl.formOpen = '';
      slLoadAll();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const inf = e.target.closest('#slInvoiceForm');
  if (inf) {
    e.preventDefault();
    try {
      const entId = Number(inf.entity_id.value);
      const auto = slAutoAccounts(state.sl.opts, entId);
      const lines = Array.from(inf.querySelectorAll('.sl-line')).map(r => ({
        income_account_id: Number(r.querySelector('[name="sl_inc"]').value),
        description: r.querySelector('[name="sl_desc"]').value.trim(),
        sac_hsn: r.querySelector('[name="sl_sac"]').value.trim(),
        quantity: Number(r.querySelector('[name="sl_qty"]').value),
        rate_paise: bkParsePaise(r.querySelector('[name="sl_rate"]').value),
        tax_rate_bps: Number(r.querySelector('[name="sl_gst"]').value),
      }));
      const res = await api('/api/sales/invoices', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: entId, client_id: Number(inf.client_id.value),
          project_id: inf.project_id.value ? Number(inf.project_id.value) : null,
          quote_id: inf.dataset.quoteId ? Number(inf.dataset.quoteId) : null,
          invoice_number: inf.invoice_number.value.trim(), invoice_date: inf.invoice_date.value,
          due_date: inf.due_date.value, place_of_supply: inf.place_of_supply.value.trim(),
          supply_type: inf.supply_type.value,
          ar_account_id: auto.ar?.id, cgst_account_id: auto.cgst?.id || null,
          sgst_account_id: auto.sgst?.id || null, igst_account_id: auto.igst?.id || null,
          rounding_account_id: auto.rounding?.id || null,
          lines, request_key: inf.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Invoice draft #${res.ticket_id} sent for approval.`);
      state.sl.formOpen = '';
      state.sl.prefillQuote = null;
      slLoadAll();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const cnf = e.target.closest('#slCreditNoteForm');
  if (cnf) {
    e.preventDefault();
    try {
      const entId = Number(cnf.entity_id.value);
      const auto = slAutoAccounts(state.sl.opts, entId);
      const res = await api('/api/sales/credit-notes', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: entId, client_id: Number(cnf.client_id.value),
          note_number: cnf.note_number.value.trim(), note_date: cnf.note_date.value,
          ar_account_id: auto.ar?.id, income_account_id: auto.income?.id,
          tax_account_id: auto.cgst?.id || null,
          taxable_paise: bkParsePaise(cnf.taxable.value), tax_paise: bkParsePaise(cnf.tax.value),
          reason: cnf.reason.value.trim(), request_key: cnf.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Credit note draft #${res.ticket_id} sent for approval.`);
      state.sl.formOpen = '';
      slLoadAll();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const rf = e.target.closest('#slReceiptForm');
  if (rf) {
    e.preventDefault();
    try {
      const entId = state.sl.opts?.companies[0]?.id;
      const auto = slAutoAccounts(state.sl.opts, entId);
      const tds = bkParsePaise(rf.tds.value);
      const res = await api('/api/sales/receipts', {
        method: 'POST',
        body: JSON.stringify({
          invoice_id: Number(rf.invoice_id.value), deposit_account_id: Number(rf.deposit_account_id.value),
          tds_account_id: tds > 0 ? auto.tds?.id : null,
          amount_paise: bkParsePaise(rf.amount.value), tds_paise: tds,
          receipt_date: rf.receipt_date.value, reference: rf.reference.value.trim(),
          request_key: rf.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Client receipt draft #${res.ticket_id} sent for approval.`);
      slLoadAll();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const af = e.target.closest('#slAdvanceForm');
  if (af) {
    e.preventDefault();
    try {
      const entId = Number(af.entity_id.value);
      const auto = slAutoAccounts(state.sl.opts, entId);
      const res = await api('/api/sales/advances', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: entId, client_id: Number(af.client_id.value),
          project_id: af.project_id.value ? Number(af.project_id.value) : null,
          deposit_account_id: Number(af.deposit_account_id.value),
          advance_account_id: auto.advance?.id,
          amount_paise: bkParsePaise(af.amount.value),
          receipt_date: af.receipt_date.value, reference: af.reference.value.trim(),
          request_key: af.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Client retainer draft #${res.ticket_id} sent for approval.`);
      slLoadAll();
    } catch (err) { notify(err.message, true); }
  }
});
