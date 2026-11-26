'use strict';
/* StudioOS Bank feed (Money -> Bank feed): bring in a bank statement, match its lines to what is in the books,
   and keep matching rules. Built on the M2-5 endpoints in books_routes.py and universal_routes.py.
   Nothing here writes to the books: every action drafts a ticket for the Admin to approve.
   Strict CSP: no inline styles or handlers; one delegated click and change listener. Loaded after books.js. */

Object.assign(state, {
  bf: {
    home: null, opts: null, docs: null, entityId: null, bankId: null,
    tab: 'feed', feed: null, statement: null, matched: null, book: null,
    picked: {}, ruleFor: null, importOpen: false, csv: null, evidenceId: null, loading: false, gen: 0,
  },
});

const BF_ROLES = ['admin', 'accounts'];
const BF_EVIDENCE_TYPES = ['pdf', 'csv', 'xlsx', 'bank_statement'];
const BF_TABS = [['feed', 'To match'], ['matched', 'Matched'], ['statement', 'Statement'], ['book', 'Bank book']];
const bfRs = p => inr(Math.abs(Number(p || 0)) / 100);
const bfKey = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : 'bf-' + Date.now() + '-' + Math.random().toString(36).slice(2));

function bfBanks() {
  const company = (state.bf.home?.companies || []).find(c => c.entity_id === state.bf.entityId);
  return company ? company.banks : [];
}

function bfBank() { return bfBanks().find(b => b.id === state.bf.bankId) || null; }

function bfAccounts() {
  return (state.bf.opts?.accounts || []).filter(a => a.entity_id === state.bf.entityId);
}

/* Money in is a positive signed amount, money out a negative one. */
function bfAmountHtml(signed) {
  const n = Number(signed || 0);
  return `<span class="num">${n >= 0 ? 'In ' : 'Out '}${esc(bfRs(n))}</span>`;
}

async function bfInit() {
  if (state.bf.loading) return;
  state.bf.loading = true;
  try {
    const [home, opts] = await Promise.all([api('/api/books/home'), api('/api/sales/options')]);
    state.bf.home = home;
    state.bf.opts = opts;
    const first = (home.companies || []).find(c => c.banks.length) || (home.companies || [])[0];
    if (!state.bf.entityId && first) state.bf.entityId = first.entity_id;
    if (!state.bf.bankId && bfBanks().length) state.bf.bankId = bfBanks()[0].id;
    await bfLoadTab();
  } catch (err) {
    notify(err.message, true);
  } finally {
    state.bf.loading = false;
    render();
  }
}

/* Loads the open tab for the chosen bank. A slow answer for a bank the person has since left is ignored. */
async function bfLoadTab() {
  const bankId = state.bf.bankId;
  if (!bankId) return;
  const gen = ++state.bf.gen;
  const tab = state.bf.tab;
  const url = {
    feed: `/api/books/bank-feed/${Number(bankId)}`,
    matched: `/api/finance-ledger/bank-reconciliations/${Number(bankId)}`,
    statement: `/api/finance-ledger/bank-statement-lines/${Number(bankId)}`,
    book: `/api/finance-ledger/bank-book/${Number(bankId)}`,
  }[tab];
  const result = await api(url);
  if (gen !== state.bf.gen) return;
  state.bf[tab] = result;
  // The matched list needs to know which matches were later un-matched; that comes with the feed.
  if (tab === 'matched' && !state.bf.feed) state.bf.feed = await api(`/api/books/bank-feed/${Number(bankId)}`);
}

function bfReset() {
  Object.assign(state.bf, {feed: null, statement: null, matched: null, book: null, picked: {}, ruleFor: null, csv: null});
}

