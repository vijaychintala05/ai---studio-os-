'use strict';
/* StudioOS M3 Financial Reports (Profit & Loss, Balance Sheet, Cash Flow, Budget vs. Actual)
   and Tax Helper, Recurring Templates (draft-only), and Account Budgets screens.
   Strict CSP: zero inline styles or handlers. Owner & accounts only. */

Object.assign(state, {
  rp: {
    opts: null, entityId: null, projectId: '', dateFrom: '', dateTo: '',
    month: new Date().toISOString().slice(0, 7),
    tab: 'pnl', data: null, loading: false, reportLoading: false, reportSeq: 0,
    taxPreview: null, recurring: [],
  },
});

const RP_ROLES = ['admin', 'accounts'];
const RP_EVENT_LABELS = {
  direct_expense: 'Direct expense',
  expense: 'Expense',
  vendor_payment: 'Supplier payment',
  supplier_payment: 'Supplier payment',
  supplier_advance: 'Supplier advance',
  client_receipt: 'Client payment received',
  client_advance: 'Client retainer received',
  bank_transfer: 'Bank / cash transfer',
  manual_journal: 'Manual journal adjustment',
  petty_cash_topup: 'Petty cash top-up',
  staff_reimbursement: 'Staff reimbursement',
};

function rpEventLabel(raw) {
  const k = String(raw || '').trim().toLowerCase();
  if (RP_EVENT_LABELS[k]) return RP_EVENT_LABELS[k];
  const spaced = k.replace(/_/g, ' ');
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : 'Other activity';
}

