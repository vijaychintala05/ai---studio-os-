'use strict';
/* Money -> Period close: lock and reopen months by area, legal holds on projects, and a vendor's or client's tax
   registration. Also warns on any money form when the chosen date falls in a locked month. Every change drafts a
   ticket; the server still refuses locked dates on its own. Loaded after gapkit.js. */

const PC_AREAS = [['sales', 'Sales'], ['purchases', 'Purchases'], ['bank', 'Bank']];
const PC_REGISTRATION = [['', 'Not recorded'], ['regular', 'Regular GST'], ['composition', 'Composition'], ['unregistered', 'Not registered']];
const pcOptions = () => api('/api/sales/options');

function pcCompanies() {
  const opts = gkGet('pc:options', pcOptions);
  return opts && opts.companies ? opts : null;
}

function pcView() {
  const title = 'Period close';
  const sub = 'Close a month so nobody can back-date into it. Every close and reopening is approved and kept in the history.';
  const raw = gkGet('pc:options', pcOptions);
  const opts = pcCompanies();
  if (!opts) return head(title, sub) + gkWait(raw);
  if (!opts.companies.length) return head(title, sub) + '<p class="muted">Set up a company first.</p>';
  const ui = state.gk.ui;
  if (!opts.companies.some(c => c.id === ui.pcEntity)) ui.pcEntity = opts.companies[0].id;
  const company = `<div class="g-form">${gkSelect('Company', 'company', opts.companies.map(c => [c.id, c.name]), ui.pcEntity, 'data-gk-change="company"')}</div>`;
  return head(title, sub) + gkSections('pcSection', [
    ['locks', 'Locked months', () => pcLocks(company)],
    ['admin', 'accounts'].includes(state.user?.role) && ['holds', 'Legal holds', pcHolds],
    ['tax', 'Tax registration', () => pcTaxProfile(opts)],
  ]);
}

function pcLocks(company) {
  const ui = state.gk.ui;
  const locks = gkGet(`pc:locks:${ui.pcEntity}`, () => api(`/api/period/locks?entity_id=${Number(ui.pcEntity)}`));
  let list = gkWait(locks);
  if (Array.isArray(locks)) {
    list = gkTable(['Month', 'Area', 'State', 'Locked by', 'Reason', ''], [...locks].reverse().map(l => [
      esc(l.year_month), esc((PC_AREAS.find(a => a[0] === l.area) || [0, l.area])[1]),
      l.open ? pill('Locked', 'warn') : pill('Reopened', 'good'), esc(l.locked_by), esc(l.open ? l.reason : `${l.reason} · reopened: ${l.reopen_reason || ''}`),
      l.open && isAdmin() ? gkButton('reopen', 'Reopen', `data-id="${Number(l.id)}"`) : '']), 'No month is locked for this company.');
  }
  const form = gkForm('lock', gkInput('Month', 'year_month', 'required', 'month') + gkSelect('Area', 'area', PC_AREAS, 'purchases') +
    gkInput('Why (at least 5 characters)', 'reason', 'required minlength="5" maxlength="300"'), 'Draft month lock');
  return gkPanel('Locked months', 'Sales, purchases and bank lock separately.', company + list + form);
}

function pcHolds() {
  if (!['admin', 'accounts'].includes(state.user?.role)) return '';
  const holds = gkGet('pc:holds', () => api('/api/period/holds'));
  const projects = gkGet('pc:projects', () => api('/api/projects'));
  let list = gkWait(holds);
  const names = Array.isArray(projects) ? projects : [];
  const nameOf = id => (names.find(p => p.id === id) || {}).name || `Project ${id}`;
  if (Array.isArray(holds)) {
    list = gkTable(['Project', 'Reason', 'Placed by', 'State', ''], holds.map(h => [esc(nameOf(h.project_id)), esc(h.reason), esc(h.placed_by),
      h.active ? pill('On hold', 'warn') : pill('Released', 'good'),
      h.active && isAdmin() ? gkButton('release', 'Release', `data-id="${Number(h.id)}"`) : '']), 'No project is on legal hold.');
  }
  const form = isAdmin() && names.length ? gkForm('hold', gkSelect('Project', 'project_id', names.map(p => [p.id, p.name]), names[0].id) +
    gkInput('Why (at least 5 characters)', 'reason', 'required minlength="5" maxlength="300"'), 'Draft legal hold') : '';
  return gkPanel('Legal holds', 'A project on hold cannot have its records deleted.', list + form);
}

