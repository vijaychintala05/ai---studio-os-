'use strict';
/* Money -> Stock and purchases: one supplier bill in detail, posted costs of a project, stock on a purchase order
   (receive, bill, issue to site) and the company's purchase path. Home -> My claims: your own out-of-pocket claims.
   Stock actions start from a chosen order, so nobody types record numbers. Loaded after gapkit.js. */

const FD_PATHS = [['bills', 'Purchase orders and supplier bills'], ['text', 'Typed entries in the chat']];
const FD_EVIDENCE = 'Entered on the Bills and stock screen; check the delivery or invoice papers before approving.';

const fdPropose = (kind, data) => gkDraft('/api/finance-ledger/proposals', {kind, data, evidence: FD_EVIDENCE});

function fdWhole(raw, what) {
  if (!/^\d{1,9}$/.test(String(raw).trim()) || Number(raw) <= 0) throw new Error(`Give ${what} as a whole number above zero.`);
  return Number(raw);
}

function fdMoney(raw, what) {
  const paise = gkPaise(raw);
  if (!paise) throw new Error(`Give ${what} in rupees, for example 350.50.`);
  return paise;
}

function fdView() {
  const title = 'Stock and purchases';
  const companies = gkGet('fd:companies', async () => (await api('/api/books/home')).companies);
  if (!Array.isArray(companies)) return head(title) + gkWait(companies);
  if (!companies.length) return head(title) + '<p class="muted">Set up a company in Books first.</p>';
  const ui = state.gk.ui;
  if (!companies.some(c => c.entity_id === ui.fdEntity)) ui.fdEntity = companies[0].entity_id;
  const pick = `<div class="g-form">${gkSelect('Company', 'company', companies.map(c => [c.entity_id, c.name]), ui.fdEntity, 'data-gk-change="company"')}</div>`;
  return head(title, 'Supplier bills, project costs and materials on purchase orders.') + gkPanel('Company', '', pick) +
    fdBills() + fdStock() + fdProject() + fdPath();
}

function fdBills() {
  const ui = state.gk.ui;
  const pay = gkGet(`fd:pay:${ui.fdEntity}`, () => api(`/api/finance-ledger/payables/${Number(ui.fdEntity)}`));
  let list = gkWait(pay);
  if (pay && pay.bills) {
    list = gkTable(['Invoice', 'Amount', 'Still owed', ''], pay.bills.map(b => [esc(b.invoice_number) + (b.reversed ? ' ' + pill('Reversed', 'warn') : ''),
      esc(gkRs(b.gross_paise)), esc(gkRs(b.outstanding_paise)), gkButton('bill', 'Details', `data-id="${Number(b.bill_id)}"`)]), 'No supplier bill from a purchase order yet.');
  }
  let detail = '';
  if (ui.fdBill) {
    const b = gkGet(`fd:bill:${ui.fdBill}`, () => api(`/api/finance-ledger/bills/${Number(ui.fdBill)}`));
    detail = b && b.bill_id
      ? gkTable(['Bill', 'Value'], [['Bill date', esc(b.bill_date || 'Not recorded')], ['Due', esc(b.due_date || 'Not recorded')],
        ['Amount', esc(gkRs(b.amount_paise))], ['Still owed', esc(gkRs(b.outstanding_paise))], ['Purchase order', `#${Number(b.po_id)}`],
        ['Posted in the books as', `journal ${Number(b.posted_journal_id)}`]], '') +
        `<p class="muted">Its documents are under Money → Attachments (supplier bill #${Number(b.bill_id)}).</p>`
      : gkWait(b);
  }
  return gkPanel('Supplier bills', 'From purchase orders.', list + detail);
}

