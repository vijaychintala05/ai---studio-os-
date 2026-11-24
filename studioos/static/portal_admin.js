'use strict';
/* StudioOS "Client portal" screen for staff (admin, manager, architect): what clients said, the files shared with them, the records of
   what was agreed, and (admin) the portal's address and contacts. Every change here is a DRAFT change request that a person approves;
   nothing a client typed is ever used as HTML (everything goes through esc()). No inline styles (strict CSP). Loaded after books.js. */

Object.assign(state, {pa: {projects: null, domainSet: false, inbox: null, pid: null, tab: 'chat', chat: null, deliverables: null, documents: null,
  records: null, setup: null, picked: [], draft: null, form: '', formId: 0, busy: false}});

const PA_ROLES = ['admin', 'manager', 'architect'];
const PA_KINDS = ['Drawing', 'Render', 'Material selection', 'Report', 'Other'];
const paWhen = iso => { try { return new Date(iso).toLocaleString(); } catch (e) { return ''; } };
const paSize = n => (n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
const paOpts = (items, sel, label) => items.map(x => `<option value="${esc(x.value ?? x)}"${String(x.value ?? x) === String(sel ?? '') ? ' selected' : ''}>${esc(x.label ?? x)}</option>`).join('');

async function paLoadProjects() {
  const [p, i] = await Promise.all([api('/api/portal-projects'), api('/api/portal-inbox')]);
  state.pa.projects = p.projects; state.pa.domainSet = p.domain_set; state.pa.inbox = i;
  if (!state.pa.pid && p.projects.length) state.pa.pid = p.projects[0].id;
}
async function paLoadTab() {
  const a = state.pa, pid = a.pid;
  if (!pid) return;
  if (a.tab === 'chat') a.chat = (await api(`/api/portal/${pid}/chat`)).messages;
  if (a.tab === 'files') { [a.deliverables, a.documents] = await Promise.all([api(`/api/portal/${pid}/deliverables`).then(r => r.deliverables), api(`/api/portal/${pid}/documents`).then(r => r.documents)]); }
  if (a.tab === 'records') { [a.records, a.deliverables, a.documents] = await Promise.all([api(`/api/portal/${pid}/conversations`), api(`/api/portal/${pid}/deliverables`).then(r => r.deliverables), api(`/api/portal/${pid}/documents`).then(r => r.documents)]); }
  if (a.tab === 'setup') a.setup = await api(`/api/portal/${pid}`);
}
function paReload() {
  state.pa.busy = true;
  return paLoadProjects().then(paLoadTab).catch(e => notify(e.message, true)).finally(() => { state.pa.busy = false; render(); });
}

function paDraftBanner() {
  const d = state.pa.draft;
  if (!d) return '';
  return `<div class="notice"><span><strong>Saved as a draft change request #${Number(d.ticket_id)}.</strong> Nothing changes for the client until it is approved.</span>
    ${isApprover() ? `<button type="button" class="btn btn-primary btn-sm" data-pa="approve" data-id="${Number(d.ticket_id)}">Approve now</button>` : ''}
    <button type="button" class="btn btn-secondary btn-sm" data-view="${isApprover() ? 'approvals' : 'tickets'}">Open change requests</button>
    <button type="button" class="btn btn-secondary btn-sm" data-pa="dismiss">Dismiss</button></div>`;
}

function paInbox() {
  const i = state.pa.inbox;
  const rows = (i?.items || []).slice(0, 8).map(x => `<li><button type="button" class="cx-link" data-pa="open-project" data-id="${Number(x.project_id)}" data-tab="${x.kind === 'client_decision' ? 'files' : 'chat'}">${x.unread ? '<span class="tag warn">new</span> ' : ''}${esc(x.project)}</button>
    <span class="muted">${esc(paWhen(x.at))}</span><div>${esc(x.summary)}</div></li>`).join('');
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">New from clients</div><div class="panel-sub">${Number(i?.unread || 0)} not read yet</div></div>
    ${i?.unread ? '<button type="button" class="btn btn-secondary btn-sm" data-pa="seen">Mark all as read</button>' : ''}</div>
    <div class="panel-body">${rows ? `<ul class="rs-history">${rows}</ul>` : '<p class="muted">Nothing yet. Messages and answers from clients appear here.</p>'}</div></section>`;
}

function paTabs() {
  const a = state.pa, tabs = [['chat', 'Messages'], ['files', 'Files'], ['records', 'What was agreed']].concat(isAdmin() ? [['setup', 'Setup']] : []);
  return `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" class="pa-tab${a.tab === k ? ' active' : ''}" aria-selected="${a.tab === k}" data-pa="tab" data-tab="${k}">${l}</button>`).join('')}</div>`;
}

/* ---------- messages ---------- */
function paChat() {
  const a = state.pa, msgs = a.chat || [];
  const list = msgs.map(m => `<li class="pa-msg ${m.from === 'client' ? 'pa-client' : 'pa-staff'}">
    <label><input type="checkbox" data-pa="pick" data-id="${Number(m.id)}"${a.picked.includes(m.id) ? ' checked' : ''} aria-label="Select this message for a record">
    <strong>${esc(m.from === 'client' ? m.author + ' (client)' : m.author)}</strong> <span class="muted">${esc(paWhen(m.at))}</span></label><div>${esc(m.body)}</div></li>`).join('');
  const n = a.picked.length;
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Conversation with the client</div>
    <div class="panel-sub">Tick messages to write up what was agreed. Clients see this thread; internal talk stays in the project chat.</div></div>
    <button type="button" class="btn btn-secondary btn-sm" data-pa="refresh">Refresh</button></div>
    <div class="panel-body">${list ? `<ul class="pa-thread">${list}</ul>` : '<p class="muted">No messages yet.</p>'}
    <form data-pa-form="reply" class="section-gap"><label class="w-sub" for="paReply">Reply to the client</label>
      <textarea id="paReply" name="body" class="form-input" rows="2" maxlength="2000" required></textarea>
      <div class="mt-17"><button type="submit" class="btn btn-primary">Send</button></div></form>
    <div class="section-gap"><button type="button" class="btn btn-secondary" data-pa="start-record"${n ? '' : ' disabled'}>Write up ${n} selected message${n === 1 ? '' : 's'}</button></div>
    ${a.form === 'record' ? paRecordForm() : ''}</div></section>`;
}
function paRecordForm() {
  return `<form data-pa-form="record" class="panel-body pa-box"><div class="panel-title">New record of what was agreed</div>
    <p class="muted">The record and each checklist line will point to the ${state.pa.picked.length} message(s) you ticked, as proof.</p>
    <label class="w-sub" for="paRt">Title</label><input id="paRt" name="title" class="form-input" maxlength="150" required>
    <label class="w-sub" for="paRs">Summary of what was agreed</label><textarea id="paRs" name="summary" class="form-input" rows="4" maxlength="4000" required></textarea>
    <label class="w-sub" for="paRa">Checklist (one item per line)</label><textarea id="paRa" name="actions" class="form-input" rows="4" placeholder="Send revised kitchen layout&#10;Add a socket near the window"></textarea>
    <label class="pa-check"><input type="checkbox" name="shared"> Show this record to the client</label>
    <div class="mt-17"><button type="submit" class="btn btn-primary">Save as draft</button> <button type="button" class="btn btn-secondary" data-pa="cancel-form">Cancel</button></div></form>`;
}

/* ---------- files ---------- */
function paFileForm(d) {
  const a = state.pa, docs = a.documents || [];
  const pick = docs.map(x => ({value: x.id, label: `${x.name} (${paSize(x.size_bytes)})`}));
  const id = d ? Number(d.id) : 0;
  return `<form data-pa-form="${d ? 'file-edit' : 'file-add'}" data-id="${id}" class="pa-box">
    <label class="w-sub" for="paFt${id}">Title the client sees</label><input id="paFt${id}" name="title" class="form-input" maxlength="300" required value="${esc(d?.title || '')}">
    <label class="w-sub" for="paFk${id}">Kind</label><select id="paFk${id}" name="kind" class="form-input">${paOpts(PA_KINDS, d?.kind)}</select>
    <label class="w-sub" for="paFf${id}">File</label>${pick.length ? `<select id="paFf${id}" name="file" class="form-input">${paOpts(pick, d?.file?.id)}</select>` : '<p class="muted">No approved uploaded files on this project yet. Add the file through the Inbox first.</p>'}
    <label class="w-sub" for="paFr${id}">Release</label><select id="paFr${id}" name="release" class="form-input">${paOpts(['Draft', 'Final', 'Superseded'], d?.release || 'Draft')}</select>
    <label class="pa-check"><input type="checkbox" name="shared"${d?.shared_with_client ? ' checked' : ''}> Share with the client (they see it only when also Final)</label>
    <label class="pa-check"><input type="checkbox" name="needs"${d?.needs_client_approval ? ' checked' : ''}> Ask the client to approve it</label>
    <label class="w-sub" for="paFn${id}">Short note for the client (optional)</label><textarea id="paFn${id}" name="note" class="form-input" rows="2" maxlength="4000">${esc(d?.note_for_client || '')}</textarea>
    <div class="mt-17"><button type="submit" class="btn btn-primary"${pick.length ? '' : ' disabled'}>Save as draft</button> <button type="button" class="btn btn-secondary" data-pa="cancel-form">Cancel</button></div></form>`;
}
function paFiles() {
  const a = state.pa, items = a.deliverables || [];
  const rows = items.map(d => {
    const ap = d.approval ? `<span class="tag ${d.approval.state === 'approved' ? 'good' : 'warn'}">${esc({approved: 'Client approved', changes_requested: 'Client asked for changes', pending: 'Waiting for the client'}[d.approval.state] || d.approval.state)}</span>
      ${d.approval.comment ? `<span class="muted">“${esc(d.approval.comment)}”</span>` : ''}${d.approval.earlier_version ? ' <span class="muted">(changed since their last answer)</span>' : ''}` : '';
    return `<li class="pa-item"><div><strong>${esc(d.title)}</strong> <span class="tag gray">${esc(d.kind)}</span> <span class="tag ${d.release === 'Final' ? 'good' : 'gray'}">${esc(d.release)}</span>
      <span class="tag ${d.client_sees ? 'good' : 'gray'}">${d.client_sees ? 'Client can see it' : 'Hidden from client'}</span></div>
      <div class="muted">${d.file ? esc(d.file.name) : 'File missing'}${d.note_for_client ? ' · ' + esc(d.note_for_client) : ''}</div><div>${ap}</div>
      <button type="button" class="btn btn-secondary btn-sm" data-pa="edit-file" data-id="${Number(d.id)}">Edit</button>
      ${a.form === 'file-edit' && a.formId === d.id ? paFileForm(d) : ''}</li>`;
  }).join('');
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Files shared with the client</div>
    <div class="panel-sub">A client sees a file only when it is Final and shared. Every change is a draft a person approves.</div></div>
    <button type="button" class="btn btn-primary btn-sm" data-pa="add-file">Add a file</button></div>
    <div class="panel-body">${a.form === 'file-add' ? paFileForm(null) : ''}${rows ? `<ul class="pa-list">${rows}</ul>` : '<p class="muted">Nothing shared yet.</p>'}</div></section>`;
}

/* ---------- records ---------- */
function paActionForm(act) {
  const a = state.pa, docs = (a.documents || []).map(x => ({value: x.id, label: x.name})), dels = (a.deliverables || []).map(x => ({value: x.id, label: x.title}));
  return `<form data-pa-form="action-edit" data-id="${Number(act.id)}" class="pa-box">
    <label class="w-sub" for="paAt${act.id}">What needs doing</label><input id="paAt${act.id}" name="text" class="form-input" maxlength="500" required value="${esc(act.text)}">
    <label class="w-sub" for="paAp${act.id}">Done?</label><select id="paAp${act.id}" name="progress" class="form-input">${paOpts(['Open', 'Done'], act.state)}</select>
    <label class="w-sub" for="paAn${act.id}">What was done (the client sees this)</label><textarea id="paAn${act.id}" name="note" class="form-input" rows="2" maxlength="4000">${esc(act.note)}</textarea>
    <label class="w-sub" for="paAf${act.id}">Uploaded file that shows it was done</label><select id="paAf${act.id}" name="file" class="form-input"><option value="keep">Keep as it is${act.file ? ' (' + esc(act.file.name) + ')' : ''}</option><option value="">None</option>${paOpts(docs, '')}</select>
    <label class="w-sub" for="paAd${act.id}">Client file that addresses it</label><select id="paAd${act.id}" name="deliverable" class="form-input"><option value="">None</option>${paOpts(dels, act.deliverable?.id)}</select>
    <div class="mt-17"><button type="submit" class="btn btn-primary">Save as draft</button> <button type="button" class="btn btn-secondary" data-pa="cancel-form">Cancel</button></div></form>`;
}
function paRecords() {
  const a = state.pa, r = a.records;
  if (!r) return '<div class="loading">Loading…</div>';
  const warn = r.thread_ok ? '' : '<div class="notice fail"><span><strong>The conversation thread failed its integrity check.</strong> Proof tags below show as not verified. Tell the owner.</span></div>';
  const cards = r.records.map(rec => {
    const good = rec.messages.length && rec.messages.every(m => m.verified);
    const acts = rec.actions.map(x => `<li class="pa-item"><span class="tag ${x.state === 'Done' ? 'good' : 'warn'}">${esc(x.state)}</span> ${esc(x.text)}
      <span class="muted">${x.owner ? esc(x.owner) + ' · ' : ''}${x.due_date ? 'due ' + esc(x.due_date) : ''}</span>${x.note ? `<div>${esc(x.note)}</div>` : ''}
      ${x.file ? `<div class="muted">File: ${esc(x.file.name)}</div>` : ''}${x.deliverable ? `<div class="muted">Client file: ${esc(x.deliverable.title)}</div>` : ''}
      <button type="button" class="btn btn-secondary btn-sm" data-pa="edit-action" data-id="${Number(x.id)}">Update</button>
      ${a.form === 'action-edit' && a.formId === x.id ? paActionForm(x) : ''}</li>`).join('');
    const proof = rec.messages.map(m => `<li class="pa-msg"><strong>${esc(m.author)}</strong> <span class="muted">${esc(paWhen(m.at))} · ${m.verified ? 'verified' : 'NOT verified'}</span><div>${esc(m.body)}</div></li>`).join('');
    return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(rec.title)}</div>
      <div class="panel-sub">${esc(paWhen(rec.created))}${rec.updated ? ' · updated ' + esc(paWhen(rec.updated)) : ''} · <span class="tag ${rec.shared_with_client ? 'good' : 'gray'}">${rec.shared_with_client ? 'Client can see it' : 'Not shared'}</span></div></div>
      <button type="button" class="btn btn-secondary btn-sm" data-pa="edit-record" data-id="${Number(rec.id)}">Edit</button></div>
      <div class="panel-body">${a.form === 'record-edit' && a.formId === rec.id ? paRecordEditForm(rec) : `<p>${esc(rec.summary)}</p>`}
      ${acts ? `<ul class="pa-list">${acts}</ul>` : '<p class="muted">No checklist items.</p>'}
      <details><summary>Proof: ${rec.messages.length} message(s) ${good ? '(verified)' : '(NOT verified)'}</summary><ul class="pa-thread">${proof}</ul></details></div></section>`;
  }).join('');
  return warn + (cards || '<p class="muted section-gap">Nothing written up yet. Tick messages in Messages and choose “Write up”.</p>');
}
function paRecordEditForm(rec) {
  return `<form data-pa-form="record-edit" data-id="${Number(rec.id)}" class="pa-box">
    <label class="w-sub" for="paEt${rec.id}">Title</label><input id="paEt${rec.id}" name="title" class="form-input" maxlength="150" required value="${esc(rec.title)}">
    <label class="w-sub" for="paEs${rec.id}">Summary</label><textarea id="paEs${rec.id}" name="summary" class="form-input" rows="4" maxlength="4000" required>${esc(rec.summary)}</textarea>
    <label class="pa-check"><input type="checkbox" name="shared"${rec.shared_with_client ? ' checked' : ''}> Show this record to the client</label>
    <div class="mt-17"><button type="submit" class="btn btn-primary">Save as draft</button> <button type="button" class="btn btn-secondary" data-pa="cancel-form">Cancel</button></div></form>`;
}

/* ---------- setup (admin) ---------- */
function paSetup() {
  const s = state.pa.setup;
  if (!s) return '<div class="loading">Loading…</div>';
  const portal = s.portal;
  const contacts = s.contacts.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.phone)}</td><td>${esc(c.email)}</td><td>${c.active ? 'On' : 'Off'}</td>
    <td><button type="button" class="btn btn-secondary btn-sm" data-pa="contact" data-id="${Number(c.id)}" data-on="${c.active ? '0' : '1'}">${c.active ? 'Switch off' : 'Switch on'}</button></td></tr>`).join('');
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Portal address</div>
    <div class="panel-sub">${portal ? `Clients open <strong>${esc(portal.address || portal.slug)}</strong> (${portal.enabled ? 'on' : 'off'})` : 'Not set up for this project yet.'}${s.domain_set ? '' : ' The portal domain is not set on the server yet (see the Runbook).'}</div></div></div>
    <form data-pa-form="portal" class="panel-body"><label class="w-sub" for="paSlug">Address name (letters, numbers, hyphens)</label>
      <input id="paSlug" name="slug" class="form-input" maxlength="40" required value="${esc(portal?.slug || '')}">
      <label class="pa-check"><input type="checkbox" name="enabled"${!portal || portal.enabled ? ' checked' : ''}> Portal is on</label>
      <div class="mt-17"><button type="submit" class="btn btn-primary">Save</button></div></form></section>
    <section class="panel section-gap"><div class="panel-head"><div class="panel-title">People who can sign in</div></div><div class="panel-body">
      ${contacts ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Name</th><th>Phone</th><th>Email</th><th>Status</th><th></th></tr></thead><tbody>${contacts}</tbody></table></div>` : '<p class="muted">Nobody yet.</p>'}
      <form data-pa-form="contact-add" class="section-gap"><label class="w-sub" for="paCn">Name</label><input id="paCn" name="name" class="form-input" maxlength="150" required>
        <label class="w-sub" for="paCp">Phone (10 digits)</label><input id="paCp" name="phone" class="form-input" inputmode="numeric" maxlength="20">
        <label class="w-sub" for="paCe">Email</label><input id="paCe" name="email" class="form-input" type="email" maxlength="200">
        <div class="mt-17"><button type="submit" class="btn btn-primary">Add person</button></div></form></div></section>`;
}

function portalView() {
  if (!PA_ROLES.includes(state.user?.role)) return head('Client portal', 'The client portal is for the owner, managers and architects.');
  const a = state.pa;
  if (!a.projects) { paReload(); return head('Client portal', 'What your clients see, and what they say.') + '<div class="loading">Loading…</div>'; }
  const project = a.projects.find(p => p.id === a.pid);
  const picker = `<label class="w-sub" for="paProject">Project</label><select id="paProject" class="form-input" data-pa-select="project">${a.projects.map(p => `<option value="${Number(p.id)}"${p.id === a.pid ? ' selected' : ''}>${esc(p.name)}${p.unread ? ` (${Number(p.unread)} new)` : ''}</option>`).join('')}</select>`;
  const body = !project ? '<p class="muted">You have no projects yet.</p>' : (!project.portal && a.tab !== 'setup'
    ? `<div class="notice warn"><span>The portal is not set up for this project.${isAdmin() ? '' : ' Ask the owner to set it up.'}</span>${isAdmin() ? '<button type="button" class="btn btn-secondary btn-sm" data-pa="tab" data-tab="setup">Set it up</button>' : ''}</div>`
      : ({chat: paChat, files: paFiles, records: paRecords, setup: paSetup}[a.tab] || paChat)());
  return head('Client portal', 'What your clients see, and what they say.') + paDraftBanner() + paInbox() + `<section class="panel section-gap"><div class="panel-body">${picker}${paTabs()}</div></section>` + body;
}

/* ---------- actions ---------- */
async function paPost(path, data, method = 'POST') { return api(path, {method, body: JSON.stringify(data || {})}); }
function paDrafted(r) { state.pa.draft = r; state.pa.form = ''; state.pa.picked = []; return paReload(); }

async function paSubmit(form) {
  const f = new FormData(form), kind = form.dataset.paForm, id = Number(form.dataset.id || 0), pid = state.pa.pid, g = k => String(f.get(k) || '').trim();
  const blank = v => (v === '' ? null : Number(v));
  try {
    if (kind === 'reply') { await paPost(`/api/portal/${pid}/chat`, {body: g('body')}); await paReload(); return; }
    if (kind === 'record') {
      const actions = g('actions').split('\n').map(x => x.trim()).filter(Boolean).map(text => ({text, message_ids: state.pa.picked}));
      await paDrafted(await paPost(`/api/portal/${pid}/conversation-records`, {title: g('title'), summary: g('summary'), message_ids: state.pa.picked, shared_with_client: f.get('shared') === 'on', actions}));
    } else if (kind === 'file-add' || kind === 'file-edit') {
      const body = {title: g('title'), kind: g('kind'), release: g('release'), shared_with_client: f.get('shared') === 'on', needs_client_approval: f.get('needs') === 'on', note_for_client: g('note')};
      if (f.get('file')) body.file = Number(f.get('file'));
      await paDrafted(await paPost(kind === 'file-add' ? `/api/portal/${pid}/deliverables` : `/api/portal/${pid}/deliverables/${id}/edit`, body));
    } else if (kind === 'record-edit') {
      await paDrafted(await paPost(`/api/portal/${pid}/conversations/${id}/edit`, {title: g('title'), summary: g('summary'), shared_with_client: f.get('shared') === 'on'}));
    } else if (kind === 'action-edit') {
      const body = {text: g('text'), progress: g('progress')}, clear = [];
      if (g('note')) body.resolution_note = g('note'); else clear.push('resolution_note');
      if (g('file') === 'keep') { /* leave the file as it is */ } else if (blank(g('file')) !== null) body.resolution_file = blank(g('file')); else clear.push('resolution_file');
      if (blank(g('deliverable')) !== null) body.resolution_deliverable = blank(g('deliverable')); else clear.push('resolution_deliverable');
      await paDrafted(await paPost(`/api/portal/${pid}/conversation-actions/${id}/edit`, {...body, clear}));
    } else if (kind === 'portal') {
      await paPost(`/api/portal/${pid}`, {slug: g('slug'), enabled: f.get('enabled') === 'on'}, 'PUT'); notify('Portal saved.'); await paReload();
    } else if (kind === 'contact-add') {
      await paPost(`/api/portal/${pid}/contacts`, {name: g('name'), phone: g('phone'), email: g('email')}); notify('Person added.'); await paReload();
    }
  } catch (e) { notify(e.message, true); }
}

document.addEventListener('submit', e => {
  const form = e.target.closest('form[data-pa-form]');
  if (!form) return;
  e.preventDefault();
  if (!state.pa.busy) paSubmit(form);
});
document.addEventListener('change', e => {
  const sel = e.target.closest('[data-pa-select="project"]');
  if (sel) { state.pa.pid = Number(sel.value); state.pa.form = ''; state.pa.picked = []; state.pa.draft = null; paReload(); return; }
  const pick = e.target.closest('[data-pa="pick"]');
  if (pick) {
    const id = Number(pick.dataset.id), set = new Set(state.pa.picked);
    if (pick.checked) set.add(id); else set.delete(id);
    state.pa.picked = [...set].sort((x, y) => x - y); render();
  }
});
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pa]');
  if (!b || b.dataset.pa === 'pick' || state.pa.busy) return;
  const a = state.pa, act = b.dataset.pa, id = Number(b.dataset.id || 0);
  if (act === 'tab') { a.tab = b.dataset.tab; a.form = ''; a.picked = []; a.records = a.setup = null; await paReload(); }
  else if (act === 'open-project') { a.pid = id; a.tab = b.dataset.tab; a.records = a.setup = null; await paReload(); }
  else if (act === 'refresh') await paReload();
  else if (act === 'seen') { try { await paPost('/api/portal-inbox/seen'); } catch (err) { notify(err.message, true); } await paReload(); }
  else if (act === 'dismiss') { a.draft = null; render(); }
  else if (act === 'approve') {
    try { await paPost(`/api/tickets/${id}/approve-and-save`); notify('Approved and saved.'); a.draft = null; a.records = null; } catch (err) { notify(err.message, true); }
    await paReload();
  }
  else if (act === 'start-record') { a.form = 'record'; render(); }
  else if (act === 'add-file') { a.form = 'file-add'; a.formId = 0; render(); }
  else if (act === 'edit-file') { a.form = 'file-edit'; a.formId = id; render(); }
  else if (act === 'edit-record') { a.form = 'record-edit'; a.formId = id; render(); }
  else if (act === 'edit-action') { a.form = 'action-edit'; a.formId = id; render(); }
  else if (act === 'cancel-form') { a.form = ''; render(); }
  else if (act === 'contact') {
    try { await paPost(`/api/portal/${a.pid}/contacts/${id}`, {active: b.dataset.on === '1'}, 'PATCH'); } catch (err) { notify(err.message, true); }
    await paReload();
  }
});

const PA_VIEWS = {portal: ['Client portal', portalView]};
const _paRender = render;
render = function () {
  const nav = document.querySelector('.nav-link[data-view="portal"]');
  if (nav) nav.hidden = !PA_ROLES.includes(state.user?.role);      // other roles never see the entry
  const v = PA_VIEWS[state.view];
  if (!v) { _paRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = v[1]();
  $('breadcrumb').textContent = v[0];
  document.querySelectorAll('.nav-link').forEach(x => x.classList.toggle('active', x.dataset.view === 'portal'));
};
document.addEventListener('click', e => { if (e.target.closest('[data-view="portal"]')) { state.pa.projects = null; state.pa.draft = null; state.pa.form = ''; } });