function bfPickersHtml() {
  const companies = (state.bf.home?.companies || []).map(c =>
    `<option value="${Number(c.entity_id)}"${c.entity_id === state.bf.entityId ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  const banks = bfBanks().map(b =>
    `<option value="${Number(b.id)}"${b.id === state.bf.bankId ? ' selected' : ''}>${esc(b.name)} ${esc(b.masked || '')}</option>`).join('');
  const tabs = BF_TABS.map(([k, label]) =>
    `<button type="button" class="btn ${state.bf.tab === k ? 'btn-primary' : 'btn-secondary'} btn-sm" data-bf="tab" data-tab="${k}">${esc(label)}</button>`).join(' ');
  return `<section class="panel section-gap"><div class="panel-body"><div class="g-form">` +
    `<label class="g-field"><span>Company</span><select id="bfCompany" class="form-input">${companies}</select></label>` +
    `<label class="g-field"><span>Bank account</span><select id="bfBank" class="form-input">${banks || '<option value="">No bank account registered</option>'}</select></label>` +
    `</div><div class="section-gap">${tabs} <button type="button" class="btn btn-secondary btn-sm" data-bf="refresh">Refresh</button>` +
    ` <button type="button" class="btn btn-secondary btn-sm" data-bf="toggle-import">Import statement (CSV)</button></div></div></section>`;
}

function bfImportHtml() {
  if (!state.bf.importOpen) return '';
  const docs = (state.bf.docs || []).filter(d => BF_EVIDENCE_TYPES.includes(String(d.doc_type || '').toLowerCase()));
  if (!docs.some(d => d.id === state.bf.evidenceId)) state.bf.evidenceId = docs[0]?.id || null;
  const docOpts = docs.map(d => `<option value="${Number(d.id)}"${d.id === state.bf.evidenceId ? ' selected' : ''}>${esc(d.name)}</option>`).join('');
  const csv = state.bf.csv;
  const preview = csv
    ? `<p class="muted">${esc(csv.name)}: ${Number(csv.rows)} row${csv.rows === 1 ? '' : 's'} after the header. Rows already brought in are skipped.</p>`
    : '';
  return `<section class="panel section-gap"><div class="panel-head"><div><h2>Import a bank statement</h2>` +
    `<p class="muted">Choose the CSV from your bank and the statement file kept in Documents as proof. ` +
    `The rows become one change request; nothing is added to the books until it is approved.</p></div></div>` +
    `<div class="panel-body"><div class="g-form">` +
    `<label class="g-field"><span>Statement CSV (columns: date, reference, and amount or debit/credit)</span>` +
    `<input type="file" id="bfCsvFile" class="form-input" accept=".csv,text/csv"></label>` +
    `<label class="g-field"><span>Proof document (bank statement PDF, CSV or XLSX)</span>` +
    `<select id="bfEvidence" class="form-input">${docOpts || '<option value="">No statement file in Documents yet</option>'}</select></label>` +
    `</div>${preview}<div class="section-gap"><button type="button" class="btn btn-primary btn-sm" data-bf="import"${csv && docOpts ? '' : ' disabled'}>Draft import for approval</button></div>` +
    `</div></section>`;
}

function bfSuggestionHtml(line, s) {
  const exact = s.confidence === 'exact';
  const picked = state.bf.picked[line.id] === s.journal_id;
  const why = exact
    ? `Same amount, ${Number(s.day_gap)} day${s.day_gap === 1 ? '' : 's'} apart`
    : `Differs by ${esc(bfRs(s.diff_paise))}. Only exact amounts can be matched; correct the entry first.`;
  return `<li><label class="bf-choice">` +
    `<input type="checkbox" data-bf="pick" data-line="${Number(line.id)}" data-journal="${Number(s.journal_id)}"${picked ? ' checked' : ''}${exact ? '' : ' disabled'}> ` +
    `Book entry #${Number(s.journal_id)} · ${esc(s.posted_date || '')} · ${esc(s.memo || '')} · ${bfAmountHtml(s.signed_amount_paise)} ` +
    `${pill(exact ? 'Exact' : 'Close', exact ? 'good' : 'warn')} <span class="muted">${why}</span></label></li>`;
}

function bfRuleFormHtml(line) {
  const accounts = bfAccounts().map(a => `<option value="${Number(a.id)}">${esc(a.code + ' ' + a.name)}</option>`).join('');
  const direction = line.signed_amount_paise > 0 ? 'inflow' : 'outflow';
  return `<form class="g-form section-gap" data-bf="rule-form" data-line="${Number(line.id)}">` +
    `<label class="g-field"><span>When the reference contains</span><input name="match_text" class="form-input" minlength="2" maxlength="120" required value="${esc(line.statement_reference)}"></label>` +
    `<label class="g-field"><span>For</span><select name="direction" class="form-input">` +
    `<option value="any">Money in or out</option><option value="inflow"${direction === 'inflow' ? ' selected' : ''}>Money in</option><option value="outflow"${direction === 'outflow' ? ' selected' : ''}>Money out</option></select></label>` +
    `<label class="g-field"><span>Suggest this account</span><select name="suggested_account_id" class="form-input" required>${accounts}</select></label>` +
    `<label class="g-field"><span>Note (optional)</span><input name="note" class="form-input" maxlength="300"></label>` +
    `<p class="muted">A rule only suggests. It never adds or matches anything by itself.</p>` +
    `<div><button type="submit" class="btn btn-primary btn-sm">Draft rule for approval</button> ` +
    `<button type="button" class="btn btn-secondary btn-sm" data-bf="rule-cancel">Cancel</button></div></form>`;
}

function bfFeedHtml() {
  const f = state.bf.feed;
  if (!f) return '<div class="loading">Loading…</div>';
  const lines = f.uncategorised || [];
  if (!lines.length) return '<p class="muted">Every statement line for this bank is matched. Import a newer statement to continue.</p>';
  const count = Object.keys(state.bf.picked).length;
  const rows = lines.map(line => {
    const suggestions = line.match_suggestions || [];
    const rule = line.rule_suggestion;
    const account = rule && bfAccounts().find(a => a.id === rule.suggested_account_id);
    return `<li class="panel section-gap"><div class="panel-body">` +
      `<div><strong>${esc(line.booking_date)}</strong> · ${esc(line.statement_reference)} · ${bfAmountHtml(line.signed_amount_paise)}</div>` +
      (rule ? `<p class="muted">Rule “${esc(rule.match_text)}” suggests ${esc(account ? account.code + ' ' + account.name : 'account #' + rule.suggested_account_id)}.</p>` : '') +
      (suggestions.length
        ? `<ul class="bf-list">${suggestions.map(s => bfSuggestionHtml(line, s)).join('')}</ul>`
        : '<p class="muted">No book entry has this amount yet. Record the payment or receipt first, then match it here.</p>') +
      (state.bf.ruleFor === line.id ? bfRuleFormHtml(line)
        : `<button type="button" class="btn btn-secondary btn-sm" data-bf="rule-open" data-line="${Number(line.id)}">Make a rule from this line</button>`) +
      `</div></li>`;
  }).join('');
  return `<div class="row-actions"><button type="button" class="btn btn-primary btn-sm" data-bf="match"${count ? '' : ' disabled'}>` +
    `Draft ${count} match${count === 1 ? '' : 'es'} for approval</button> <span class="muted">Tick one book entry per statement line.</span></div>` +
    `<ul class="bf-list">${rows}</ul>`;
}

function bfMatchedHtml() {
  const m = state.bf.matched;
  if (!m) return '<div class="loading">Loading…</div>';
  const undone = new Set((state.bf.feed?.reconciliations || []).filter(r => r.unreconciled).map(r => r.id));
  if (!m.matches.length) return '<p class="muted">Nothing is matched for this bank yet.</p>';
  const rows = m.matches.map(r => `<tr><td>${esc(r.statement_reference)}</td><td>${bfAmountHtml(r.signed_amount_paise)}</td>` +
    `<td>Book entry #${Number(r.journal_id)}</td><td>${undone.has(r.id) ? pill('Un-matched', 'warn')
      : `<button type="button" class="btn btn-secondary btn-sm" data-bf="unmatch" data-id="${Number(r.id)}">Un-match</button>`}</td></tr>`).join('');
  return `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Statement line</th><th>Amount</th><th>Matched to</th><th></th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>` + (m.has_more ? `<p class="muted">Showing the first ${m.matches.length} of ${Number(m.total)}.</p>` : '');
}

function bfStatementHtml() {
  const s = state.bf.statement;
  if (!s) return '<div class="loading">Loading…</div>';
  if (!s.lines.length) return '<p class="muted">No statement lines yet. Use “Import statement (CSV)”.</p>';
  const rows = s.lines.map(l => `<tr><td>${esc(l.booking_date)}</td><td>${esc(l.statement_reference)}</td><td>${bfAmountHtml(l.signed_amount_paise)}</td>` +
    `<td>${l.matched_journal_id ? 'Book entry #' + Number(l.matched_journal_id) : pill('To match', 'warn')}</td></tr>`).join('');
  return `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Date</th><th>Reference</th><th>Amount</th><th>Match</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>` + (s.has_more ? `<p class="muted">Showing the first ${s.lines.length} of ${Number(s.total)}.</p>` : '');
}

function bfBookHtml() {
  const b = state.bf.book;
  if (!b) return '<div class="loading">Loading…</div>';
  const net = Number(b.book_net_paise || 0);
  const rows = b.movements.map(m => `<tr><td>Book entry #${Number(m.journal_id)}</td><td>${m.side === 'debit' ? 'In' : 'Out'}</td>` +
    `<td class="num">${esc(bfRs(m.amount_paise))}</td><td>${m.bank_reconciled ? pill('Matched', 'good') : pill('Not matched', 'warn')}</td></tr>`).join('');
  return `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${net < 0 ? '−' : ''}${esc(bfRs(net))}</div><div class="v-tile-label">Balance in the books</div></div></div>` +
    (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Entry</th><th>Direction</th><th>Amount</th><th>Statement</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<p class="muted">No book entries on this bank account yet.</p>');
}

function bfView() {
  const title = 'Bank feed';
  const sub = 'Bring in your bank statement and match each line to the books. Every match is approved before it counts.';
  if (!BF_ROLES.includes(state.user?.role)) return head(title, 'The bank feed is for the owner and accounts.');
  if (!state.bf.home) {
    bfInit();
    return head(title, sub) + '<div class="loading">Loading…</div>';
  }
  if (!bfBanks().length) {
    return head(title, sub) + bfPickersHtml() + '<p class="muted">This company has no bank account yet. Add one in Books first.</p>';
  }
  const body = {feed: bfFeedHtml, matched: bfMatchedHtml, statement: bfStatementHtml, book: bfBookHtml}[state.bf.tab]();
  return head(title, sub) + bfPickersHtml() + bfImportHtml() + `<section class="panel section-gap"><div class="panel-body">${body}</div></section>`;
}

async function bfSwitch(fn) {
  try { await fn(); } catch (err) { notify(err.message, true); }
  render();
}

/* One book entry per statement line, and one statement line per book entry, as the server requires. */
function bfTogglePick(lineId, journalId, on) {
  const picked = state.bf.picked;
  if (!on) { if (picked[lineId] === journalId) delete picked[lineId]; return; }
  for (const k of Object.keys(picked)) if (picked[k] === journalId) delete picked[k];
  picked[lineId] = journalId;
}

async function bfDraftMatches() {
  const matches = Object.entries(state.bf.picked).map(([line, journal]) => ({statement_line_id: Number(line), journal_id: Number(journal)}));
  if (!matches.length) return;
  const r = await api(`/api/finance-ledger/banks/${Number(state.bf.bankId)}/reconciliation-draft`, {method: 'POST', body: JSON.stringify({matches})});
  notify(`Drafted ${r.to_review} match${r.to_review === 1 ? '' : 'es'} as change request #${r.ticket_id}. Nothing is matched until it is approved.`);
  refresh();
  state.bf.picked = {};
  await bfLoadTab();
}

async function bfDraftImport() {
  const csv = state.bf.csv;
  const evidence = Number(state.bf.evidenceId || 0);
  if (!csv || !evidence) { notify('Choose the statement CSV and its proof document first.', true); return; }
  const r = await api(`/api/books/bank-feed/${Number(state.bf.bankId)}/import-csv`, {method: 'POST',
    body: JSON.stringify({csv_text: csv.text, evidence_document_id: evidence, request_key: bfKey()})});
  notify(`Drafted ${r.imported_count} new line${r.imported_count === 1 ? '' : 's'} as change request #${r.ticket_id}` +
    (r.skipped_count ? `; ${r.skipped_count} already brought in were skipped` : '') + '. Nothing is added until it is approved.');
  refresh();
  Object.assign(state.bf, {importOpen: false, csv: null});
}

async function bfDraftRule(form) {
  const data = new FormData(form);
  const body = {entity_id: state.bf.entityId, bank_id: state.bf.bankId, match_text: String(data.get('match_text') || '').trim(),
    direction: String(data.get('direction') || 'any'), suggested_account_id: Number(data.get('suggested_account_id') || 0),
    note: String(data.get('note') || '').trim(), request_key: bfKey()};
  if (body.match_text.length < 2 || !body.suggested_account_id) { notify('Give the words to look for and the account to suggest.', true); return; }
  const r = await api('/api/books/bank-rules', {method: 'POST', body: JSON.stringify(body)});
  notify(`Rule drafted as change request #${r.ticket_id}. It starts suggesting once approved.`);
  state.bf.ruleFor = null;
  refresh();
}

async function bfUnmatch(id) {
  const reason = await askText('Why should this match be undone? (at least 5 characters, kept in the history)', '', 'Draft un-match');
  if (reason === null || reason === undefined) return;
  if (String(reason).trim().length < 5) { notify('Please give a reason of at least 5 characters.', true); return; }
  const r = await api('/api/books/bank-unreconcile', {method: 'POST',
    body: JSON.stringify({reconciliation_id: Number(id), reason: String(reason).trim(), request_key: bfKey()})});
  notify(`Un-match drafted as change request #${r.ticket_id}. The match stays until it is approved.`);
  refresh();
}

document.addEventListener('click', e => {
  const t = e.target.closest('[data-bf]');
  if (!t || state.view !== 'bankfeed') return;
  const action = t.dataset.bf;
  if (action === 'tab') { state.bf.tab = t.dataset.tab; bfSwitch(bfLoadTab); return; }
  if (action === 'refresh') { bfReset(); bfSwitch(bfLoadTab); return; }
  if (action === 'toggle-import') {
    state.bf.importOpen = !state.bf.importOpen;
    if (state.bf.importOpen && !state.bf.docs) { bfSwitch(async () => { state.bf.docs = await api('/api/documents'); }); return; }
    render();
    return;
  }
  if (action === 'import') { bfSwitch(bfDraftImport); return; }
  if (action === 'match') { bfSwitch(bfDraftMatches); return; }
  if (action === 'rule-open') { state.bf.ruleFor = Number(t.dataset.line); render(); return; }
  if (action === 'rule-cancel') { state.bf.ruleFor = null; render(); return; }
  if (action === 'unmatch') { bfSwitch(() => bfUnmatch(t.dataset.id)); }
});

document.addEventListener('change', e => {
  if (state.view !== 'bankfeed') return;
  const t = e.target;
  if (t.id === 'bfCompany') {
    state.bf.entityId = Number(t.value);
    state.bf.bankId = bfBanks()[0]?.id || null;
    bfReset();
    bfSwitch(bfLoadTab);
    return;
  }
  if (t.id === 'bfEvidence') { state.bf.evidenceId = Number(t.value) || null; return; }
  if (t.id === 'bfBank') { state.bf.bankId = Number(t.value); bfReset(); bfSwitch(bfLoadTab); return; }
  if (t.dataset && t.dataset.bf === 'pick') {
    bfTogglePick(Number(t.dataset.line), Number(t.dataset.journal), t.checked);
    render();
    return;
  }
  if (t.id === 'bfCsvFile' && t.files && t.files[0]) {
    const file = t.files[0];
    file.text().then(text => {
      const rows = text.split(/\r?\n/).filter(l => l.trim()).length - 1;
      state.bf.csv = {name: file.name, text, rows: Math.max(rows, 0)};
      render();
    }).catch(() => notify('That file could not be read. Save it again as CSV and retry.', true));
  }
});

document.addEventListener('submit', e => {
  const form = e.target.closest('[data-bf="rule-form"]');
  if (!form) return;
  e.preventDefault();
  bfSwitch(() => bfDraftRule(form));
});

const _bfRender = render;
render = function () {
  if (state.view !== 'bankfeed') { _bfRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = bfView();
  $('breadcrumb').textContent = 'Bank feed';
};

const _bfSwitchView = switchView;
switchView = function (view) {
  if (view === 'bankfeed') { state.bf.home = null; bfReset(); }
  return _bfSwitchView(view);
};