function fdStock() {
  const ui = state.gk.ui;
  const opts = gkGet('fd:options', () => api('/api/sales/options'));
  if (!opts || !opts.vendors) return gkPanel('Stock on purchase orders', '', gkWait(opts));
  if (!opts.vendors.length) return gkPanel('Stock on purchase orders', '', '<p class="muted">No vendor yet.</p>');
  if (!opts.vendors.some(v => v.id === ui.fdVendor)) ui.fdVendor = opts.vendors[0].id;
  const party = gkGet(`fd:party:${ui.fdVendor}`, () => api(`/api/books/parties/${Number(ui.fdVendor)}`));
  const orders = party && party.orders ? party.orders : null;
  let body = `<div class="g-form">${gkSelect('Vendor', 'vendor', opts.vendors.map(v => [v.id, v.name]), ui.fdVendor, 'data-gk-change="vendor"')}`;
  if (!orders) return gkPanel('Stock on purchase orders', '', body + '</div>' + gkWait(party));
  if (!orders.some(o => o.id === ui.fdOrder)) ui.fdOrder = orders.length ? orders[orders.length - 1].id : null;
  body += orders.length ? gkSelect('Purchase order (last 10)', 'order', orders.map(o => [o.id, `${o.po_number} · ${gkRs(o.amount_paise)}`]), ui.fdOrder, 'data-gk-change="order"') + '</div>' : '</div><p class="muted">No purchase order for this vendor.</p>';
  if (ui.fdOrder) {
    const s = gkGet(`fd:stock:${ui.fdOrder}`, () => api(`/api/finance-ledger/inventory/po/${Number(ui.fdOrder)}`));
    if (!s || !s.receipts) body += gkWait(s);
    else {
      body += gkTable(['Received', 'Quantity', 'Value'], s.receipts.map(r => ['Received', Number(r.quantity), esc(gkRs(r.value_paise))])
        .concat(s.issues.map(i => ['Issued to site', Number(i.quantity), esc(gkRs(i.value_paise))])), 'Nothing received on this order yet.');
      body += gkForm('grn', gkInput('Quantity received', 'quantity', 'required inputmode="numeric"') + gkInput('Cost of one (₹)', 'unit', 'required inputmode="decimal"') +
        gkInput('Delivery note number', 'reference', 'required maxlength="120"'), 'Draft goods receipt');
      body += gkForm('invbill', gkInput('Supplier invoice number', 'invoice', 'required maxlength="120"') + gkInput('Invoice amount (₹)', 'amount', 'required inputmode="decimal"') +
        gkInput('Invoice date', 'bill_date', '', 'date') + gkInput('Due date', 'due_date', '', 'date') + gkInput('Payment terms (days)', 'terms', 'inputmode="numeric"'), 'Draft stock invoice');
      body += gkForm('issue', gkInput('Quantity issued to site', 'quantity', 'required inputmode="numeric"') + gkInput('Issue slip number', 'reference', 'required maxlength="120"'), 'Draft material issue');
    }
  }
  const enable = isAdmin() ? gkForm('enable', gkInput('Stock account code', 'inventory_code', 'required maxlength="20" placeholder="1400"') +
    gkInput('Goods-received-not-billed account code', 'grni_code', 'required maxlength="20" placeholder="2200"'), 'Draft: turn stock tracking on') : '';
  return gkPanel('Stock on purchase orders', 'Receive goods, record the invoice, issue material to site.', body + enable);
}

function fdProject() {
  const ui = state.gk.ui;
  const projects = gkGet('fd:projects', () => api('/api/projects'));
  if (!Array.isArray(projects)) return gkPanel('Posted project costs', '', gkWait(projects));
  if (!projects.length) return '';
  if (!projects.some(p => p.id === ui.fdProject)) ui.fdProject = projects[0].id;
  const c = gkGet(`fd:cost:${ui.fdProject}`, () => api(`/api/finance-ledger/project-costs/${Number(ui.fdProject)}`));
  const result = c && c.entries
    ? `<p><strong>${esc(gkRs(c.posted_material_expense_net_paise))}</strong> posted as expense. ${esc(c.basis)}${c.truncated ? ' Showing the first 1,000 lines.' : ''}</p>` +
      gkTable(['Journal', 'Account', 'Amount'], c.entries.slice(-50).reverse().map(e => [Number(e.journal_id), esc(e.account_code), (e.side === 'credit' ? '−' : '') + esc(gkRs(e.amount_paise))]), 'Nothing posted for this project yet.')
    : gkWait(c);
  return gkPanel('Posted project costs', 'What the books actually hold for a project.',
    `<div class="g-form">${gkSelect('Project', 'project', projects.map(p => [p.id, p.name]), ui.fdProject, 'data-gk-change="project"')}</div>` + result);
}

