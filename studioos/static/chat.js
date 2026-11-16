'use strict';
/* StudioOS v0.9.0 conversational chat (decision lines, build requests and record types added).
   Originally v0.8.0 conversational chat. Loaded after app.js; replaces the old
   assistant() and sendChat(). The chat is the landing page. Nothing here saves
   business data by itself: drafts become records only through "Approve and save"
   (a full ticket approval and atomic commit on the server). */

Object.assign(state, {view: 'assistant', thinking: false, editing: null, attachments: [], historyOpen: false, sessions: []});

const CX_SAMPLES = [
  {label: 'Log an expense', fill: 'Paid ₹ '},
  {label: 'Add a task', fill: 'Add task: '},
  {label: 'Site update', fill: 'Site update for '},
  {label: "What's pending?", send: 'Show pending tasks'},
  {label: 'Budget summary', send: 'Show the budget summary'},
];
const REDUCED_MOTION = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function md(s) {
  // Small, safe formatting: **bold**, line breaks and "- " bullets. Everything is escaped first.
  const lines = esc(s).split('\n');
  let html = '', list = false;
  for (const line of lines) {
    const bullet = /^\s*[-•]\s+(.*)$/.exec(line);
    if (bullet) { if (!list) { html += '<ul>'; list = true; } html += `<li>${bullet[1]}</li>`; continue; }
    if (list) { html += '</ul>'; list = false; }
    html += line.trim() ? `<p>${line}</p>` : '';
  }
  if (list) html += '</ul>';
  return html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
function plain(s) { return String(s ?? '').replace(/\*\*/g, ''); }
function greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'; }
function firstName() { return (state.user?.display_name || state.user?.username || '').split(' ')[0]; }
function cleanStored(text) { return String(text || '').split('\nPROPOSED ACTION:')[0]; }

/* ------------------------------------------------------------------ view */
function assistant() {
  const msgs = state.messages;
  const lastCardIndex = {};
  msgs.forEach((m, i) => { if (m.card?.id) lastCardIndex[m.card.id] = i; });
  const body = msgs.length
    ? msgs.map((m, i) => (m.afterSaving && !msgs[i - 1]?.afterSaving ? '<div class="cx-divider"><span>After saving</span></div>' : '') + cxMessage(m, i, lastCardIndex)).join('') + (state.thinking ? cxThinking() : '')
    : cxWelcome();
  return `<div class="cx" id="cx">
    <div class="cx-bar">
      <button class="cx-icon-btn" data-action="cx-menu" aria-label="Menu">☰</button>
      <button class="cx-icon-btn" data-action="cx-history" aria-label="Past conversations"><span>Chats</span></button>
      <div class="cx-bar-title">StudioOS${state.settings?.environment === 'test' ? ' <span class="cx-test">TEST COPY</span>' : ''}</div>
      <button class="cx-icon-btn" data-action="new-conversation" aria-label="New conversation">✎ <span>New</span></button>
    </div>
    <div class="cx-scroll" id="chatMessages" aria-live="polite">${body}</div>
    ${cxComposer()}
    ${state.historyOpen ? cxHistory() : ''}
  </div>`;
}

function cxWelcome() {
  return `<div class="cx-welcome"><div class="cx-mark">✦</div>
    <h2>${esc(greeting())}${firstName() ? ', ' + esc(firstName()) : ''}.</h2>
    <p>Tell me what happened, ask about a project, or attach a bill or photo. I'll draft it; nothing is saved until it's approved.</p>
    ${cxReminders()}
    <div class="cx-chips">${CX_SAMPLES.map((s, i) => `<button class="cx-chip" data-action="cx-sample" data-i="${i}">${esc(s.label)}</button>`).join('')}</div></div>`;
}
function cxThinking() {
  return `<div class="cx-msg ai"><div class="cx-avatar">✦</div><div class="cx-body"><div class="cx-dots" role="status" aria-label="Thinking"><span></span><span></span><span></span></div></div></div>`;
}

function cxReminders() {
  const w = state.waiting; if (!w || !isApprover()) return '';
  const due = w.reminders || []; const open = (w.requests || []).filter(r => r.state === 'waiting_for_approval');
  if (!open.length) return '';
  return `<button class="cx-reminder${due.length ? ' due' : ''}" data-view="newtypes">${due.length ? '⏰ ' : ''}${open.length} kind${open.length === 1 ? '' : 's'} of information ${open.length === 1 ? 'is' : 'are'} waiting for a place${due.length ? ` · ${due.length} for over a week` : ''} <span>Open</span></button>`;
}

function cxMessage(m, i, lastCardIndex) {
  if (m.role === 'system') return `<div class="cx-decision" role="note">${esc(m.reply)}</div>`;
  if (m.role === 'user') return `<div class="cx-msg me"><div class="cx-bubble">${md(m.reply)}${(m.files || []).map(f => `<div class="cx-file">📎 ${esc(f)}</div>`).join('')}</div></div>`;
  const revealing = m.reveal && !REDUCED_MOTION;
  const text = revealing ? '' : md(m.reply);
  const live = m.card && lastCardIndex[m.card.id] === i;
  const card = !m.card ? '' : live ? cxCard(m.card) : `<div class="cx-stale">${esc(m.card.items?.[0]?.line || 'Draft')} <span class="muted">· updated below</span></div>`;
  const asks = live && m.ask?.length ? cxAsks(m.ask, m.card) : (!m.card && m.ask?.length ? cxAsks(m.ask, null) : '');
  const hold = m.build_request ? cxBuildRequest(m.build_request)
    : m.holding_item ? `<div class="cx-note">Kept unchanged in the waiting area. <button class="cx-link" data-action="open-new-type" data-id="${Number(m.holding_item.id)}">Open</button></div>` : '';
  return `<div class="cx-msg ai${m.error ? ' error' : ''}"><div class="cx-avatar">✦</div><div class="cx-body">
    <div class="cx-text" data-i="${i}">${text}</div>
    <div class="cx-after${revealing ? ' hidden' : ''}" data-i="${i}">${asks}${card}${hold}${(m.drafts || []).map(d => `<button class="btn btn-secondary btn-sm" data-action="cx-open-drafts" data-id="${esc(d.session_id)}">Review ${Number(d.drafted)} drafted ${esc(d.title)}</button>`).join(' ')}</div></div></div>`;
}

function cxAsks(asks, card) {
  const editable = card && !['committed', 'reversed'].includes(card.status);
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

const MARK_LABEL = {sourced: 'from your words', answered: 'you answered', edited: 'edited', guessed: 'AI guess, please check', missing: 'missing', invalid: 'check this'};
const MARK_SYMBOL = {sourced: '✓', answered: '✓', edited: '✓', guessed: '?', missing: '!', invalid: '!'};
function cxCard(card) {
  const saved = card.status === 'committed', reversed = card.status === 'reversed';
  const head = saved ? '<span class="cx-state ok">Saved ✓</span>' : reversed ? '<span class="cx-state">Undone</span>' : '<span class="cx-state draft">Draft · not saved</span>';
  const items = card.items.map(item => {
    const decided = item.status !== 'pending';
    const fields = (item.fields || []).map(f => {
      const editing = state.editing && state.editing.item === item.id && state.editing.field === f.key;
      if (editing) return cxEditForm(item, f);
      const mark = f.marker || 'guessed';
      return `<button class="cx-field m-${esc(mark)}" ${saved || reversed || decided || f.locked ? 'disabled' : ''} data-action="cx-edit" data-item="${Number(item.id)}" data-field="${esc(f.key)}" title="${esc(f.source ? 'Source: ' + f.source : MARK_LABEL[mark] || '')}">
        <span class="cx-f-label">${esc(f.label)}</span><span class="cx-f-value">${esc(f.display)}</span><span class="cx-f-mark" aria-label="${esc(MARK_LABEL[mark] || mark)}">${MARK_SYMBOL[mark] || '?'}</span></button>`;
    }).join('');
    const flags = (item.flags || []).filter(fl => !/offline interpreter|requires reapproval/i.test(fl)).map(fl => `<div class="cx-flag">${esc(humanFlag(fl))}</div>`).join('');
    const confirm = !saved && !reversed && item.status === 'pending' ? (item.needs_confirmation || []).map(c => `<label class="cx-confirm"><input type="checkbox" name="cx-confirm" value="${esc(c)}" data-ticket="${Number(card.id)}"> ${c === 'duplicate' ? "I checked this isn't already entered" : 'I checked this amount is correct'}</label>`).join('') : '';
    const status = item.status === 'rejected' ? '<span class="tag critical">Rejected</span>' : item.status === 'approved' && !saved ? '<span class="tag good">Approved</span>' : '';
    if (saved || reversed) return `<div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(item.title || 'Draft')}</span>${status}</div><div class="cx-done-line">${esc(String(item.line || '').split(' · ').slice(1).join(' · '))}</div></div>`;
    const pendingCount = card.items.filter(x => x.status === 'pending').length;
    const notNow = card.can_approve && item.status === 'pending' && pendingCount > 1 ? `<button class="cx-link cx-notnow" data-action="cx-reject-item" data-id="${Number(item.id)}">Not now</button>` : '';
    return `<div class="cx-item"><div class="cx-item-head"><span class="cx-kind">${esc(item.title || 'Draft')}</span>${status}${notNow}</div><div class="cx-fields">${fields}</div>${cxStructured(item)}${flags}${confirm}</div>`;
  }).join('');
  let actions;
  if (saved) actions = `<div class="cx-actions">${isAdmin() ? `<button class="btn btn-secondary btn-sm" data-action="cx-undo" data-id="${Number(card.id)}">Undo</button>` : ''}<button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div>`;
  else if (reversed) actions = '';
  else if (card.can_approve) actions = `<div class="cx-legend"><span class="ok">✓</span> from you <span class="guess">?</span> AI guess, check <span class="miss">!</span> missing · tap a value to change it</div><div class="cx-actions"><button class="btn btn-primary" data-action="cx-approve" data-id="${Number(card.id)}">Approve and save</button><button class="btn btn-secondary" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div><div class="cx-fine">Saving records your approval on the ticket.</div>`;
  else actions = `<div class="cx-waiting">${esc(card.reason || 'Waiting for approval.')}</div><div class="cx-actions"><button class="btn btn-secondary btn-sm" data-action="open-ticket" data-id="${Number(card.id)}">Details</button></div>`;
  return `<section class="cx-card" aria-label="Draft to review"><div class="cx-card-head">${head}<span class="muted">Ticket #${Number(card.id)}</span></div>${items}${actions}</section>`;
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
  if (/^MISSING:/i.test(s)) return 'Missing: ' + s.replace(/^MISSING:\s*/i, '');
  return s.replace(/_/g, ' ');
}
function cxEditForm(item, f) {
  const id = `cxe-${Number(item.id)}-${esc(f.key)}`;
  let input;
  if (f.choices?.length) input = `<select class="form-input" id="${id}" name="value">${f.raw == null ? '<option value="">Choose…</option>' : ''}${f.choices.map(c => `<option value="${esc(c.value)}" ${String(f.raw) === String(c.value) ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select>`;
  else if (f.type === 'money' && item.graph) input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw?.amount == null ? '' : esc(String(f.raw.amount))}" placeholder="Amount in ₹">`;
  else if (f.type === 'money') input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw == null ? '' : esc(String(f.raw / 100))}" placeholder="Amount in ₹">`;
  else if (f.type === 'project') input = `<select class="form-input" id="${id}" name="value"><option value="">No project</option>${(state.projects || []).map(p => `<option ${f.display === p.name || f.raw === p.name ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`;
  else if (f.key === 'payment_mode') input = `<select class="form-input" id="${id}" name="value">${[['cash', 'Cash'], ['upi', 'UPI'], ['bank_transfer', 'Bank transfer'], ['cheque', 'Cheque'], ['card', 'Card']].map(([v, l]) => `<option value="${v}" ${f.raw === v ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
  else if (f.key === 'kind') input = `<select class="form-input" id="${id}" name="value"><option value="expense" ${f.raw === 'expense' ? 'selected' : ''}>Already spent</option><option value="commitment" ${f.raw === 'commitment' ? 'selected' : ''}>Purchase order</option></select>`;
  else if (f.key === 'gst_included') input = `<select class="form-input" id="${id}" name="value"><option value="">Not sure yet</option><option value="true" ${f.raw === true ? 'selected' : ''}>Included</option><option value="false" ${f.raw === false ? 'selected' : ''}>Not included</option></select>`;
  else if (f.key.endsWith('_paise')) input = `<input class="form-input" id="${id}" name="value" inputmode="decimal" value="${f.raw == null ? '' : esc(String(f.raw / 100))}" placeholder="Amount in ₹">`;
  else if (f.key === 'project' && item.record_type) input = `<select class="form-input" id="${id}" name="value">${[...(state.projects || []).map(p => p.name), 'Not project related'].map(n => `<option ${f.raw === n ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
  else if (f.type === 'boolean') input = `<select class="form-input" id="${id}" name="value"><option value="">Not known</option><option value="yes" ${f.raw === true ? 'selected' : ''}>Yes</option><option value="no" ${f.raw === false ? 'selected' : ''}>No</option></select>`;
  else if (f.type === 'date') input = `<input class="form-input" id="${id}" name="value" type="date" value="${esc(f.raw || '')}">`;
  else if (f.type === 'integer' || f.type === 'decimal') input = `<input class="form-input" id="${id}" name="value" inputmode="${f.type === 'integer' ? 'numeric' : 'decimal'}" value="${f.raw == null ? '' : esc(String(f.raw))}">`;
  else if (f.key.startsWith('data.')) input = `<textarea class="form-input" id="${id}" name="value" rows="2">${f.raw == null ? '' : esc(String(f.raw))}</textarea>`;
  else if (f.key === 'progress') input = `<input class="form-input" id="${id}" name="value" inputmode="numeric" value="${f.raw == null ? '' : esc(String(f.raw))}" placeholder="0 to 100">`;
  else input = `<input class="form-input" id="${id}" name="value" value="${f.raw == null ? '' : esc(String(f.raw))}">`;
  return `<form class="cx-edit" data-item="${Number(item.id)}" data-field="${esc(f.key)}"><label for="${id}">${esc(f.label)}</label>${input}<div class="cx-edit-actions"><button class="btn btn-primary btn-sm" type="submit">Update</button><button class="btn btn-secondary btn-sm" type="button" data-action="cx-edit-cancel">Cancel</button></div></form>`;
}

function cxComposer() {
  const speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  return `<div class="cx-composer">
    ${state.attachments.length ? `<div class="cx-attached">${state.attachments.map((f, i) => `<span class="cx-att">📎 ${esc(f.name)} <button data-action="cx-unattach" data-i="${i}" aria-label="Remove">✕</button></span>`).join('')}<div class="cx-fine">Attachments are kept unchanged for review.</div></div>` : ''}
    <form class="cx-form" id="chatForm">
      <label class="cx-tool" title="Attach a photo or file" aria-label="Attach a photo or file">＋<input type="file" id="chatFiles" multiple accept="image/*,.pdf,.txt,.csv" class="cx-file-input"></label>
      <textarea class="cx-input" id="chatInput" rows="1" placeholder="Message StudioOS" aria-label="Message" ${state.thinking ? 'disabled' : ''}>${esc(state.draftText || '')}</textarea>
      ${speech ? `<button class="cx-tool${state.listening ? ' on' : ''}" type="button" data-action="cx-mic" aria-label="Speak">🎤</button>` : ''}
      <button class="cx-send" type="submit" id="chatSend" aria-label="Send" ${state.thinking ? 'disabled' : ''}>↑</button>
    </form></div>`;
}

function cxHistory() {
  const rows = state.sessions.length ? state.sessions.map(s => `<button class="cx-hrow${s.id === state.sessionId ? ' current' : ''}" data-action="cx-open-session" data-id="${esc(s.id)}">
      <span class="cx-htitle">${esc(s.title)}</span><span class="cx-hmeta">${esc(time(s.updated_at))}${s.ticket_status ? ' · ' + esc({committed: 'saved', reversed: 'undone', draft: 'draft', in_review: 'in review'}[s.ticket_status] || s.ticket_status) : ''}</span></button>`).join('')
    : '<p class="muted">No conversations yet.</p>';
  return `<div class="cx-drawer-backdrop" data-action="cx-history-close"></div><aside class="cx-drawer" aria-label="Past conversations"><div class="cx-drawer-head"><strong>Conversations</strong><button class="cx-icon-btn" data-action="cx-history-close" aria-label="Close">✕</button></div>
    <button class="btn btn-primary cx-newchat" data-action="new-conversation">✎ New conversation</button><div class="cx-hlist">${rows}</div></aside>`;
}

/* ------------------------------------------------------------------ behaviour */
function afterChatRender() {
  if (state.view !== 'assistant') return;
  const scroll = $('chatMessages');
  if (scroll) { const last = state.messages.length - 1; if (last >= 0 && state.messages[last].role === 'assistant' && !state.thinking && !state.keepScroll) showReply(last); else scroll.scrollTop = scroll.scrollHeight; }
  state.keepScroll = false;
  sizeInput();
  const i = state.messages.findIndex(m => m.reveal);
  if (i >= 0 && !REDUCED_MOTION) revealMessage(i);
}
function showReply(i) {
  // Show a new reply from its start if it is taller than the visible chat, like Claude or ChatGPT.
  const scroll = $('chatMessages'); const msg = document.querySelector(`.cx-text[data-i="${i}"]`)?.closest('.cx-msg');
  if (!scroll || !msg) return;
  if (msg.offsetHeight > scroll.clientHeight * 0.8) scroll.scrollTop = msg.offsetTop - scroll.offsetTop - 8;
  else scroll.scrollTop = scroll.scrollHeight;
}
function sizeInput() { const t = $('chatInput'); if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 160) + 'px'; }

function revealMessage(i) {
  const m = state.messages[i];
  const el = document.querySelector(`.cx-text[data-i="${i}"]`);
  if (!el || m.revealing) return;
  m.revealing = true;
  const words = plain(m.reply).split(/(\s+)/);
  let n = 0;
  const step = Math.max(1, Math.ceil(words.length / 45));  // about 0.7 seconds however long
  const timer = setInterval(() => {
    n += step;
    const live = document.querySelector(`.cx-text[data-i="${i}"]`);
    if (!live) { clearInterval(timer); m.reveal = false; m.revealing = false; return; }
    live.textContent = words.slice(0, n).join('');
    const scroll = $('chatMessages'); if (scroll) scroll.scrollTop = scroll.scrollHeight;
    if (n >= words.length) {
      clearInterval(timer); m.reveal = false; m.revealing = false;
      live.innerHTML = md(m.reply);
      document.querySelector(`.cx-after[data-i="${i}"]`)?.classList.remove('hidden');
      showReply(i);
    }
  }, 16);
}

function pushReply(r, extra = {}) {
  state.messages.push({role: 'assistant', reply: r.reply || '', card: r.preview || r.card || null, ask: r.ask || [], holding_item: r.holding_item, build_request: r.build_request || null, reveal: !REDUCED_MOTION, ...extra});
}

async function sendChat(content) {
  const v = String(content ?? '').trim();
  const files = state.attachments.slice();
  if ((!v && !files.length) || state.thinking) return;
  state.messages.push({role: 'user', reply: v || 'Attached files', files: files.map(f => f.name)});
  state.draftText = ''; state.attachments = []; state.thinking = true; state.editing = null;
  render();
  try {
    let r;
    if (files.length) {
      const attachments = []; for (const f of files) attachments.push(await encodeFile(f));
      r = await api('/api/new-types/intake', {method: 'POST', body: JSON.stringify({text: v || 'Attached files', session_id: state.sessionId, attachments})});
      r = {...r, reply: `I've kept ${files.length === 1 ? 'that file' : 'those files'} unchanged for review. Reading bills automatically comes with the live AI model.`};
    } else {
      r = await api('/api/chat', {method: 'POST', body: JSON.stringify({message: v, session_id: state.sessionId})});
    }
    state.sessionId = r.session_id; try { sessionStorage.setItem('studioos-chat-id', state.sessionId); } catch (e) {}
    pushReply(r);
  } catch (err) {
    state.messages.push({role: 'assistant', reply: 'Sorry, that did not go through: ' + err.message, error: true});
  } finally {
    state.thinking = false;
    render();
    if (state.messages.at(-1)?.card) refresh();
  }
}

async function reloadCard() {
  if (!state.sessionId) return;
  const h = await api('/api/chat/history/' + encodeURIComponent(state.sessionId));
  const idx = state.messages.map(m => !!m.card).lastIndexOf(true);
  if (h.card && idx >= 0) { state.messages[idx].card = h.card; if (['committed', 'reversed'].includes(h.card.status)) state.messages[idx].ask = []; }
  const bidx = state.messages.map(m => !!m.build_request).lastIndexOf(true);
  if (h.build_request && bidx >= 0) state.messages[bidx].build_request = h.build_request;
  // Bring in decision lines written by the server (approved, saved, undone...).
  const known = state.messages.filter(m => m.role === 'system').length;
  h.messages.filter(m => m.speaker === 'system').slice(known).forEach(m => state.messages.push({role: 'system', reply: m.content, afterSaving: m.after_saving}));
  return h;
}

async function openSession(id) {
  const h = await api('/api/chat/history/' + encodeURIComponent(id));
  state.sessionId = id; try { sessionStorage.setItem('studioos-chat-id', id); } catch (e) {}
  state.messages = h.messages.map(m => ({role: m.speaker === 'user' ? 'user' : m.speaker === 'system' ? 'system' : 'assistant', reply: cleanStored(m.content), afterSaving: !!m.after_saving}));
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
function toggleMic() {
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Speech) return;
  if (state.listening && recognition) { recognition.stop(); return; }
  let told = false; try { told = localStorage.getItem('studioos-voice-notice') === '1'; } catch (e) {}
  if (!told) {
    if (!confirm("Voice is turned into text by your phone's or browser's own speech service (Apple on iPhone, Google on Chrome). Continue?")) return;
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
  if (a === 'new-conversation') { e.stopImmediatePropagation(); state.sessionId = ''; state.messages = []; state.historyOpen = false; state.editing = null; try { sessionStorage.removeItem('studioos-chat-id'); } catch (x) {} if (state.view !== 'assistant') state.view = 'assistant'; render(); return; }
  e.stopImmediatePropagation();
  try {
    if (a === 'cx-sample') { const s = CX_SAMPLES[Number(b.dataset.i)]; if (s.send) sendChat(s.send); else { state.draftText = s.fill; render(); const t = $('chatInput'); t?.focus(); t?.setSelectionRange(t.value.length, t.value.length); } return; }
    if (a === 'cx-history') { state.historyOpen = true; render(); state.sessions = await api('/api/chat/sessions'); render(); return; }
    if (a === 'cx-history-close') { state.historyOpen = false; render(); return; }
    if (a === 'cx-open-session') { await openSession(b.dataset.id); return; }
    if (a === 'cx-mic') { toggleMic(); return; }
    if (a === 'cx-unattach') { state.attachments.splice(Number(b.dataset.i), 1); render(); return; }
    if (a === 'cx-reply-hint') { $('chatInput')?.focus(); return; }
    if (a === 'cx-menu') { $('sidebar').classList.toggle('open'); return; }
    if (a === 'cx-edit') { state.editing = {item: Number(b.dataset.item), field: b.dataset.field}; const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc; document.querySelector('.cx-edit .form-input')?.focus(); return; }
    if (a === 'cx-edit-cancel') { state.editing = null; const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc; return; }
    if (a === 'cx-answer') {
      const msg = [...state.messages].reverse().find(m => m.ask?.some(x => x.id === b.dataset.ask));
      const ask = msg?.ask.find(x => x.id === b.dataset.ask); const choice = ask?.choices[Number(b.dataset.j)];
      if (!choice) return;
      if (!ask.field || !ask.item_id) { sendChat(String(choice.value)); return; }
      state.messages.push({role: 'user', reply: choice.label}); state.thinking = true; render();
      try {
        const r = await api('/api/chat/answer', {method: 'POST', body: JSON.stringify({session_id: state.sessionId, item_id: ask.item_id, field: ask.field, value: choice.value, label: choice.label})});
        pushReply(r);
      } finally { state.thinking = false; render(); }
      return;
    }
    if (a === 'cx-approve') {
      const id = Number(b.dataset.id);
      const confirmed = [...document.querySelectorAll(`input[name="cx-confirm"][data-ticket="${id}"]:checked`)].map(x => x.value);
      b.disabled = true;
      try {
        const r = await api(`/api/tickets/${id}/approve-and-save`, {method: 'POST', body: JSON.stringify({confirmed})});
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
      await api(`/api/tickets/items/${Number(b.dataset.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Not now (from the chat)'})});
      await reloadCard(); state.keepScroll = true; render(); return;
    }
    if (a === 'cx-build-answer') { state.answeringBuild = Number(b.dataset.id); state.keepScroll = true; render(); document.querySelector('.cx-bq textarea')?.focus(); return; }
    if (a === 'cx-build-cancel') { state.answeringBuild = null; state.keepScroll = true; render(); return; }
    if (a === 'cx-build-keep') { notify('It stays safely in the waiting area. Nothing is lost.'); return; }
    if (a === 'cx-build-reject') {
      if (!confirm('Do not build this kind of record? The waiting entries stay in the history.')) return;
      await api(`/api/new-types/${Number(b.dataset.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Rejected from the chat'})});
      await reloadCard(); render(); refresh(); return;
    }
    if (a === 'cx-build-approve') {
      if (!confirm('Build this kind of record? It adds a new record type only; existing data and tables are not changed.')) return;
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
      if (!confirm('Undo this save? The records are hidden and kept in the history, not deleted.')) return;
      const undo=await api(`/api/tickets/${Number(b.dataset.id)}/reverse`, {method: 'POST', body: JSON.stringify({reason: 'Undone from the chat after saving'})});
      notify('Ticket #'+undo.ticket_id+' opened. Review it to undo this save.');
      await reloadCard();
      state.messages.push({role: 'assistant', reply: 'Undone. The records are hidden and kept in the history.', reveal: !REDUCED_MOTION});
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
  if (form.classList?.contains('cx-edit')) {
    e.preventDefault(); e.stopImmediatePropagation();
    const itemId = Number(form.dataset.item), field = form.dataset.field;
    const card = [...state.messages].reverse().find(m => m.card?.items?.some(i => i.id === itemId))?.card;
    const item = card?.items.find(i => i.id === itemId);
    if (!item) return;
    let raw = new FormData(form).get('value'), value = raw;
    if (field.endsWith('_paise')) { const n = Number(String(raw).replace(/[₹,\s]/g, '')); if (!Number.isFinite(n) || n < 0) { notify('Enter an amount in rupees, like 12500', true); return; } value = Math.round(n * 100); }
    else if (field === 'progress' || field === 'cost_id') { if (!/^\d+$/.test(String(raw).trim())) { notify('Enter a whole number', true); return; } value = Number(raw); }
    else if (field === 'gst_included') value = raw === '' ? null : raw === 'true';
    const shown = (item.fields || []).find(x => x.key === field) || {};
    if (shown.type === 'money' && !item.graph && String(raw).trim() !== '') { const n = Number(String(raw).replace(/[₹,\s]/g, '')); if (!Number.isFinite(n) || n <= 0) { notify('Enter an amount in rupees, like 12500', true); return; } value = Math.round(n * 100); }
    if ((field === 'parent_id' || field.startsWith('accounts.')) && /^\d+$/.test(String(raw))) value = Number(raw);
    if (field === 'slots.gst_rate' && String(raw).trim() !== '') value = Number(String(raw).replace('%', ''));
    const [group, sub] = field.includes('.') ? [field.slice(0, field.indexOf('.')), field.slice(field.indexOf('.') + 1)] : [null, null];
    const after = group ? {...item.after, [group]: {...(item.after[group] || {}), [sub]: value}} : {...item.after, [field]: value};
    try {
      await api('/api/tickets/items/' + itemId, {method: 'PATCH', body: JSON.stringify({after, note: ''})});
      state.editing = null; await reloadCard(); const sc = $('chatMessages')?.scrollTop; render(); if (sc != null && $('chatMessages')) $('chatMessages').scrollTop = sc;
    } catch (err) { notify(err.message, true); }
    return;
  }
  if (form.id === 'chatForm') { e.preventDefault(); e.stopImmediatePropagation(); sendChat($('chatInput').value); }
}, true);

document.addEventListener('input', e => { if (e.target.id === 'chatInput') { state.draftText = e.target.value; sizeInput(); } });
document.addEventListener('change', e => {
  if (e.target.id === 'chatFiles') {
    for (const f of e.target.files) { if (f.size > 8 * 1024 * 1024) { notify(`${f.name} is larger than 8 MB`, true); continue; } state.attachments.push(f); }
    render();
  }
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

document.addEventListener('click', async e => {
  if (!e.target.closest('#navLogout')) return;
  try { await api('/api/auth/logout', {method: 'POST'}); } catch (x) {}
  $('sidebar').classList.remove('open'); state.messages = []; showLogin();
});
