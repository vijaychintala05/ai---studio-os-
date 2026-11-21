'use strict';
/* StudioOS navigation rules (App Flows map):
   - Back goes where you came from: each screen change is a history entry, so the phone's Back button walks back through screens.
   - Reopen at the last screen if you were away less than 30 minutes, otherwise start at Home.
   - Undo for 10 seconds after any approval: the approval is held for 10 seconds with an Undo button, and only then sent.
   - The Inbox has two parts: Needs you (waiting for a decision) and Updates (already decided).
   - Long-press on the Capture tab opens New.
   Loaded after shell.js and overlays.js. No inline styles (strict CSP). */

Object.assign(state, {flow: {inbox: 'needs', started: false, pop: false, ovPop: false}});

const FLOW_LAST = 'studioos-last';
const FLOW_AWAY_MS = 30 * 60 * 1000;
const FLOW_UNDO_SECONDS = 10;
const FLOW_APPROVALS = ['approve-ticket-item', 'commit-ticket', 'approve-cost', 'approve-payment', 'approve-new-type', 'w-approve'];

// pure rules (also run by the tests) ----------------------------------------------------------------
function flowChooseStart(saved, now, validViews, home) {
  if (saved && typeof saved.view === 'string' && Number.isFinite(saved.ts) && now - saved.ts >= 0 && now - saved.ts <= FLOW_AWAY_MS && validViews.includes(saved.view)) return saved.view;
  return home;
}
function flowInboxSplit(rows) {
  const done = t => ['committed', 'reversed'].includes(t.status);
  return {needs: rows.filter(t => !done(t)), updates: rows.filter(done)};
}

function flowSave() {
  try { localStorage.setItem(FLOW_LAST, JSON.stringify({view: state.view, ts: Date.now(), pid: state.view === 'project' ? state.pp.id : null})); } catch (e) { /* not kept */ }
}
function flowLoad() {
  try { return JSON.parse(localStorage.getItem(FLOW_LAST) || 'null'); } catch (e) { return null; }
}
const flowViews = () => Array.from(document.querySelectorAll('[data-view]')).map(b => b.dataset.view).concat(['project']);
const flowHome = () => (typeof shellTabs === 'function' && state.user ? shellTabs(state.user.role)[0].top : 'overview');

// history -------------------------------------------------------------------------------------------
const _flowSwitch = switchView;
switchView = function (v) {
  if (!state.flow.pop && state.view !== v) { try { history.pushState({v: v}, ''); } catch (e) { /* history blocked */ } }
  _flowSwitch(v);
  flowSave();
};
window.addEventListener('popstate', e => {
  if (state.ov || state.flow.ovPop) { state.flow.ovPop = false; return; }       // that Back closed an overlay
  if (e.state && typeof e.state.v === 'string' && state.user) {
    state.flow.pop = true;
    try { _flowSwitch(e.state.v); flowSave(); } finally { state.flow.pop = false; }
  }
});

// reopen at the last screen, once, after sign-in ---------------------------------------------------------
const _flowRender = render;
render = function () {
  if (state.user && !state.mustSetup2fa && !state.flow.started) {
    state.flow.started = true;
    const saved = flowLoad();
    const start = flowChooseStart(saved, Date.now(), flowViews(), flowHome());
    if (start === 'project' && saved && Number.isInteger(saved.pid)) { state.pp.id = saved.pid; state.pp.data = null; }
    if (start !== state.view) state.view = start;
    try { history.replaceState({v: state.view}, ''); } catch (e) { /* ignore */ }
  }
  _flowRender();
  flowSave();
};

// Inbox: Needs you / Updates ----------------------------------------------------------------------------
const _flowTickets = tickets;
tickets = function () {
  const all = state.tickets || [];
  const split = flowInboxSplit(all);
  const seg = state.flow.inbox;
  state.tickets = split[seg === 'updates' ? 'updates' : 'needs'];
  let html;
  try { html = _flowTickets(); } finally { state.tickets = all; }
  const tab = (k, label, n) => `<button type="button" class="w-tab${seg === k ? ' on' : ''}" role="tab" aria-selected="${seg === k}" data-flow="inbox" data-seg="${k}">${label} <span class="muted">${n}</span></button>`;
  return `<div class="w-tabs" role="tablist" aria-label="Inbox">${tab('needs', 'Needs you', split.needs.length)}${tab('updates', 'Updates', split.updates.length)}</div>` + html;
};

// 10 seconds to undo an approval ---------------------------------------------------------------------------
let flowHold = null;
function flowBar() {
  let bar = document.getElementById('undoBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'undoBar';
    bar.className = 'undo-bar';
    bar.setAttribute('role', 'status');
    document.body.appendChild(bar);
  }
  return bar;
}
function flowFire(held) {
  const t = document.createElement('button');
  Object.assign(t.dataset, held.dataset);
  t.dataset.flowGo = '1';
  document.body.appendChild(t);
  t.click();
  t.remove();
}
function flowClearHold() {
  if (flowHold) { clearInterval(flowHold.timer); flowHold = null; }
  const bar = document.getElementById('undoBar');
  if (bar) bar.hidden = true;
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-action]');
  if (b && FLOW_APPROVALS.includes(b.dataset.action) && !b.dataset.flowGo) {
    e.preventDefault();
    e.stopImmediatePropagation();
    if (flowHold) return;                                     // one approval at a time
    const held = {dataset: {...b.dataset}, left: FLOW_UNDO_SECONDS};
    const bar = flowBar();
    const paint = () => { bar.hidden = false; bar.innerHTML = `<span>Approving in ${held.left} s</span><button type="button" class="btn btn-secondary btn-sm" data-flow="undo">Undo</button>`; };
    paint();
    held.timer = setInterval(() => {
      held.left -= 1;
      if (held.left <= 0) { const h = flowHold; flowClearHold(); if (h) flowFire(h); } else paint();
    }, 1000);
    flowHold = held;
    return;
  }
  const f = e.target.closest('[data-flow]');
  if (!f) return;
  if (f.dataset.flow === 'undo') { flowClearHold(); notify('Not approved. Nothing was changed.'); }
  if (f.dataset.flow === 'inbox') { state.flow.inbox = f.dataset.seg; render(); }
}, true);
window.addEventListener('beforeunload', e => { if (flowHold) { e.preventDefault(); e.returnValue = ''; } });

// long-press on Capture opens New --------------------------------------------------------------------------
(function longPress() {
  let timer = null, fired = false;
  document.addEventListener('pointerdown', e => {
    if (!e.target.closest('[data-shell-tab="capture"]')) return;
    fired = false;
    timer = setTimeout(() => { fired = true; if (typeof ovOpen === 'function') ovOpen('newform'); }, 500);
  });
  const stop = () => clearTimeout(timer);
  document.addEventListener('pointerup', stop);
  document.addEventListener('pointercancel', stop);
  document.addEventListener('click', e => {
    if (fired && e.target.closest('[data-shell-tab="capture"]')) { e.preventDefault(); e.stopImmediatePropagation(); fired = false; }
  }, true);
}());