function fdPath() {
  const ui = state.gk.ui;
  const p = gkGet(`fd:path:${ui.fdEntity}`, () => api(`/api/finance-ledger/purchase-path/${Number(ui.fdEntity)}`));
  if (!p || p.gkError || p.how === undefined) return gkPanel('How purchases reach the books', '', gkWait(p));
  const now = p.path ? (FD_PATHS.find(x => x[0] === p.path) || [0, p.path])[1] : 'Not chosen yet';
  const form = isAdmin() ? gkForm('path', gkSelect('Use', 'path', FD_PATHS, p.path || 'bills'), 'Save choice') : '<p class="muted">Only the Admin can change this.</p>';
  return gkPanel('How purchases reach the books', 'One way per company, so a purchase is never counted twice.', `<p>Now: <strong>${esc(now)}</strong></p>` + form);
}

gkScreen('findetail', {
  title: 'Stock and purchases', roles: ['admin', 'accounts'], view: fdView,
  change: {
    company: el => Object.assign(state.gk.ui, {fdEntity: Number(el.value), fdBill: null}),
    vendor: el => Object.assign(state.gk.ui, {fdVendor: Number(el.value), fdOrder: null}),
    order: el => { state.gk.ui.fdOrder = Number(el.value); },
    project: el => { state.gk.ui.fdProject = Number(el.value); },
  },
  click: {bill: el => { state.gk.ui.fdBill = Number(el.dataset.id); }},
  submit: {
    grn: async form => { const v = gkValues(form); await fdPropose('finance_goods_receipt', {po_id: state.gk.ui.fdOrder, quantity: fdWhole(v.quantity, 'the quantity'),
      unit_cost_paise: fdMoney(v.unit, 'the cost of one'), receipt_reference: v.reference, idempotency_key: gkKey()}); },
    invbill: async form => {
      const v = gkValues(form);
      await fdPropose('finance_inventory_bill', {po_id: state.gk.ui.fdOrder, invoice_number: v.invoice, amount_paise: fdMoney(v.amount, 'the invoice amount'),
        ...(v.bill_date ? {bill_date: v.bill_date} : {}), ...(v.due_date ? {due_date: v.due_date} : {}), ...(v.terms ? {payment_terms_days: Number(v.terms)} : {})});
    },
    issue: async form => { const v = gkValues(form); await fdPropose('finance_material_issue', {po_id: state.gk.ui.fdOrder, quantity: fdWhole(v.quantity, 'the quantity'),
      issue_reference: v.reference, idempotency_key: gkKey()}); },
    enable: async form => { const v = gkValues(form); await fdPropose('finance_enable_inventory', {entity_id: state.gk.ui.fdEntity, inventory_code: v.inventory_code, grni_code: v.grni_code}); },
    path: async form => {
      const v = gkValues(form);
      if (!await askConfirm('Change how purchases reach the books for this company?', 'Save choice')) return;
      await api(`/api/finance-ledger/purchase-path/${Number(state.gk.ui.fdEntity)}`, {method: 'PUT', body: JSON.stringify({path: v.path})});
      gkForget('fd:path:');
      notify('Purchase path saved.');
    },
  },
});

function claimsView() {
  const title = 'My claims';
  const c = gkGet('claims:mine', () => api('/api/reimbursements/mine'));
  if (!c || !c.claims) return head(title) + gkWait(c);
  return head(title, 'Money you spent for the studio that has not been paid back yet.') +
    gkPanel(`${gkRs(c.owed_paise)} owed to you`, '', gkTable(['Date', 'What for', 'Amount'], c.claims.map(x => [esc(x.date), esc(x.note || ''), esc(gkRs(x.amount_paise))]), 'Nothing is owed to you right now.'));
}

gkScreen('myclaims', {title: 'My claims', view: claimsView});
