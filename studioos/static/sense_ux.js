'use strict';
/* SENSE STUDIOS — Ease-of-Use Flows Layer (Global + New, Slide-Over Drawers, Smart Vendor Auto-Fill,
   Immediate Review & Approve Sheet, and Zoho-style Quick Account / Client / Bill creation).
   Every write still opens an approval ticket (the AI/UI proposes, a person approves).
   Zero inline styles or inline event handlers (strict CSP). Loaded after nav.js. */

const SENSE_DRAWER = {open: false, kind: null, ticketId: null};

const SENSE_ACCOUNT_TYPES = [
  ['cash', 'Cash'], ['bank', 'Bank'], ['other_current_asset', 'Other Current Asset'],
  ['fixed_asset', 'Fixed Asset'], ['accounts_receivable', 'Accounts Receivable'], ['stock', 'Stock / Inventory'],
  ['other_current_liability', 'Other Current Liability'], ['accounts_payable', 'Accounts Payable'],
  ['credit_card', 'Credit Card'], ['long_term_liability', 'Long-Term Liability'], ['other_liability', 'Other Liability'],
  ['equity', 'Equity'], ['income', 'Income'], ['other_income', 'Other Income'],
  ['cost_of_goods_sold', 'Cost of Goods Sold'], ['expense', 'Expense'], ['other_expense', 'Other Expense'],
  ['input_tax', 'Input Tax (GST)'], ['output_tax', 'Output Tax (GST)'],
];

function senseQuickItemsForRole(role) {
  const groups = [];
  if (['admin', 'accounts'].includes(role)) {
    groups.push({
      label: 'Books & Purchases',
      items: [
        {id: 'bill', title: 'Supplier bill', hint: 'GST · TDS · PO'},
        {id: 'due', title: 'Pay bills due', hint: 'Batch payment'},
        {id: 'vendor', title: 'New vendor', hint: 'GSTIN · PAN · TDS'},
        {id: 'client', title: 'New client', hint: 'Billing profile'},
        {id: 'account', title: 'New account / bank', hint: 'Chart of accounts'},
        {id: 'transfer', title: 'Move money', hint: 'Bank / Cash'},
        {id: 'journal', title: 'Manual journal', hint: 'Debit / Credit'},
      ],
    });
  }
  if (['admin', 'manager', 'accounts'].includes(role)) {
    groups.push({
      label: 'Sales & Projects',
      items: [
        {id: 'sales-view', title: 'Sales quote or invoice', hint: 'Open Sales'},
        {id: 'project-new', title: 'New project', hint: 'Studio project'},
      ],
    });
  }
  if (['admin', 'manager', 'architect', 'site_engineer'].includes(role)) {
    groups.push({
      label: 'Studio & Site',
      items: [
        {id: 'site-report', title: 'Log site report', hint: 'Daily update'},
        {id: 'expense-new', title: 'Record site expense', hint: 'Receipt / cost'},
      ],
    });
  }
  return groups;
}

function senseRenderQuickMenu() {
  const menu = $('senseQuickNewMenu');
  const btn = $('senseQuickNewBtn');
  if (!menu || !btn) return;
  const role = state.user?.role || '';
  const groups = senseQuickItemsForRole(role);
  btn.hidden = groups.length === 0;
  if (!groups.length) { menu.hidden = true; return; }
  menu.innerHTML = groups.map(g =>
    `<div class="sense-quick-group">${esc(g.label)}</div>` +
    g.items.map(it =>
      `<button type="button" class="sense-quick-item" role="menuitem" data-sense-new="${esc(it.id)}">` +
      `<span>${esc(it.title)}</span><span class="sense-quick-hint">${esc(it.hint)}</span></button>`
    ).join('')
  ).join('');
}

