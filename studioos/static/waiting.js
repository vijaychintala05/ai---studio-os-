'use strict';
/* StudioOS v0.9.0: "Waiting for a place" and record-type screens, and the ticket
   conversation with decision lines. Loaded after app.js and chat.js. Replaces the
   New Data Inbox list; the detailed review (newTypeDetail) is kept underneath. */

Object.assign(state, {ntTab: 'waiting', rtOpen: null});

const W_STATE = {waiting_for_approval: ['Waiting for approval', 'warn'], built: ['Built', 'good'], retired: ['Undone', 'critical'], rejected: ['Not built', 'critical'], kept: ['Kept as a note', '']};
const E_STATE = {waiting: 'Waiting', drafted: 'Drafted, needs approval', added: 'Added ✓', undone: 'Undone', nothing_to_add: 'Nothing to add'};

function wCap(s) { return String(s || '').replace(/^./, c => c.toUpperCase()); }

function waitingRequest(r) {
  const [label, tone] = W_STATE[r.state] || [r.state, ''];
  const cols = r.fields || [];
  const table = r.samples?.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Project</th>${cols.map(f => `<th>${esc(f.label)}</th>`).join('')}</tr></thead><tbody>${r.samples.map(s => `<tr><td>${esc(s.project || '—')}</td>${cols.map(f => `<td>${esc(s.values?.[f.name] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '';
  const fields = cols.map(f => `<span class="w-field">${esc(f.label)}${f.required && f.required !== 'optional' ? ' <em>needed</em>' : ''}</span>`).join('');
  const entries = (r.entry_list || []).map(e => `<li><span class="w-entry-state s-${esc(e.status)}">${esc(E_STATE[e.status] || e.status)}</span> ${esc(e.text)} <small class="muted">${esc(time(e.created_at))}</small>${e.status === 'drafted' && e.session_id ? ` <button class="cx-link" data-action="w-open-drafts" data-id="${esc(e.session_id)}">Review</button>` : ''}${e.note ? `<br><small class="muted">${esc(e.note)}</small>` : ''}</li>`).join('');
  const buttons = r.state === 'waiting_for_approval'
    ? `${isAdmin() ? `<button class="btn btn-primary" data-action="w-approve" data-id="${Number(r.request_id)}">Approve build</button>` : ''}<button class="btn btn-secondary" data-action="open-new-type" data-id="${Number(r.request_id)}">Full design</button>${isAdmin() ? `<button class="btn btn-danger btn-sm" data-action="w-reject" data-id="${Number(r.request_id)}">Reject</button>` : ''}`
    : `<button class="btn btn-secondary" data-action="open-new-type" data-id="${Number(r.request_id)}">Full design</button>`;
  return `<article class="w-card${r.remind ? ' remind' : ''}">
    <div class="w-head"><strong>${esc(wCap(r.title))}</strong> ${pill(label, tone)}${r.remind ? ' <span class="tag warn">⏰ waiting over a week</span>' : ''}</div>
    ${r.purpose ? `<p><strong>Why it's needed:</strong> ${esc(r.purpose)}</p>` : ''}
    <p class="muted">${esc(r.why_needed)}${r.oldest_days ? ` Oldest: ${r.oldest_days} day${r.oldest_days === 1 ? '' : 's'}.` : ''}</p>
    <div class="w-counts"><span>${r.waiting} waiting</span><span>${r.drafted} drafted</span><span>${r.added} added</span>${r.nothing_to_add ? `<span>${r.nothing_to_add} description only</span>` : ''}</div>
    <div class="w-sub">Fields</div><div class="w-fields">${fields}</div>
    ${table ? `<div class="w-sub">How the waiting entries would look</div>${table}` : ''}
    ${r.unanswered_questions?.length && r.state === 'waiting_for_approval' ? `<div class="w-sub">Open questions</div><ul class="w-qs">${r.unanswered_questions.map(q => `<li>${esc(q.text)}</li>`).join('')}</ul>` : ''}
    <p class="muted w-impact">${esc(r.impact)}</p>
    <details><summary>Waiting entries (${(r.entry_list || []).length})</summary><ul class="w-entries">${entries}</ul></details>
    <div class="approval-buttons">${buttons}</div></article>`;
}

function waitingTab() {
  const w = state.waiting || {requests: [], other_parked: []};
  const open = w.requests.filter(r => r.state === 'waiting_for_approval');
  const rest = w.requests.filter(r => r.state !== 'waiting_for_approval');
  const others = (w.other_parked || []).map(o => `<div class="approval-card ticket-list-row"><div><strong>Kept #${Number(o.id)}</strong><p>${esc(o.text)}</p><small>${esc(time(o.created_at))}</small></div><button class="btn btn-secondary" data-action="open-new-type" data-id="${Number(o.id)}">Review</button></div>`).join('');
  return `<section class="panel"><div class="panel-head"><div><div class="panel-title">Waiting for approval</div><div class="panel-sub">Information StudioOS has no place for yet. It is kept unchanged until a place is built.</div></div>${isAdmin() ? '<button class="btn btn-secondary btn-sm" data-action="w-check">Check waiting area now</button>' : ''}</div>
    ${open.length ? open.map(waitingRequest).join('') : empty('▧', 'Nothing waiting', 'When you mention information StudioOS cannot store yet, it waits here.')}</section>
    ${rest.length ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Decided</div></div></div>${rest.map(waitingRequest).join('')}</section>` : ''}
    ${others ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Other kept information</div><div class="panel-sub">Fits something StudioOS already stores, or needs the Admin to place it.</div></div></div>${others}</section>` : ''}`;
}

function recordTypesTab() {
  const types = state.recordTypes || [];
  const list = types.length ? types.map(t => `<button class="w-type${state.rtOpen?.key === t.key ? ' current' : ''}" data-action="w-open-type" data-key="${esc(t.key)}"><strong>${esc(wCap(t.title))}</strong> ${t.status === 'active' ? '' : pill('Undone', 'critical')}<span class="muted">${Number(t.records)} record${t.records === 1 ? '' : 's'} · ${esc(t.fields.map(f => f.label).join(', '))}</span></button>`).join('')
    : empty('▤', 'No record types yet', 'Approved build requests appear here.');
  const o = state.rtOpen;
  const records = !o ? '' : `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(wCap(o.title))}</div><div class="panel-sub">${o.records.length} saved${o.status === 'active' ? '' : ' · no longer accepts new records'}</div></div>${o.status === 'active' ? `<button class="btn btn-primary btn-sm" data-action="w-add-record" data-title="${esc(o.title)}">Add in chat</button>` : ''}</div>
    ${o.records.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Project</th>${o.records[0].values.map(v => `<th>${esc(v.label)}</th>`).join('')}<th>Saved</th></tr></thead><tbody>${o.records.map(r => `<tr><td>${esc(r.project || 'Not project related')}</td>${r.values.map(v => `<td>${esc(v.display)}</td>`).join('')}<td>${esc(time(r.created_at))}</td></tr>`).join('')}</tbody></table></div>` : empty('▤', 'No records yet', 'Add one in the chat.')}</section>`;
  return `<section class="panel"><div class="panel-head"><div><div class="panel-title">Record types</div><div class="panel-sub">Kinds of records built from approved requests. Each is checked against its approved fields on every save.</div></div></div><div class="w-types">${list}</div></section>${records}`;
}

function wHead(title, sub) { return head(title, sub).replace('STUDIOOS / NEWTYPES', 'STUDIOOS / ' + esc(title.toUpperCase())); }
newTypesView = function () {
  const tab = state.ntTab === 'types' ? 'types' : 'waiting';
  return wHead(tab === 'types' ? 'Record types' : 'Waiting for a place', tab === 'types' ? 'New kinds of records you have built.' : 'Nothing here is lost. Approve a build and the waiting entries are drafted for you.') +
    `<div class="w-tabs" role="tablist"><button class="w-tab${tab === 'waiting' ? ' on' : ''}" role="tab" data-action="w-tab" data-tab="waiting">Waiting</button><button class="w-tab${tab === 'types' ? ' on' : ''}" role="tab" data-action="w-tab" data-tab="types">Record types</button></div>` +
    (tab === 'types' ? recordTypesTab() : waitingTab()) +
    (state.newTypeDetail ? newTypeDetail(state.newTypeDetail) : '');
};

/* The ticket's conversation, with decision lines and the point it was saved. */
function ticketTranscript(conv) {
  let divided = false;
  return (conv || []).map(m => {
    const divider = m.after_saving && !divided ? (divided = true, '<div class="cx-divider"><span>After saving</span></div>') : '';
    if (m.decision) return divider + `<p class="t-decision${m.after_saving ? ' after' : ''}">${esc(m.text)}</p>`;
    return divider + `<p class="${m.after_saving ? 'after' : ''}"><strong>${esc({user: 'You', assistant: 'StudioOS'}[m.speaker] || m.speaker)}:</strong> ${esc(m.text)}<small class="muted"> · ${esc(time(m.created_at))}</small></p>`;
  }).join('');
}
const _ticketDetail = ticketDetail;
ticketDetail = function (t) {
  return _ticketDetail({...t, conversation: []}).replace('<div class="ticket-transcript"></div>', `<div class="ticket-transcript">${ticketTranscript(t.conversation)}</div>`);
};

const _wRender = render;
render = function () {
  _wRender();
  if (state.view === 'newtypes') { const bc = $('breadcrumb'); if (bc) bc.textContent = state.ntTab === 'types' ? 'Record types' : 'Waiting for a place'; }
};

document.addEventListener('click', async e => {
  const nav = e.target.closest('[data-view="newtypes"][data-tab]');
  if (nav) { state.ntTab = nav.dataset.tab; return; }  // let app.js switch the view
  const b = e.target.closest('[data-action^="w-"]');
  if (!b) return;
  e.stopImmediatePropagation();
  const a = b.dataset.action;
  try {
    if (a === 'w-tab') { state.ntTab = b.dataset.tab; render(); return; }
    if (a === 'w-open-type') { state.rtOpen = await api('/api/record-types/' + encodeURIComponent(b.dataset.key) + '/records'); render(); return; }
    if (a === 'w-add-record') { state.view = 'assistant'; state.draftText = `Log ${b.dataset.title} for `; render(); $('chatInput')?.focus(); return; }
    if (a === 'w-open-drafts') { state.view = 'assistant'; await openSession(b.dataset.id); return; }
    if (a === 'w-check') {
      const r = await api('/api/waiting/check', {method: 'POST', body: '{}'});
      const n = (r.drafted || []).reduce((t, x) => t + (x.drafted || 0), 0);
      notify(n ? `${n} waiting ${n === 1 ? 'entry was' : 'entries were'} drafted for approval.` : 'Nothing new could be added yet.');
      await refresh(); return;
    }
    if (a === 'w-approve') {
      if (!confirm('Build this kind of record? It adds a new record type only; existing data and tables are not changed.')) return;
      const r = await api(`/api/new-types/${Number(b.dataset.id)}/approve-structure`, {method: 'POST', body: JSON.stringify({note: 'Approved from Waiting for a place'})});
      const n = (r.waiting_check || []).reduce((t, x) => t + (x.drafted || 0), 0);
      notify(n ? `Built. ${n} waiting ${n === 1 ? 'entry was' : 'entries were'} drafted for your approval.` : 'Built. You can add these records in the chat now.');
      await refresh(); return;
    }
    if (a === 'w-reject') {
      if (!confirm('Do not build this? The waiting entries stay in the history.')) return;
      await api(`/api/new-types/${Number(b.dataset.id)}/reject`, {method: 'POST', body: JSON.stringify({note: 'Rejected from Waiting for a place'})});
      await refresh(); return;
    }
  } catch (err) { notify(err.message, true); }
}, true);
