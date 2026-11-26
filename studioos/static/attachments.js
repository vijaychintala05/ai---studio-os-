'use strict';
/* Money -> Attachments: see and attach documents on posted money entries (bills, payments, transfers, journals,
   expenses). The list comes from the posted journals, so nobody types a record number. Attaching drafts a change
   request. Loaded after gapkit.js. */

const AT_EVENTS = {
  DIRECT_BILL_POSTED: ['direct_bill', 'Bill'],
  SUPPLIER_BILL_ACCEPTED: ['supplier_bill', 'Supplier bill'],
  SUPPLIER_INVENTORY_BILL: ['supplier_bill', 'Supplier stock bill'],
  SUPPLIER_PAYMENT_POSTED: ['payment', 'Supplier payment'],
  DIRECT_BILL_PAYMENT_POSTED: ['direct_bill_payment', 'Bill payment'],
  INTERNAL_TRANSFER_POSTED: ['transfer', 'Transfer'],
  MANUAL_JOURNAL_POSTED: ['manual_journal', 'Manual journal'],
  DIRECT_EXPENSE_POSTED: ['expense', 'Expense'],
  STAFF_EXPENSE_CLAIMED: ['expense', 'Staff expense claim'],
};

function atEntries(journals) {
  return (journals || []).filter(j => AT_EVENTS[j.source_event]).map(j => ({
    kind: AT_EVENTS[j.source_event][0], label: AT_EVENTS[j.source_event][1], id: j.source_id, journal: j.id,
    amount: (j.lines || []).filter(l => l.side === 'debit').reduce((t, l) => t + l.amount_paise, 0),
  })).reverse();
}

async function atCompanies() { return (await api('/api/books/home')).companies; }

function atView() {
  const title = 'Attachments';
  const sub = 'Keep the bill, receipt or proof with each money entry.';
  const companies = gkGet('at:companies', atCompanies);
  if (!Array.isArray(companies)) return head(title, sub) + gkWait(companies);
  if (!companies.length) return head(title, sub) + '<p class="muted">Set up a company in Books first.</p>';
  const ui = state.gk.ui;
  if (!companies.some(c => c.entity_id === ui.atEntity)) ui.atEntity = companies[0].entity_id;
  const journals = gkGet(`at:journals:${ui.atEntity}`, () => api(`/api/finance-ledger/journals/${Number(ui.atEntity)}`));
  const picker = `<div class="g-form">${gkSelect('Company', 'entity', companies.map(c => [c.entity_id, c.name]), ui.atEntity, 'data-gk-change="company"')}</div>`;
  let list = gkWait(journals);
  if (Array.isArray(journals)) {
    list = gkTable(['Entry', 'Amount', ''], atEntries(journals).map(e => [
      `${esc(e.label)} #${Number(e.id)} <span class="muted">journal ${Number(e.journal)}</span>`, `<span class="num">${esc(gkRs(e.amount))}</span>`,
      gkButton('open', 'Attachments', `data-kind="${esc(e.kind)}" data-id="${Number(e.id)}"`)]), 'No money entries have been posted for this company yet.');
  }
  return head(title, sub) + gkPanel('Money entries', 'Newest first.', picker + list) + atDetail();
}

function atDetail() {
  const pick = state.gk.ui.atPick;
  if (!pick) return '';
  const found = gkGet(`at:list:${pick.kind}:${pick.id}`, () => api(`/api/books/attachments?target_kind=${encodeURIComponent(pick.kind)}&target_id=${Number(pick.id)}`));
  const docs = gkGet('at:docs', () => api('/api/documents'));
  let body = gkWait(found);
  if (found && found.attachments) {
    body = gkTable(['Document', 'Note', 'Same file elsewhere'], found.attachments.map(a => [
      `<a class="cx-link" href="/api/documents/${Number(a.document_id)}/file" target="_blank" rel="noopener">${esc(a.document_name || 'Document #' + a.document_id)}</a>`,
      esc(a.note), a.duplicate_elsewhere ? pill('Yes, check it', 'warn') : 'No']), 'Nothing attached yet.');
  }
  let form = gkWait(docs);
  if (Array.isArray(docs)) {
    form = docs.length
      ? gkForm('attach', gkSelect('Document', 'document_id', docs.map(d => [d.id, d.name]), docs[0].id) +
        gkInput('Note (optional)', 'note', 'maxlength="250"'), 'Attach for approval')
      : '<p class="muted">No documents yet. Add a file in Documents or Files to sort first.</p>';
  }
  return gkPanel(`Attachments for ${pick.kind.replaceAll('_', ' ')} #${pick.id}`, '', body + form);
}

async function atAttach(form) {
  const v = gkValues(form);
  const pick = state.gk.ui.atPick;
  const r = await gkDraft('/api/books/attachments', {entity_id: state.gk.ui.atEntity, target_kind: pick.kind, target_id: pick.id,
    document_id: Number(v.document_id), note: v.note || '', request_key: gkKey()}, 'Attachment drafted');
  if (r.duplicate_warning) {
    const where = (r.existing_targets || []).map(t => `${String(t.target_kind).replaceAll('_', ' ')} #${t.target_id}`).join(', ');
    notify(`This file is already attached to ${where || 'another entry'}. Check it is not a duplicate before approving.`, true);
  }
}

gkScreen('moneyfiles', {
  title: 'Attachments', roles: ['admin', 'accounts'], view: atView,
  change: {company: el => { state.gk.ui.atEntity = Number(el.value); state.gk.ui.atPick = null; }},
  click: {open: el => { state.gk.ui.atPick = {kind: el.dataset.kind, id: Number(el.dataset.id)}; }},
  submit: {attach: atAttach},
});
