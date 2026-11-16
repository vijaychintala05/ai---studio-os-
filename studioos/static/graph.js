'use strict';
/* StudioOS v0.10.0 "Work": one generic screen for every universal type (made at runtime or
   installed from a business pack). Lists, a form built from the type's fields (with pickers for
   staff, tasks, projects, files and other records), a record page with its links in both
   directions and its history, reports, notices and business packs.
   Every change opens an approval ticket; nothing here writes business data directly.
   Loaded after app.js, chat.js, waiting.js, connectors.js, universal.js, chart.js. */

Object.assign(state, {g: {tab: 'records', catalog: null, type: null, list: null, q: '', record: null, form: null,
  options: {}, report: null, reportKey: null, notices: null, pack: null}});

const gApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const gType = key => (state.g.catalog?.types || []).find(t => t.key === key);
const gTitle = key => gType(key)?.title || (state.g.catalog?.system_types || []).find(s => s.key === key)?.title || key;

async function gLoad() {
  state.g.catalog = await gApi('/api/graph/catalog');
  if (!state.g.type && state.g.catalog.types.length) state.g.type = state.g.catalog.types[0].key;
  if (!state.g.catalog.types.length && isAdmin()) state.g.tab = 'packs';
}

async function gPropose(kind, data, evidence) {
  const r = await gApi('/api/universal/proposals', {kind, data, evidence});
  notify(`Ticket #${r.ticket_id} opened. Nothing is saved until it is approved.`);
  return r;
}

// ------------------------------------------------------------------ views

function gTabs() {
  const tabs = [['records', 'Records'], ['reports', 'Reports'], ['notices', 'Notices']].concat(isAdmin() ? [['packs', 'Business packs']] : []);
  return `<div class="g-tabs" role="tablist">${tabs.map(([k, l]) => `<button class="g-tab ${state.g.tab === k ? 'active' : ''}" data-g="tab" data-key="${k}" role="tab" aria-selected="${state.g.tab === k}">${esc(l)}</button>`).join('')}</div>`;
}

function gTypeChips() {
  const groups = {};
  state.g.catalog.types.forEach(t => { (groups[t.pack || 'other'] = groups[t.pack || 'other'] || []).push(t); });
  const packTitle = k => (state.g.catalog.packs.find(p => p.key === k) || {}).title || 'Other types';
  return Object.entries(groups).map(([k, ts]) => `<div class="g-chip-group"><div class="g-chip-label">${esc(packTitle(k))}</div>${ts.map(t =>
    `<button class="g-chip ${state.g.type === t.key ? 'active' : ''}" data-g="type" data-key="${esc(t.key)}">${esc(t.title)}</button>`).join('')}</div>`).join('');
}