function senseCloseQuickMenu() {
  const menu = $('senseQuickNewMenu');
  const btn = $('senseQuickNewBtn');
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function openSenseDrawer(title, subtitle, bodyHtml, footHtml = '', kind = null) {
  const drawer = $('senseDrawer');
  const scrim = $('senseDrawerScrim');
  if (!drawer || !scrim) return;
  SENSE_DRAWER.open = true;
  SENSE_DRAWER.kind = kind;
  $('senseDrawerTitle').textContent = title || 'StudioOS';
  $('senseDrawerSub').textContent = subtitle || '';
  $('senseDrawerBody').innerHTML = bodyHtml || '';
  const foot = $('senseDrawerFoot');
  if (foot) {
    foot.innerHTML = footHtml || '';
    foot.hidden = !footHtml;
  }
  scrim.hidden = false;
  drawer.hidden = false;
  requestAnimationFrame(() => {
    scrim.classList.add('open');
    drawer.classList.add('open');
    const focusable = drawer.querySelector('input:not([type="hidden"]), select, textarea, button:not(#senseDrawerClose)');
    if (focusable) focusable.focus();
  });
}

function closeSenseDrawer() {
  const drawer = $('senseDrawer');
  const scrim = $('senseDrawerScrim');
  if (!drawer || !scrim) return;
  SENSE_DRAWER.open = false;
  SENSE_DRAWER.kind = null;
  SENSE_DRAWER.ticketId = null;
  scrim.classList.remove('open');
  drawer.classList.remove('open');
  setTimeout(() => {
    if (!SENSE_DRAWER.open) {
      scrim.hidden = true;
      drawer.hidden = true;
    }
  }, 240);
}

function senseClientFormHtml() {
  return `<form id="senseClientForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Client name *</span><input name="name" class="form-input" required maxlength="200" placeholder="e.g. Meera & Rohan Residence"></label>` +
    `<label class="g-field"><span>GST treatment *</span><select name="gst_treatment" class="form-input" required><option value="unregistered">Unregistered / Individual</option><option value="registered_regular">Registered — Regular</option><option value="registered_composition">Registered — Composition</option><option value="overseas">Overseas</option></select></label>` +
    `<label class="g-field"><span>GSTIN (if registered)</span><input name="gstin" class="form-input" maxlength="15" placeholder="29ABCDE1234F1Z5"></label>` +
    `<label class="g-field"><span>PAN</span><input name="pan" class="form-input" maxlength="10" placeholder="ABCDE1234F"></label>` +
    `<label class="g-field"><span>State code (2-digit)</span><input name="state_code" class="form-input" maxlength="2" placeholder="29"></label>` +
    `<label class="g-field"><span>Phone (10 digits)</span><input name="phone" class="form-input" maxlength="10" placeholder="9876543210"></label>` +
    `<label class="g-field"><span>Email</span><input name="email" type="email" class="form-input" maxlength="120" placeholder="client@example.com"></label>` +
    `<label class="g-field"><span>Payment terms (days)</span><input name="payment_terms_days" type="number" class="form-input" min="0" max="365" value="15"></label>` +
    `<label class="g-field"><span>Billing address</span><input name="billing_address" class="form-input" maxlength="300" placeholder="Street, City, State"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send client for approval</button></div></form>`;
}

function senseAccountFormHtml(opts) {
  const companies = opts?.companies || [];
  if (!companies.length) return '<p class="muted">Set up a company first before adding an account.</p>';
  const entId = companies[0].id;
  const compOpts = companies.map(c => `<option value="${Number(c.id)}">${esc(c.name)}</option>`).join('');
  const typeOpts = SENSE_ACCOUNT_TYPES.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  const parents = (opts.accounts || []).filter(a => Number(a.entity_id) === Number(entId));
  const parentOpts = '<option value="">None (top-level account)</option>' +
    parents.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' · ' + a.name)}</option>`).join('');
  return `<form id="senseAccountForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company *</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Account type *</span><select name="account_type" class="form-input" required>${typeOpts}</select></label>` +
    `<label class="g-field"><span>Account name *</span><input name="name" class="form-input" required maxlength="160" placeholder="e.g. HDFC Current Account"></label>` +
    `<label class="g-field"><span>Account code</span><input name="code" class="form-input" maxlength="40" placeholder="Auto or custom e.g. 1115"></label>` +
    `<label class="g-field"><span>Sub-account of (optional)</span><select name="parent_account_id" class="form-input">${parentOpts}</select></label>` +
    `<label class="g-field"><span>Description</span><input name="description" class="form-input" maxlength="300" placeholder="What this account tracks"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send account for approval</button></div></form>`;
}

