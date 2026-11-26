'use strict';
/* StudioOS outbox: when there is no signal, the drafts a person makes on site (a site report, a task, a time entry, a work change, the
   evening status) are kept on the phone and sent when the connection is back. Only requests that make a DRAFT for approval are kept;
   nothing is ever approved or changed by this. Kept in IndexedDB on this device; a send the server refuses is shown to the person
   instead of being retried. Also registers the service worker (sw.js) so the app opens offline.
   Loaded after app.js and the screen modules. No inline styles (strict CSP). */

const OUTBOX_PATHS = [/^\/api\/site-reports$/, /^\/api\/site-expenses$/, /^\/api\/tasks$/, /^\/api\/time\/propose$/, /^\/api\/work\/propose$/, /^\/api\/rhythm\/status\/reply$/];
const OUTBOX_LABELS = {
  '/api/site-reports': 'Site report',
  '/api/site-expenses': 'Site expense',
  '/api/tasks': 'Task',
  '/api/time/propose': 'Time entry',
  '/api/work/propose': 'Work change',
  '/api/rhythm/status/reply': 'Evening status',
};
function outboxLabel(path, body) {
  const base = OUTBOX_LABELS[String(path || '').split('?')[0]] || 'Draft';
  try {
    const parsed = typeof body === 'string' && body ? JSON.parse(body) : null;
    const hint = parsed && (parsed.title || parsed.note || parsed.text || parsed.activity || parsed.kind);
    if (hint) return base + ' (' + String(hint).trim().slice(0, 40) + ')';
  } catch (e) { /* ignore */ }
  return base;
}
function outboxQueueable(method, path) {
  return String(method).toUpperCase() === 'POST' && OUTBOX_PATHS.some(rx => rx.test(String(path).split('?')[0]));
}
function outboxSummary(items, last) {
  const waiting = items.filter(i => !i.failed).length, failed = items.filter(i => i.failed).length;
  const parts = [];
  if (waiting) parts.push(`Saved on phone · ${waiting} waiting`);
  if (failed) parts.push(`${failed} could not be sent`);
  if (last) parts.push(`last synced ${new Date(last).toTimeString().slice(0, 5)}`);
  return parts.join(' · ');
}

// ------------------------------------------------------------------ storage (IndexedDB, guarded)
let outboxDb = null;
function outboxOpen() {
  if (outboxDb) return Promise.resolve(outboxDb);
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) { reject(new Error('no storage')); return; }
    const req = indexedDB.open('studioos-outbox', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('q', {keyPath: 'id', autoIncrement: true});
    req.onsuccess = () => { outboxDb = req.result; resolve(outboxDb); };
    req.onerror = () => reject(req.error);
  });
}
function outboxTx(mode, fn) {
  return outboxOpen().then(db => new Promise((resolve, reject) => {
    const tx = db.transaction('q', mode), store = tx.objectStore('q');
    const req = fn(store);
    tx.oncomplete = () => resolve(req && req.result !== undefined ? req.result : undefined);
    tx.onerror = () => reject(tx.error);
  }));
}
const outboxAll = () => outboxTx('readonly', s => s.getAll());
const outboxAdd = item => outboxTx('readwrite', s => s.add(item));
const outboxPut = item => outboxTx('readwrite', s => s.put(item));
const outboxDelete = id => outboxTx('readwrite', s => s.delete(id));

// ------------------------------------------------------------------ keeping a draft when the network fails
const _outboxApi = api;
api = async function (path, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  const owner = state.user?.id, session = state.session;
  try { return await _outboxApi(path, opts); }
  catch (err) {
    if (err instanceof TypeError && owner != null && session === state.session && outboxQueueable(method, path)) {
      try {
        await outboxAdd({path, method, body: opts.body || '', label: outboxLabel(path, opts.body || ''), at: Date.now(), user: owner});
        if (session === state.session) {
          notify('Saved on your phone. It will be sent when you are back online.');
          outboxPaint();
        }
        return {queued: true, saved_on_phone: true};
      } catch (e) { /* storage unavailable: show the original problem */ }
    }
    throw err;
  }
};