function pcTaxProfile(opts) {
  const ui = state.gk.ui;
  const parties = [...(opts.clients || []).map(p => [p.id, `${p.name} (client)`]), ...(opts.vendors || []).map(p => [p.id, `${p.name} (vendor)`])];
  if (!parties.length) return '';
  if (!parties.some(p => p[0] === ui.pcParty)) ui.pcParty = parties[0][0];
  const profiles = gkGet(`pc:tax:${ui.pcParty}`, () => api(`/api/period/tax-profiles?party_id=${Number(ui.pcParty)}`));
  let list = gkWait(profiles);
  if (Array.isArray(profiles)) {
    list = gkTable(['From', 'Registration'], profiles.map(p => [esc(p.effective_from),
      esc((PC_REGISTRATION.find(r => r[0] === p.registration_type) || [0, p.registration_type])[1])]), 'No tax registration recorded for this contact.');
  }
  const form = gkForm('profile', gkSelect('Registration', 'registration_type', PC_REGISTRATION, 'regular') +
    gkInput('Applies from', 'effective_from', 'required', 'date'), 'Draft registration change');
  return gkPanel('Tax registration', 'Kept by date, so older bills keep the registration that applied then.',
    `<div class="g-form">${gkSelect('Contact', 'party', parties, ui.pcParty, 'data-gk-change="party"')}</div>` + list + form);
}

async function pcReason(question) {
  const reason = await askText(question, '', 'Draft for approval');
  if (reason === null || reason === undefined) return null;
  if (String(reason).trim().length < 5) { notify('Please give a reason of at least 5 characters.', true); return null; }
  return String(reason).trim();
}

const pcPropose = (kind, data) => gkDraft('/api/period/propose', {kind, data});

gkScreen('periodclose', {
  title: 'Period close', roles: ['admin', 'accounts'], view: pcView,
  change: {company: el => { state.gk.ui.pcEntity = Number(el.value); }, party: el => { state.gk.ui.pcParty = Number(el.value); }},
  click: {
    reopen: async el => { const reason = await pcReason('Why should this month be reopened?'); if (reason) await pcPropose('period_area_reopen', {lock_id: Number(el.dataset.id), reason}); },
    release: async el => { const reason = await pcReason('Why can this legal hold be released?'); if (reason) await pcPropose('legal_hold_release', {hold_id: Number(el.dataset.id), reason}); },
  },
  submit: {
    lock: async form => { const v = gkValues(form); await pcPropose('period_area_lock', {entity_id: state.gk.ui.pcEntity, year_month: v.year_month, area: v.area, reason: v.reason}); },
    hold: async form => { const v = gkValues(form); await pcPropose('legal_hold_place', {project_id: Number(v.project_id), reason: v.reason}); },
    profile: async form => { const v = gkValues(form); await pcPropose('party_tax_profile', {party_id: state.gk.ui.pcParty, registration_type: v.registration_type, effective_from: v.effective_from}); },
  },
});

/* ---------------------------------------------------------------- warn on money forms ---------------- */
const PC_DATE_FIELDS = ['bill_date', 'payment_date', 'date', 'invoice_date', 'receipt_date', 'note_date', 'transfer_date', 'journal_date'];
const PC_MONEY_VIEWS = ['books', 'party', 'sales', 'receipts', 'budget', 'ledger', 'expense', 'moneyfiles', 'bankfeed'];

function pcAreaFor(view, name) {
  if (view === 'sales' || view === 'receipts') return 'sales';
  if (name === 'transfer_date' || name === 'journal_date') return 'bank';
  return 'purchases';
}

/* The company is taken from the form, then the sales screen; with only one company there is no doubt. */
async function pcEntityFor(form) {
  const field = form?.querySelector?.('[name="entity_id"]');
  const own = Number(field?.value || form?.dataset?.entity || 0);
  if (own) return own;
  if (['sales', 'receipts'].includes(state.view) && state.sales?.companyId) return state.sales.companyId;
  const home = await api('/api/books/home');
  return home.companies.length === 1 ? home.companies[0].entity_id : 0;
}

async function pcWarn(input) {
  if (!PC_MONEY_VIEWS.includes(state.view) || input.type !== 'date' || !input.value) return;
  if (!PC_DATE_FIELDS.includes(input.name)) return;
  const entity = await pcEntityFor(input.form);
  if (!entity) return;
  const r = await api(`/api/period/check?entity_id=${Number(entity)}&area=${pcAreaFor(state.view, input.name)}&document_date=${encodeURIComponent(input.value)}`);
  if (r.locked) notify(`${r.why} The entry will be refused unless the month is reopened.`, true);
}

document.addEventListener('change', e => {
  if (e.target && e.target.type === 'date') pcWarn(e.target).catch(() => {});   // a warning only; the server decides
});