async function senseOpenAction(actionId) {
  senseCloseQuickMenu();
  if (actionId === 'sales-view') { switchView('sales'); return; }
  if (actionId === 'project-new') {
    if (typeof openCreate === 'function') openCreate('project');
    else switchView('projects');
    return;
  }
  if (actionId === 'site-report') {
    if (typeof openCreate === 'function') openCreate('site');
    else switchView('site');
    return;
  }
  if (actionId === 'expense-new') {
    if (typeof openCreate === 'function') openCreate('expense');
    else switchView('expenses');
    return;
  }
  if (actionId === 'vendor') {
    openSenseDrawer('New vendor', 'GST treatment, PAN, TDS section, and bank details.', bkVendorFormHtml(), '', 'vendor');
    return;
  }
  if (actionId === 'client') {
    openSenseDrawer('New client', 'Client billing profile with GSTIN and payment terms.', senseClientFormHtml(), '', 'client');
    return;
  }
  if (actionId === 'bill') {
    openSenseDrawer('New supplier bill', 'GST, TDS, Asset/COGS accounts, and partial PO billing.', '<div class="loading">Loading bill form…</div>', '', 'bill');
    try {
      if (!state.bk.billOpts) state.bk.billOpts = await api('/api/books/bill-options');
      if (SENSE_DRAWER.open && SENSE_DRAWER.kind === 'bill') {
        $('senseDrawerBody').innerHTML = bkBillFormHtml();
      }
    } catch (err) {
      notify(err.message, true);
      closeSenseDrawer();
    }
    return;
  }
  if (actionId === 'due') {
    openSenseDrawer('Bills due & Pay selected', 'Tick unpaid bills to pay together in one approval.', '<div class="loading">Loading bills due…</div>', '', 'due');
    try {
      state.bk.dueData = await api('/api/books/bills-due');
      if (SENSE_DRAWER.open && SENSE_DRAWER.kind === 'due') {
        $('senseDrawerBody').innerHTML = bkBillsDueHtml();
      }
    } catch (err) {
      notify(err.message, true);
      closeSenseDrawer();
    }
    return;
  }
  if (actionId === 'transfer' || actionId === 'journal' || actionId === 'account') {
    const titles = {
      transfer: ['Move money', 'Transfer between two bank or cash accounts.'],
      journal: ['Manual journal', 'Owner or accountant adjustment. Debits and credits must match.'],
      account: ['New account / bank', 'Add a bank, credit card, expense, COGS, or sub-account.'],
    };
    openSenseDrawer(titles[actionId][0], titles[actionId][1], '<div class="loading">Loading accounts…</div>', '', actionId);
    try {
      if (!state.bk.journalOpts) state.bk.journalOpts = await api('/api/books/journal-options');
      if (SENSE_DRAWER.open && SENSE_DRAWER.kind === actionId) {
        if (actionId === 'transfer') $('senseDrawerBody').innerHTML = bkTransferFormHtml();
        else if (actionId === 'journal') $('senseDrawerBody').innerHTML = bkManualJournalFormHtml();
        else $('senseDrawerBody').innerHTML = senseAccountFormHtml(state.bk.journalOpts);
      }
    } catch (err) {
      notify(err.message, true);
      closeSenseDrawer();
    }
  }
}

