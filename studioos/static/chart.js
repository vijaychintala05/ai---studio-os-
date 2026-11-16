'use strict';
/* StudioOS v0.9.14: "Chart of accounts". Accounts in their groups with posted totals,
   income / expenses / profit, a ledger for any account, entries typed in the chat, and
   suggestions for improving the chart. Installing a standard opens a ticket in the chat;
   nothing here writes. Loaded after app.js, chat.js, waiting.js, connectors.js, universal.js. */

Object.assign(state, {coa: null, coaEntity: null, coaLedger: null});

function coaMoney(p) { return inr(Number(p || 0) / 100); }

async function coaLoad() {
  const companies = await api('/api/finance-ledger/entities');
  const entity = companies.find(c => c.id === state.coaEntity) || companies[0];
  if (!entity) { state.coa = {companies, entity: null}; return; }
  state.coaEntity = entity.id;
  const [standards, chart, entries, ideas] = await Promise.all([
    api('/api/finance-ledger/standards/' + entity.id), api('/api/finance-ledger/chart/' + entity.id),
    api('/api/finance-ledger/text-entries/' + entity.id), api('/api/finance-ledger/chart-ideas/' + entity.id)]);
  state.coa = {companies, entity, standards, chart, entries: entries.entries, ideas};
}

function coaTree(chart) {
  const kids = {};
  chart.accounts.forEach(a => { (kids[a.parent ?? 'root'] = kids[a.parent ?? 'root'] || []).push(a); });
  const unplaced = chart.accounts.filter(a => a.parent == null && !a.is_group);
  const walk = (parent, depth) => (kids[parent] || []).filter(a => parent !== 'root' || a.is_group).sort((x, y) => x.name.localeCompare(y.name)).map(a => {
    if (!a.is_group && !a.debit_paise && !a.credit_paise) return '';
    const amount = a.balance_paise ? `${coaMoney(a.balance_paise)} ${esc(a.side)}` : '—';
    const name = a.is_group ? esc(a.name) : `<button class="cx-link" data-action="coa-ledger" data-id="${Number(a.id)}">${esc(a.name)}</button>`;
    return `<tr class="${a.is_group ? 'b-group' : ''} d${Math.min(depth, 4)}"><td>${name}</td><td class="b-num">${a.debit_paise ? coaMoney(a.debit_paise) : ''}</td><td class="b-num">${a.credit_paise ? coaMoney(a.credit_paise) : ''}</td><td class="b-num">${amount}</td></tr>${walk(a.id, depth + 1)}`;
  }).join('');
  const loose = unplaced.filter(a => a.debit_paise || a.credit_paise).map(a => `<tr class="d0"><td><button class="cx-link" data-action="coa-ledger" data-id="${Number(a.id)}">${esc(a.name)}</button> <span class="tag warn">not in a group</span></td><td class="b-num">${coaMoney(a.debit_paise)}</td><td class="b-num">${coaMoney(a.credit_paise)}</td><td class="b-num">${coaMoney(a.balance_paise)} ${esc(a.side)}</td></tr>`).join('');
  return walk('root', 0) + loose;
}

