'use strict';
/* StudioOS: the filter bar, the look switcher and the view builder on the Saved views screen (Projects > Saved views).
   - Filter bar: narrow the view you opened ("Match all" or "Match any"). It is only a way of looking: nothing is saved and
     nothing needs approval, and it can only narrow what the view already shows.
   - Look switcher: the same view as a table, a board or a calendar, when its fields allow it.
   - "New view": pick a kind of record, its fields, a filter and a look, preview it on your own data, and save it for yourself
     or send it for approval for everyone. Saving is a ticket (a personal view may approve itself, as it always did).
   - Task boards: "Mark done" opens the usual ticket. Nothing moves until it is approved.
   No inline styles or scripts (strict CSP). Loaded after newwork.js, which calls fbRunPanel / fbBuilderPanel / fbReset. */

Object.assign(state.nw, {fb: {conds: [], mode: 'and', look: null, catalog: null, catalogLoading: false, error: '', moved: {}, busy: false,
  b: {open: false, name: '', type: '', fields: [], look: 'table', conds: [], preview: null, error: '', busy: false}}});

const FB_OPS = {eq: 'is', neq: 'is not', in: 'is one of', contains: 'contains', empty: 'is empty', not_empty: 'is filled in', gt: 'is more than',
  gte: 'is at least', lt: 'is less than', lte: 'is at most', before: 'is before', after: 'is after'};
const FB_NO_VALUE = ['empty', 'not_empty'];
const FB_LOOKS = {table: 'Table', board: 'Board', calendar: 'Calendar'};
const FB_DATES = [['', 'Pick a day…'], ['today', 'Today'], ['today-1', 'Yesterday'], ['today+1', 'Tomorrow'], ['today-7', '7 days ago'], ['today+7', 'In 7 days'],
  ['week_start', 'Start of this week'], ['week_start+6', 'End of this week'], ['month_start', 'Start of this month']];
const FB_PROPOSERS = ['admin', 'manager', 'architect', 'site_engineer', 'accounts'];
const FB_CLOSED = ['done', 'closed', 'cancelled'];
const fbLabel = name => String(name).replace(/[_.]+/g, ' ').replace(/^./, c => c.toUpperCase());
const fbEmpty = () => ({field: '', op: 'eq', value: ''});

function fbReset() { Object.assign(state.nw.fb, {conds: [], mode: 'and', look: null, error: ''}); }

async function fbLoadCatalog() {
  const fb = state.nw.fb;
  if (fb.catalog || fb.catalogLoading) return;
  fb.catalogLoading = true;
  try { fb.catalog = await api('/api/viewspecs/builder'); } catch (err) { fb.catalog = {types: [], operators: {}, looks: []}; }
  fb.catalogLoading = false;
  render();
}

// ------------------------------------------------------------------ turning rows into a filter

function fbValue(c, kind) {
  const raw = String(c.value ?? '').trim();
  if (c.op === 'in') return raw.split(',').map(x => x.trim()).filter(Boolean);
  if (kind === 'number' && raw !== '' && !Number.isNaN(Number(raw))) return Number(raw);
  if (kind === 'boolean') return raw === 'true';
  return raw;
}

function fbReady(c, kinds) {
  if (!c.field || !kinds[c.field]) return false;
  return FB_NO_VALUE.includes(c.op) || String(c.value ?? '').trim() !== '';
}

function fbConditions(conds, kinds) {
  return conds.filter(c => fbReady(c, kinds)).map(c => ({field: c.field, op: c.op, ...(FB_NO_VALUE.includes(c.op) ? {} : {value: fbValue(c, kinds[c.field])})}));
}

function fbQuery(r) {
  const fb = state.nw.fb, kinds = Object.fromEntries((r.fields || []).map(f => [f.name, f.kind]));
  const ready = fbConditions(fb.conds, kinds);
  const q = new URLSearchParams();
  if (ready.length) q.set('filter', JSON.stringify(ready.length === 1 ? ready[0] : {[fb.mode]: ready}));
  if (fb.look) q.set('as', fb.look);
  return q.toString();
}

