'use strict';
/* StudioOS v0.14.0 "Inbox": photos, PDFs, spreadsheets, WhatsApp and e-mail messages and voice notes
   arrive here first. Read text is shown with the words the reader was unsure of; "Make a draft"
   opens the usual draft card (a ticket); spreadsheets get column matching, 20 sample rows, the rows
   that cannot be read, and one ticket per import. Unknown senders wait in quarantine.
   Loaded after app.js and graph.js. */

Object.assign(state, {ib: {items: null, open: null, table: null, filter: '', types: null}});

const ibApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const IB_STATUS = {new: 'New', drafted: 'Draft made', quarantined: 'Unknown sender', rejected: 'Rejected', table: 'Spreadsheet',
  needs_reading: 'Needs reading by hand', needs_listening: 'Voice note: needs listening', imported: 'Imported', kept: 'Kept'};
const IB_SOURCE = {upload: 'Uploaded', whatsapp: 'WhatsApp', email: 'E-mail', voice: 'Voice'};

async function ibLoad() {
  const [list, cat] = await Promise.all([ibApi('/api/intake/items' + (state.ib.filter ? '?status=' + encodeURIComponent(state.ib.filter) : '')),
    state.ib.types ? Promise.resolve(null) : ibApi('/api/graph/catalog')]);
  state.ib.items = list.items;
  if (cat) state.ib.types = cat.types || [];
}

function ibMarkText(text, unsure) {
  const bad = new Set((unsure || []).map(w => w.toLowerCase()));
  return esc(text).split(/(\s+)/).map(w => bad.has(w.trim().toLowerCase()) && w.trim() ? `<mark class="ib-unsure">${w}</mark>` : w).join('');
}