async function senseOfferImmediateReview(ticketId, heading = 'Draft created') {
  if (!ticketId) return;
  SENSE_DRAWER.ticketId = Number(ticketId);
  const canDirectApprove = state.user?.role === 'admin';
  openSenseDrawer(
    heading,
    `Ticket #${Number(ticketId)} is ready for review.`,
    '<div class="loading">Loading approval preview…</div>',
    '',
    'review'
  );
  try {
    const ticket = await api(`/api/tickets/${Number(ticketId)}`);
    const items = ticket.items || [];
    const summaryRows = items.map(it => {
      const label = it.summary || it.kind || 'Entry';
      return `<dt>${esc(String(it.kind || 'item').replace(/_/g, ' '))}</dt><dd>${esc(label)}</dd>`;
    }).join('');
    const approveBtn = canDirectApprove
      ? `<button type="button" class="btn btn-accent" data-sense-approve="${Number(ticketId)}">Approve &amp; Post</button>`
      : '';
    const body = `<div class="sense-review-box">` +
      `<div class="sense-review-kicker">Approval Ticket #${Number(ticketId)} · ${esc(ticket.status || 'pending')}</div>` +
      `<p>${esc(ticket.title || heading)}</p>` +
      (summaryRows ? `<dl class="sense-review-rows">${summaryRows}</dl>` : '') +
      `<p class="muted">${canDirectApprove ? 'As Admin, you can approve and post this immediately, or leave it in your Inbox.' : 'Sent to the Inbox for approval (two-person rule applies to money entries).'}</p>` +
      `</div>`;
    const foot = `${approveBtn}<button type="button" class="btn btn-secondary" data-sense-goto-inbox="1">Open Inbox</button>` +
      `<button type="button" class="btn btn-secondary" data-sense-close="1">Done</button>`;
    if (SENSE_DRAWER.open && SENSE_DRAWER.kind === 'review') {
      $('senseDrawerBody').innerHTML = body;
      const footEl = $('senseDrawerFoot');
      if (footEl) { footEl.innerHTML = foot; footEl.hidden = false; }
    }
  } catch (err) {
    if (SENSE_DRAWER.open && SENSE_DRAWER.kind === 'review') {
      $('senseDrawerBody').innerHTML = `<div class="sense-review-box"><p>Ticket #${Number(ticketId)} was created and sent to your Inbox.</p></div>`;
      const footEl = $('senseDrawerFoot');
      if (footEl) {
        footEl.innerHTML = `<button type="button" class="btn btn-secondary" data-sense-goto-inbox="1">Open Inbox</button><button type="button" class="btn btn-primary" data-sense-close="1">Done</button>`;
        footEl.hidden = false;
      }
    }
  }
}

// Smart Vendor Auto-Fill on #bkBillForm: selecting a vendor populates Payment Terms, Due Date, and Default TDS Section
function senseApplyVendorDefaults(form) {
  if (!form || !state.bk.billOpts?.vendors) return;
  const vid = Number(form.supplier_id?.value);
  const vendor = state.bk.billOpts.vendors.find(v => Number(v.id) === vid);
  if (!vendor) return;
  if (vendor.payment_terms_days != null && form.payment_terms_days) {
    form.payment_terms_days.value = String(vendor.payment_terms_days);
    const due = bkAddDays(form.bill_date?.value, vendor.payment_terms_days);
    if (due && form.due_date) form.due_date.value = due;
  }
  if (vendor.default_tds_section && form.tds_section) {
    form.tds_section.value = vendor.default_tds_section;
  }
}

// Hook into render so Global + New menu updates with current user role
const _senseUxRender = render;
render = function () {
  _senseUxRender();
  senseRenderQuickMenu();
};