function fbWords(r) {
  const fb = state.nw.fb, kinds = Object.fromEntries((r.fields || []).map(f => [f.name, f.kind]));
  const parts = fbConditions(fb.conds, kinds).map(c => `${fbLabel(c.field).toLowerCase()} ${FB_OPS[c.op]}${'value' in c ? ' ' + (Array.isArray(c.value) ? c.value.join(', ') : c.value) : ''}`);
  return parts.length ? 'Showing records where ' + parts.join(fb.mode === 'or' ? ' or ' : ' and ') + '.' : '';
}

// ------------------------------------------------------------------ opening and running a view

async function fbRun(key) {
  const fb = state.nw.fb, r = state.nw.ran;
  const query = r && r.fields ? fbQuery(r) : '';
  fb.busy = true;
  try {
    state.nw.ran = await api(`/api/viewspecs/${encodeURIComponent(key)}/run${query ? '?' + query : ''}`);
    fb.error = '';
  } catch (err) {
    if (!state.nw.ran || state.nw.ran.error) state.nw.ran = {name: key, version: '', error: err.message};
    else fb.error = err.message;
  }
  fb.busy = false;
  render();
}

// ------------------------------------------------------------------ the filter bar

function fbValueControl(c, field, attr) {
  if (FB_NO_VALUE.includes(c.op)) return '';
  const v = esc(c.value ?? '');
  if (field.options && field.options.length && c.op !== 'in' && c.op !== 'contains') {
    return `<select class="form-input fb-value" ${attr} data-fb="value" aria-label="Value"><option value="">Choose…</option>${field.options.map(o => `<option value="${esc(o)}"${o === c.value ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
  }
  if (field.kind === 'boolean') {
    return `<select class="form-input fb-value" ${attr} data-fb="value" aria-label="Value"><option value="true"${c.value === 'false' ? '' : ' selected'}>Yes</option><option value="false"${c.value === 'false' ? ' selected' : ''}>No</option></select>`;
  }
  if (field.kind === 'date') {
    return `<span class="fb-date"><input class="form-input fb-value" ${attr} data-fb="value" value="${v}" placeholder="2026-12-31 or today" aria-label="Day" autocomplete="off">` +
      `<select class="form-input fb-shortcut" ${attr} data-fb="shortcut" aria-label="Date shortcut">${FB_DATES.map(([val, label]) => `<option value="${esc(val)}">${esc(label)}</option>`).join('')}</select></span>`;
  }
  return `<input class="form-input fb-value" ${attr} data-fb="value" value="${v}" ${field.kind === 'number' ? 'inputmode="decimal"' : ''} placeholder="${c.op === 'in' ? 'a, b, c' : 'Value'}" aria-label="Value" autocomplete="off">`;
}

function fbRows(conds, fields, ops, scope) {
  const byName = Object.fromEntries(fields.map(f => [f.name, f]));
  return conds.map((c, i) => {
    const attr = `data-scope="${scope}" data-i="${i}"`, field = byName[c.field] || fields[0] || {name: '', kind: 'text'};
    const allowed = (ops[field.kind] || []).filter(o => FB_OPS[o]);
    return `<div class="fb-row"><select class="form-input fb-field" ${attr} data-fb="field" aria-label="Field">${fields.map(f => `<option value="${esc(f.name)}"${f.name === field.name ? ' selected' : ''}>${esc(f.label || fbLabel(f.name))}</option>`).join('')}</select>` +
      `<select class="form-input fb-op" ${attr} data-fb="op" aria-label="Condition">${allowed.map(o => `<option value="${o}"${o === c.op ? ' selected' : ''}>${esc(FB_OPS[o])}</option>`).join('')}</select>` +
      `${fbValueControl(c, field, attr)}<button type="button" class="btn btn-secondary btn-sm" ${attr} data-fb="remove" aria-label="Remove this condition">Remove</button></div>`;
  }).join('');
}

function fbChips(r) {
  const date = (r.fields || []).find(f => f.kind === 'date');
  if (!date) return '';
  const label = /due/.test(date.name) ? 'Due' : fbLabel(date.name);
  const chip = (id, text) => `<button type="button" class="ov-chip fb-chip" data-fb="chip" data-chip="${id}" data-field="${esc(date.name)}">${esc(text)}</button>`;
  return `<div class="ov-chips fb-chips" role="group" aria-label="Quick filters">${chip('overdue', 'Overdue')}${chip('week', label + ' this week')}${chip('next7', label + ' in the next 7 days')}</div>`;
}

const FB_CHIPS = {
  // "Overdue" leaves out finished work when the view shows a status
  overdue: (f, fields) => [{field: f, op: 'before', value: 'today'}, ...(fields.includes('status') ? [{field: 'status', op: 'neq', value: 'done'}] : [])],
  week: f => [{field: f, op: 'after', value: 'week_start-1'}, {field: f, op: 'before', value: 'week_start+7'}],
  next7: f => [{field: f, op: 'after', value: 'today-1'}, {field: f, op: 'before', value: 'today+8'}],
};

function fbBar(r) {
  const fb = state.nw.fb, cat = fb.catalog;
  if (!r.filter_bar || !r.fields || !r.fields.length) return '';          // the owner's switch is off: the view looks as it always did
  if (!cat) { fbLoadCatalog(); return '<p class="muted">Loading the filter bar…</p>'; }
  const fields = r.fields.map(f => ({...f, label: fbLabel(f.name)}));
  const looks = (r.looks || []).length > 1 ? `<div class="ov-chips fb-looks" role="group" aria-label="Show as">${r.looks.map(l => `<button type="button" class="ov-chip" data-fb="look" data-look="${l}" aria-pressed="${l === r.look}">${FB_LOOKS[l]}</button>`).join('')}</div>` : '';
  const rows = fbRows(fb.conds, fields, cat.operators || {}, 'bar');
  const sentence = fbWords(r);
  return `<form class="fb-bar" id="fbForm" data-key="${esc(r.key)}">${looks}${fbChips(r)}` +
    `<div class="fb-rows">${rows}</div>` +
    `<div class="fb-actions"><button type="button" class="btn btn-secondary btn-sm" data-fb="add">+ Add a condition</button>` +
    `${fb.conds.length > 1 ? `<label class="fb-mode">Show records that match <select class="form-input" data-fb="mode" aria-label="Match all or any"><option value="and"${fb.mode === 'and' ? ' selected' : ''}>all conditions</option><option value="or"${fb.mode === 'or' ? ' selected' : ''}>any condition</option></select></label>` : ''}` +
    `<button type="submit" class="btn btn-primary btn-sm"${fb.busy ? ' disabled' : ''}>Apply</button>` +
    `${fb.conds.length ? '<button type="button" class="btn btn-secondary btn-sm" data-fb="clear">Clear</button>' : ''}</div>` +
    `${sentence ? `<p class="muted fb-sentence">${esc(sentence)} ${r.filtered ? pill('Temporary: only for you, only now', 'warn') : ''}</p>` : ''}` +
    `${fb.error ? `<p class="fb-error" role="alert">${esc(fb.error)}</p>` : ''}</form>`;
}

// ------------------------------------------------------------------ the opened view

function fbBoard(s, r) {
  const tasks = r.record_type === 'system.task';
  return `<div class="v-board">${(s.lanes || []).map(l => `<section class="v-lane"><div class="v-lane-head">${esc(l.name)} <span class="muted">${Number(l.count)}</span></div>${l.cards.map(c => {
    const waiting = state.nw.fb.moved[c.id];
    const act = tasks && !FB_CLOSED.includes(String(l.name).toLowerCase())
      ? (waiting ? `<div>${pill('Waiting for approval', 'warn')}</div>` : `<button type="button" class="btn btn-secondary btn-sm" data-fb="mark-done" data-id="${Number(c.id)}">Mark done</button>`) : '';
    return `<div class="fb-card"><button class="v-card cx-link" data-v="open" data-id="${Number(c.id)}">${esc(c.label)}</button>${act}</div>`;
  }).join('')}</section>`).join('')}</div>`;
}

function fbMore(r) {
  const res = r.shown && r.shown.result;
  if (!res || !res.rows || !(res.matched > res.rows.length)) return '';
  return `<p class="muted fb-more">Showing the first ${Number(res.rows.length)} of ${res.incomplete ? 'at least ' : ''}${Number(res.matched)} records. Add a condition to narrow it down.</p>`;
}

function fbRunPanel(r) {
  const shown = (r.shown && r.shown.kind === 'board' ? fbBoard(r.shown, r) : vRender(r.shown)) + fbMore(r);
  return `<section class="panel section-gap fb-panel"><div class="panel-head"><div><div class="panel-title">${esc(r.name)}</div>` +
    `<div class="panel-sub">Version ${Number(r.version)}. Only records you may see are shown.</div></div></div>` +
    `<div class="v-pad">${fbBar(r)}${shown}</div></section>`;
}

// ------------------------------------------------------------------ the builder

function fbType() {
  const b = state.nw.fb.b, types = (state.nw.fb.catalog || {}).types || [];
  return types.find(t => t.key === b.type) || null;
}

function fbSpec() {
  const b = state.nw.fb.b, t = fbType();
  if (!t) throw new Error('Choose what the view shows.');
  const name = b.name.trim();
  if (name.length < 2) throw new Error('Give the view a name.');
  if (!b.fields.length) throw new Error('Tick at least one field to show.');
  const kinds = Object.fromEntries(t.fields.map(f => [f.name, f.kind]));
  const chosen = t.fields.filter(f => b.fields.includes(f.name));
  const item = {record_type: t.key, fields: chosen.map(f => ({field: f.name}))};
  const conds = fbConditions(b.conds, kinds);
  if (conds.length) item.filter = {and: conds};
  const spec = {spec_version: 1, id: `mine.u${Number(state.user.id)}.${name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 28) || 'view'}.${Date.now().toString(36)}`,
    name: name.slice(0, 80), primitive: b.look, source: {items: [item]}, actions: ['open']};
  if (b.look === 'board') {
    const col = chosen.find(f => f.kind === 'select') || chosen.find(f => f.kind === 'text' && /(status|stage)$/.test(f.name));
    if (!col) throw new Error('A board needs a status-like field. Tick one, or choose Table.');
    spec.group = {columns: {field: col.name}};
  }
  if (b.look === 'calendar') {
    const col = chosen.find(f => f.kind === 'date');
    if (!col) throw new Error('A calendar needs a date field. Tick one, or choose Table.');
    spec.layout = {date_field: col.name};
  }
  return spec;
}

function fbSwitchPanel(on) {
  if (state.user?.role !== 'admin') return '';
  return on ? `<p class="muted fb-switch">The filter bar and view builder are on. <button type="button" class="btn btn-secondary btn-sm" data-fb="switch" data-on="false">Turn off</button></p>`
    : `<section class="panel section-gap"><div class="panel-body"><strong>Filter bar and view builder</strong><p class="muted">Off. Turning them on lets people narrow a view, see it as a table, board or calendar, and build their own views. Nothing already saved changes, and you can turn them off again.</p>` +
      `<button type="button" class="btn btn-primary" data-fb="switch" data-on="true">Turn on</button></div></section>`;
}

function fbBuilderPanel() {
  const fb = state.nw.fb, b = fb.b;
  if (!fb.catalog) { fbLoadCatalog(); return ''; }
  if (!fb.catalog.enabled) return fbSwitchPanel(false);
  if (!FB_PROPOSERS.includes(state.user?.role)) return '';
  if (!b.open) return `<div class="section-gap"><button type="button" class="btn btn-primary" data-fb="builder-open">+ New view</button> ${fbSwitchPanel(true)}</div>`;
  const types = fb.catalog.types || [], t = fbType();
  const rows = t ? fbRows(b.conds, t.fields, fb.catalog.operators || {}, 'builder') : '';
  const preview = b.preview ? `<div class="w-sub">${b.preview.valid ? 'What you would see' : 'Not ready yet'}</div>` +
    (b.preview.valid ? (b.preview.shown ? vRender(b.preview.shown) : '<p class="muted">Nothing to show yet.</p>') : `<ul>${b.preview.errors.map(e => `<li>${esc(e.message)}</li>`).join('')}</ul>`) +
    (b.preview.warnings.map(w => `<p class="preview-flag">⚑ ${esc(w)}</p>`).join('')) : '';
  return `<section class="panel section-gap fb-builder"><div class="panel-head"><div><div class="panel-title">New view</div>` +
    `<div class="panel-sub">Pick what to show, add a filter, and check it on your own data before you save it.</div></div></div><form class="panel-body" id="fbBuilder">` +
    `<label class="field"><span>Name</span><input class="form-input" data-fb="b-name" value="${esc(b.name)}" maxlength="80" placeholder="For example: My open tasks" autocomplete="off"></label>` +
    `<label class="field"><span>What does it show?</span><select class="form-input" data-fb="b-type"><option value="">Choose…</option>${types.map(x => `<option value="${esc(x.key)}"${x.key === b.type ? ' selected' : ''}>${esc(x.title)}</option>`).join('')}</select></label>` +
    (t ? `<fieldset class="fb-fields"><legend>Fields to show</legend>${t.fields.map(f => `<label class="fb-check"><input type="checkbox" data-fb="b-field" value="${esc(f.name)}"${b.fields.includes(f.name) ? ' checked' : ''}> ${esc(f.label)}</label>`).join('')}</fieldset>` +
      `<div class="w-sub">Filter</div><div class="fb-rows">${rows}</div><div class="fb-actions"><button type="button" class="btn btn-secondary btn-sm" data-fb="b-add">+ Add a condition</button></div>` +
      `<p class="muted">A saved view shows records that match all of its conditions. To match any, use the filter bar on the view itself.</p>` +
      `<label class="field"><span>Show as</span><select class="form-input" data-fb="b-look">${['table', 'board', 'calendar'].map(l => `<option value="${l}"${l === b.look ? ' selected' : ''}>${FB_LOOKS[l]}</option>`).join('')}</select></label>` : '') +
    `${b.error ? `<p class="fb-error" role="alert">${esc(b.error)}</p>` : ''}${preview}` +
    `<div class="fb-actions"><button type="button" class="btn btn-secondary" data-fb="b-preview"${b.busy ? ' disabled' : ''}>Check it</button>` +
    `<button type="button" class="btn btn-primary" data-fb="b-save" data-scope="user"${b.busy ? ' disabled' : ''}>Save just for me</button>` +
    `${['admin', 'manager'].includes(state.user?.role) ? `<button type="button" class="btn btn-primary" data-fb="b-save" data-scope="system"${b.busy ? ' disabled' : ''}>Send for approval for everyone</button>` : ''}` +
    `<button type="button" class="btn btn-secondary" data-fb="b-close">Cancel</button></div></form></section>`;
}

// ------------------------------------------------------------------ wiring

function fbRowsOf(scope) { return scope === 'builder' ? state.nw.fb.b.conds : state.nw.fb.conds; }

function fbFieldsOf(scope) {
  if (scope === 'builder') return (fbType() || {fields: []}).fields;
  return (state.nw.ran && state.nw.ran.fields) || [];
}

function fbFirstOp(field) {
  const ops = ((state.nw.fb.catalog || {}).operators || {})[field ? field.kind : 'text'] || [];
  return ops.includes('eq') ? 'eq' : (ops[0] || 'eq');
}

document.addEventListener('change', e => {
  const el = e.target.closest('[data-fb]');
  if (!el) return;
  const fb = state.nw.fb, b = fb.b, kind = el.dataset.fb, scope = el.dataset.scope, i = Number(el.dataset.i);
  if (['field', 'op', 'value', 'shortcut'].includes(kind)) {
    const rows = fbRowsOf(scope), c = rows[i];
    if (!c) return;
    if (kind === 'field') {
      const f = fbFieldsOf(scope).find(x => x.name === el.value);
      Object.assign(c, {field: el.value, op: fbFirstOp(f), value: ''});
      render();
    } else if (kind === 'op') { c.op = el.value; if (FB_NO_VALUE.includes(c.op)) c.value = ''; render(); }
    else if (kind === 'shortcut') { if (el.value) { c.value = el.value; render(); } }
    else c.value = el.value;
  } else if (kind === 'mode') { fb.mode = el.value; }
  else if (kind === 'b-name') { b.name = el.value; }
  else if (kind === 'b-type') { Object.assign(b, {type: el.value, fields: [], conds: [], preview: null, error: ''}); const t = fbType(); b.fields = t ? t.fields.slice(0, 3).map(f => f.name) : []; render(); }
  else if (kind === 'b-look') { b.look = el.value; b.preview = null; }
  else if (kind === 'b-field') { b.fields = [...document.querySelectorAll('[data-fb="b-field"]:checked')].map(x => x.value); b.preview = null; }
});

document.addEventListener('submit', e => {
  if (e.target.id === 'fbForm') { e.preventDefault(); fbRun(e.target.dataset.key); }
  if (e.target.id === 'fbBuilder') e.preventDefault();
});

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-fb]');
  if (!b || ['SELECT', 'INPUT'].includes(b.tagName)) return;
  const fb = state.nw.fb, bd = fb.b, kind = b.dataset.fb, r = state.nw.ran, key = r && r.key;
  try {
    if (kind === 'look') { fb.look = b.dataset.look; await fbRun(key); }
    else if (kind === 'add') { const f = (r.fields || [])[0]; fb.conds.push({field: f ? f.name : '', op: fbFirstOp(f), value: ''}); render(); }
    else if (kind === 'remove') { fbRowsOf(b.dataset.scope).splice(Number(b.dataset.i), 1); render(); }
    else if (kind === 'clear') { fb.conds = []; fb.mode = 'and'; await fbRun(key); }
    else if (kind === 'chip') { fb.conds = FB_CHIPS[b.dataset.chip](b.dataset.field, (r.fields || []).map(f => f.name)).map(c => ({...c})); fb.mode = 'and'; await fbRun(key); }
    else if (kind === 'mark-done') {
      b.disabled = true;
      const t = await api(`/api/tasks/${Number(b.dataset.id)}/complete`, {method: 'PATCH', body: '{}'});
      fb.moved[Number(b.dataset.id)] = t.ticket_id;
      notify(`Ticket #${t.ticket_id} opened. The task moves to done once it is approved.`);
      render();
    } else if (kind === 'switch') {
      const s = await api('/api/viewspecs/builder/switch', {method: 'POST', body: JSON.stringify({on: b.dataset.on === 'true'})});
      notify(s.enabled ? 'The filter bar and view builder are on.' : 'The filter bar and view builder are off.');
      fb.catalog = null; fbReset();
      if (key) await fbRun(key); else render();
    } else if (kind === 'builder-open') { bd.open = true; render(); }
    else if (kind === 'b-close') { Object.assign(bd, {open: false, name: '', type: '', fields: [], look: 'table', conds: [], preview: null, error: ''}); render(); }
    else if (kind === 'b-add') { const t = fbType(), f = t && t.fields[0]; bd.conds.push({field: f ? f.name : '', op: fbFirstOp(f), value: ''}); render(); }
    else if (kind === 'b-preview' || kind === 'b-save') {
      bd.error = '';
      let spec;
      try { spec = fbSpec(); } catch (err) { bd.error = err.message; bd.preview = null; render(); return; }
      bd.busy = true;
      if (kind === 'b-preview') {
        bd.preview = await api('/api/viewspecs/preview', {method: 'POST', body: JSON.stringify({spec})});
      } else {
        const d = await api('/api/viewspecs/propose', {method: 'POST', body: JSON.stringify({kind: 'view_create', data: {spec, scope: b.dataset.scope}})});
        notify(d.auto_approved ? 'Saved. Your view is ready.' : `Ticket #${d.ticket_id} opened. The view appears once it is approved.`);
        Object.assign(bd, {open: false, name: '', type: '', fields: [], look: 'table', conds: [], preview: null});
        state.nw.views = null;
      }
      bd.busy = false;
      render();
    }
  } catch (err) {
    bd.busy = false;
    if (kind === 'mark-done') b.disabled = false;
    if (kind.startsWith('b-')) { bd.error = err.message; render(); } else notify(err.message, true);
  }
});
