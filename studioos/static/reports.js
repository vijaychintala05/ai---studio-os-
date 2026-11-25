'use strict';
/* StudioOS M3 Financial Reports (Profit & Loss, Balance Sheet, Cash Flow, Budget vs. Actual)
   and Tax Helper, Recurring Templates (draft-only), and Account Budgets screens.
   Strict CSP: zero inline styles or handlers. Owner & accounts only. */

Object.assign(state, {
  rp: {
    opts: null, entityId: null, projectId: '', dateFrom: '', dateTo: '',
    month: new Date().toISOString().slice(0, 7),
    tab: 'pnl', data: null, loading: false,
    taxPreview: null, recurring: [],
  },
});

const RP_ROLES = ['admin', 'accounts'];

async function rpInit() {
  if (state.rp.loading) return;
  state.rp.loading = true;
  try {
    const [opts, rec] = await Promise.all([api('/api/sales/options'), api('/api/books/recurring')]);
    state.rp.opts = opts;
    state.rp.recurring = rec.entries || [];
    if (!state.rp.entityId && opts.companies.length) state.rp.entityId = opts.companies[0].id;
    if (opts.today) state.rp.month = opts.today.slice(0, 7);
    await rpFetchReport();
  } catch (err) {
    notify(err.message, true);
  } finally {
    state.rp.loading = false;
    render();
  }
}

async function rpFetchReport() {
  const entId = state.rp.entityId;
  if (!entId) return;
  const tab = state.rp.tab;
  const qs = new URLSearchParams({entity_id: String(entId)});
  let url = '/api/books/reports/pnl';
  if (tab === 'pnl') {
    if (state.rp.projectId) qs.set('project_id', state.rp.projectId);
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else if (tab === 'bs') {
    url = '/api/books/reports/balance-sheet';
    if (state.rp.dateTo) qs.set('as_of', state.rp.dateTo);
  } else if (tab === 'cf') {
    url = '/api/books/reports/cash-flow';
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else {
    url = '/api/books/reports/budget-vs-actual';
    qs.set('year_month', state.rp.month || new Date().toISOString().slice(0, 7));
  }
  state.rp.data = await api(`${url}?${qs.toString()}`);
}

function rpBodyHtml() {
  const d = state.rp.data;
  if (!d) return '<p class="muted">Select a company to load this report.</p>';
  if (state.rp.tab === 'pnl') {
    const incRows = (d.income || []).map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('');
    const expRows = (d.expenses || []).map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('');
    return `<div class="v-tiles">` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.total_income_paise))}</div><div class="v-tile-label">Total Income</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.total_expense_paise))}</div><div class="v-tile-label">Total Expenses</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.net_profit_paise))}</div><div class="v-tile-label">Net Profit</div></div></div>` +
      `<div class="w-sub">Income</div>${incRows ? `<div class="w-table-wrap"><table class="w-table"><tbody>${incRows}</tbody></table></div>` : '<p class="muted">No posted income.</p>'}` +
      `<div class="w-sub">Expenses</div>${expRows ? `<div class="w-table-wrap"><table class="w-table"><tbody>${expRows}</tbody></table></div>` : '<p class="muted">No posted expenses.</p>'}`;
  }
  if (state.rp.tab === 'bs') {
    const sec = (title, rows) => `<div class="w-sub">${esc(title)}</div>` +
      (rows.length ? `<div class="w-table-wrap"><table class="w-table"><tbody>${rows.map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">None.</p>');
    const badge = d.balanced ? pill('Balanced', 'good') : pill('Out of balance', 'critical');
    return `<p>${badge} Assets ${esc(bkRs(d.total_assets_paise))} · Liabilities ${esc(bkRs(d.total_liabilities_paise))} · Equity + Net Profit ${esc(bkRs((d.total_equity_paise || 0) + (d.retained_net_profit_paise || 0)))}</p>` +
      sec('Assets', d.assets || []) + sec('Liabilities', d.liabilities || []) + sec('Equity', d.equity || []);
  }
  if (state.rp.tab === 'cf') {
    const rows = (d.by_event || []).map(x => `<tr><td>${esc(x.event_type)}</td><td class="num">${esc(bkRs(x.net_paise))}</td></tr>`).join('');
    return `<div class="v-tiles">` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.inflow_paise))}</div><div class="v-tile-label">Money In</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.outflow_paise))}</div><div class="v-tile-label">Money Out</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.net_cash_change_paise))}</div><div class="v-tile-label">Net Cash Change</div></div></div>` +
      (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Activity</th><th>Net</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No bank or cash activity.</p>');
  }
  const rows = (d.rows || []).map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.budget_paise))}</td><td class="num">${esc(bkRs(x.actual_paise))}</td>` +
    `<td class="num">${esc(bkRs(x.variance_paise))}</td><td>${x.over_budget ? pill('Over budget', 'critical') : pill('On track', 'good')}</td></tr>`).join('');
  return rows
    ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Account</th><th>Budget</th><th>Actual</th><th>Variance</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<p class="muted">No monthly account budgets set for this month.</p>';
}

