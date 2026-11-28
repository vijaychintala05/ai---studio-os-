'use strict';
/* StudioOS v0.9.0 conversational chat (decision lines, build requests and record types added).
   Originally v0.8.0 conversational chat. Loaded after app.js; replaces the old
   assistant() and sendChat(). The chat is the landing page. Nothing here saves
   business data by itself: drafts become records only through "Approve and save"
   (a full ticket approval and atomic commit on the server). */

Object.assign(state, {view: 'assistant', thinking: false, thinkingText: '', editing: null, attachments: [], historyOpen: false, sessions: [], sessionsLoading: false, historyQuery: '', historyFilter: 'all', draggingFiles: false});

const CX_SAMPLES = [
  {label: 'Log an expense', fill: 'Paid ₹ ', roles: ['admin', 'manager', 'accounts']},
  {label: 'Add a task', fill: 'Add task: ', roles: ['admin', 'manager', 'architect']},
  {label: 'Site update', fill: 'Site update for ', roles: ['admin', 'manager', 'site_engineer']},
  {label: 'Show all projects', send: 'Show all projects', roles: ['viewer']},
  {label: "What's pending?", send: 'Show pending tasks'},
  {label: 'Budget summary', send: 'Show the budget summary', roles: ['admin', 'manager', 'accounts']},
];
function cxSamplesForRole() {
  const role = state.user?.role;
  return CX_SAMPLES.filter(s => !s.roles || s.roles.includes(role));
}
const REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// --- pure chat ux helpers (no page and no network: tested directly with node)
function cxEsc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function cxInlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code class="cx-code">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
function md(s) {
  // Safe formatting: headings, **bold**, `code`, unordered/ordered lists, and simple pipe tables. Escaped first.
  const lines = cxEsc(s).split('\n');
  let html = '', list = '';
  const closeList = () => { if (list) { html += `</${list}>`; list = ''; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    // Simple pipe table: header row + separator row (|---|---|) + body rows
    if (/^\|.+\|$/.test(trimmed) && i + 1 < lines.length && /^\|[\s:|-]+\|$/.test(lines[i + 1].trim())) {
      closeList();
      const cells = r => r.trim().slice(1, -1).split('|').map(c => c.trim());
      const head = cells(trimmed);
      i += 2;
      const body = [];
      while (i < lines.length && /^\|.+\|$/.test(lines[i].trim())) { body.push(cells(lines[i])); i++; }
      i--;
      html += `<div class="cx-table-wrap"><table class="cx-table"><thead><tr>${head.map(c => `<th>${cxInlineMd(c)}</th>`).join('')}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${cxInlineMd(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      continue;
    }
    const heading = /^#{1,3}\s+(.+)$/.exec(trimmed);
    if (heading) { closeList(); html += `<div class="cx-h">${cxInlineMd(heading[1])}</div>`; continue; }
    const bullet = /^\s*[-•]\s+(.*)$/.exec(line);
    if (bullet) {
      if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
      html += `<li>${cxInlineMd(bullet[1])}</li>`;
      continue;
    }
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ordered) {
      if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
      html += `<li>${cxInlineMd(ordered[1])}</li>`;
      continue;
    }
    closeList();
    html += trimmed ? `<p>${cxInlineMd(line)}</p>` : '';
  }
  closeList();
  return html;
}
function cxFilterSessions(sessions, query, filter) {
  const q = String(query || '').trim().toLowerCase();
  return (sessions || []).filter(s => {
    if (filter === 'open' && !['draft', 'in_review'].includes(s.ticket_status)) return false;
    if (filter === 'saved' && s.ticket_status !== 'committed') return false;
    if (q && !String(s.title || '').toLowerCase().includes(q)) return false;
    return true;
  });
}
function cxGroupSessions(sessions, nowMs) {
  const now = new Date(nowMs ?? Date.now());
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startYesterday = startToday - 86400000;
  const groups = {Today: [], Yesterday: [], Earlier: []};
  for (const s of sessions || []) {
    const raw = String(s.updated_at || '');
    const t = Date.parse(raw.includes('T') || raw.endsWith('Z') ? raw : raw.replace(' ', 'T') + 'Z');
    if (Number.isFinite(t) && t >= startToday) groups.Today.push(s);
    else if (Number.isFinite(t) && t >= startYesterday) groups.Yesterday.push(s);
    else groups.Earlier.push(s);
  }
  return Object.entries(groups).filter(([, list]) => list.length > 0).map(([label, items]) => ({label, items}));
}
// --- end pure chat ux helpers
function plain(s) { return String(s ?? '').replace(/\*\*/g, ''); }
function greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'; }
function firstName() { return (state.user?.display_name || state.user?.username || '').split(' ')[0]; }
function cleanStored(text) { return String(text || '').split('\nPROPOSED ACTION:')[0]; }
function cxOpenDraft() {
  const card = [...state.messages].reverse().find(m => m.card)?.card;
  return card && !['committed', 'reversed'].includes(card.status) && (card.items || []).some(it => it.status === 'pending') ? card : null;
}
function cxCanSend() { return !state.thinking && (Boolean(String(state.draftText || '').trim()) || state.attachments.length > 0); }

/* ------------------------------------------------------------------ view */
function assistant() {
  const msgs = state.messages;
  const lastCardIndex = {};
  msgs.forEach((m, i) => { if (m.card?.id) lastCardIndex[m.card.id] = i; });
  const body = msgs.length
    ? msgs.map((m, i) => (m.afterSaving && !msgs[i - 1]?.afterSaving ? '<div class="cx-divider"><span>After saving</span></div>' : '') + cxMessage(m, i, lastCardIndex)).join('') + (state.thinking ? cxThinking() : '')
    : cxWelcome();
  const scopeBar = state.scope?.project_id
    ? `<div class="cx-scope-bar"${state.historyOpen ? ' inert' : ''}><span>Project context: <strong>${esc(state.scope.name)}</strong></span><button type="button" class="cx-link" data-action="cx-clear-scope">Clear</button></div>`
    : '';
  return `<div class="cx${state.draggingFiles ? ' cx-drop-active' : ''}" id="cx">
    <div class="cx-bar"${state.historyOpen ? ' inert' : ''}>
      <button class="cx-icon-btn" data-action="cx-menu" aria-label="Menu">☰</button>
      <button class="cx-icon-btn" data-action="cx-history" aria-label="Past conversations"><span>Chats</span></button>
      <div class="cx-bar-title">StudioOS${state.settings?.environment === 'test' ? ' <span class="cx-test">TEST COPY</span>' : ''}</div>
      <button class="cx-icon-btn" data-action="new-conversation" aria-label="New conversation" ${state.thinking ? 'disabled' : ''}>✎ <span>New</span></button>
    </div>
    ${scopeBar}
    <div class="cx-scroll" id="chatMessages" aria-live="polite"${state.historyOpen ? ' inert' : ''}>${body}</div>
    <button type="button" class="cx-jump" id="cxJump" data-action="cx-jump-bottom" aria-label="Jump to latest" hidden>↓ Latest</button>
    <div class="cx-drop-overlay" aria-hidden="true"><span>Drop photos or PDFs to attach</span></div>
    ${cxComposer()}
    ${state.historyOpen ? cxHistory() : ''}
  </div>`;
}

function cxWelcome() {
  const isViewer = state.user?.role === 'viewer';
  return `<div class="cx-welcome"><div class="cx-mark">✦</div>
    <h2>${esc(greeting())}${firstName() ? ', ' + esc(firstName()) : ''}.</h2>
    <p>${isViewer ? 'Ask about the projects and tasks you can see. Your role has read-only access.' : "Tell me what happened, ask about a project, or attach a bill or photo. I'll draft it; nothing is saved until it's approved."}</p>
    ${cxReminders()}
    <div class="cx-chips">${cxSamplesForRole().map(s => `<button class="cx-chip" data-action="cx-sample" data-i="${CX_SAMPLES.indexOf(s)}">${esc(s.label)}</button>`).join('')}</div></div>`;
}
function cxThinking() {
  const label = state.thinkingText || 'Thinking…';
  return `<div class="cx-msg ai"><div class="cx-avatar">✦</div><div class="cx-body"><div class="cx-thinking-row" role="status" aria-label="${esc(label)}"><div class="cx-dots"><span></span><span></span><span></span></div><span class="cx-thinking-label">${esc(label)}</span></div></div></div>`;
}

function cxReminders() {
  const w = state.waiting; if (!w || !isApprover()) return '';
  const due = w.reminders || []; const open = (w.requests || []).filter(r => r.state === 'waiting_for_approval');
  if (!open.length) return '';
  return `<button class="cx-reminder${due.length ? ' due' : ''}" data-view="newtypes">${due.length ? '⏰ ' : ''}${open.length} kind${open.length === 1 ? '' : 's'} of information ${open.length === 1 ? 'is' : 'are'} waiting for a place${due.length ? ` · ${due.length} for over a week` : ''} <span>Open</span></button>`;
}

function cxMessage(m, i, lastCardIndex) {
  if (m.role === 'system') return `<div class="cx-decision" role="note">${esc(m.reply)}</div>`;
  const stamp = m.createdAt ? `<span class="cx-time">${esc(time(m.createdAt))}</span>` : '';
  if (m.role === 'user') {
    const failed = m.failed
      ? `<div class="cx-failed" role="alert"><span>Not sent: ${esc(m.errorText || 'Connection error')}</span><button type="button" class="cx-link" data-action="cx-retry" data-i="${i}">Retry</button><button type="button" class="cx-link" data-action="cx-dismiss-failed" data-i="${i}">Remove</button></div>`
      : '';
    return `<div class="cx-msg me${m.failed ? ' failed' : ''}"><div class="cx-me-wrap"><div class="cx-bubble">${md(m.reply)}${(m.files || []).map(f => `<div class="cx-file">📎 ${esc(f)}</div>`).join('')}</div>${stamp ? `<div class="cx-meta cx-meta-me">${stamp}</div>` : ''}${failed}</div></div>`;
  }
  const text = md(m.reply);
  const live = m.card && lastCardIndex[m.card.id] === i;
  const card = !m.card ? '' : live ? cxCard(m.card, m.ask) : `<div class="cx-stale">${esc(m.card.items?.[0]?.line || 'Draft')} <span class="muted">· updated below</span></div>`;
  const asks = live && m.ask?.length ? cxAsks(m.ask, m.card) : (!m.card && m.ask?.length ? cxAsks(m.ask, null) : '');
  const hold = m.build_request ? cxBuildRequest(m.build_request)
    : m.holding_item ? `<div class="cx-note">Kept unchanged in the waiting area. <button class="cx-link" data-action="open-new-type" data-id="${Number(m.holding_item.id)}">Open</button></div>` : '';
  const copyBtn = m.reply && String(m.reply).trim() ? `<button type="button" class="cx-copy-btn" data-action="cx-copy" data-i="${i}" aria-label="Copy reply">Copy</button>` : '';
  const meta = (stamp || copyBtn) ? `<div class="cx-meta">${stamp}${copyBtn}</div>` : '';
  return `<div class="cx-msg ai${m.error ? ' error' : ''}${m.fresh ? ' cx-msg-new' : ''}"><div class="cx-avatar">✦</div><div class="cx-body">
    <div class="cx-text" data-i="${i}">${text}</div>
    <div class="cx-after" data-i="${i}">${asks}${card}${hold}${(m.drafts || []).map(d => `<button class="btn btn-secondary btn-sm" data-action="cx-open-drafts" data-id="${esc(d.session_id)}">Review ${Number(d.drafted)} drafted ${esc(d.title)}</button>`).join(' ')}</div>${meta}</div></div>`;
}

function cxAsks(allAsks, card) {
  const editable = card && !['committed', 'reversed'].includes(card.status);
  const asks = cxVisibleAsks(allAsks, card);
  if (!asks.length) return '';
  return `<div class="cx-asks">${asks.map(a => `<div class="cx-ask"><div class="cx-ask-q">${esc(a.text)}</div>${
    a.choices?.length ? `<div class="cx-ask-choices">${a.choices.map((c, j) => `<button class="cx-choice" ${editable || !a.field ? '' : 'disabled'} data-action="cx-answer" data-ask="${esc(a.id)}" data-j="${j}">${esc(c.label)}</button>`).join('')}</div>`
    : `<button class="cx-link" data-action="cx-reply-hint">Type your answer below</button>`}</div>`).join('')}</div>`;
}

function cxBuildRequest(r) {
  const states = {waiting_for_approval: ['Waiting for a place', 'draft'], built: ['Built ✓', 'ok'], retired: ['Undone', ''], rejected: ['Not built', ''], kept: ['Kept as a note', '']};
  const [label, cls] = states[r.state] || [r.state, ''];
  const sample = (r.samples || [])[0];
  const preview = (r.fields || []).map(f => `<div class="cx-bfield"><span class="cx-f-label">${esc(f.label)}${f.required && f.required !== 'optional' ? ' <em>' + esc({draft: 'needed to save', approve: 'needed', close: 'needed to close'}[f.required] || '') + '</em>' : ''}</span><span class="cx-f-value">${esc(sample?.values?.[f.name] ?? '—')}</span></div>`).join('');
  const qs = r.unanswered_questions || [];
  const answering = state.answeringBuild === r.request_id;
  const form = answering ? `<form class="cx-bq" data-id="${Number(r.request_id)}">${qs.map((q, j) => `<label for="bq-${j}">${esc(q.text)}</label><textarea class="form-input" id="bq-${j}" name="${esc(q.id)}" rows="2" maxlength="600"></textarea>`).join('')}<div class="cx-edit-actions"><button class="btn btn-primary btn-sm" type="submit">Save answers</button><button class="btn btn-secondary btn-sm" type="button" data-action="cx-build-cancel">Cancel</button></div></form>` : '';
  let actions = '';
  if (r.state === 'waiting_for_approval') {
    actions = `<div class="cx-actions">${isAdmin() ? `<button class="btn btn-primary" data-action="cx-build-approve" data-id="${Number(r.request_id)}">Approve build</button>` : ''}${qs.length && !answering ? `<button class="btn btn-secondary" data-action="cx-build-answer" data-id="${Number(r.request_id)}">Answer questions (${qs.length})</button>` : ''}<button class="btn btn-secondary" data-action="cx-build-keep">Keep waiting</button>${isAdmin() ? `<button class="btn btn-danger btn-sm" data-action="cx-build-reject" data-id="${Number(r.request_id)}">Reject</button>` : ''}</div>
      ${isAdmin() ? '' : '<div class="cx-fine">The Admin approves new kinds of records.</div>'}`;
  } else if (r.state === 'built') {
    actions = `<div class="cx-fine">${r.added} added · ${r.drafted} drafted for approval · ${r.waiting} still waiting</div>`;
  }
  return `<section class="cx-card cx-build" aria-label="New kind of record"><div class="cx-card-head"><span class="cx-state ${cls}">${esc(label)}</span><span class="muted">Request #${Number(r.request_id)}</span></div>
    <div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(String(r.title || '').replace(/^./, c => c.toUpperCase()))}</span></div>
    ${r.purpose ? `<p class="cx-bp"><strong>Why:</strong> ${esc(r.purpose)}</p>` : ''}
    <p class="cx-bp"><strong>Waiting:</strong> ${esc(r.why_needed)}${r.oldest_days ? ` Oldest ${r.oldest_days} day${r.oldest_days === 1 ? '' : 's'}.` : ''}</p>
    <div class="cx-bsub">How one record would look${sample ? ' (filled from a waiting entry)' : ''}</div><div class="cx-fields">${preview}</div>
    <p class="cx-bp muted">${esc(r.impact)}</p></div>${form}${actions}</section>`;
}

// --- pure card helpers (no page and no network: the tests run this block directly with node)
// Turn what a person typed into the value the server stores (rupees become paise, numbers become numbers). Shared by the one-field
// editor and the missing-details form, so both follow the same rules.
function cxCoerce(item, field, raw) {
  const text = raw == null ? '' : String(raw);
  const rupees = () => Number(text.replace(/[₹,\s]/g, ''));
  const shown = (item.fields || []).find(x => x.key === field) || {};
  let value = raw;
  if (field.endsWith('_paise')) {
    const n = rupees();
    if (!Number.isFinite(n) || n < 0) return {error: 'Enter an amount in rupees, like 12500'};
    value = Math.round(n * 100);
  } else if (field === 'progress' || field === 'cost_id') {
    if (!/^\d+$/.test(text.trim())) return {error: 'Enter a whole number'};
    value = Number(raw);
  } else if (field === 'gst_included') value = text === '' ? null : text === 'true';
  else if (field === 'markup_bps') {                              // typed as a percentage
    const n = Number(text.replace('%', '').trim());
    if (!Number.isFinite(n) || n < 0 || n > 100) return {error: 'Enter the mark-up as a percentage from 0 to 100'};
    value = Math.round(n * 100);
  } else if (field.endsWith('_id') && /^\d+$/.test(text.trim()) && (item.fields || []).some(x => x.key === field && x.choices)) value = Number(text);
  else if (shown.type === 'boolean' && !item.graph) value = text === 'yes' ? true : text === 'no' ? false : null;
  if (shown.type === 'record_id') {
    const found = (shown.choices || []).find(choice => String(choice.value) === text);
    if (!found) return {error: 'Choose a record from the list'};
    value = found.value;
  }
  if (shown.type === 'money' && !item.graph && text.trim() !== '') {
    const n = rupees();
    if (!Number.isFinite(n) || n <= 0) return {error: 'Enter an amount in rupees, like 12500'};
    value = Math.round(n * 100);
  }
  if ((field === 'parent_id' || field.startsWith('accounts.')) && /^\d+$/.test(text)) value = Number(raw);
  if (field === 'slots.gst_rate' && text.trim() !== '') value = Number(text.replace('%', ''));
  return {value};
}

// The draft's values with one field changed ("group.name" changes a value inside a group).
function cxAfterWith(after, field, value) {
  const dot = field.indexOf('.');
  if (dot < 0) return {...after, [field]: value};
  const group = field.slice(0, dot), sub = field.slice(dot + 1);
  return {...after, [group]: {...(after[group] || {}), [sub]: value}};
}

// Details a person can fill in together: missing values on any pending draft (everyday entries, built record types, books entries).
// A detail that is already asked as a tap-to-choose question stays a question (one tap is quicker than a form). On a built-type
// record the project is only ever chosen by tap, so it is never part of the form.
const CX_FORM_MAX = 6;
function cxMissingFields(card, asks) {
  if (!card || ['committed', 'reversed'].includes(card.status)) return [];
  const tapped = new Set((asks || []).filter(a => a.choices && a.choices.length && a.item_id && a.field).map(a => a.item_id + ':' + a.field));
  const out = [];
  for (const item of card.items || []) {
    if (item.status !== 'pending') continue;
    for (const f of item.fields || []) {
      if (item.graph && f.key === 'project_id') continue;
      if (f.marker === 'missing' && !f.locked && !tapped.has(item.id + ':' + f.key)) out.push({item, field: f});
    }
  }
  return out.slice(0, CX_FORM_MAX);
}

// Free-typing questions that the form already covers are not asked twice.
function cxVisibleAsks(asks, card) {
  const covered = new Set(cxMissingFields(card, asks).map(r => r.item.id + ':' + r.field.key));
  return (asks || []).filter(a => !(a.free_text && a.item_id && a.field && covered.has(a.item_id + ':' + a.field)));
}
// A "MISSING: field" flag repeats a detail the card already shows as missing: leave it out.
function cxRedundantMissing(flag, item) {
  if (/^MISSING required:/i.test(String(flag))) return true;      // the form below the card already lists what is still needed
  const m = /^MISSING:\s*(.+)$/i.exec(String(flag));
  if (!m) return false;
  return m[1].split(/[,\s]+/).filter(Boolean).every(key => (item.fields || []).some(f => f.key === key && f.marker === 'missing'));
}
// --- end pure card helpers

// one sentence that would fill this kind of form, shown under it
const CX_EDIT_EXAMPLES = {
  create_project: 'start date 5 December, manager Ravi', create_task: 'due date friday, assigned to Ravi, priority High',
  record_cost: 'date today, expense account Materials, paid through UPI', record_payment: 'payment date today, paid through cash',
  finance_expense: 'paid through cash, vendor Fictional Tile House, invoice number INV-12',
  finance_po: 'vendor Fictional Tile House, amount 25000, po number PO-12',
  finance_payment: 'paid through cash, reference UTR123', finance_direct_bill_payment: 'paid through cash, reference UTR123',
};
function cxMissingForm(card, asks) {
  const rows = cxMissingFields(card, asks);
  if (!rows.length) return '';
  const several = new Set(rows.map(r => r.item.id)).size > 1;
  const one = ({item, field}) => {
    const id = `cxm-${Number(item.id)}-${esc(field.key)}`;
    const input = cxFieldInput(item, field, id).replace(/ name="value"/, ` name="${esc('m__' + Number(item.id) + '__' + field.key)}"`);
    const where = several ? `${esc(item.title || 'Draft')}: ` : '';          // name the draft only when the form spans several
    return `<div class="cx-missing-field${field.required ? ' req' : ''}"><label for="${id}">${where}${esc(field.label)}${field.required ? '<span class="req-star" aria-hidden="true">*</span>' : ''}</label>${input}</div>`;
  };
  const need = rows.filter(r => r.field.required), more = rows.filter(r => !r.field.required);
  const head = need.length ? `<strong>${need.length === 1 ? '1 required detail to fill in' : need.length + ' required details to fill in'}</strong>` +
    `<span class="muted">Fill them in here, or just tell me in the chat, for example “${CX_EDIT_EXAMPLES[rows[0].item.item_type] || 'start date 5 December'}”.</span>`
    : '<strong>All the required details are in</strong><span class="muted">You can add more below, or tell me in the chat.</span>';
  return `<form class="cx-missing" data-ticket="${Number(card.id)}"><div class="cx-missing-head">${head}</div>${need.map(one).join('')}` +
    (more.length ? `<details class="cx-more"${need.length ? '' : ' open'}><summary>More details (optional)</summary>${more.map(one).join('')}</details>` : '') +
    `<div class="cx-edit-actions"><button class="btn btn-primary btn-sm" type="submit">Save details</button></div></form>`;
}

const MARK_LABEL = {sourced: 'from your words', answered: 'you answered', edited: 'edited', guessed: 'AI guess, please check', missing: 'missing', invalid: 'check this'};
const MARK_SYMBOL = {sourced: '✓', answered: '✓', edited: '✓', guessed: '?', missing: '!', invalid: '!'};
function cxCard(card, asks) {
  const reviewStatus = card.review_status || card.status;
  const saved = reviewStatus === 'committed', reversed = reviewStatus === 'reversed', rejected = reviewStatus === 'rejected';
  const head = saved ? '<span class="cx-state ok">Saved ✓</span>' : reversed ? '<span class="cx-state">Undone</span>' : rejected ? '<span class="cx-state">Rejected</span>' : '<span class="cx-state draft">Draft · not saved</span>';
  const inMissingForm = new Set(cxMissingFields(card, asks).map(r => r.item.id + ':' + r.field.key));
  const items = card.items.map(item => {
    if (item.status === 'rejected') {
      return `<div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(item.title || 'Proposed change')}</span><span class="tag critical">Rejected</span></div>${item.note ? `<p>Rejected: ${esc(item.note)}</p>` : ''}</div>`;
    }
    const decided = item.status !== 'pending';
    // an optional detail that is still blank is not a problem: it waits in "More details (optional)" below;
    // a missing detail already shown in the missing-details form below is not repeated in the top grid
    const fields = (item.fields || []).filter(f => !((f.marker === 'missing' && f.required === false) || (f.marker === 'missing' && inMissingForm.has(item.id + ':' + f.key)))).map(f => {
      const editing = state.editing && state.editing.item === item.id && state.editing.field === f.key;
      if (editing) return cxEditForm(item, f);
      const mark = f.marker || 'guessed';
      return `<button class="cx-field m-${esc(mark)}" ${saved || reversed || decided || f.locked ? 'disabled' : ''} data-action="cx-edit" data-item="${Number(item.id)}" data-field="${esc(f.key)}" title="${esc(f.source ? 'Source: ' + f.source : MARK_LABEL[mark] || '')}">
        <span class="cx-f-label">${esc(f.label)}${f.required && mark === 'missing' ? '<span class="req-star" aria-hidden="true">*</span>' : ''}</span><span class="cx-f-value">${esc(f.display)}</span><span class="cx-f-mark" aria-label="${esc(MARK_LABEL[mark] || mark)}">${MARK_SYMBOL[mark] || '?'}</span></button>`;
    }).join('');
    const flags = (item.flags || []).filter(fl => !/offline interpreter|requires reapproval/i.test(fl) && !cxRedundantMissing(fl, item)).map(fl => `<div class="cx-flag">${esc(humanFlag(fl))}</div>`).join('');
    const confirm = !saved && !reversed && item.status === 'pending' ? (item.needs_confirmation || []).map(c => `<label class="cx-confirm"><input type="checkbox" name="cx-confirm" value="${esc(c)}" data-ticket="${Number(card.id)}"> ${c === 'duplicate' ? "I checked this isn't already entered" : 'I checked this amount is correct'}</label>`).join('') : '';
    const status = item.status === 'approved' && !saved ? '<span class="tag good">Approved</span>' : '';
    if (saved || reversed) return `<div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(item.title || 'Draft')}</span>${status}</div><div class="cx-done-line">${esc(String(item.line || '').split(' · ').slice(1).join(' · '))}</div></div>`;
    const pendingCount = card.items.filter(x => x.status === 'pending').length;
    const notNow = item.can_reject === true && item.status === 'pending' && pendingCount > 1 ? `<button class="cx-link cx-notnow" data-action="cx-reject-item" data-id="${Number(item.id)}">Reject</button>` : '';
    return `<div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(item.title || 'Draft')}</span>${status}${notNow}</div>${fields ? `<div class="cx-fields">${fields}</div>` : ''}${cxStructured(item)}${item.attachments?.length ? approvalFiles(item) : ''}${flags}${confirm}</div>`;
  }).join('');
  let actions;
  if (saved) actions = `<div class="cx-actions">${isAdmin() ? `<button class="btn btn-secondary btn-sm" data-action="cx-undo" data-id="${Number(card.id)}">Undo</button>` : ''}<button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div>`;
  else if (rejected) actions = `<div class="cx-actions"><button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div>`;
  else if (reversed) actions = '';
  else if (card.can_approve === true) {
    const hasPending = card.items.some(x => x.status === 'pending');
    actions = `<div class="cx-legend"><span class="ok">✓</span> from you <span class="guess">?</span> AI guess, check <span class="miss">!</span> missing · tap a value to change it</div><div class="cx-actions"><button class="btn btn-primary" data-action="cx-approve" data-id="${Number(card.id)}" data-review="${esc(JSON.stringify(Object.fromEntries(card.items.map(item => [item.id, item.review_fingerprint]))))}">Approve and save</button>${hasPending ? `<button class="btn btn-secondary" data-action="cx-discard-draft" data-id="${Number(card.id)}">Discard</button>` : ''}<button class="btn btn-secondary" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div><div class="cx-fine">Saving records your approval.</div>`;
  } else actions = `<div class="cx-waiting">${esc(card.reason || 'Waiting for approval.')}</div><div class="cx-actions"><button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div>`;
  return `<section class="cx-card" aria-label="Draft to review"><div class="cx-card-head">${head}<span class="muted">Ticket #${Number(card.id)}</span></div>${items}${cxMissingForm(card, asks)}${actions}</section>`;
}
// v0.10.0: what a structured draft adds to the card: the double-entry lines, the steps
// of a procedure, why each account was chosen, and anything still stopping it being saved.
function cxStructured(item) {
  let out = '';
  if (item.journal?.length) out += `<table class="cx-journal"><caption>How it will be entered in the books</caption><tbody>${item.journal.map(j => `<tr><td class="cx-j-side">${esc(j.side)}</td><td>${esc(j.account)}${j.new ? ' <span class="tag">new</span>' : ''}</td><td class="cx-j-amt">${esc(j.amount)}</td></tr>`).join('')}</tbody></table>`;
  if (item.steps?.length) out += `<ol class="cx-steps">${item.steps.map(t => `<li>${esc(t)}</li>`).join('')}</ol>`;
  if (item.notes?.length) out += `<ul class="cx-notes">${item.notes.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
  if (item.explain?.length) out += `<div class="cx-why">${item.explain.map(t => `<div>${esc(t)}</div>`).join('')}</div>`;
  if (item.problems?.length && item.status === 'pending') out += item.problems.map(t => `<div class="cx-flag">${esc(t)}</div>`).join('');
  return out;
}
function humanFlag(f) {
  const s = String(f);
  if (/possible_duplicate|near_match/i.test(s)) return 'Looks like something already entered: ' + s.replace(/^[^:]*:\s*/, '');
  if (/unusually_high_amount/i.test(s)) return 'This amount is unusually high for this kind of entry.';
  if (/invalid_phone/i.test(s)) return 'The phone number does not look like a 10-digit mobile number.';
  if (/^MISSING:/i.test(s)) return 'Missing: ' + s.replace(/^MISSING:\s*/i, '').replace(/_paise\b/g, '').replace(/_/g, ' ');
  if (/date[_ ]interpretation[_ ]shown/i.test(s)) return 'Please check the interpreted date above.';
  if (/low[_ ]confidence/i.test(s)) return 'The AI was not sure about this one. Please check the values.';
  return s.replace(/_/g, ' ');
}
function cxFieldInput(item, f, id) {
  let input;
  if (f.choices?.length) input = `<select class="form-input" id="${id}" name="value">${f.raw == null ? '<option value="">Choose…</option>' : ''}${f.choices.map(c => `<option value="${esc(c.value)}" ${String(f.raw) === String(c.value) ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select>`;
  else if (f.type === 'money' && item.graph) input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw?.amount == null ? '' : esc(String(f.raw.amount))}" placeholder="Amount in ₹">`;
  else if (f.type === 'money') input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw == null ? '' : esc(String(f.raw / 100))}" placeholder="Amount in ₹">`;
  else if (f.type === 'project') input = `<select class="form-input" id="${id}" name="value"><option value="">No project</option>${(state.projects || []).map(p => `<option ${f.display === p.name || f.raw === p.name ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`;
  else if (f.key === 'payment_mode') input = `<select class="form-input" id="${id}" name="value">${[['cash', 'Cash'], ['upi', 'UPI'], ['bank_transfer', 'Bank transfer'], ['cheque', 'Cheque'], ['card', 'Card']].map(([v, l]) => `<option value="${v}" ${f.raw === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  else if (f.key === 'kind') input = `<select class="form-input" id="${id}" name="value"><option value="expense" ${f.raw === 'expense' ? 'selected' : ''}>Already spent</option><option value="commitment" ${f.raw === 'commitment' ? 'selected' : ''}>Purchase order</option></select>`;
  else if (f.key === 'gst_included') input = `<select class="form-input" id="${id}" name="value"><option value="">Not sure yet</option><option value="true" ${f.raw === true ? 'selected' : ''}>Included</option><option value="false" ${f.raw === false ? 'selected' : ''}>Not included</option></select>`;
  else if (f.key.endsWith('_paise')) input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw == null ? '' : esc(String(f.raw / 100))}" placeholder="Amount in ₹">`;
  else if (f.key === 'project' && !item.record_type && (state.projects || []).length) input = `<select class="form-input" id="${id}" name="value"><option value="">Choose a project…</option>${(state.projects || []).map(p => `<option ${f.raw === p.name ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`;
  else if (f.key === 'project' && item.record_type) input = `<select class="form-input" id="${id}" name="value">${[...(state.projects || []).map(p => p.name), 'Not project related'].map(n => `<option ${f.raw === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
  else if (f.type === 'boolean') input = `<select class="form-input" id="${id}" name="value"><option value="">Not known</option><option value="yes" ${f.raw === true ? 'selected' : ''}>Yes</option><option value="no" ${f.raw === false ? 'selected' : ''}>No</option></select>`;
  else if (f.type === 'date') input = `<input class="form-input" id="${id}" name="value" type="date" value="${esc(f.raw || '')}">`;
  else if (f.type === 'integer' || f.type === 'decimal') input = `<input class="form-input" id="${id}" name="value" inputmode="${f.type === 'integer' ? 'numeric' : 'decimal'}" value="${f.raw == null ? '' : esc(String(f.raw))}">`;
  else if (typeof regMeta === 'function' && regMeta(item, f.key) && regControl(regMeta(item, f.key), id, f.raw)) input = regControl(regMeta(item, f.key), id, f.raw);   // calendar, drop-down or people list from the form's field list
  else if (f.key.startsWith('data.')) input = `<textarea class="form-input" id="${id}" name="value" rows="2">${f.raw == null ? '' : esc(String(f.raw))}</textarea>`;
  else if (f.key === 'markup_bps') input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" placeholder="e.g. 10" value="${f.raw == null ? '' : esc(String(f.raw / 100))}">`;
  else if (f.key === 'progress') input = `<input class="form-input" id="${id}" name="value" inputmode="numeric" value="${f.raw == null ? '' : esc(String(f.raw))}" placeholder="0 to 100">`;
  else if (f.key === 'assignee' && (state.users || []).some(u => u.active !== false && u.role !== 'viewer')) {
    const people = (state.users || []).filter(u => u.active !== false && u.role !== 'viewer');
    const opts = people.map(u => { const name = u.display_name || u.username; return `<option value="${esc(name)}" ${f.raw === name ? 'selected' : ''}>${esc(name)} · ${esc(String(u.role).replaceAll('_', ' '))}</option>`; }).join('');
    input = `<select class="form-input" id="${id}" name="value"><option value="">Not assigned yet</option>${opts}</select>`;
  }
  else input = `<input class="form-input" id="${id}" name="value" value="${f.raw == null ? '' : esc(String(f.raw))}">`;
  return input;
}

function cxEditForm(item, f) {
  const id = `cxe-${Number(item.id)}-${esc(f.key)}`;
  const input = cxFieldInput(item, f, id);
  return `<form class="cx-edit" data-item="${Number(item.id)}" data-field="${esc(f.key)}"><label for="${id}">${esc(f.label)}</label>${input}<div class="cx-edit-actions"><button class="btn btn-primary btn-sm" type="submit">Update</button><button class="btn btn-secondary btn-sm" type="button" data-action="cx-edit-cancel">Cancel</button></div></form>`;
}

function cxComposer() {
  const speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  const placeholder = cxOpenDraft() ? "Reply to update this draft (e.g. 'paid through UPI'), or tap any field above" : 'Message StudioOS';
  const attached = state.attachments.length
    ? `<div class="cx-attached">${state.attachments.map((f, i) => {
        const preview = f.previewUrl ? `<img class="cx-att-thumb" src="${esc(f.previewUrl)}" alt="">` : `<span class="cx-att-badge">${esc((f.name.split('.').pop() || 'FILE').toUpperCase().slice(0, 4))}</span>`;
        return `<span class="cx-att">${preview}<span class="cx-att-name">${esc(f.name)}</span><button type="button" data-action="cx-unattach" data-i="${i}" aria-label="Remove ${esc(f.name)}">✕</button></span>`;
      }).join('')}<div class="cx-fine">Attachments are kept unchanged for review.</div></div>`
    : '';
  return `<div class="cx-composer"${state.historyOpen ? ' inert' : ''}>
    ${attached}
    <form class="cx-form" id="chatForm">
      ${state.user?.role === 'viewer' ? '' : '<label class="cx-tool" title="Attach a photo or file" aria-label="Attach a photo or file">＋<input type="file" id="chatFiles" multiple accept="image/*,.pdf,.txt,.csv" class="cx-file-input"></label>'}
      <textarea class="cx-input" id="chatInput" rows="1" placeholder="${esc(placeholder)}" aria-label="Message" ${state.thinking ? 'disabled' : ''}>${esc(state.draftText || '')}</textarea>
      ${speech ? `<button class="cx-tool${state.listening ? ' on' : ''}" type="button" data-action="cx-mic" aria-label="Speak">🎤</button>` : ''}
      <button class="cx-send" type="submit" id="chatSend" aria-label="Send" ${cxCanSend() ? '' : 'disabled'}>↑</button>
    </form></div>`;
}

function cxHistoryStatusPill(status) {
  if (!status) return '';
  const map = {committed: ['Saved', 'ok'], reversed: ['Undone', ''], rejected: ['Rejected', 'bad'], draft: ['Open draft', 'draft'], in_review: ['In review', 'draft']};
  const [label, cls] = map[status] || [status, ''];
  return `<span class="cx-hpill${cls ? ' ' + cls : ''}">${esc(label)}</span>`;
}
function cxHistoryListHtml() {
  if (state.sessionsLoading) return '<p class="muted cx-hempty">Loading conversations…</p>';
  const filtered = cxFilterSessions(state.sessions, state.historyQuery, state.historyFilter);
  if (!filtered.length) return `<p class="muted cx-hempty">${state.sessions.length ? 'No matching conversations.' : 'No conversations yet.'}</p>`;
  return cxGroupSessions(filtered).map(g => `<div class="cx-hgroup">${esc(g.label)}</div>` + g.items.map(s => `<button class="cx-hrow${s.id === state.sessionId ? ' current' : ''}" data-action="cx-open-session" data-id="${esc(s.id)}">
      <span class="cx-htitle">${esc(s.title)}</span><span class="cx-hmeta"><span>${esc(time(s.updated_at))}</span>${cxHistoryStatusPill(s.ticket_status)}</span></button>`).join('')).join('');
}
function cxHistory() {
  const filters = [['all', 'All'], ['open', 'Open drafts'], ['saved', 'Saved']];
  return `<div class="cx-drawer-backdrop" data-action="cx-history-close"></div><aside class="cx-drawer" role="dialog" aria-modal="true" aria-label="Past conversations"><div class="cx-drawer-head"><strong>Conversations</strong><button class="cx-icon-btn" data-action="cx-history-close" aria-label="Close">✕</button></div>
    <button class="btn btn-primary cx-newchat" data-action="new-conversation" ${state.thinking ? 'disabled' : ''}>✎ New conversation</button>
    <input class="form-input cx-hsearch" id="cxHistorySearch" type="search" placeholder="Search conversations…" aria-label="Search conversations" value="${esc(state.historyQuery || '')}">
    <div class="cx-hfilters" role="group" aria-label="Filter conversations">${filters.map(([k, l]) => `<button type="button" class="cx-hfilter${state.historyFilter === k ? ' active' : ''}" data-action="cx-hfilter" data-filter="${k}" aria-pressed="${state.historyFilter === k ? 'true' : 'false'}">${l}</button>`).join('')}</div>
    <div class="cx-hlist" id="cxHistoryList">${cxHistoryListHtml()}</div></aside>`;
}

/* ------------------------------------------------------------------ behaviour */
function cxUpdateJump() {
  const scroll = $('chatMessages'), btn = $('cxJump');
  if (!scroll || !btn) return;
  const dist = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
  btn.hidden = dist < 160;
}
function afterChatRender() {
  if (state.view !== 'assistant') return;
  if (state.historyOpen) document.querySelector('.cx-drawer [data-action="cx-history-close"]')?.focus();
  const scroll = $('chatMessages');
  if (scroll) {
    scroll.addEventListener('scroll', cxUpdateJump, {passive: true});
    const last = state.messages.length - 1;
    if (last >= 0 && state.messages[last].role === 'assistant' && !state.thinking && !state.keepScroll) showReply(last);
    else if (!state.keepScroll) scroll.scrollTop = scroll.scrollHeight;
    cxUpdateJump();
  }
  state.keepScroll = false;
  sizeInput();
  state.messages.forEach(m => { if (m.fresh) m.fresh = false; });
}
function showReply(i) {
  // Show a new reply from its start if it is taller than the visible chat, like Claude or ChatGPT.
  const scroll = $('chatMessages'); const msg = document.querySelector(`.cx-text[data-i="${i}"]`)?.closest('.cx-msg');
  if (!scroll || !msg) return;
  if (msg.offsetHeight > scroll.clientHeight * 0.8) scroll.scrollTop = msg.offsetTop - scroll.offsetTop - 8;
  else scroll.scrollTop = scroll.scrollHeight;
}
function sizeInput() { const t = $('chatInput'); if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; }

function cxIsRasterImage(file) {
  return /^image\/(jpeg|png|webp)$/.test(file?.type || '');
}

// The page's image policy permits data URLs but blocks blob URLs.
async function cxRasterDataUrl(file) {
  const {base64} = await encodeFile(file);
  return `data:${file.type};base64,${base64}`;
}

function cxCompressImage(file) {
  if (!cxIsRasterImage(file)) return Promise.resolve(file);
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      const maxDim = 1600, scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      if (scale >= 1 && file.size < 600 * 1024 && file.type !== 'image/webp') { resolve(file); return; }
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      c.toBlob(blob => {
        if (!blob) { resolve(file); return; }
        const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
        resolve(new File([blob], name, {type: 'image/jpeg'}));
      }, 'image/jpeg', 0.82);
    };
    img.onerror = () => resolve(file);
    cxRasterDataUrl(file).then(url => { img.src = url; }, () => resolve(file));
  });
}
function cxAddFiles(fileList) {
  if (!fileList || !fileList.length || state.user?.role === 'viewer') return;
  for (const f of fileList) {
    if (f.size > 8 * 1024 * 1024) { notify(`${f.name} is larger than 8 MB`, true); continue; }
    const attachment = {file: f, name: f.name || 'image.png', type: f.type || '', previewUrl: ''};
    state.attachments.push(attachment);
    if (cxIsRasterImage(f)) cxRasterDataUrl(f).then(url => {
      if (!state.attachments.includes(attachment)) return;
      attachment.previewUrl = url;
      if (state.view === 'assistant') render();
    }, () => {});
  }
  render();
}
function cxRemoveAttachment(index) {
  state.attachments.splice(index, 1);
  render();
}
function cxClearAttachments() {
  state.attachments = [];
}

/* With a draft open on the screen, "start date 5 December" or "paid through cash" is an edit of that draft, not a new question:
   it goes straight to the chat (the server applies it to the draft). Questions ("what is the budget...") are left alone. */
const CX_EDIT_WORDS = ['date', 'manager', 'status', 'stage', 'client', 'customer', 'location', 'address', 'budget', 'amount', 'vendor', 'supplier', 'paid',
  'account', 'project', 'phone', 'mobile', 'priority', 'due', 'assign', 'assigned', 'owner', 'invoice', 'reference', 'billable', 'markup', 'mark-up',
  'notes', 'note', 'description', 'code', 'type', 'start', 'end', 'category', 'through', 'name', 'title'];
function cxLooksLikeEdit(text) {
  const open = [...state.messages].reverse().find(m => m.card)?.card;
  if (!open || ['committed', 'reversed'].includes(open.status)) return false;
  const t = String(text || '').toLowerCase().trim();
  if (/^(?:what|how|which|who|when|where|why|show|list|give|tell|can|could|is|are|do|does)\b/.test(t)) return false;
  const words = new Set(CX_EDIT_WORDS);
  for (const it of open.items || []) for (const f of it.fields || []) String(f.label || '').toLowerCase().split(/[^a-z#-]+/).filter(w => w.length > 3).forEach(w => words.add(w));
  const first = /^(?:please\s+)?(?:also\s+|and\s+)?(?:set\s+|change\s+|update\s+|make\s+|put\s+|edit\s+|use\s+|add\s+|with\s+)?(?:the\s+|its\s+)?([a-z#-]+)/.exec(t);
  if (first && words.has(first[1])) return true;
  return /\b(?:is|to|=|:)\s+\S/.test(t) && [...words].some(w => new RegExp('\\b' + w + '\\b').test(t));
}

function pushReply(r, extra = {}) {
  state.messages.push({role: 'assistant', reply: r.reply || '', card: r.preview || r.card || null, ask: r.ask || [], holding_item: r.holding_item, build_request: r.build_request || null, createdAt: new Date().toISOString(), fresh: !REDUCED_MOTION, ...extra});
}

async function sendChat(content, retryFiles = null, replaceIndex = -1) {
  const v = String(content ?? '').trim();
  const attached = retryFiles ? retryFiles.slice() : state.attachments.slice();
  const files = attached.map(a => (a && a.file ? a.file : a));
  if ((!v && !files.length) || state.thinking) return;
  const outgoing = {role: 'user', reply: v || 'Attached files', files: files.map(f => f.name), createdAt: new Date().toISOString()};
  const session = state.session;
  if (replaceIndex >= 0 && state.messages[replaceIndex]) state.messages.splice(replaceIndex, 1, outgoing);
  else state.messages.push(outgoing);
  if (!retryFiles) { state.draftText = ''; cxClearAttachments(); }
  state.thinking = true;
  state.thinkingText = files.length ? (files.length === 1 ? 'Uploading attachment…' : `Uploading ${files.length} attachments…`) : 'Thinking…';
  state.editing = null;
  render();
  try {
    let r;
    const receiptTypes = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
    if (files.length && v && files.length <= 5 && files.every(f => receiptTypes.includes(f.type))) {
      // words plus photos or PDFs: the photos are the receipt of the expense or payment drafted from the words
      const ids = [];
      for (const f of files) {
        const prepared = await cxCompressImage(f);
        const enc = await encodeFile(prepared);
        const saved = await api('/api/expense-images', {method: 'POST', body: JSON.stringify({filename: enc.filename, base64: enc.base64})});
        ids.push(saved.id);
      }
      state.thinkingText = 'Drafting your entry…'; render();
      r = await api('/api/chat', {method: 'POST', body: JSON.stringify({message: v, session_id: state.sessionId, attachment_ids: ids, ...(state.scope && state.scope.project_id ? {project_id: state.scope.project_id} : {})})});
      const attached = new Set((r.preview?.items || []).flatMap(item => item.after?.receipt_ids || []));
      if (ids.some(id => !attached.has(id))) {
        r.reply += '\n\nThe file uploaded, but it was not linked to this change.';
      }
    } else if (files.length) {
      const attachments = [];
      for (const f of files) attachments.push(await encodeFile(await cxCompressImage(f)));
      r = await api('/api/new-types/intake', {method: 'POST', body: JSON.stringify({text: v || 'Attached files', session_id: state.sessionId, attachments})});
      r = {...r, reply: `I've kept ${files.length === 1 ? 'that file' : 'those files'} unchanged for review. To draft an expense from a receipt photo right away, include a short note (for example, "Paid ₹1,200 to Ravi").`};
    } else {
      r = await api('/api/chat', {method: 'POST', body: JSON.stringify({message: v, session_id: state.sessionId, ...(state.scope && state.scope.project_id ? {project_id: state.scope.project_id} : {})})});
    }
    if (session !== state.session) return;
    state.sessionId = r.session_id; try { sessionStorage.setItem('studioos-chat-id', state.sessionId); } catch (e) {}
    pushReply(r);
  } catch (err) {
    if (session === state.session) {
      outgoing.failed = true;
      outgoing.errorText = err.message || 'Could not send';
      outgoing.retryPayload = {text: v, files};
      notify(err.message, true);
    }
  } finally {
    if (session === state.session) {
      state.thinking = false;
      state.thinkingText = '';
      render();
      if (state.messages.at(-1)?.card) refresh();
    }
  }
}

async function reloadCard() {
  if (!state.sessionId) return;
  const h = await api('/api/chat/history/' + encodeURIComponent(state.sessionId));
  const idx = state.messages.map(m => !!m.card).lastIndexOf(true);
  if (h.card && idx >= 0) { state.messages[idx].card = h.card; state.messages[idx].ask = ['committed', 'reversed'].includes(h.card.status) ? [] : (h.ask || []); }
  const bidx = state.messages.map(m => !!m.build_request).lastIndexOf(true);
  if (h.build_request && bidx >= 0) state.messages[bidx].build_request = h.build_request;
  // Bring in decision lines written by the server (approved, saved, undone...).
  const known = state.messages.filter(m => m.role === 'system').length;
  h.messages.filter(m => m.speaker === 'system').slice(known).forEach(m => state.messages.push({role: 'system', reply: m.content, afterSaving: m.after_saving, createdAt: m.created_at || ''}));
  return h;
}

async function openSession(id) {
  const h = await api('/api/chat/history/' + encodeURIComponent(id));
  state.sessionId = id; try { sessionStorage.setItem('studioos-chat-id', id); } catch (e) {}
  state.messages = h.messages.map(m => ({role: m.speaker === 'user' ? 'user' : m.speaker === 'system' ? 'system' : 'assistant', reply: cleanStored(m.content), afterSaving: !!m.after_saving, createdAt: m.created_at || ''}));
  const extra = h.card ? {card: h.card, ask: h.ask || []} : h.build_request ? {build_request: h.build_request} : null;
  if (extra) {
    const firstAfter = state.messages.findIndex(m => m.afterSaving);
    const roles = state.messages.map(m => m.role);
    const before = firstAfter >= 0 ? roles.slice(0, firstAfter) : roles;
    const last = before.lastIndexOf('assistant');
    if (last >= 0) Object.assign(state.messages[last], extra); else state.messages.push({role: 'assistant', reply: '', ...extra});
  }
  state.historyOpen = false; state.editing = null;
  render();
}

async function restoreConversation() {
  if (!state.sessionId || state.messages.length) return;
  try { await openSession(state.sessionId); } catch (e) { state.sessionId = ''; try { sessionStorage.removeItem('studioos-chat-id'); } catch (x) {} }
}

let recognition = null;
async function toggleMic() {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) return;
  if (state.listening && recognition) { recognition.stop(); return; }
  let told = false; try { told = localStorage.getItem('studioos-voice-notice') === '1'; } catch (e) {}
  if (!told) {
    if (!await askConfirm("Voice is turned into text by your phone's or browser's own speech service (Apple on iPhone, Google on Chrome). Continue?")) return;
    try { localStorage.setItem('studioos-voice-notice', '1'); } catch (e) {}
  }
  recognition = new Speech();
  recognition.lang = 'en-IN'; recognition.interimResults = true; recognition.continuous = false;
  const start = $('chatInput')?.value || '';
  recognition.onresult = e => { const said = Array.from(e.results).map(r => r[0].transcript).join(''); const t = $('chatInput'); if (t) { t.value = (start ? start + ' ' : '') + said; state.draftText = t.value; sizeInput(); } };
  recognition.onend = () => { state.listening = false; render(); };
  recognition.onerror = e => { state.listening = false; if (e.error !== 'aborted' && e.error !== 'no-speech') notify('Voice input stopped: ' + e.error, true); render(); };
  state.listening = true; render(); recognition.start();
}

/* Delegated handlers. Registered on the capture phase so they run before app.js's. */
document.addEventListener('click', async e => {
  // v0.9.0 fix: "Details" on a chat card opened the ticket behind the chat, so nothing seemed to happen.
  const det = e.target.closest('[data-action="open-ticket"]');
  if (det && state.view === 'assistant') {
    e.stopImmediatePropagation();
    try { state.ticketDetail = await api('/api/tickets/' + Number(det.dataset.id)); state.view = 'tickets'; render(); document.getElementById('ticketReview')?.scrollIntoView(); } catch (err) { notify(err.message, true); }
    return;
  }
  const b = e.target.closest('[data-action^="cx-"],[data-action="new-conversation"]');
  if (!b) return;
  const a = b.dataset.action;
  if (a === 'new-conversation') { e.stopImmediatePropagation(); if (state.thinking) return; state.sessionId = ''; state.messages = []; state.draftText = ''; cxClearAttachments(); state.historyOpen = false; state.editing = null; try { sessionStorage.removeItem('studioos-chat-id'); } catch (x) {} if (state.view !== 'assistant') state.view = 'assistant'; render(); return; }
  e.stopImmediatePropagation();
  if (state.thinking && ['cx-history','cx-open-session'].includes(a)) return;
  try {
    if (a === 'cx-sample') { const s = CX_SAMPLES[Number(b.dataset.i)]; if (s.send) sendChat(s.send); else { state.draftText = s.fill; render(); const t = $('chatInput'); t?.focus(); t?.setSelectionRange(t.value.length, t.value.length); } return; }
    if (a === 'cx-history') { state.historyOpen = true; state.sessionsLoading = true; render(); try { state.sessions = await api('/api/chat/sessions'); } finally { state.sessionsLoading = false; if (state.historyOpen) render(); } return; }
    if (a === 'cx-history-close') { state.historyOpen = false; render(); document.querySelector('[data-action="cx-history"]')?.focus(); return; }
    if (a === 'cx-hfilter') { state.historyFilter = b.dataset.filter || 'all'; render(); return; }
    if (a === 'cx-open-session') { await openSession(b.dataset.id); return; }
    if (a === 'cx-clear-scope') { ovSetScope(null); render(); return; }
    if (a === 'cx-jump-bottom') { const sc = $('chatMessages'); if (sc) sc.scrollTop = sc.scrollHeight; cxUpdateJump(); return; }
    if (a === 'cx-copy') {
      const m = state.messages[Number(b.dataset.i)];
      if (m && navigator.clipboard?.writeText) { await navigator.clipboard.writeText(plain(m.reply)); notify('Copied to clipboard.'); }
      return;
    }
    if (a === 'cx-retry') {
      const idx = Number(b.dataset.i), m = state.messages[idx];
      if (m?.retryPayload) await sendChat(m.retryPayload.text, m.retryPayload.files, idx);
      return;
    }
    if (a === 'cx-dismiss-failed') { state.messages.splice(Number(b.dataset.i), 1); state.keepScroll = true; render(); return; }
    if (a === 'cx-mic') { toggleMic(); return; }
    if (a === 'cx-unattach') { cxRemoveAttachment(Number(b.dataset.i)); return; }
    if (a === 'cx-reply-hint') { $('chatInput')?.focus(); return; }
    if (a === 'cx-menu') { if (window.matchMedia('(max-width:599px)').matches) { switchView('me'); return; } $('sidebar').classList.toggle('open'); return; }
    if (a === 'cx-edit') { state.editing = {item: Number(b.dataset.item), field: b.dataset.field}; const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc; document.querySelector('.cx-edit .form-input')?.focus(); return; }
    if (a === 'cx-edit-cancel') { state.editing = null; const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc; return; }
    if (a === 'cx-discard-draft') {
      const card = [...state.messages].reverse().find(m => m.card && Number(m.card.id) === Number(b.dataset.id))?.card;
      const pending = (card?.items || []).filter(x => x.status === 'pending');
      if (!pending.length) return;
      if (!await askConfirm('Discard this draft? Nothing was saved.')) return;
      b.disabled = true;
      try {
        for (const it of pending) await api(`/api/tickets/items/${Number(it.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Discarded from the chat'})});
        await reloadCard();
        state.keepScroll = true;
        render(); refresh();
        notify('Draft discarded.');
      } catch (err) { b.disabled = false; notify(err.message, true); }
      return;
    }
    if (a === 'cx-answer') {
      const msg = [...state.messages].reverse().find(m => m.ask?.some(x => x.id === b.dataset.ask));
      const ask = msg?.ask.find(x => x.id === b.dataset.ask); const choice = ask?.choices[Number(b.dataset.j)];
      if (!choice) return;
      if (!ask.field || !ask.item_id) { sendChat(String(choice.value)); return; }
      state.messages.push({role: 'user', reply: choice.label, createdAt: new Date().toISOString()}); state.thinking = true; state.thinkingText = 'Updating draft…'; render();
      try {
        const r = await api('/api/chat/answer', {method: 'POST', body: JSON.stringify({session_id: state.sessionId, item_id: ask.item_id, field: ask.field, value: choice.value, label: choice.label})});
        pushReply(r);
      } finally { state.thinking = false; state.thinkingText = ''; render(); }
      return;
    }
    if (a === 'cx-approve') {
      const id = Number(b.dataset.id);
      const confirmed = b.dataset.confirmed ? JSON.parse(b.dataset.confirmed) :
        [...document.querySelectorAll(`input[name="cx-confirm"][data-ticket="${id}"]:checked`)].map(x => x.value);
      b.disabled = true;
      try {
        const r = await api(`/api/tickets/${id}/approve-and-save`, {method: 'POST', body: JSON.stringify({confirmed, review_fingerprints: JSON.parse(b.dataset.review)})});
        await reloadCard();
        const n = (r.committed_records || []).length;
        state.messages.push({role: 'assistant', reply: `Saved. ${n === 1 ? 'The record is' : n + ' records are'} now in StudioOS${isAdmin() ? ', and you can undo it from the card' : ''}.`, reveal: !REDUCED_MOTION});
        render(); refresh();
      } catch (err) {
        b.disabled = false;
        if (err.data?.needs_confirmation) { const box = document.querySelector(`input[name="cx-confirm"][value="${err.data.needs_confirmation}"]`)?.closest('label'); if (box) { box.classList.add('attention'); box.scrollIntoView({block: 'center'}); } else notify(err.message, true); }
        else notify(err.message, true);
      }
      return;
    }
    if (a === 'cx-reject-item') {
      await api(`/api/tickets/items/${Number(b.dataset.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Rejected from the chat'})});
      await reloadCard(); state.keepScroll = true; render(); return;
    }
    if (a === 'cx-build-answer') { state.answeringBuild = Number(b.dataset.id); state.keepScroll = true; render(); document.querySelector('.cx-bq textarea')?.focus(); return; }
    if (a === 'cx-build-cancel') { state.answeringBuild = null; state.keepScroll = true; render(); return; }
    if (a === 'cx-build-keep') { notify('It stays safely in the waiting area. Nothing is lost.'); return; }
    if (a === 'cx-build-reject') {
      if (!await askConfirm('Do not build this kind of record? The waiting entries stay in the history.')) return;
      await api(`/api/new-types/${Number(b.dataset.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Rejected from the chat'})});
      await reloadCard(); render(); refresh(); return;
    }
    if (a === 'cx-build-approve') {
      if (!await askConfirm('Build this kind of record? It adds a new record type only; existing data and tables are not changed.')) return;
      b.disabled = true;
      try {
        const r = await api(`/api/new-types/${Number(b.dataset.id)}/approve-structure`, {method: 'POST', body: JSON.stringify({note: 'Approved from the chat'})});
        await reloadCard();
        const done = (r.waiting_check || []).filter(x => x.session_id);
        const n = done.reduce((t, x) => t + x.drafted, 0);
        state.messages.push({role: 'assistant', reveal: !REDUCED_MOTION, drafts: done,
          reply: n ? `Built. I checked the waiting area and drafted **${n}** ${n === 1 ? 'entry' : 'entries'} for you to approve. Nothing is saved until you approve them.` : 'Built. You can now add these records in the chat. Nothing else was waiting with values to add.'});
        render(); refresh();
      } catch (err) { b.disabled = false; notify(err.message, true); }
      return;
    }
    if (a === 'cx-open-drafts') { await openSession(b.dataset.id); return; }
    if (a === 'cx-undo') {
      if (!await askConfirm('Undo this save? The history will keep a record of the change.')) return;
      const undo=await api(`/api/tickets/${Number(b.dataset.id)}/reverse`, {method: 'POST', body: JSON.stringify({reason: 'Undone from the chat after saving'})});
      notify('Ticket #'+undo.ticket_id+' opened. Review it to undo this save.');
      await reloadCard();
      state.messages.push({role: 'assistant', reply: 'I opened an undo request. Review and approve it to undo the saved change.', reveal: !REDUCED_MOTION});
      render(); refresh();
    }
  } catch (err) { notify(err.message, true); }
}, true);

document.addEventListener('submit', async e => {
  const form = e.target;
  if (form.classList?.contains('cx-bq')) {
    e.preventDefault(); e.stopImmediatePropagation();
    const answers = {}; for (const [k, v] of new FormData(form)) if (String(v).trim()) answers[k] = String(v).trim();
    if (!Object.keys(answers).length) { notify('Answer at least one question', true); return; }
    try {
      await api(`/api/new-types/${Number(form.dataset.id)}/answers`, {method: 'POST', body: JSON.stringify({answers})});
      state.answeringBuild = null; await reloadCard(); state.keepScroll = true; render(); notify('Thanks. The proposed record was updated.');
    } catch (err) { notify(err.message, true); }
    return;
  }
  if (form.classList?.contains('cx-missing')) {
    e.preventDefault(); e.stopImmediatePropagation();
    const card = [...state.messages].reverse().find(m => m.card && Number(m.card.id) === Number(form.dataset.ticket))?.card;
    if (!card) return;
    const changes = new Map();
    for (const [name, raw] of new FormData(form).entries()) {
      const m = /^m__(\d+)__(.+)$/.exec(name);
      if (!m || String(raw).trim() === '') continue;                    // left empty: it stays missing
      const item = card.items.find(i => i.id === Number(m[1]));
      if (!item) continue;
      const got = cxCoerce(item, m[2], raw);
      if (got.error) { const label = (item.fields || []).find(x => x.key === m[2])?.label || m[2]; notify(label + ': ' + got.error, true); return; }
      const entry = changes.get(item.id) || {item, after: item.after};
      entry.after = cxAfterWith(entry.after, m[2], got.value);
      changes.set(item.id, entry);
    }
    if (!changes.size) { notify('Fill in at least one detail, or leave them for later.', true); return; }
    const sc = $('chatMessages')?.scrollTop;
    try {
      for (const {item, after} of changes.values()) await api('/api/tickets/items/' + item.id, {method: 'PATCH', body: JSON.stringify({after, note: ''})});
    } catch (err) { notify(err.message, true); }
    try { await reloadCard(); } catch (err) { /* the card refreshes on the next message */ }
    render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc;
    return;
  }
  if (form.classList?.contains('cx-edit')) {
    e.preventDefault(); e.stopImmediatePropagation();
    const itemId = Number(form.dataset.item), field = form.dataset.field;
    const card = [...state.messages].reverse().find(m => m.card?.items?.some(i => i.id === itemId))?.card;
    const item = card?.items.find(i => i.id === itemId);
    if (!item) return;
    const raw = new FormData(form).get('value');
    const got = cxCoerce(item, field, raw);
    if (got.error) { notify(got.error, true); return; }
    const after = cxAfterWith(item.after, field, got.value);
    try {
      await api('/api/tickets/items/' + itemId, {method: 'PATCH', body: JSON.stringify({after, note: ''})});
      state.editing = null; await reloadCard(); const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc;
    } catch (err) { notify(err.message, true); }
    return;
  }
  if (form.id === 'chatForm') { e.preventDefault(); e.stopImmediatePropagation(); sendChat($('chatInput').value); }
}, true);

document.addEventListener('input', e => {
  if (e.target.id === 'chatInput') {
    state.draftText = e.target.value;
    sizeInput();
    const sendBtn = $('chatSend');
    if (sendBtn) sendBtn.disabled = !cxCanSend();
  } else if (e.target.id === 'cxHistorySearch') {
    state.historyQuery = e.target.value;
    const list = $('cxHistoryList');
    if (list) list.innerHTML = cxHistoryListHtml();
  }
});
document.addEventListener('change', e => {
  if (e.target.id === 'chatFiles') {
    cxAddFiles(e.target.files);
    e.target.value = '';
  }
});
document.addEventListener('paste', e => {
  if (e.target?.id !== 'chatInput' || state.user?.role === 'viewer') return;
  const items = [...(e.clipboardData?.items || [])].filter(it => it.kind === 'file' && it.type.startsWith('image/'));
  if (!items.length) return;
  const files = items.map(it => it.getAsFile()).filter(Boolean);
  if (files.length) { e.preventDefault(); cxAddFiles(files); }
});
let cxDragDepth = 0;
document.addEventListener('dragenter', e => {
  if (state.view !== 'assistant' || state.user?.role === 'viewer' || !e.dataTransfer?.types?.includes('Files')) return;
  cxDragDepth++;
  const cx = $('cx');
  if (cx) cx.classList.add('cx-drop-active');
});
document.addEventListener('dragover', e => {
  if (state.view !== 'assistant' || state.user?.role === 'viewer' || !e.dataTransfer?.types?.includes('Files')) return;
  e.preventDefault();
});
document.addEventListener('dragleave', e => {
  if (state.view !== 'assistant' || cxDragDepth <= 0) return;
  cxDragDepth--;
  if (cxDragDepth === 0) { const cx = $('cx'); if (cx) cx.classList.remove('cx-drop-active'); }
});
document.addEventListener('drop', e => {
  if (state.view !== 'assistant' || state.user?.role === 'viewer' || !e.dataTransfer?.files?.length) return;
  e.preventDefault();
  cxDragDepth = 0;
  const cx = $('cx');
  if (cx) cx.classList.remove('cx-drop-active');
  cxAddFiles(e.dataTransfer.files);
});

// Re-apply chat behaviour after every render; restore the open conversation on start.
const _render = render;
render = function () {
  document.body.classList.toggle('chat-mode', state.view === 'assistant');
  _render();
  afterChatRender();
};
const _refresh = refresh;
refresh = async function () {
  await _refresh();
  if (state.user) { try { state.waiting = await api('/api/waiting'); state.recordTypes = await api('/api/record-types'); } catch (e) { console.warn('Waiting area not loaded', e); } if (state.view !== 'assistant' || !state.messages.length) render(); }
  await restoreConversation();
};

document.addEventListener('click', e => {
  if (e.target.closest('#navLogout')) signOut();
});

document.addEventListener('keydown', event => {
  const drawer = document.querySelector('.cx-drawer');
  if (!drawer || state.ov) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    drawer.querySelector('[data-action="cx-history-close"]')?.click();
  } else if (event.key === 'Tab') {
    const buttons = [...drawer.querySelectorAll('button:not(:disabled)')];
    const first = buttons[0], last = buttons.at(-1);
    if ((event.shiftKey && document.activeElement === first) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first)?.focus();
    }
  }
});