document.addEventListener('click', async e => {
  const qBtn = e.target.closest('#senseQuickNewBtn');
  if (qBtn) {
    const menu = $('senseQuickNewMenu');
    if (!menu) return;
    senseRenderQuickMenu();
    const opening = menu.hidden;
    menu.hidden = !opening;
    qBtn.setAttribute('aria-expanded', String(opening));
    return;
  }
  const qItem = e.target.closest('[data-sense-new]');
  if (qItem) {
    senseOpenAction(qItem.dataset.senseNew);
    return;
  }
  if (!e.target.closest('#senseQuickWrap')) senseCloseQuickMenu();

  if (e.target.closest('#senseDrawerClose') || e.target.closest('#senseDrawerScrim') || e.target.closest('[data-sense-close]')) {
    closeSenseDrawer();
    return;
  }
  if (e.target.closest('[data-sense-goto-inbox]')) {
    closeSenseDrawer();
    switchView('tickets');
    return;
  }
  const approveBtn = e.target.closest('[data-sense-approve]');
  if (approveBtn) {
    const tid = Number(approveBtn.dataset.senseApprove);
    approveBtn.disabled = true;
    try {
      await api(`/api/tickets/${tid}/approve-and-save`, {method: 'POST', body: JSON.stringify({})});
      notify(`Ticket #${tid} approved and posted.`);
      closeSenseDrawer();
      state.bk.home = null;
      state.bk.billOpts = null;
      state.bk.journalOpts = null;
      state.home.data = null;
      await refresh();
    } catch (err) {
      notify(err.message, true);
      approveBtn.disabled = false;
    }
    return;
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    senseCloseQuickMenu();
    if (SENSE_DRAWER.open) closeSenseDrawer();
  }
});

document.addEventListener('change', e => {
  const billForm = e.target.closest('#bkBillForm');
  if (billForm && e.target.name === 'supplier_id') {
    senseApplyVendorDefaults(billForm);
    return;
  }
  const accForm = e.target.closest('#senseAccountForm');
  if (accForm && e.target.name === 'entity_id' && state.bk.journalOpts) {
    const entId = Number(accForm.entity_id.value);
    const parents = (state.bk.journalOpts.accounts || []).filter(a => Number(a.entity_id) === entId);
    accForm.parent_account_id.innerHTML = '<option value="">None (top-level account)</option>' +
      parents.map(a => `<option value="${Number(a.id)}">${esc(a.code + ' · ' + a.name)}</option>`).join('');
  }
});

document.addEventListener('submit', async e => {
  const cForm = e.target.closest('#senseClientForm');
  if (cForm) {
    e.preventDefault();
    const btn = cForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/clients', {
        method: 'POST',
        body: JSON.stringify({
          name: cForm.name.value.trim(),
          gst_treatment: cForm.gst_treatment.value,
          gstin: cForm.gstin.value.trim(),
          pan: cForm.pan.value.trim(),
          state_code: cForm.state_code.value.trim(),
          phone: cForm.phone.value.trim(),
          email: cForm.email.value.trim(),
          payment_terms_days: Number(cForm.payment_terms_days.value || 15),
          billing_address: cForm.billing_address.value.trim(),
          request_key: cForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Client draft #${res.ticket_id} sent for approval.`);
      await senseOfferImmediateReview(res.ticket_id, 'Client draft ready');
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
    return;
  }
  const aForm = e.target.closest('#senseAccountForm');
  if (aForm) {
    e.preventDefault();
    const btn = aForm.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/accounts', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(aForm.entity_id.value),
          account_type: aForm.account_type.value,
          name: aForm.name.value.trim(),
          code: aForm.code.value.trim(),
          parent_account_id: aForm.parent_account_id.value ? Number(aForm.parent_account_id.value) : null,
          description: aForm.description.value.trim(),
          request_key: aForm.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Account draft #${res.ticket_id} sent for approval.`);
      state.bk.journalOpts = null;
      await senseOfferImmediateReview(res.ticket_id, 'Account draft ready');
      refresh();
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }
});