function rpReportsView() {
  if (!RP_ROLES.includes(state.user?.role)) return head('Reports', 'Financial reports are for the owner and accounts.');
  if (!state.rp.opts) {
    rpInit();
    return head('Reports', 'Profit & Loss, Balance Sheet, Cash Flow, and Budget vs. Actual.') + '<div class="loading">Loading…</div>';
  }
  const opts = state.rp.opts;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}"${c.id === state.rp.entityId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const projOpts = '<option value="">All projects</option>' + opts.projects.map(p => `<option value="${Number(p.id)}"${String(p.id) === state.rp.projectId ? ' selected' : ''}>${esc(p.name)}</option>`).join('');
  const tabs = [['pnl', 'Profit & Loss'], ['bs', 'Balance Sheet'], ['cf', 'Cash Flow'], ['bva', 'Budget vs. Actual']]
    .map(([k, lbl]) => `<button type="button" class="btn ${state.rp.tab === k ? 'btn-primary' : 'btn-secondary'} btn-sm" data-rp="tab" data-tab="${k}">${esc(lbl)}</button>`).join(' ');

  return head('Financial Reports', 'Live Profit & Loss, Balance Sheet, Cash Flow, and Budget vs. Actual from posted journals.') +
    `<section class="panel section-gap"><div class="panel-body"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select id="rpCompany" class="form-input">${compOpts}</select></label>` +
    `<label class="g-field"><span>Project (P&L)</span><select id="rpProject" class="form-input">${projOpts}</select></label>` +
    `<label class="g-field"><span>From date</span><input type="date" id="rpFrom" class="form-input" value="${esc(state.rp.dateFrom)}"></label>` +
    `<label class="g-field"><span>To / As of date</span><input type="date" id="rpTo" class="form-input" value="${esc(state.rp.dateTo)}"></label>` +
    `<label class="g-field"><span>Budget month</span><input type="month" id="rpMonth" class="form-input" value="${esc(state.rp.month)}"></label>` +
    `</div><div class="section-gap">${tabs} <button type="button" class="btn btn-secondary btn-sm" data-rp="refresh">Refresh</button></div></div></section>` +
    `<section class="panel section-gap"><div class="panel-body">${rpBodyHtml()}</div></section>`;
}