function chartView() {
  const intro = 'Every figure comes from approved, posted journals. Type entries in the chat, for example “Bought 50 bags of cement from Sri Ram Traders for ₹21,000 plus 18% GST”.';
  const c = state.coa;
  if (!c) { coaLoad().then(render).catch(err => notify(err.message, true)); return head('Chart of accounts',intro,hasFinance()?'New money entry':'','coa-new-entry') + '<div class="loading">Loading…</div>'; }
  if (!c.entity) return head('Chart of accounts',intro,hasFinance()?'New money entry':'','coa-new-entry') + '<div class="empty"><div class="empty-big">₹</div>No company is set up for accounting yet. Use “Propose initial finance mapping” on the Accounting Ledger screen first.</div>';
  const picker = c.companies.length > 1 ? `<label class="coa-company">Company <select class="form-input" id="coaCompany">${c.companies.map(x => `<option value="${Number(x.id)}" ${x.id === c.entity.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>` : '';
  const std = c.standards.map(s => `<div class="ck-row"><div><strong>${esc(s.title)}</strong> ${pill(s.state === 'installed' ? 'Installed v' + s.installed_version : s.state === 'update available' ? 'Update available' : 'Not installed', s.state === 'installed' ? 'good' : s.state === 'update available' ? 'warn' : '')}
      <div class="muted ck-meta">${esc(s.description)}</div><div class="muted ck-meta">${Number(s.groups)} groups, ${Number(s.accounts)} accounts · understands: ${esc(s.recipes.join(', '))}</div></div>
      ${isAdmin() && s.state !== 'installed' ? `<button class="btn btn-primary btn-sm" data-action="coa-install" data-key="${esc(s.key)}">${s.state === 'update available' ? 'Propose update' : 'Propose install'}</button>` : ''}</div>`).join('');
  const ch = c.chart;
  if (!ch.standard) return head('Chart of accounts',intro,hasFinance()?'New money entry':'','coa-new-entry') + picker + `<section class="panel"><div class="panel-head"><div><div class="panel-title">Choose a chart of accounts</div><div class="panel-sub">Installing opens a ticket; nothing changes until the Admin approves it. Existing accounts are kept and placed in their groups.</div></div></div><div class="panel-body core-packs">${std}</div></section>`;
  const ledger = state.coaLedger ? `<section class="panel section-gap" id="coaLedger"><div class="panel-head"><div><div class="panel-title">${esc(state.coaLedger.account_name)}</div><div class="panel-sub">Balance ${coaMoney(Math.abs(state.coaLedger.closing_signed_debit_paise))} ${state.coaLedger.closing_signed_debit_paise > 0 ? 'Dr' : state.coaLedger.closing_signed_debit_paise < 0 ? 'Cr' : ''}</div></div><button class="btn btn-secondary btn-sm" data-action="coa-ledger-close">Close</button></div>
      <div class="w-table-wrap"><table class="w-table"><thead><tr><th>Date</th><th>Entry</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead><tbody>${state.coaLedger.entries.map(r => `<tr><td>${esc(r.posted_date_utc)}</td><td>${esc(r.narration || r.source_event.replace(/_/g, ' ').toLowerCase())} <button class="cx-link" data-action="open-ticket" data-id="${Number(r.ticket_id)}">#${Number(r.ticket_id)}</button></td><td class="b-num">${r.side === 'debit' ? coaMoney(r.amount_paise) : ''}</td><td class="b-num">${r.side === 'credit' ? coaMoney(r.amount_paise) : ''}</td><td class="b-num">${coaMoney(Math.abs(r.running_balance_paise))} ${r.running_balance_paise > 0 ? 'Dr' : r.running_balance_paise < 0 ? 'Cr' : ''}</td></tr>`).join('') || '<tr><td colspan="5">No entries.</td></tr>'}</tbody></table></div></section>` : '';
  const entries = c.entries.length ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Entries typed in the chat</div><div class="panel-sub">Newest first. A wrong entry is reversed, never deleted.</div></div></div><div class="panel-body w-list">${c.entries.slice(0, 30).map(e => `<article class="w-card"><div class="w-head"><strong>${esc(e.narration)}</strong> ${e.reversed ? pill('Reversed', 'critical') : ''} <small class="muted">${esc(e.date)} · ticket #${Number(e.ticket_id)}</small></div><table class="cx-journal"><tbody>${e.lines.map(l => `<tr><td class="cx-j-side">${esc(l.side)}</td><td>${esc(l.account)}</td><td class="cx-j-amt">${coaMoney(l.amount_paise)}</td></tr>`).join('')}</tbody></table></article>`).join('')}</div></section>` : '';
  const ideas = c.ideas.length ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Could be better</div><div class="panel-sub">Found by checking the books. Suggestions only; nothing changes by itself.</div></div></div><div class="panel-body"><ul class="cx-notes">${c.ideas.map(i => `<li>${esc(i.text)}</li>`).join('')}</ul></div></section>` : '';
  return head('Chart of accounts',intro,hasFinance()?'New money entry':'','coa-new-entry') + picker
    + `<div class="financial-strip"><div class="financial-tile"><div class="label">Income</div><div class="num">${coaMoney(ch.income_paise)}</div></div><div class="financial-tile"><div class="label">Expenses</div><div class="num">${coaMoney(ch.expense_paise)}</div></div><div class="financial-tile"><div class="label">${ch.profit_paise < 0 ? 'Loss so far' : 'Profit so far'}</div><div class="num">${coaMoney(Math.abs(ch.profit_paise))}</div></div><div class="financial-tile"><div class="label">Trial balance</div><div class="num">${ch.balanced ? 'Balanced ✓' : 'Not balanced'}</div><small>Dr ${coaMoney(ch.total_debit_paise)} · Cr ${coaMoney(ch.total_credit_paise)}</small></div></div>`
    + ledger
    + `<section class="panel"><div class="panel-head"><div><div class="panel-title">Accounts</div><div class="panel-sub">${esc(ch.standard.key.replace(/_/g, ' '))} v${Number(ch.standard.version)} · accounts with entries, inside their groups. Tap an account for its ledger.</div></div></div><div class="w-table-wrap"><table class="w-table b-table"><thead><tr><th>Account</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead><tbody>${coaTree(ch) || '<tr><td colspan="4">No entries yet.</td></tr>'}</tbody></table></div><p class="muted coa-basis">${esc(ch.basis)}</p></section>`
    + entries + ideas
    + (c.standards.some(s => s.state === 'update available') ? `<section class="panel section-gap"><div class="panel-body core-packs">${std}</div></section>` : '');
}

const _coaRender = render;
render = function () {
  if (state.view === 'chart') {
    updateIdentity();
    $('mainContent').innerHTML = chartView();
    $('breadcrumb').textContent = 'Chart of accounts';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _coaRender();
};

document.addEventListener('change', async e => {
  if (e.target.id !== 'coaCompany') return;
  state.coaEntity = Number(e.target.value); state.coa = null; state.coaLedger = null; render();
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="chart"]')) { state.coa = null; state.coaLedger = null; return; }   // fresh figures each visit
  const b = e.target.closest('[data-action^="coa-"]:not([data-action="coa-new-entry"])');
  if (!b) return;
  e.stopImmediatePropagation();
  const a = b.dataset.action;
  try {
    if (a === 'coa-install') {
      b.disabled = true;
      const r = await api('/api/finance-ledger/proposals', {method: 'POST', body: JSON.stringify({kind: 'finance_install_chart',
        data: {entity_id: state.coaEntity, standard: b.dataset.key}, evidence: 'Install the chart of accounts standard ' + b.dataset.key})});
      notify(`Ticket #${r.ticket_id} opened. Approve it to install the chart.`);
      state.coa = null; render();
      return;
    }
    if (a === 'coa-ledger') {
      const r = await api(`/api/finance-ledger/general-ledger/${state.coaEntity}/${Number(b.dataset.id)}`);
      const narr = Object.fromEntries((state.coa?.entries || []).map(x => [x.journal_id, x.narration]));
      r.entries.forEach(x => { x.narration = narr[x.journal_id]; });
      state.coaLedger = r; render(); $('coaLedger')?.scrollIntoView({block: 'start'}); return;
    }
    if (a === 'coa-ledger-close') { state.coaLedger = null; render(); return; }
  } catch (err) { b.disabled = false; notify(err.message, true); }
}, true);