function rpFiscalYear(isoDate) {
  const s = String(isoDate || '').trim();
  const m = /^(\d{4})-(\d{2})/.exec(s);
  const y = m ? Number(m[1]) : new Date().getFullYear();
  const mo = m ? Number(m[2]) : (new Date().getMonth() + 1);
  const start = mo >= 4 ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`;
}

function rpStateOptions(selectedCode) {
  const states = typeof SALES_STATES !== 'undefined' ? SALES_STATES : {'29': 'Karnataka'};
  const sel = String(selectedCode || '29');
  return Object.entries(states).sort((a, b) => a[1].localeCompare(b[1]))
    .map(([code, name]) => `<option value="${esc(code)}"${code === sel ? ' selected' : ''}>${esc(name)} (${esc(code)})</option>`).join('');
}

function rpCsvEscape(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function rpExportCsv() {
  const d = state.rp.data;
  if (!d) { notify('No report data to export.', true); return; }
  const tab = state.rp.tab;
  const rows = [];
  if (tab === 'pnl') {
    rows.push(['Section', 'Code', 'Account', 'Amount (INR)']);
    (d.income || []).forEach(x => rows.push(['Income', x.code, x.name, (Number(x.amount_paise || 0) / 100).toFixed(2)]));
    rows.push(['Total Income', '', '', (Number(d.total_income_paise || 0) / 100).toFixed(2)]);
    (d.expenses || []).forEach(x => rows.push(['Expense', x.code, x.name, (Number(x.amount_paise || 0) / 100).toFixed(2)]));
    rows.push(['Total Expenses', '', '', (Number(d.total_expense_paise || 0) / 100).toFixed(2)]);
    rows.push(['Net Profit', '', '', (Number(d.net_profit_paise || 0) / 100).toFixed(2)]);
  } else if (tab === 'bs') {
    rows.push(['Section', 'Code', 'Account', 'Amount (INR)']);
    [['Assets', d.assets || []], ['Liabilities', d.liabilities || []], ['Equity', d.equity || []]].forEach(([sec, list]) => {
      list.forEach(x => rows.push([sec, x.code, x.name, (Number(x.amount_paise || 0) / 100).toFixed(2)]));
    });
  } else if (tab === 'cf') {
    rows.push(['Activity', 'Net (INR)']);
    (d.by_event || []).forEach(x => rows.push([rpEventLabel(x.event_type), (Number(x.net_paise || 0) / 100).toFixed(2)]));
    rows.push(['Money In', (Number(d.inflow_paise || 0) / 100).toFixed(2)]);
    rows.push(['Money Out', (Number(d.outflow_paise || 0) / 100).toFixed(2)]);
    rows.push(['Net Cash Change', (Number(d.net_cash_change_paise || 0) / 100).toFixed(2)]);
  } else {
    rows.push(['Code', 'Account', 'Budget (INR)', 'Actual (INR)', 'Variance (INR)', 'Status']);
    (d.rows || []).forEach(x => rows.push([
      x.code, x.name, (Number(x.budget_paise || 0) / 100).toFixed(2),
      (Number(x.actual_paise || 0) / 100).toFixed(2), (Number(x.variance_paise || 0) / 100).toFixed(2),
      x.over_budget ? 'Over budget' : 'On track',
    ]));
  }
  const csv = rows.map(r => r.map(rpCsvEscape).join(',')).join('\r\n');
  const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `studioos-${tab}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

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
  const seq = state.rp.reportSeq = (state.rp.reportSeq || 0) + 1;
  state.rp.reportLoading = true;
  if (state.view === 'reports') render();
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
  } else if (tab === 'tb') {
    url = '/api/books/reports/trial-balance';
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else if (tab === 'proj') {
    url = '/api/books/reports/project-profitability';
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else if (tab === 'ar') {
    url = '/api/books/reports/ar-ageing';
    if (state.rp.dateTo) qs.set('as_of', state.rp.dateTo);
  } else if (tab === 'gstr3b') {
    url = '/api/books/reports/gstr3b';
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else if (tab === 'tds') {
    url = '/api/books/reports/tds-register';
    if (state.rp.dateFrom) qs.set('date_from', state.rp.dateFrom);
    if (state.rp.dateTo) qs.set('date_to', state.rp.dateTo);
  } else {
    url = '/api/books/reports/budget-vs-actual';
    qs.set('year_month', state.rp.month || new Date().toISOString().slice(0, 7));
  }
  try {
    const res = await api(`${url}?${qs.toString()}`);
    if (state.rp.reportSeq !== seq) return;
    state.rp.data = res;
  } finally {
    if (state.rp.reportSeq === seq) state.rp.reportLoading = false;
  }
}

function rpBodyHtml() {
  if (state.rp.reportLoading) return '<div class="loading" role="status">Loading report…</div>';
  const d = state.rp.data;
  if (!d) return '<p class="muted">Select a company to load this report.</p>';
  if (state.rp.tab === 'pnl') {
    const mk = rows => (rows || []).map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('');
    const incRows = mk(d.income), cogsRows = mk(d.cogs), opexRows = mk(d.operating_expenses);
    return `<div class="v-tiles">` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.total_income_paise))}</div><div class="v-tile-label">Total Income</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.total_cogs_paise || 0))}</div><div class="v-tile-label">Cost of Goods Sold</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.gross_profit_paise != null ? d.gross_profit_paise : d.total_income_paise))}</div><div class="v-tile-label">Gross Profit</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.net_profit_paise))}</div><div class="v-tile-label">Net Profit</div></div></div>` +
      `<div class="w-sub">Income</div>${incRows ? `<div class="w-table-wrap"><table class="w-table"><tbody>${incRows}</tbody></table></div>` : '<p class="muted">No posted income.</p>'}` +
      `<div class="w-sub">Cost of Goods Sold</div>${cogsRows ? `<div class="w-table-wrap"><table class="w-table"><tbody>${cogsRows}</tbody></table></div>` : '<p class="muted">No posted COGS.</p>'}` +
      `<div class="w-sub">Operating Expenses</div>${opexRows ? `<div class="w-table-wrap"><table class="w-table"><tbody>${opexRows}</tbody></table></div>` : '<p class="muted">No posted operating expenses.</p>'}`;
  }
  if (state.rp.tab === 'bs') {
    const secGrouped = (title, groups, fallback) => {
      if (groups && groups.length) {
        return `<div class="w-sub">${esc(title)}</div>` + groups.map(g =>
          `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>${esc(g.label)}</th><th class="num">${esc(bkRs(g.total_paise))}</th></tr></thead><tbody>` +
          g.accounts.map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('') + `</tbody></table></div>`
        ).join('');
      }
      return `<div class="w-sub">${esc(title)}</div>` +
        (fallback.length ? `<div class="w-table-wrap"><table class="w-table"><tbody>${fallback.map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.amount_paise))}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">None.</p>');
    };
    const badge = d.balanced ? pill('Balanced', 'good') : pill('Out of balance', 'critical');
    return `<p>${badge} Assets ${esc(bkRs(d.total_assets_paise))} · Liabilities ${esc(bkRs(d.total_liabilities_paise))} · Equity + Net Profit ${esc(bkRs((d.total_equity_paise || 0) + (d.retained_net_profit_paise || 0)))}</p>` +
      secGrouped('Assets', d.assets_grouped, d.assets || []) +
      secGrouped('Liabilities', d.liabilities_grouped, d.liabilities || []) +
      secGrouped('Equity', d.equity_grouped, d.equity || []);
  }
  if (state.rp.tab === 'tb') {
    const rows = (d.rows || []).map(x => `<tr><td>${esc(x.code + ' ' + x.name)}</td><td class="num">${esc(bkRs(x.opening_debit_paise))}</td><td class="num">${esc(bkRs(x.opening_credit_paise))}</td><td class="num">${esc(bkRs(x.period_debit_paise))}</td><td class="num">${esc(bkRs(x.period_credit_paise))}</td><td class="num">${esc(bkRs(x.closing_debit_paise))}</td><td class="num">${esc(bkRs(x.closing_credit_paise))}</td></tr>`).join('');
    const badge = d.balanced ? pill('Balanced', 'good') : pill('Out of balance', 'critical');
    return `<p>${badge}</p>` + (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Account</th><th>Open Dr</th><th>Open Cr</th><th>Period Dr</th><th>Period Cr</th><th>Close Dr</th><th>Close Cr</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No posted entries.</p>');
  }
  if (state.rp.tab === 'proj') {
    const rows = (d.rows || []).map(x => `<tr><td>${esc(x.project_name)}</td><td class="num">${esc(bkRs(x.income_paise))}</td><td class="num">${esc(bkRs(x.cogs_paise))}</td><td class="num">${esc(bkRs(x.gross_profit_paise))}</td><td class="num">${esc(bkRs(x.operating_expense_paise))}</td><td class="num">${esc(bkRs(x.net_profit_paise))}</td></tr>`).join('');
    return rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Project</th><th>Income</th><th>COGS</th><th>Gross Profit</th><th>OpEx</th><th>Net Profit</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No project entries.</p>';
  }
  if (state.rp.tab === 'ar') {
    const a = d.ageing || {};
    const rows = (d.by_client || []).map(x => `<tr><td>${esc(x.client_name)}</td><td class="num">${esc(bkRs(x.current))}</td><td class="num">${esc(bkRs(x.days_31_60))}</td><td class="num">${esc(bkRs(x.days_61_90))}</td><td class="num">${esc(bkRs(x.over_90))}</td><td class="num">${esc(bkRs(x.total_paise))}</td></tr>`).join('');
    return `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.total_receivable_paise || 0))}</div><div class="v-tile-label">Total Receivable</div></div><div class="v-tile"><div class="v-tile-value">${esc(bkRs(a.current || 0))}</div><div class="v-tile-label">0-30 days</div></div><div class="v-tile"><div class="v-tile-value">${esc(bkRs(a.over_90 || 0))}</div><div class="v-tile-label">90+ days</div></div></div>` +
      (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Client</th><th>0-30d</th><th>31-60d</th><th>61-90d</th><th>90+d</th><th>Total</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No open client invoices.</p>');
  }
  if (state.rp.tab === 'gstr3b') {
    const o = d.outward_tax || {}, i = d.eligible_itc || {};
    return `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(bkRs(o.total_paise || 0))}</div><div class="v-tile-label">Output GST</div></div><div class="v-tile"><div class="v-tile-value">${esc(bkRs(i.total_paise || 0))}</div><div class="v-tile-label">Eligible ITC</div></div><div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.net_payable_paise || 0))}</div><div class="v-tile-label">Net GST Payable</div></div><div class="v-tile"><div class="v-tile-value">${esc(bkRs(d.itc_carry_forward_paise || 0))}</div><div class="v-tile-label">ITC Carry Forward</div></div></div>`;
  }
  if (state.rp.tab === 'tds') {
    const rows = (d.rows || []).map(x => `<tr><td>${esc(x.bill_date)}</td><td>${esc(x.invoice_number)}</td><td>${esc(x.supplier_name)}</td><td>${esc(x.tds_section)}</td><td class="num">${esc(bkRs(x.taxable_paise))}</td><td class="num">${esc(bkRs(x.tds_paise))}</td></tr>`).join('');
    return `<p>Total TDS Payable: <strong>${esc(bkRs(d.total_tds_paise || 0))}</strong></p>` +
      (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Date</th><th>Invoice</th><th>Vendor</th><th>Section</th><th>Taxable</th><th>TDS</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No TDS deducted in this period.</p>');
  }
  if (state.rp.tab === 'cf') {
    const rows = (d.by_event || []).map(x => `<tr><td>${esc(rpEventLabel(x.event_type))}</td><td class="num">${esc(bkRs(x.net_paise))}</td></tr>`).join('');
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
    return head('Reports', 'Profit & Loss, Balance Sheet, Trial Balance, Cash Flow, and Tax Reports.') + '<div class="loading">Loading…</div>';
  }
  const opts = state.rp.opts;
  const tab = state.rp.tab;
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}"${c.id === state.rp.entityId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const projOpts = '<option value="">All projects</option>' + opts.projects.map(p => `<option value="${Number(p.id)}"${String(p.id) === state.rp.projectId ? ' selected' : ''}>${esc(p.name)}</option>`).join('');
  const tabs = [['pnl', 'Profit & Loss'], ['bs', 'Balance Sheet'], ['tb', 'Trial Balance'], ['proj', 'Project Profit'], ['cf', 'Cash Flow'], ['ar', 'AR Ageing'], ['gstr3b', 'GSTR-3B'], ['tds', 'TDS Register'], ['bva', 'Budget vs. Actual']]
    .map(([k, lbl]) => `<button type="button" role="tab" aria-selected="${tab === k}" class="btn ${tab === k ? 'btn-primary' : 'btn-secondary'} btn-sm" data-rp="tab" data-tab="${k}">${esc(lbl)}</button>`).join(' ');
  const csvKindMap = {pnl: 'pnl', bs: 'balance-sheet', tb: 'trial-balance', proj: 'project-profitability', tds: 'tds'};
  const csvKind = csvKindMap[tab];
  const csvQs = new URLSearchParams({entity_id: String(state.rp.entityId || ''), kind: csvKind || ''});
  if (state.rp.dateFrom) csvQs.set('date_from', state.rp.dateFrom);
  if (state.rp.dateTo) csvQs.set('date_to', state.rp.dateTo);
  const csvAction = csvKind && state.rp.entityId
    ? `<a class="btn btn-secondary btn-sm" href="/api/books/reports/export.csv?${csvQs.toString()}" target="_blank" rel="noopener">Export CSV</a>`
    : `<button type="button" class="btn btn-secondary btn-sm" data-rp="csv">Export CSV</button>`;
  const needsFrom = ['pnl', 'cf', 'proj', 'gstr3b', 'tds'].includes(tab);
  const needsTo = tab !== 'bva';
  const filters = `<label class="g-field"><span>Company</span><select id="rpCompany" class="form-input">${compOpts}</select></label>` +
    (tab === 'pnl' ? `<label class="g-field"><span>Project</span><select id="rpProject" class="form-input">${projOpts}</select></label>` : '') +
    (needsFrom ? `<label class="g-field"><span>From date</span><input type="date" id="rpFrom" class="form-input" value="${esc(state.rp.dateFrom)}"></label>` : '') +
    (needsTo ? `<label class="g-field"><span>${['bs', 'tb', 'ar'].includes(tab) ? 'As of date' : 'To date'}</span><input type="date" id="rpTo" class="form-input" value="${esc(state.rp.dateTo)}"></label>` : '') +
    (tab === 'bva' ? `<label class="g-field"><span>Budget month</span><input type="month" id="rpMonth" class="form-input" value="${esc(state.rp.month)}"></label>` : '');

  return head('Financial Reports', 'Live Profit & Loss (with COGS), Balance Sheet, Trial Balance, Project Profitability, AR Ageing, and Tax Registers.') +
    `<section class="panel section-gap"><div class="panel-body"><div class="g-form">${filters}</div>` +
    `<div class="row-actions section-gap" role="tablist" aria-label="Report type">${tabs} ` +
    `<button type="button" class="btn btn-secondary btn-sm" data-rp="refresh">Refresh</button> ${csvAction} ` +
    `<button type="button" class="btn btn-secondary btn-sm" data-rp="print">Print</button></div></div></section>` +
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
  const activeCompany = opts.companies.find(c => c.id === entId) || opts.companies[0];
  const defaultState = activeCompany?.state_code || '29';
  const defaultFy = rpFiscalYear(opts.today || (state.rp.month ? state.rp.month + '-01' : ''));
  const compOpts = opts.companies.map(c => `<option value="${Number(c.id)}"${c.id === entId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const accOpts = (opts.accounts || []).filter(a => Number(a.entity_id) === Number(entId)).map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');

  const tp = state.rp.taxPreview;
  const tpHtml = tp
    ? `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.invoice_total_paise))}</div><div class="v-tile-label">Invoice Total (rounded)</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.gst.total_tax_paise))}</div><div class="v-tile-label">${tp.place_of_supply.supply_type === 'intra' ? 'CGST + SGST' : 'IGST'}</div></div>` +
      (tp.tds ? `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.tds.tds_paise))}</div><div class="v-tile-label">TDS (${esc(tp.tds.section)})</div></div>` : '') +
      (tp.net_cash_settlement_paise != null ? `<div class="v-tile"><div class="v-tile-value">${esc(bkRs(tp.net_cash_settlement_paise))}</div><div class="v-tile-label">Net Cash Settlement</div></div>` : '') +
      `</div><p class="muted">${esc(tp.place_of_supply.rule)}${tp.itc ? ' · ' + esc(tp.itc.reason) : ''}</p>`
    : '';

  const recRows = (state.rp.recurring || []).map(r => `<tr><td><strong>${esc(r.title)}</strong></td><td>${esc(rpEventLabel(r.entry_kind))}</td><td>${esc(r.cadence)}</td><td>${esc(r.next_run_date)}</td>` +
    `<td><button type="button" class="btn btn-secondary btn-sm" data-rp="gen-rec" data-id="${Number(r.id)}">Generate Draft</button></td></tr>`).join('');

  return head('Tax & Recurring', 'GST & TDS preview calculator, company tax settings, draft-only recurring entries, and monthly account budgets.') +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Live GST & TDS Calculator (Sole Proprietorship rules)</div></div><div class="panel-body">` +
    `<form id="rpTaxCalcForm"><div class="g-form">` +
    `<label class="g-field"><span>Taxable base (₹)</span><input name="taxable" class="form-input" inputmode="decimal" required value="100000.00"></label>` +
    `<label class="g-field"><span>SAC / HSN</span><input name="sac_hsn" class="form-input" value="998391"></label>` +
    `<label class="g-field"><span>Firm state</span><select name="firm_state" class="form-input">${rpStateOptions(defaultState)}</select></label>` +
    `<label class="g-field"><span>Site state</span><select name="site_state" class="form-input">${rpStateOptions(defaultState)}</select></label>` +
    `<label class="g-field"><span>GST %</span><select name="gst_bps" class="form-input"><option value="1800">18%</option><option value="1200">12%</option><option value="500">5%</option><option value="0">0%</option></select></label>` +
    `<label class="g-field"><span>TDS section (optional)</span><select name="tds_sec" class="form-input"><option value="">None</option><option value="194C">194C (Contractor 1%/2%)</option><option value="194J">194J (Professional 10%)</option><option value="194I">194I (Rent 10%)</option></select></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Calculate</button></div></form><div class="section-gap">${tpHtml}</div></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Company GST & TDS settings</div></div><div class="panel-body">` +
    `<form id="rpTaxSettingForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>GSTIN</span><input name="gstin" class="form-input" maxlength="15" placeholder="29ABCDE1234F1Z5"></label>` +
    `<label class="g-field"><span>State</span><select name="state_code" class="form-input" required>${rpStateOptions(defaultState)}</select></label>` +
    `<label class="g-field"><span>TDS deductor active?</span><select name="tds_active" class="form-input"><option value="false">No (under threshold)</option><option value="true">Yes</option></select></label>` +
    `</div><div class="section-gap"><button type="submit" class="btn btn-primary">Send settings for approval</button></div></form></div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Recurring templates (draft-only, never auto-posts)</div></div><div class="panel-body">` +
    (recRows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Title</th><th>Type</th><th>Cadence</th><th>Next run</th><th>Action</th></tr></thead><tbody>${recRows}</tbody></table></div>` : '<p class="muted">No recurring templates saved yet.</p>') +
    `</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Set monthly account budget</div></div><div class="panel-body">` +
    `<form id="rpBudgetForm" data-request-key="${esc(formRequestKey())}"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select name="entity_id" class="form-input" required>${compOpts}</select></label>` +
    `<label class="g-field"><span>Account</span><select name="account_id" class="form-input" required>${accOpts}</select></label>` +
    `<label class="g-field"><span>Financial year</span><input name="fiscal_year" class="form-input" required value="${esc(defaultFy)}"></label>` +
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
  if (e.target.closest('[data-rp="csv"]')) {
    rpExportCsv();
    return;
  }
  if (e.target.closest('[data-rp="print"]')) {
    window.print();
    return;
  }
  const genRec = e.target.closest('[data-rp="gen-rec"]');
  if (genRec) {
    if (genRec.disabled) return;
    genRec.disabled = true;
    try {
      const res = await api(`/api/books/recurring/${Number(genRec.dataset.id)}/generate-draft`, {method: 'POST', body: '{}'});
      notify(`Draft change request #${res.ticket_id} generated and sent to Inbox for approval.`);
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (genRec.isConnected) genRec.disabled = false;
    }
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
    return;
  }
  const bf = e.target.closest('#rpBudgetForm');
  if (bf && state.rp.opts) {
    if (e.target.name === 'entity_id') {
      const entId = Number(bf.entity_id.value);
      const accSel = bf.querySelector('select[name="account_id"]');
      if (accSel) {
        accSel.innerHTML = (state.rp.opts.accounts || []).filter(a => Number(a.entity_id) === entId)
          .map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
      }
    } else if (e.target.name === 'year_month' && bf.fiscal_year) {
      bf.fiscal_year.value = rpFiscalYear(e.target.value + '-01');
    }
  }
});