function rpTaxToolsView() {
  if (!RP_ROLES.includes(state.user?.role)) return head('Tax & Recurring', 'For owner and accounts.');
  if (!state.rp.opts) {
    rpInit();
    return head('Tax & Recurring', 'GST & TDS calculator, company tax settings, recurring drafts, and account budgets.') + '<div class="loading">Loading…</div>';
  }
  const opts = state.rp.opts;
  const entId = state.rp.entityId || opts.companies[0]?.id;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}"${c.id === entId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const accOpts = (opts.accounts || []).filter(a => a.entity_id === entId).map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');

  const tp = state.rp.taxPreview;
  const tpHtml = tp
    ? `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.invoice_total_paise))}</div><div class="v-tile-label">Invoice Total (Sec 170)</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.gst.total_tax_paise))}</div><div class="v-tile-label">${tp.place_of_supply.supply_type === 'intra' ? 'CGST + SGST' : 'IGST'}</div></div>` +
      (tp.tds ? `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.tds.tds_paise))}</div><div class="v-tile-label">TDS (${esc(tp.tds.section)})</div></div>` : '') +
      (tp.net_cash_settlement_paise != null ? `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.net_cash_settlement_paise))}</div><div class="v-tile-label">Net Cash Settlement</div></div>` : '') +
      `</div><p class="muted">${esc(tp.place_of_supply.rule)}${tp.itc ? ' · ' + esc(tp.itc.reason) : ''}</p>`
    : '';

  const recRows = (state.rp.recurring || []).map(r => `<tr><td><strong>${esc(r.title)}</strong></td><td>${esc(r.entry_kind)}</td><td>${esc(r.cadence)}</td><td>${esc(r.next_run_date)}</td>` +
    `<td><button type="button" class="btn btn-secondary btn-sm" data-rp="gen-rec" data-id="${Number(r.id)}">Generate Draft</button></td></tr>`).join('');

  return head('Tax & Recurring', 'GST & TDS preview calculator, company tax settings, draft-only recurring entries, and monthly account budgets.') +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Live GST & TDS Calculator (Sole Proprietorship rules)</div></div><div class="panel-body">` +
    `<form id="rpTaxCalcForm"><div class="g-form">` +
    `<label class="g-field"><span>Taxable base (₹)</span><input name="taxable" class="form-input" inputmode="decimal" required value="100000.00"></label>` +
    `<label class="g-field"><span>SAC / HSN</span><input name="sac_hsn" class="form-input" value="998391"></label>` +
    `<label class="g-field"><span>Firm state code</span><input name="firm_state" class="form-input" maxlength="2" value="29"></label>` +
    `<label class="g-field"><span>Site state code</span><input name="site_state" class="form-input" maxlength="2" value="29"></label>` +
    `<label class="g-field"><span>GST %</span><select name="gst_bps" class="form-input"><option value="1800">18%</option><option value="1200">12%</option><option value="500">5%</option><option value="0">0%</option></select></label>` +
    `<label class="g-field"><span>TDS section (optional)</span><select name="tds_sec" class="form-input"><option value="">None</option><option value="194C">194C (Contractor 1%/2%)</option><option value="194J">194J (Professional 10%)</option><option value="194I">194I (Rent 10%)</option></select></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Calculate</button></div></form><div class="section-gap">${tpHtml}</div></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Company GST & TDS settings</div></div><div class="panel-body">` +
    `<form id="rpTaxSettingForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>GSTIN</span><input name="gstin" class="form-input" maxlength="15" placeholder="29ABCDE1234F1Z5"></label>` +
    `<label class="g-field"><span>State code</span><input name="state_code" class="form-input" maxlength="2" required value="29"></label>` +
    `<label class="g-field"><span>TDS deductor active?</span><select name="tds_active" class="form-input"><option value="false">No (under threshold)</option><option value="true">Yes</option></select></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send settings for approval</button></div></form></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Recurring templates (draft-only, never auto-posts)</div></div><div class="panel-body">` +
    (recRows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Title</th><th>Type</th><th>Cadence</th><th>Next run</th><th>Action</th></tr></thead><tbody>${recRows}</tbody></table></div>` : '<p class="muted">No recurring templates saved yet.</p>') +
    `</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Set monthly account budget</div></div><div class="panel-body">` +
    `<form id="rpBudgetForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Account</span><select name="account_id" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Fiscal year</span><input name="fiscal_year" class="form-input" required value="2026-27"></label>` +
    `<label class="g-field"><span>Month</span><input type="month" name="year_month" class="form-input" required value="${esc(state.rp.month)}"></label>` +
    `<label class="g-field"><span>Monthly budget (₹)</span><input name="budget" class="form-input" inputmode="decimal" required placeholder="50000.00"></label>` +
    `<label class="g-field"><span>Note</span><input name="note" class="form-input" maxlength="250" placeholder="Optional note"></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send budget for approval</button></div></form></div></section>`;
}