// ------------------------------------------------------------------ sending when the connection is back
let outboxBusy = false;
async function outboxFor(owner) {
  return owner == null ? [] : (await outboxAll()).filter(i => i.user === owner);
}

async function outboxFlush() {
  if (outboxBusy || !state.user) return;
  const owner = state.user.id, session = state.session;
  outboxBusy = true;
  try {
    const items = (await outboxFor(owner)).filter(i => !i.failed).sort((a, b) => a.id - b.id);
    for (const it of items) {
      if (session !== state.session) break;
      try {
        await _outboxApi(it.path, {method: it.method, body: it.body});
        await outboxDelete(it.id);
        if (session === state.session) state.outboxLast = Date.now();
      } catch (err) {
        if (session !== state.session || err instanceof TypeError) break; // retry on the next connection or sign-in
        await outboxPut({...it, failed: true, reason: String(err.message || 'Refused').slice(0, 200)});   // the server said no: show it, do not retry
      }
    }
  } catch (e) { /* storage unavailable */ }
  outboxBusy = false;
  outboxPaint();
}

async function outboxPaint() {
  let chip = document.getElementById('outboxChip');
  const owner = state.user?.id, session = state.session;
  if (owner == null) { if (chip) chip.hidden = true; return; }
  let items = [];
  try { items = await outboxFor(owner); } catch (e) { /* none */ }
  if (session !== state.session) return;
  const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
  if (!items.length && !offline) { if (chip) chip.hidden = true; return; }
  if (!chip) {
    chip = document.createElement('div');
    chip.id = 'outboxChip';
    chip.className = 'notice outbox-chip';
    chip.setAttribute('role', 'status');
    const main = document.getElementById('mainContent');
    (main ? main.parentNode : document.body).insertBefore(chip, main || null);
  }
  chip.hidden = false;
  const waiting = items.filter(i => !i.failed);
  const failed = items.filter(i => i.failed);
  const sendNow = !offline && waiting.length ? ' <button type="button" class="btn btn-primary btn-sm" data-outbox="flush">Send now</button>' : '';
  chip.innerHTML = `<span>${offline ? 'Offline. ' : ''}${esc(outboxSummary(items, state.outboxLast)) || 'Nothing waiting'}</span>${sendNow}` +
    (failed.length ? '<ul>' + failed.map(item => `<li><strong>${esc(item.label || outboxLabel(item.path, item.body))}</strong>: ${esc(item.reason)}</li>`).join('') +
      '</ul><button type="button" class="btn btn-secondary btn-sm" data-outbox="discard">Discard what could not be sent</button>' : '');
}

document.addEventListener('click', async e => {
  const flushBtn = e.target.closest('[data-outbox="flush"]');
  if (flushBtn) {
    if (flushBtn.disabled) return;
    flushBtn.disabled = true;
    flushBtn.textContent = 'Sending…';
    try { await outboxFlush(); }
    finally { if (flushBtn.isConnected) { flushBtn.disabled = false; flushBtn.textContent = 'Send now'; } }
    return;
  }
  const b = e.target.closest('[data-outbox="discard"]');
  if (!b) return;
  if (typeof askConfirm === 'function' && !await askConfirm('Discard all drafts that could not be sent? This cannot be undone.', 'Discard')) return;
  const session = state.session;
  for (const i of (await outboxFor(state.user?.id)).filter(x => x.failed)) {
    if (session !== state.session) break;
    await outboxDelete(i.id);
  }
  outboxPaint();
});
window.addEventListener('online', () => { outboxFlush(); });
window.addEventListener('offline', () => { outboxPaint(); });
setInterval(() => { if (navigator.onLine !== false) outboxFlush(); }, 60000);

const _outboxRender = render;
render = function () {
  _outboxRender();
  outboxPaint();
  if (!state.outboxStarted && state.user) { state.outboxStarted = true; outboxFlush(); }
};

if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => { /* the app works without it */ }); });
}
