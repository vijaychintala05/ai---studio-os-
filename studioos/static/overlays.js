'use strict';
/* StudioOS overlays (App Flows map): Search, New, Filter and sort, Scope picker, Quick peek and Preview as role. Each slides up over the
   current screen and closes with Back, Escape, a tap outside or a swipe down, leaving you exactly where you were. The scope strip says
   which project the app is narrowed to; chat and search start narrowed to it, and one tap widens to all projects.
   No inline styles (strict CSP). Loaded after app.js, chat.js and projectpage.js. */

Object.assign(state, {scope: null, ov: null, ovFilter: {status: 'all', mine: false, due: 'all', sort: 'due'}});

function ovLoadScope() {
  if (!state.user) return;
  try {
    const id = Number(sessionStorage.getItem('studioos-scope:' + state.user.username));
    const project = state.projects.find(p => p.id === id);
    if (project) state.scope = {project_id: project.id, name: project.name};
  } catch (e) { /* no stored scope */ }
}
function ovSaveScope() {
  if (!state.user) return;
  try { sessionStorage.setItem('studioos-scope:' + state.user.username, String(state.scope?.project_id || '')); } catch (e) { /* kept for this page only */ }
}
function ovSetScope(project) {
  state.scope = project ? {project_id: Number(project.id), name: project.name} : null;
  ovSaveScope();
}

const OV_TITLES = {search: 'Search', scope: 'Where are you working?', filter: 'Filter and sort', newform: 'New', peek: 'Quick look', role: 'Preview as role'};
const OV_ROLES = ['admin', 'manager', 'architect', 'site_engineer', 'accounts'];
const OV_NEW = [
  {action: 'task', label: 'Task', roles: ['admin', 'manager', 'architect']},
  {action: 'site', label: 'Site report', roles: ['admin', 'manager', 'site_engineer']},
  {action: 'siteexpense', label: 'Site expense', roles: ['admin', 'manager', 'site_engineer']},
  {action: 'cost', label: 'Cost or purchase', roles: ['admin', 'manager', 'accounts']},
  {action: 'payment', label: 'Record payment', roles: ['admin', 'manager', 'accounts']},
  {action: 'project', label: 'Project', roles: ['admin', 'manager']},
];
const ovProjects = () => (state.budgets || []).concat(state.projects || []).filter((p, i, a) => a.findIndex(x => x.id === p.id) === i);

// ------------------------------------------------------------------ the sheet
function ovRoot() {
  let r = document.getElementById('ovRoot');
  if (!r) {
    r = document.createElement('div');
    r.id = 'ovRoot';
    r.className = 'ov-root';
    r.hidden = true;
    document.body.appendChild(r);
  }
  return r;
}

