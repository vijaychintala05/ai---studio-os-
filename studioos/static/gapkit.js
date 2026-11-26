'use strict';
/* Small shared pieces for the screens added from FRONTEND_GAPS_PLAN.md: register a screen, load its data once,
   build forms and tables, and draft a change request in plain words. Nothing here writes to the books.
   Strict CSP: no inline styles or handlers; one delegated click, change and submit listener. Loaded after app.js. */

Object.assign(state, {gk: {data: {}, ui: {}}});

const GK_SCREENS = {};
const gkRs = p => inr(Number(p || 0) / 100);
const gkKey = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : 'gk-' + Date.now() + '-' + Math.random().toString(36).slice(2));

/* Rupees typed by a person to whole paise, without floating point. Returns null when it is not an amount. */
function gkPaise(raw) {
  const m = /^\s*(\d{1,12})(?:\.(\d{1,2}))?\s*$/.exec(String(raw ?? '').replace(/,/g, ''));
  return m ? Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0') || 0) : null;
}

/* gkScreen('period', {title, roles, view: () => html, click: {name: el => ...}, submit: {...}, change: {...}}) */
function gkScreen(name, def) { GK_SCREENS[name] = def; }

/* Data for a screen is asked for once; a failure is shown instead of asked for again on every repaint. */
function gkGet(key, load) {
  const have = state.gk.data[key];
  if (have !== undefined) return have.value;
  const entry = state.gk.data[key] = {value: undefined};
  Promise.resolve().then(load).then(value => { entry.value = value; })
    .catch(err => { entry.value = {gkError: err.message}; })
    .then(() => { if (state.gk.data[key] === entry) render(); });
  return undefined;
}

function gkForget(prefix = '') {
  for (const key of Object.keys(state.gk.data)) if (key.startsWith(prefix)) delete state.gk.data[key];
}

function gkWait(value) {
  if (value === undefined) return '<div class="loading">Loading…</div>';
  if (value && value.gkError) return `<p class="muted">${esc(value.gkError)}</p>`;
  return '';
}

function gkPanel(title, sub, body) {
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(title)}</div>` +
    (sub ? `<div class="panel-sub">${esc(sub)}</div>` : '') + `</div></div><div class="panel-body">${body}</div></section>`;
}

/* Cells are HTML already escaped by the caller. */
function gkTable(headers, rows, emptyText) {
  if (!rows.length) return `<p class="muted">${esc(emptyText)}</p>`;
  return `<div class="w-table-wrap"><table class="w-table"><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>` +
    `<tbody>${rows.map(cells => `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function gkOptions(list, selected) {
  return list.map(([value, label]) => `<option value="${esc(value)}"${String(value) === String(selected ?? '') ? ' selected' : ''}>${esc(label)}</option>`).join('');
}

function gkSelect(label, name, list, selected, extra = '') {
  return `<label class="g-field"><span>${esc(label)}</span><select class="form-input" name="${esc(name)}" ${extra}>${gkOptions(list, selected)}</select></label>`;
}

function gkInput(label, name, extra = '', type = 'text', value = '') {
  return `<label class="g-field"><span>${esc(label)}</span><input class="form-input" type="${esc(type)}" name="${esc(name)}" value="${esc(value)}" ${extra}></label>`;
}

function gkForm(submit, fields, button, attrs = '') {
  return `<form class="g-form" data-gk-submit="${esc(submit)}" ${attrs}>${fields}<div><button type="submit" class="btn btn-primary btn-sm">${esc(button)}</button></div></form>`;
}

function gkButton(action, label, attrs = '', primary = false) {
  return `<button type="button" class="btn ${primary ? 'btn-primary' : 'btn-secondary'} btn-sm" data-gk-click="${esc(action)}" ${attrs}>${esc(label)}</button>`;
}

function gkValues(form) {
  const out = {};
  for (const [k, v] of new FormData(form)) out[k] = typeof v === 'string' ? v.trim() : v;
  return out;
}

/* Put the shared tab bar of related screens under the heading, as the project workspace does. */
function gkHubBar() {
  if (typeof navHubBar !== 'function') return;
  const bar = navHubBar(state.view, state.user?.role, typeof ROLE_MENU !== 'undefined' ? ROLE_MENU[state.user?.role] : undefined);
  const main = $('mainContent');
  if (!bar || !main?.querySelector) return;
  const heading = main.querySelector('.headline');
  if (heading) heading.insertAdjacentHTML('afterend', bar); else main.insertAdjacentHTML('afterbegin', bar);
}

/* One section at a time, chosen with pills. list: [id, label, () => html]; only the shown section loads its data. */
function gkSections(key, list) {
  const open = list.filter(Boolean);
  if (state.gk.ui.sectionAll) return open.map(s => s[2]()).join('');
  const current = open.find(s => s[0] === state.gk.ui[key]) || open[0];
  if (!current) return '';
  return `<div class="sense-filter-bar" role="tablist">` + open.map(([id, label]) =>
    `<button type="button" class="sense-filter-pill${id === current[0] ? ' active' : ''}" role="tab" aria-selected="${id === current[0]}" data-gk-click="section" data-key="${esc(key)}" data-id="${esc(id)}">${esc(label)}</button>`).join('') +
    `</div>` + current[2]();
}

GK_SCREENS._any = {click: {section: el => { state.gk.ui[el.dataset.key] = el.dataset.id; }}, submit: {}};

/* After drafting, offer the same review sheet the rest of the app uses (the Admin may approve there). */
function gkDrafted(ticket, what) {
  if (typeof senseOfferImmediateReview === 'function') senseOfferImmediateReview(ticket, what);   // its sheet says what happens next
  else notify(`${what} as change request #${ticket}. Nothing changes until it is approved.`);
  refresh();   // so the new request shows in Change requests and Approvals straight away
}

/* Send a change for approval and say so. The server decides whether it is allowed. */
async function gkDraft(url, body, what = 'Drafted') {
  const r = await api(url, {method: 'POST', body: JSON.stringify(body)});
  const ticket = r.ticket_id || r.ticket?.id;
  gkDrafted(ticket, what);
  return r;
}

async function gkRun(fn) {
  try { await fn(); } catch (err) { notify(err.message, true); }
  render();
}

for (const kind of ['click', 'change', 'submit']) {
  document.addEventListener(kind, e => {
    const attr = `data-gk-${kind}`;
    const el = e.target.closest(`[${attr}]`);
    const screen = GK_SCREENS[state.view];
    if (!el) return;
    const name = el.getAttribute(attr);
    const handler = (screen && screen[kind] && screen[kind][name]) || (GK_SCREENS._any && GK_SCREENS._any[kind] && GK_SCREENS._any[kind][name]);
    if (!handler) return;
    if (kind === 'submit') e.preventDefault();
    gkRun(() => handler(el));
  });
}

const _gkRender = render;
render = function () {
  const screen = GK_SCREENS[state.view];
  if (!screen || !screen.view) { _gkRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  const body = screen.roles && !screen.roles.includes(state.user?.role)
    ? head(screen.title, 'Your role does not include this screen.') : screen.view();
  $('mainContent').innerHTML = body;
  $('breadcrumb').textContent = screen.title;
  gkHubBar();
};

/* Whenever the app reloads (after an approval, for example) these screens ask for their lists again. */
const _gkRefresh = refresh;
refresh = function () {
  gkForget();
  return _gkRefresh.apply(this, arguments);
};

const _gkSwitchView = switchView;
switchView = function (view) {
  if (GK_SCREENS[view]) gkForget();
  return _gkSwitchView(view);
};