function gRecordsView() {
  const c = state.g.catalog;
  if (!c.types.length) return `<div class="empty"><div class="empty-big">▦</div>No record types yet.${isAdmin() ? ' Install a business pack, or make a type on the Universal Types screen.' : ' Ask the Admin to install a business pack.'}</div>`;
  const t = gType(state.g.type);
  if (state.g.form) return gChips() + gFormView();
  if (state.g.record) return gChips() + gRecordView();
  const l = state.g.list;
  const table = !l ? '<div class="loading">Loading…</div>' : l.records.length
    ? `<div class="w-table-wrap"><table class="w-table g-table"><thead><tr><th>${esc(t.title)}</th>${l.columns.slice(1).map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${l.records.map(r =>
      `<tr><td><button class="cx-link" data-g="open" data-id="${Number(r.id)}">${esc(r.label)}</button></td>${r.cells.slice(1).map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
    : `<p class="muted g-pad">No ${esc(t.title.toLowerCase())} records you can see${state.g.q ? ' match the search' : ''}.</p>`;
  return gChips() + `<section class="panel"><div class="panel-head"><div><div class="panel-title">${esc(t.title)}</div><div class="panel-sub">${esc(t.description || '')} ${l ? `${Number(l.total)} record${l.total === 1 ? '' : 's'}` : ''}</div></div>${state.user?.role !== 'viewer' ? `<button class="btn btn-primary btn-sm" data-g="new">+ New</button>` : ''}</div>
    <div class="g-search"><input class="form-input" id="gSearch" placeholder="Search ${esc(t.title.toLowerCase())}…" value="${esc(state.g.q)}" aria-label="Search"></div>${table}
    <p class="muted g-pad">Approved by: ${esc(t.approver_roles.join(', '))}. Or type it in the chat, for example “${esc(gExample(t))}”.</p></section>`;
}
function gChips() { return `<div class="g-chips">${gTypeChips()}</div>`; }
function gExample(t) {
  const ex = {timesheet_entry: 'Timesheet: Ravi 6 hours on drawings yesterday', work_issue: 'Issue: glass partition delayed; owner: Asha; severity: high',
    attendance_entry: 'Attendance: Asha present today', leave_request: 'Leave request: Ravi casual leave 20 Nov to 21 Nov',
    sop: 'SOP: site handover checklist', meeting_note: 'Meeting note: client approved the kitchen layout'}[t.key];
  return ex || `${t.title}: …`;
}

function gValueCell(v) {
  if (v.type === 'reference' && v.raw && v.target === 'system.document') return `<a class="cx-link" href="/api/documents/${Number(v.raw)}/file" download>${esc(v.display || 'Download document')}</a>`;
  if (v.type === 'reference' && v.raw && v.target && !v.target.startsWith('system.')) return `<button class="cx-link" data-g="open" data-id="${Number(v.raw)}">${esc(v.display)}</button>`;
  return esc(v.display || '—');
}

function gRecordView() {
  const r = state.g.record;
  const vals = r.values.map(v => `<div class="g-kv"><div class="g-k">${esc(v.label)}</div><div class="g-v">${gValueCell(v)}</div></div>`).join('');
  const canWrite = state.user?.role !== 'viewer';
  const out = r.outgoing.map(g => `<div class="g-links"><div class="g-links-head"><strong>${esc(g.label)}</strong> <small class="muted">→ ${esc(g.target_title)}</small>
      ${canWrite && (g.cardinality === 'many' || !g.items.length) ? `<button class="btn btn-secondary btn-sm" data-g="link-add" data-rel="${esc(g.relation)}" data-target="${esc(g.target_type)}">Link</button>` : ''}</div>
      ${g.items.length ? `<ul class="g-link-list">${g.items.map(i => `<li>${i.is_record ? `<button class="cx-link" data-g="open" data-id="${Number(i.id)}">${esc(i.label)}</button>` : esc(i.label)}${canWrite ? ` <button class="g-x" data-g="link-remove" data-edge="${Number(i.edge_id)}" aria-label="Remove link to ${esc(i.label)}">Remove</button>` : ''}</li>`).join('')}</ul>` : '<p class="muted">None yet.</p>'}
      <div class="g-picker" id="gPick-${esc(g.relation)}"></div></div>`).join('');
  const inc = r.incoming.map(g => `<div class="g-links"><div class="g-links-head"><strong>${esc(g.label)}</strong> <small class="muted">${esc(g.source_title)}</small>
      ${canWrite ? `<button class="btn btn-secondary btn-sm" data-g="new-linked" data-type="${esc(g.source_type)}" data-rel="${esc(g.relation)}">+ Add</button>` : ''}</div>
      ${g.items.length ? `<ol class="g-link-list">${g.items.map(i => `<li><button class="cx-link" data-g="open" data-id="${Number(i.id)}">${esc(i.label)}</button></li>`).join('')}</ol>` : '<p class="muted">None yet.</p>'}</div>`).join('');
  const hist = r.history.map(h => `<li>Version ${Number(h.version)} · ${esc(h.actor || '')} · ticket <button class="cx-link" data-action="open-ticket" data-id="${Number(h.ticket_id)}">#${Number(h.ticket_id)}</button>${h.changed.length ? ' · ' + esc(h.changed.join(', ').replace(/_/g, ' ')) : ''}</li>`).join('');
  return `<section class="panel"><div class="panel-head"><div><button class="cx-link" data-g="back">← ${esc(r.type_title)}</button><div class="panel-title">${esc(r.label)}</div>
      <div class="panel-sub">${esc(r.type_title)}${r.project ? ' · ' + esc(r.project) : ' · company-wide'} · version ${Number(r.current_version)}</div></div>
      ${canWrite ? '<button class="btn btn-secondary btn-sm" data-g="edit">Edit</button>' : ''}</div>
    <div class="panel-body g-values">${vals}</div></section>
    ${out || inc ? `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Links</div></div><div class="panel-body">${out}${inc}</div></section>` : ''}
    <section class="panel section-gap"><div class="panel-head"><div class="panel-title">History</div><div class="panel-sub">Every change was an approved ticket.</div></div><div class="panel-body"><ul class="cx-notes">${hist}</ul></div></section>`;
}

function gInput(f, value) {
  const name = `g-${esc(f.name)}`, req = f.required ? ' required' : '', label = `${esc(f.meaning || f.name)}${f.required ? ' *' : ''}`;
  const v = value ?? '';
  let input;
  if (f.type === 'enum') input = `<select class="form-input" name="${name}"${req}><option value="">Choose…</option>${f.options.map(o => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  else if (f.type === 'boolean') input = `<select class="form-input" name="${name}"${req}><option value="">—</option><option value="true" ${v === true ? 'selected' : ''}>Yes</option><option value="false" ${v === false ? 'selected' : ''}>No</option></select>`;
  else if (f.type === 'reference') input = `<select class="form-input" name="${name}" data-target="${esc(f.target)}" data-value="${esc(v)}"${req}><option value="">Loading ${esc(f.target_title || '')}…</option></select>`;
  else if (f.type === 'date') input = `<input class="form-input" type="date" name="${name}" value="${esc(v)}"${req}>`;
  else if (f.type === 'integer') input = `<input class="form-input" inputmode="numeric" pattern="-?[0-9]*" name="${name}" value="${esc(v)}"${req}>`;
  else if (f.type === 'decimal') input = `<input class="form-input" inputmode="decimal" name="${name}" value="${esc(v)}"${req}>`;
  else if (f.type === 'money') input = `<input class="form-input" inputmode="decimal" name="${name}" placeholder="₹" value="${esc(v?.amount ?? '')}"${req}>`;
  else if (f.type === 'quantity') input = `<span class="g-qty"><input class="form-input" inputmode="decimal" name="${name}" value="${esc(v?.value ?? '')}"${req}><select class="form-input" name="${name}-unit">${f.units.map(u => `<option ${u === v?.unit ? 'selected' : ''}>${esc(u)}</option>`).join('')}</select></span>`;
  else if (f.type === 'datetime') input = `<input class="form-input" type="datetime-local" name="${name}"${req}>`;
  else input = `<textarea class="form-input" rows="2" name="${name}"${req}>${esc(v)}</textarea>`;
  return `<label class="g-field"><span>${label}</span>${input}</label>`;
}

function gFormView() {
  const f = state.g.form, t = gType(f.type);
  const projects = (state.projects || []).map(p => `<option value="${Number(p.id)}" ${Number(p.id) === f.project_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
  return `<section class="panel"><div class="panel-head"><div><button class="cx-link" data-g="cancel">← Cancel</button><div class="panel-title">${f.record ? 'Edit' : 'New'} ${esc(t.title.toLowerCase())}</div>
      <div class="panel-sub">${f.link ? 'Will be linked to ' + esc(f.link.label) + '. ' : ''}Opens a ticket; saved after approval.</div></div></div>
    <form class="panel-body g-form" id="gForm"><label class="g-field"><span>Project</span><select class="form-input" name="g-project" ${f.record ? 'disabled' : ''}><option value="">Not project-related (company-wide)</option>${projects}</select></label>
    ${t.fields.map(x => gInput(x, f.values[x.name])).join('')}
    <div class="g-actions"><button class="btn btn-primary" type="submit">${f.record ? 'Propose changes' : 'Propose'}</button></div></form></section>`;
}

function gReportsView() {
  const reps = state.g.catalog.reports;
  if (!reps.length) return '<div class="empty"><div class="empty-big">▤</div>No reports yet. Business packs bring their own.</div>';
  const list = `<div class="g-chips">${reps.map(r => `<button class="g-chip ${state.g.reportKey === r.key ? 'active' : ''}" data-g="report" data-key="${esc(r.key)}">${esc(r.title)}</button>`).join('')}</div>`;
  const r = state.g.report;
  if (!r) return list + '<p class="muted g-pad">Choose a report. Figures include only records you are allowed to see.</p>';
  const body = r.mode === 'grouped'
    ? `<table class="w-table"><thead><tr>${r.group_labels.map(x => `<th>${esc(x)}</th>`).join('')}${r.measure_labels.map(x => `<th class="b-num">${esc(x)}</th>`).join('')}</tr></thead><tbody>${r.rows.map(x =>
      `<tr>${x.group.map(g => `<td>${esc(g)}</td>`).join('')}${x.values.map(v => `<td class="b-num">${esc(v)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${r.group_labels.length + r.measure_labels.length}">Nothing matches.</td></tr>`}</tbody></table>`
    : `<table class="w-table"><thead><tr>${r.column_labels.map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${r.rows.map(x =>
      `<tr>${x.cells.map((c, i) => `<td>${i === 0 && x.record_id ? `<button class="cx-link" data-g="open" data-id="${Number(x.record_id)}">${esc(c)}</button>` : esc(c)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${r.column_labels.length}">Nothing matches.</td></tr>`}</tbody></table>`;
  return list + `<section class="panel"><div class="panel-head"><div><div class="panel-title">${esc(r.title)}</div><div class="panel-sub">${Number(r.matched)} of ${Number(r.scanned)} records · as of ${esc(r.as_of)}</div></div>
    <a class="btn btn-secondary btn-sm" href="/api/graph/reports/${encodeURIComponent(r.key)}/export.csv">CSV</a></div><div class="w-table-wrap">${body}</div></section>`;
}

function gNoticesView() {
  const n = state.g.notices;
  if (!n) return '<div class="loading">Loading…</div>';
  if (!n.length) return '<div class="empty"><div class="empty-big">✓</div>No notices for you.</div>';
  return `<section class="panel"><div class="panel-body w-list">${n.map(x => `<article class="w-card"><div class="w-head"><strong>${esc(x.message)}</strong> ${x.for_me ? pill('For you', 'warn') : ''}</div>
    <small class="muted">${esc(x.type_title)} · <button class="cx-link" data-g="open" data-id="${Number(x.record_id)}">${esc(x.record)}</button> · ${esc((x.at || '').slice(0, 10))}</small></article>`).join('')}</div></section>`;
}

function gPacksView() {
  const c = state.g.catalog;
  const packs = c.packs.map(p => `<article class="w-card g-pack"><div class="w-head"><strong>${esc(p.title)}</strong> ${p.installed_version ? pill('Installed v' + p.installed_version, 'good') : pill('Not installed')}</div>
    <p class="muted">${esc(p.description)}</p><p class="muted">${esc(p.type_titles.join(', '))} · ${Number(p.contents.relations)} links · ${Number(p.contents.reports)} reports · ${Number(p.contents.workflows)} rules</p>
    ${p.installed_version ? '' : `<button class="btn btn-primary btn-sm" data-g="install" data-key="${esc(p.key)}" data-version="${Number(p.version)}" data-sha="${esc(p.sha256)}">Propose install</button>`}</article>`).join('');
  const legacy = c.legacy_types.length ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Types made in the chat</div><div class="panel-sub">Bring them into the same engine, so they can be linked and reported on. Stored records are not changed.</div></div></div><div class="panel-body">${c.legacy_types.map(t =>
    `<div class="ck-row"><span>${esc(t.title)}</span><button class="btn btn-secondary btn-sm" data-g="adopt" data-key="${esc(t.key)}">Propose</button></div>`).join('')}</div></section>` : '';
  return `<section class="panel"><div class="panel-head"><div><div class="panel-title">Business packs</div><div class="panel-sub">Ready-made types, links, reports and rules, installed as data by one Admin ticket. No code or tables are added.</div></div></div><div class="panel-body w-list">${packs}</div></section>${legacy}`;
}

function workView() {
  const intro = 'Every kind of record, its links and reports, from approved definitions.';
  if (!state.g.catalog) { gLoad().then(() => gRefresh()).catch(err => notify(err.message, true)); return head('Work', intro) + '<div class="loading">Loading…</div>'; }
  const tab = state.g.tab;
  const body = tab === 'reports' ? gReportsView() : tab === 'notices' ? gNoticesView() : tab === 'packs' ? gPacksView() : gRecordsView();
  return head('Work', intro) + gTabs() + body;
}

// ------------------------------------------------------------------ data

async function gRefresh() {
  const g = state.g;
  if (g.tab === 'records' && g.type && !g.record && !g.form) {
    g.list = await gApi(`/api/graph/records/${encodeURIComponent(g.type)}?q=${encodeURIComponent(g.q)}`);
  }
  if (g.tab === 'notices') g.notices = (await gApi('/api/graph/notices')).notices;
  render();
  if (g.form) gFillPickers();
}

async function gFillPickers() {
  const pid = Number(document.querySelector('#gForm [name="g-project"]')?.value || 0) || '';
  for (const sel of document.querySelectorAll('#gForm select[data-target]')) {
    const key = sel.dataset.target + '|' + pid;
    try {
      state.g.options[key] = state.g.options[key] || await gApi(`/api/graph/targets/${encodeURIComponent(sel.dataset.target)}${pid ? '?project_id=' + pid : ''}`);
    } catch (err) { state.g.options[key] = []; }
    const want = sel.dataset.value;
    sel.innerHTML = `<option value="">Choose…</option>` + state.g.options[key].map(o => `<option value="${Number(o.id)}" ${String(o.id) === want ? 'selected' : ''}>${esc(o.label)}${o.detail ? ' · ' + esc(o.detail) : ''}</option>`).join('');
  }
}

async function gOpen(id) {
  state.g.record = await gApi('/api/graph/record/' + Number(id));
  state.g.type = state.g.record.type_key; state.g.form = null; state.g.tab = 'records';
  render(); window.scrollTo(0, 0);
}

function gReadForm(form, t) {
  const fd = new FormData(form), values = {};
  for (const f of t.fields) {
    const raw = String(fd.get('g-' + f.name) ?? '').trim();
    if (!raw) { if (f.required) throw new Error(`${f.meaning || f.name} is required`); continue; }
    if (f.type === 'integer') { if (!/^-?\d+$/.test(raw)) throw new Error(`${f.meaning || f.name}: whole number`); values[f.name] = Number(raw); }
    else if (f.type === 'reference') values[f.name] = Number(raw);
    else if (f.type === 'boolean') values[f.name] = raw === 'true';
    else if (f.type === 'money') values[f.name] = {amount: raw.replace(/[₹,\s]/g, ''), currency: 'INR'};
    else if (f.type === 'quantity') values[f.name] = {value: raw, unit: fd.get('g-' + f.name + '-unit')};
    else if (f.type === 'datetime') values[f.name] = new Date(raw).toISOString();
    else values[f.name] = raw;
  }
  return values;
}

// ------------------------------------------------------------------ events

const _gRender = render;
render = function () {
  if (state.view === 'work') {
    document.body.classList.remove('chat-mode');   // v0.11.0: coming from the chat, the page must scroll again
    updateIdentity();
    $('mainContent').innerHTML = workView();
    $('breadcrumb').textContent = 'Work';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    if (state.g.form) gFillPickers();
    return;
  }
  _gRender();
};

let gSearchTimer = null;
document.addEventListener('input', e => {
  if (e.target.id !== 'gSearch') return;
  state.g.q = e.target.value;
  clearTimeout(gSearchTimer);
  gSearchTimer = setTimeout(async () => { await gRefresh(); const s = $('gSearch'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 300);
});
document.addEventListener('change', e => {
  if (e.target.name === 'g-project' && e.target.closest('#gForm')) gFillPickers();
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="work"]')) { state.g.catalog = null; state.g.record = null; state.g.form = null; state.g.list = null; return; }
  const b = e.target.closest('[data-g]');
  if (!b) return;
  e.preventDefault();
  const g = state.g, a = b.dataset.g;
  try {
    if (a === 'tab') { g.tab = b.dataset.key; g.record = null; g.form = null; await gRefresh(); return; }
    if (a === 'type') { g.type = b.dataset.key; g.record = null; g.form = null; g.q = ''; g.list = null; render(); await gRefresh(); return; }
    if (a === 'open') { await gOpen(b.dataset.id); return; }
    if (a === 'back') { g.record = null; g.list = null; render(); await gRefresh(); return; }
    if (a === 'cancel') { g.form = null; render(); if (!g.record) await gRefresh(); return; }
    if (a === 'new') { g.form = {type: g.type, values: {}, project_id: null}; render(); return; }
    if (a === 'edit') {
      const r = g.record;
      g.form = {type: r.type_key, record: r, project_id: r.project_id, values: Object.fromEntries(r.values.filter(v => v.raw !== null && v.raw !== undefined).map(v => [v.name, v.raw]))};
      render(); return;
    }
    if (a === 'new-linked') {
      const r = g.record;
      g.form = {type: b.dataset.type, values: {}, project_id: r.project_id, link: {relation: b.dataset.rel, target_id: r.id, label: r.label}};
      render(); return;
    }
    if (a === 'link-add') {
      const box = document.getElementById('gPick-' + b.dataset.rel);
      const opts = await gApi(`/api/graph/targets/${encodeURIComponent(b.dataset.target)}${g.record.project_id ? '?project_id=' + g.record.project_id : ''}`);
      box.innerHTML = opts.length ? `<select class="form-input" id="gPickSel-${esc(b.dataset.rel)}">${opts.map(o => `<option value="${Number(o.id)}">${esc(o.label)}${o.detail ? ' · ' + esc(o.detail) : ''}</option>`).join('')}</select> <button class="btn btn-primary btn-sm" data-g="link-save" data-rel="${esc(b.dataset.rel)}">Propose link</button>` : '<p class="muted">Nothing you can link here yet.</p>';
      return;
    }
    if (a === 'link-save') {
      const sel = document.getElementById('gPickSel-' + b.dataset.rel);
      await gPropose('metadata_edge', {relation_key: b.dataset.rel, source_id: g.record.id, target_id: Number(sel.value)},
        `Link ${g.record.label} (${b.dataset.rel})`);
      return;
    }
    if (a === 'link-remove') {
      const reason = prompt('Why remove this link? (kept in the history)');
      if (!reason) return;
      await gPropose('metadata_edge_remove', {edge_id: Number(b.dataset.edge), reason}, 'Remove a link: ' + reason);
      return;
    }
    if (a === 'report') {
      g.reportKey = b.dataset.key; g.report = null; render();
      g.report = await gApi('/api/graph/reports/' + encodeURIComponent(b.dataset.key) + '/run'); render(); return;
    }
    if (a === 'install') {
      b.disabled = true;
      await gPropose('metadata_pack_install', {pack: b.dataset.key, version: Number(b.dataset.version), sha256: b.dataset.sha},
        'Install the business pack ' + b.dataset.key);
      return;
    }
    if (a === 'adopt') {
      await gPropose('metadata_type_adopt', {type_key: b.dataset.key}, 'Bring the chat-built type ' + b.dataset.key + ' into the universal engine');
      return;
    }
  } catch (err) { b.disabled = false; notify(err.message, true); }
}, true);

document.addEventListener('submit', async e => {
  if (e.target.id !== 'gForm') return;
  e.preventDefault();
  const g = state.g, f = g.form, t = gType(f.type);
  try {
    const values = gReadForm(e.target, t);
    const pid = Number(new FormData(e.target).get('g-project') || 0) || null;
    let r;
    if (f.record) {
      r = await gPropose('metadata_record_update', {type_key: t.key, record_id: f.record.id, expected_version: f.record.current_version,
        project_id: f.record.project_id, values}, `Edit ${t.title} ${f.record.label}`);
    } else {
      const data = {type_key: t.key, project_id: pid, values};
      if (f.link) data.links = [{relation_key: f.link.relation, target_id: f.link.target_id}];
      r = await gPropose('metadata_record', data, `New ${t.title}` + (f.link ? ' for ' + f.link.label : ''));
    }
    g.form = null; render(); if (!g.record) await gRefresh();
  } catch (err) { notify(err.message, true); }
});