function ovBody(kind) {
  const o = state.ov;
  if (kind === 'search') {
    const qTrim = String(o.q || '').trim();
    const groups = o.results ? Object.entries(o.results.groups).map(([g, rows]) => `<div class="w-sub">${esc(g)}</div>` + rows.map(x =>
      `<button type="button" class="ov-row" data-ov="peek" data-group="${esc(g)}" data-i="${rows.indexOf(x)}"><strong>${esc(x.title)}</strong><span class="muted">${esc(x.detail || '')}</span></button>`).join('')).join('') : '';
    const screens = typeof ovScreenRows === 'function' ? ovScreenRows(o.q) : '';          // screens that match, from the menu map (nav.js)
    const hint = qTrim.length === 1 ? '<p class="muted">Type at least 2 characters to search.</p>' : '';
    const loading = o.searching ? '<p class="muted" role="status">Searching…</p>' : '';
    const none = !o.searching && !screens && o.results && !o.results.total ? `<p class="muted">Nothing found${state.scope ? ' in ' + esc(state.scope.name) : ''}.</p>` : '';
    return `<label class="ov-field"><span class="muted">${state.scope ? 'Searching in ' + esc(state.scope.name) : 'Searching everything you can see'}</span>` +
      `<input class="form-input" id="ovQuery" type="search" inputmode="search" autocomplete="off" maxlength="80" placeholder="A screen, project, task, snag, file or contact" aria-label="Search" value="${esc(o.q || '')}"></label>` +
      `<div id="ovResults">${hint}${screens}${loading}${groups}${none}</div>`;
  }
  if (kind === 'scope') {
    const list = ovProjects().map(p => `<button type="button" class="ov-row${state.scope && state.scope.project_id === p.id ? ' current' : ''}" data-ov="pick-scope" data-id="${Number(p.id)}"><strong>${esc(p.name)}</strong><span class="muted">${esc(p.stage || '')}</span></button>`).join('');
    return `<button type="button" class="ov-row${state.scope ? '' : ' current'}" data-ov="pick-scope" data-id="0"><strong>General</strong><span class="muted">Everything your role allows</span></button>${list}`;
  }
  if (kind === 'filter') {
    const f = state.ovFilter;
    const dueOpts = [['all', 'Any due date'], ['overdue', 'Overdue'], ['next7', 'Next 7 days'], ['nodate', 'No due date']];
    return `<p class="muted">For the Tasks list. Saved views have their own filters.</p>` +
      `<div class="w-sub">Show</div><div class="ov-chips">${['all', 'open', 'done'].map(s => `<button type="button" class="ov-chip" data-ov="filter" data-key="status" data-value="${s}" aria-pressed="${f.status === s}">${s === 'all' ? 'All' : s === 'open' ? 'Open' : 'Done'}</button>`).join('')}` +
      `<button type="button" class="ov-chip" data-ov="filter" data-key="mine" data-value="${!f.mine}" aria-pressed="${f.mine}">Only mine</button></div>` +
      `<div class="w-sub">Due date</div><div class="ov-chips">${dueOpts.map(([k, lbl]) => `<button type="button" class="ov-chip" data-ov="filter" data-key="due" data-value="${k}" aria-pressed="${(f.due || 'all') === k}">${lbl}</button>`).join('')}</div>` +
      `<div class="w-sub">Sort by</div><div class="ov-chips">${['due', 'title'].map(s => `<button type="button" class="ov-chip" data-ov="filter" data-key="sort" data-value="${s}" aria-pressed="${f.sort === s}">${s === 'due' ? 'Due date' : 'Name'}</button>`).join('')}</div>` +
      `<button type="button" class="btn btn-secondary" data-ov="filter-reset">Clear</button>`;
  }
  if (kind === 'newform') {
    const mine = OV_NEW.filter(k => k.roles.includes(state.user?.role));
    return (state.scope ? `<p class="muted">Starts with ${esc(state.scope.name)} chosen.</p>` : '') +
      (mine.length ? mine.map(k => `<button type="button" class="ov-row" data-ov="new" data-action="${k.action}"><strong>${esc(k.label)}</strong></button>`).join('') : '<p class="muted">Your role has read-only access and cannot add new records.</p>');
  }
  if (kind === 'peek') {
    const x = o.item;
    if (!x) return '';
    const canDone = x.type === 'task' && ['admin', 'manager', 'architect', 'site_engineer'].includes(state.user?.role);
    const backBtn = o.back ? '<p><button type="button" class="btn btn-secondary btn-sm" data-ov="back">← Back to search</button></p>' : '';
    return `${backBtn}<h3>${esc(x.title)}</h3><p class="muted">${esc(x.detail || '')}</p>` +
      `<div class="ov-actions"><button type="button" class="btn btn-primary" data-ov="open-item">Open</button>${canDone ? '<button type="button" class="btn btn-secondary" data-ov="done-item">Mark done</button>' : ''}</div>`;
  }
  if (kind === 'role') {
    const sections = o.sections ? `<ul>${o.sections.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : '';
    return `<p class="muted">See ${state.scope ? esc(state.scope.name) : 'a project'} as another role would. Nothing is changed.</p>` +
      `<div class="ov-chips">${OV_ROLES.map(r => `<button type="button" class="ov-chip" data-ov="role" data-value="${r}" aria-pressed="${o.role === r}">${esc(r.replace('_', ' '))}</button>`).join('')}</div>` +
      (state.scope ? sections || '<p class="muted">Choose a role.</p>' : '<p class="muted">Choose a project first (the scope button at the top).</p>');
  }
  return '';
}

function ovDraw() {
  const r = ovRoot();
  if (!state.ov) { r.hidden = true; r.innerHTML = ''; return; }
  const k = state.ov.kind;
  r.hidden = false;
  r.innerHTML = `<div class="ov-backdrop" data-ov="close"></div><section class="ov-sheet" role="dialog" aria-modal="true" aria-label="${esc(OV_TITLES[k])}">` +
    `<div class="ov-handle" aria-hidden="true"></div><div class="ov-head"><h2>${esc(OV_TITLES[k])}</h2><button type="button" class="icon-btn" data-ov="close" aria-label="Close" title="Close">${icon('close', 24)}</button></div>` +
    `<div class="ov-body">${ovBody(k)}</div></section>`;
  const q = document.getElementById('ovQuery');
  if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}

function ovOpen(kind, extra) {
  if (!state.user || state.mustSetup2fa) return;
  if (!state.ov) state.ovReturnFocus = document.activeElement;
  state.ov = Object.assign({kind}, extra || {});
  try { history.pushState({ov: kind}, ''); } catch (e) { /* history may be blocked */ }
  ovDraw();
  document.querySelector('.shell').inert = true;
  if (!ovRoot().contains(document.activeElement)) ovRoot().querySelector('.ov-head button')?.focus();
}
function ovClose(fromPop) {
  if (!state.ov) return;
  state.ov = null;
  ovDraw();
  document.querySelector('.shell').inert = !state.user;
  if (state.ovReturnFocus?.isConnected) state.ovReturnFocus.focus();
  state.ovReturnFocus = null;
  if (!fromPop) { try { if (history.state && history.state.ov) history.back(); } catch (e) { /* ignore */ } }
}
window.addEventListener('popstate', () => { if (state.ov) { ovClose(true); if (state.flow) state.flow.ovPop = true; } });
document.addEventListener('keydown', e => {
  if (e.key === 'Tab' && state.ov) {
    const controls = [...ovRoot().querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]')].filter(node => node.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if ((e.shiftKey && document.activeElement === first) || (!e.shiftKey && document.activeElement === last)) {
      e.preventDefault();
      (e.shiftKey ? last : first)?.focus();
    }
  } else if (state.ov && state.ov.kind === 'search' && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || (e.key === 'Enter' && document.activeElement?.id === 'ovQuery'))) {
    const rows = [...ovRoot().querySelectorAll('#ovResults .ov-row')];
    if (!rows.length) return;
    if (e.key === 'Enter') { e.preventDefault(); rows[0].click(); return; }
    e.preventDefault();
    const idx = rows.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') rows[idx < rows.length - 1 ? idx + 1 : 0].focus();
    else if (idx <= 0) document.getElementById('ovQuery')?.focus();
    else rows[idx - 1].focus();
  } else if (e.key === 'Escape') ovClose();
  else if (e.key === '/' && !state.ov && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '') && state.user) { e.preventDefault(); ovOpen('search'); }
});
(function swipeDown() {
  let y0 = null;
  document.addEventListener('touchstart', e => { y0 = e.target.closest('.ov-head,.ov-handle') ? e.touches[0].clientY : null; }, {passive: true});
  document.addEventListener('touchend', e => { if (y0 !== null && e.changedTouches[0].clientY - y0 > 90) ovClose(); y0 = null; }, {passive: true});
}());

// ------------------------------------------------------------------ search
let ovTimer = null;
async function ovRunSearch(q) {
  if (!state.ov || state.ov.kind !== 'search') return;
  state.ov.q = q;
  if (q.trim().length < 2) { state.ov.results = null; state.ov.searching = false; ovPaintResults(); return; }
  state.ov.searching = true;
  ovPaintResults();
  const qs = new URLSearchParams({q: q.trim()});
  if (state.scope) qs.set('project_id', state.scope.project_id);
  try {
    const r = await api('/api/search?' + qs.toString());
    if (state.ov && state.ov.kind === 'search' && state.ov.q === q) { state.ov.results = r; state.ov.searching = false; ovPaintResults(); }
  } catch (err) {
    if (state.ov && state.ov.kind === 'search' && state.ov.q === q) { state.ov.searching = false; ovPaintResults(); }
    notify(err.message, true);
  }
}
function ovPaintResults() {
  const box = document.getElementById('ovResults');
  if (!box) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = ovBody('search');
  const fresh = tmp.querySelector('#ovResults');
  if (fresh) box.innerHTML = fresh.innerHTML;
}
document.addEventListener('input', e => {
  if (e.target.id !== 'ovQuery') return;
  clearTimeout(ovTimer);
  const v = e.target.value;
  if (state.ov) { state.ov.q = v; ovPaintResults(); }          // matching screens show at once; records follow from the server
  ovTimer = setTimeout(() => ovRunSearch(v), 250);
});

// ------------------------------------------------------------------ the task filter (applies to the Tasks screen)
function filterTaskRows(orig, f, me, todayIso) {
  const today = todayIso || new Date().toISOString().slice(0, 10);
  const plus7Date = new Date(today + 'T00:00:00Z');
  plus7Date.setUTCDate(plus7Date.getUTCDate() + 7);
  const plus7 = plus7Date.toISOString().slice(0, 10);
  const dueMode = f.due || 'all';
  let rows = orig.filter(t => {
    if (f.status !== 'all' && (f.status === 'done' ? t.status !== 'done' : t.status === 'done')) return false;
    if (f.mine && !me.has(t.assignee)) return false;
    const d = t.due_date ? String(t.due_date).slice(0, 10) : '';
    if (dueMode === 'overdue') return Boolean(d && d < today && t.status !== 'done');
    if (dueMode === 'next7') return Boolean(d && d >= today && d <= plus7);
    if (dueMode === 'nodate') return !d;
    return true;
  });
  return rows.slice().sort((a, b) => f.sort === 'title' ? String(a.title).localeCompare(String(b.title)) : String(a.due_date || '9999').localeCompare(String(b.due_date || '9999')));
}
const _ovRender = render;
render = function () {
  const f = state.ovFilter, orig = state.tasks;
  const active = f.status !== 'all' || f.mine || (f.due && f.due !== 'all') || f.sort !== 'due';
  if (state.view === 'tasks' && Array.isArray(orig) && active) {
    const me = new Set([state.user?.display_name, state.user?.username].filter(Boolean));
    const rows = filterTaskRows(orig, f, me);
    state.tasks = rows;
    state.ovFilterActive = true;
    state.ovTotalTasks = orig.length;
    try { _ovRender(); } finally { state.tasks = orig; state.ovFilterActive = false; state.ovTotalTasks = 0; }
    const parts = [];
    if (f.status !== 'all') parts.push(f.status === 'open' ? 'Open only' : 'Done only');
    if (f.mine) parts.push('Only mine');
    if (f.due === 'overdue') parts.push('Overdue');
    else if (f.due === 'next7') parts.push('Due in next 7 days');
    else if (f.due === 'nodate') parts.push('No due date');
    if (f.sort !== 'due') parts.push('Sorted by Name');
    const panel = document.querySelector('#mainContent .panel');
    if (panel && !document.getElementById('taskFilterBar')) {
      panel.insertAdjacentHTML('beforebegin', `<div class="notice" id="taskFilterBar"><span>Filters active: <strong>${esc(parts.join(' · '))}</strong> (${rows.length} of ${orig.length})</span><button type="button" class="btn btn-secondary btn-sm" data-ov="filter-reset">Clear</button></div>`);
    }
  } else _ovRender();
  ovChrome();
  const target = state.ovRecord;
  if (target?.view === state.view) {
    const record = document.querySelector(`[data-record-type="${target.type}"][data-record-id="${Number(target.id)}"]`);
    if (record) {
      state.ovRecord = null;
      record.focus({preventScroll: true});
      queueMicrotask(() => { if (record.isConnected) record.scrollIntoView({block: 'center'}); });
    }
  }
};

// ------------------------------------------------------------------ the strip, and the buttons in the top bar
function ovChrome() {
  if (!state.user) return;
  let strip = document.getElementById('scopeStrip');
  const main = document.getElementById('mainContent');
  if (!strip && main) {
    strip = document.createElement('div');
    strip.id = 'scopeStrip';
    strip.className = 'scope-strip';
    main.parentNode.insertBefore(strip, main);
  }
  if (strip) {
    strip.hidden = !state.scope || state.view === 'project';          // the project page has its own strip
    strip.innerHTML = state.scope ? `<span>Narrowed to <strong>${esc(state.scope.name)}</strong></span><button type="button" class="btn btn-secondary btn-sm" data-ov="widen">All projects</button>` : '';
  }
  const tr = document.querySelector('.top-right');
  if (tr && !document.getElementById('ovButtons')) {
    const box = document.createElement('span');
    box.id = 'ovButtons';
    box.className = 'ov-buttons';
    box.innerHTML = `<button type="button" class="icon-btn" data-ov="open" data-kind="search" aria-label="Search" title="Search (press /)">${icon('search', 24)}</button>` +
      `<button type="button" class="icon-btn" data-ov="open" data-kind="scope" aria-label="Choose project" title="Choose project">${icon('scope', 24)}</button>` +
      `<button type="button" class="icon-btn" data-ov="open" data-kind="newform" aria-label="New" title="New">${icon('plus', 24)}</button>`;
    tr.insertBefore(box, tr.firstChild);
  }
  const box = document.getElementById('ovButtons');
  if (box) {
    const canAdd = OV_NEW.some(k => k.roles.includes(state.user.role));
    const newBtn = box.querySelector('[data-kind="newform"]');
    if (newBtn) newBtn.hidden = !canAdd;
    let extra = box.querySelector('[data-kind="filter"]');
    if (state.view === 'tasks' && !extra) {
      box.insertAdjacentHTML('beforeend', `<button type="button" class="icon-btn" data-ov="open" data-kind="filter" aria-label="Filter and sort" title="Filter and sort">${icon('filter', 24)}</button>`);
      extra = box.querySelector('[data-kind="filter"]');
    }
    if (state.view === 'tasks' && extra) {
      const f = state.ovFilter || {};
      const on = f.status !== 'all' || f.mine || (f.due && f.due !== 'all') || f.sort !== 'due';
      extra.classList.toggle('active', on);
      extra.setAttribute('aria-pressed', String(on));
    }
    if (state.view !== 'tasks' && extra) extra.remove();
    const preview = box.querySelector('[data-kind="role"]');
    if (state.user.role === 'admin' && !preview) box.insertAdjacentHTML('beforeend', `<button type="button" class="icon-btn" data-ov="open" data-kind="role" aria-label="Preview as role" title="Preview as role">${icon('eye', 24)}</button>`);
    if (state.user.role !== 'admin' && preview) preview.remove();
  }
}

// ------------------------------------------------------------------ clicks
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-ov]');
  if (!b) {
    // opening a project page narrows the app to that project
    return;
  }
  const a = b.dataset.ov;
  if (a === 'open') { ovOpen(b.dataset.kind); return; }
  if (a === 'close') { ovClose(); return; }
  if (a === 'widen') { ovSetScope(null); render(); return; }
  if (a === 'pick-scope') {
    const p = ovProjects().find(x => x.id === Number(b.dataset.id));
    ovSetScope(p || null);
    ovClose();
    render();
    return;
  }
  if (a === 'filter') {
    const v = b.dataset.value;
    state.ovFilter[b.dataset.key] = v === 'true' ? true : v === 'false' ? false : v;
    ovDraw();
    render();
    return;
  }
  if (a === 'back' && state.ov?.back) { state.ov = state.ov.back; ovDraw(); return; }
  if (a === 'filter-reset') { state.ovFilter = {status: 'all', mine: false, due: 'all', sort: 'due'}; ovDraw(); render(); return; }
  if (a === 'new') {
    const action = b.dataset.action;
    const projectId = state.scope ? state.scope.project_id : null;
    ovClose();
    if (typeof modal === 'function') {
      modal(action, projectId ? {projectId} : {});
      if (action === 'siteexpense' && typeof loadSiteExpenseOptions === 'function') loadSiteExpenseOptions(true);
    }
    return;
  }
  if (a === 'peek') {
    const rows = state.ov.results?.groups[b.dataset.group] || [];
    state.ov = {kind: 'peek', item: rows[Number(b.dataset.i)], back: state.ov};
    ovDraw();
    return;
  }
  if (a === 'open-item') {
    const x = state.ov.item;
    ovClose(true);
    if (x.type === 'project') openProject(x.id);
    else if (x.type === 'party') openParty(x.id);
    else {
      const view = {document: 'documents', task: 'tasks', site_report: 'site', snag: 'project'}[x.type];
      state.ovRecord = view ? {view, type: x.type, id: x.id} : null;
      if (x.type === 'snag') openProject(x.project_id, 'snags');
      else if (view) {
        if (view === 'tasks') state.ovFilter = {status: 'all', mine: false, sort: state.ovFilter.sort};
        switchView(view);
      }
    }
    return;
  }
  if (a === 'done-item') {
    const id = state.ov.item.id;
    ovClose();
    const t = document.createElement('button');
    t.dataset.action = 'complete';
    t.dataset.id = String(id);
    document.body.appendChild(t);
    t.click();
    t.remove();
    return;
  }
  if (a === 'role') {
    if (!state.scope) return;
    state.ov.role = b.dataset.value;
    try {
      const d = await api(`/api/projects/${state.scope.project_id}/page?as_role=${encodeURIComponent(b.dataset.value)}`);
      state.ov.sections = d.sections.map(s => PP_TITLES[s] || s);
    } catch (err) { state.ov.sections = null; notify(err.message, true); }
    ovDraw();
  }
});

// a project page sets the scope to its project
const _ovPpLoad = ppLoad;
ppLoad = async function (id) {
  await _ovPpLoad(id);
  if (state.pp.data) { ovSetScope({id: state.pp.data.project.id, name: state.pp.data.project.name}); ovChrome(); }
};