const RP_VIEWS = {reports: ['Financial Reports', rpReportsView], taxtools: ['Tax & Recurring', rpTaxToolsView]};
const _rpRender = render;
render = function () {
  const v = RP_VIEWS[state.view];
  if (!v) { _rpRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = v[1]().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / ' + v[0].toUpperCase());
  $('breadcrumb').textContent = v[0];
};

document.addEventListener('click', async e => {
  const tabBtn = e.target.closest('[data-rp="tab"]');
  if (tabBtn) {
    state.rp.tab = tabBtn.dataset.tab;
    try { await rpFetchReport(); } catch (err) { notify(err.message, true); }
    render();
    return;
  }
  if (e.target.closest('[data-rp="refresh"]')) {
    try { await rpFetchReport(); } catch (err) { notify(err.message, true); }
    render();
    return;
  }
  const genRec = e.target.closest('[data-rp="gen-rec"]');
  if (genRec) {
    try {
      const res = await api(`/api/books/recurring/${Number(genRec.dataset.id)}/generate-draft`, {method: 'POST', body: '{}'});
      notify(`Draft ticket #${res.ticket_id} generated and sent to Inbox for approval.`);
    } catch (err) { notify(err.message, true); }
  }
});

document.addEventListener('change', async e => {
  if (['rpCompany', 'rpProject', 'rpFrom', 'rpTo', 'rpMonth'].includes(e.target.id)) {
    if (e.target.id === 'rpCompany') state.rp.entityId = Number(e.target.value);
    if (e.target.id === 'rpProject') state.rp.projectId = e.target.value;
    if (e.target.id === 'rpFrom') state.rp.dateFrom = e.target.value;
    if (e.target.id === 'rpTo') state.rp.dateTo = e.target.value;
    if (e.target.id === 'rpMonth') state.rp.month = e.target.value;
    try { await rpFetchReport(); } catch (err) { notify(err.message, true); }
    render();
  }
});

document.addEventListener('submit', async e => {
  const tc = e.target.closest('#rpTaxCalcForm');
  if (tc) {
    e.preventDefault();
    try {
      state.rp.taxPreview = await api('/api/books/tax/preview', {
        method: 'POST',
        body: JSON.stringify({
          firm_state_code: tc.firm_state.value.trim(),
          counterparty_state_code: tc.site_state.value.trim(),
          site_state_code: tc.site_state.value.trim(),
          sac_hsn: tc.sac_hsn.value.trim(),
          taxable_paise: bkParsePaise(tc.taxable.value),
          gst_rate_bps: Number(tc.gst_bps.value),
          tds_section: tc.tds_sec.value || null,
          tds_deductor_active: Boolean(tc.tds_sec.value),
        }),
      });
      render();
    } catch (err) { notify(err.message, true); }
    return;
  }
  const ts = e.target.closest('#rpTaxSettingForm');
  if (ts) {
    e.preventDefault();
    try {
      const res = await api('/api/books/tax/settings', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(ts.entity_id.value), gstin: ts.gstin.value.trim(),
          state_code: ts.state_code.value.trim(), tds_deductor_active: ts.tds_active.value === 'true',
          composition_scheme: false, request_key: ts.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Tax settings draft #${res.ticket_id} sent for approval.`);
    } catch (err) { notify(err.message, true); }
    return;
  }
  const bf = e.target.closest('#rpBudgetForm');
  if (bf) {
    e.preventDefault();
    try {
      const res = await api('/api/books/account-budgets', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(bf.entity_id.value), account_id: Number(bf.account_id.value),
          fiscal_year: bf.fiscal_year.value.trim(), year_month: bf.year_month.value,
          budget_paise: bkParsePaise(bf.budget.value), note: bf.note.value.trim(),
          request_key: bf.dataset.requestKey || formRequestKey(),
        }),
      });
      notify(`Monthly budget draft #${res.ticket_id} sent for approval.`);
    } catch (err) { notify(err.message, true); }
  }
});