function ibTablePanel(it) {
  const t = state.ib.table;
  if (!t) return `<div class="ib-actions"><label>Into<select class="form-input" id="ibTableType"><option value="">A new kind of record</option>${(state.ib.types || []).map(x =>
    `<option value="${esc(x.key)}">${esc(x.title)}</option>`).join('')}</select></label> <button class="btn btn-secondary btn-sm" data-ib="table">Match columns</button></div>`;
  if (t.new_type) return `<p><strong>New kind of record: ${esc(t.new_type.title)}</strong> (${Number(t.rows)} rows)</p><ul class="rs-impact">${t.new_type.fields.map(f =>
    `<li>${esc(f.meaning)} → ${esc(f.type)}${f.options ? ' (' + esc(f.options.join(', ')) + ')' : ''}</li>`).join('')}</ul>
    <button class="btn btn-primary btn-sm" data-ib="import-new">Propose the new kind and import</button>`;
  const fieldOpts = sel => `<option value="">(not imported)</option>` + t.fields.map(f => `<option value="${esc(f.name)}" ${sel === f.name ? 'selected' : ''}>${esc(f.meaning)}${f.required ? ' *' : ''}</option>`).join('');
  return `<div class="ib-map">${t.headers.map((h, i) => `<label>${esc(h)}<select class="form-input" data-ib-col="${i}">${fieldOpts(t.mapping[i])}</select></label>`).join('')}</div>
    <button class="btn btn-secondary btn-sm" data-ib="rematch">Check again</button> <button class="btn btn-secondary btn-sm" data-ib="table-reset">Choose another kind</button>
    <p class="muted">${Number(t.to_import)} row(s) to import of ${Number(t.total)}; ${Number(t.already_imported)} already imported; ${t.unreadable.length} cannot be read.</p>
    ${t.sample.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr>${Object.keys(t.sample[0].values).map(k => `<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${t.sample.map(r =>
      `<tr>${Object.keys(t.sample[0].values).map(k => `<td>${esc(typeof r.values[k] === 'object' ? JSON.stringify(r.values[k]) : r.values[k] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
    ${t.unreadable.length ? `<details class="rs-bad" open><summary>Rows that cannot be read</summary><ul>${t.unreadable.slice(0, 50).map(b => `<li>Row ${Number(b.row)}: ${esc(b.problems.join('; '))}</li>`).join('')}</ul></details>` : ''}
    <button class="btn btn-primary btn-sm" data-ib="import" ${t.to_import ? '' : 'disabled'}>Import ${Number(t.to_import)} row(s): one ticket</button>`;
}

function ibOpenPanel() {
  const it = state.ib.open;
  if (!it) return '';
  const canDraft = it.status === 'new' && it.text;
  return `<section class="panel ib-open"><div class="panel-head"><div><div class="panel-title">${esc(IB_SOURCE[it.source] || it.source)} · ${esc(it.filename || 'message')}</div>
    <div class="panel-sub">${esc(IB_STATUS[it.status] || it.status)} · from ${esc(it.sender || '—')}${it.scan ? ' · scan: ' + esc(it.scan === 'not_scanned' ? 'not scanned (no scanner installed)' : it.scan) : ''}</div></div>
    <button class="btn btn-secondary btn-sm" data-ib="close">Close</button></div><div class="v-pad">
    ${it.has_file ? `<p><a class="cx-link" href="/api/intake/items/${Number(it.id)}/file" download>Download the original</a></p>` : ''}
    ${it.text ? `<div class="ib-text">${ibMarkText(it.text, it.unsure_words)}</div>${(it.unsure_words || []).length ? '<p class="muted">Highlighted words were hard to read: check them on the draft.</p>' : ''}` : ''}
    ${it.status === 'quarantined' ? `<div class="notice warn"><span>This sender is not known as staff or a contact. Nothing has been read into StudioOS.</span></div>
      ${isAdmin() ? '<button class="btn btn-secondary btn-sm" data-ib="release">It is genuine: move to inbox</button> ' : ''}<button class="btn btn-secondary btn-sm" data-ib="reject">Reject</button>` : ''}
    ${canDraft ? `<div class="ib-actions"><label>Make a draft of<select class="form-input" id="ibType">${(state.ib.types || []).map(x => `<option value="${esc(x.key)}">${esc(x.title)}</option>`).join('')}</select></label>
      <button class="btn btn-primary btn-sm" data-ib="draft">Make a draft</button></div>` : ''}
    ${it.status === 'table' ? ibTablePanel(it) : ''}
    ${it.ticket_id ? `<p class="muted">Ticket #${Number(it.ticket_id)} is waiting for approval.</p>` : ''}</div></section>`;
}

function ibView() {
  if (!state.ib.items) { ibLoad().then(render).catch(err => notify(err.message, true)); return head('Inbox', 'Loading…') + '<div class="loading">Loading…</div>'; }
  const filters = [['', 'All'], ['new', 'New'], ['table', 'Spreadsheets'], ['quarantined', 'Unknown senders'], ['needs_reading', 'Needs reading']];
  return head('Inbox', 'Photos, PDFs, spreadsheets, WhatsApp and e-mail arrive here first. Nothing is saved until a ticket is approved.') +
    (state.user?.role !== 'viewer' ? `<section class="panel v-pad"><label class="btn btn-primary" for="ibFile">Send a photo, PDF or spreadsheet</label>
      <input class="newtype-file-input" type="file" id="ibFile" accept="image/jpeg,image/png,application/pdf,.csv,.xlsx,audio/*"><p class="muted">Up to 8 MB. Programs, scripts and macros are refused.</p></section>` : '') +
    ibOpenPanel() +
    `<div class="g-tabs">${filters.map(([k, l]) => `<button class="g-tab ${state.ib.filter === k ? 'active' : ''}" data-ib="filter" data-key="${k}">${esc(l)}</button>`).join('')}</div>
    <section class="panel">${state.ib.items.length ? `<ul class="rs-history">${state.ib.items.map(x => `<li><span><strong>${esc(IB_SOURCE[x.source] || x.source)}</strong> · ${esc(x.filename || x.text.slice(0, 60) || 'message')}
      <br><span class="muted">${esc(IB_STATUS[x.status] || x.status)} · ${esc(x.sender || '')}</span></span><button class="btn btn-secondary btn-sm" data-ib="open" data-id="${Number(x.id)}">Open</button></li>`).join('')}</ul>`
      : '<p class="muted v-pad">Nothing here.</p>'}</section>`;
}

const _ibRender = render;
render = function () {
  if (state.view === 'inbox') {
    document.body.classList.remove('chat-mode');
    updateIdentity();
    $('mainContent').innerHTML = ibView();
    $('breadcrumb').textContent = 'Inbox';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _ibRender();
};

function ibMapping() {
  const m = {};
  document.querySelectorAll('[data-ib-col]').forEach(s => { if (s.value) m[s.dataset.ibCol] = s.value; });
  return m;
}

document.addEventListener('change', async e => {
  if (e.target.id !== 'ibFile' || !e.target.files.length) return;
  const f = e.target.files[0];
  if (f.size > 8 * 1024 * 1024) { notify('Files up to 8 MB', true); return; }
  try {
    const b64 = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1] || ''); r.onerror = bad; r.readAsDataURL(f); });
    state.ib.open = await ibApi('/api/intake/upload', {filename: f.name, base64: b64});
    state.ib.table = null; state.ib.items = null; notify('Received. Nothing is saved until a ticket is approved.'); render();
  } catch (err) { notify(err.message, true); }
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="inbox"]')) { state.ib.items = null; state.ib.open = null; state.ib.table = null; return; }
  const b = e.target.closest('[data-ib]');
  if (!b) return;
  e.preventDefault();
  const ib = state.ib, it = ib.open, a = b.dataset.ib;
  try {
    if (a === 'filter') { ib.filter = b.dataset.key; ib.items = null; render(); return; }
    if (a === 'open') { ib.open = await ibApi('/api/intake/items/' + Number(b.dataset.id)); ib.table = null; render(); return; }
    if (a === 'close') { ib.open = null; ib.table = null; render(); return; }
    if (a === 'table-reset') { ib.table = null; render(); return; }
    b.disabled = true;
    if (a === 'draft') {
      const r = await ibApi(`/api/intake/items/${it.id}/draft`, {type_key: $('ibType').value});
      notify(`Ticket #${r.ticket_id} opened.${r.low_confidence.length ? ' Check the highlighted details.' : ''}`);
      ib.open = await ibApi('/api/intake/items/' + it.id); ib.items = null;
    } else if (a === 'table') {
      const tk = $('ibTableType').value || null;
      ib.table = await ibApi(`/api/intake/items/${it.id}/table`, {type_key: tk}); ib.table.type_key = tk;
    } else if (a === 'rematch') {
      const tk = ib.table.type_key;
      ib.table = await ibApi(`/api/intake/items/${it.id}/table`, {type_key: tk, mapping: ibMapping()}); ib.table.type_key = tk;
    } else if (a === 'import') {
      const r = await ibApi(`/api/intake/items/${it.id}/import`, {type_key: ib.table.type_key, mapping: ibMapping()});
      notify(`Ticket #${r.ticket_id} opened for the import.`); ib.open = await ibApi('/api/intake/items/' + it.id); ib.table = null; ib.items = null;
    } else if (a === 'import-new') {
      const r = await ibApi(`/api/intake/items/${it.id}/import`, {new_type: ib.table.new_type});
      notify(`Ticket #${r.ticket_id} opened: the new kind of record and the import.`); ib.table = null; ib.items = null;
    } else if (a === 'release' || a === 'reject') {
      ib.open = await ibApi(`/api/intake/items/${it.id}/${a}`, {}); ib.items = null;
    }
    render();
  } catch (err) { b.disabled = false; notify(err.message, true); }
});