document.addEventListener('submit', async e => {
  const tc = e.target.closest('#rpTaxCalcForm');
  if (tc) {
    e.preventDefault();
    const btn = tc.querySelector('button[type="submit"]');
    if (btn?.disabled) return;
    if (btn) btn.disabled = true;
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
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn && btn.isConnected) btn.disabled = false;
    }
    return;
  }
  const ts = e.target.closest('#rpTaxSettingForm');
  if (ts) {
    e.preventDefault();
    const btn = ts.querySelector('button[type="submit"]');
    if (btn?.disabled) return;
    if (btn) btn.disabled = true;
    try {
      const res = await api('/api/books/tax/settings', {
        method: 'POST',
        body: JSON.stringify({
          entity_id: Number(ts.entity_id.value), gstin: ts.gstin.value.trim(),
          state_code: ts.state_code.value.trim(), tds_deductor_active: ts.tds_active.value === 'true',
          composition_scheme: false, request_key: ts.dataset.requestKey || formRequestKey(),
        }),
      });
      ts.dataset.requestKey = formRequestKey();
      notify(`Tax settings draft #${res.ticket_id} sent for approval.`);
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn && btn.isConnected) btn.disabled = false;
    }
    return;
  }
  const bf = e.target.closest('#rpBudgetForm');
  if (bf) {
    e.preventDefault();
    const btn = bf.querySelector('button[type="submit"]');
    if (btn?.disabled) return;
    if (btn) btn.disabled = true;
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
      bf.dataset.requestKey = formRequestKey();
      notify(`Monthly budget draft #${res.ticket_id} sent for approval.`);
    } catch (err) {
      notify(err.message, true);
    } finally {
      if (btn && btn.isConnected) btn.disabled = false;
    }
  }
});
