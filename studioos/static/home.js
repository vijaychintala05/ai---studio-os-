'use strict';
/* StudioOS Home, by role (App Flows map): the widgets this person's role gets, each a figure or a short list that opens its screen.
   Read-only. Money widgets exist only for roles that may see money. No inline styles (strict CSP). Loaded after app.js. */

Object.assign(state, {home: {data: null}});

const HOME_TONE = {good: 'good', warn: 'warn', critical: 'critical'};
const homeRs = p => inr(Number(p || 0) / 100);

function homeDate(iso) {   // 2026-11-25 -> Wednesday, 25 November 2026
  const d = new Date(String(iso || '') + 'T00:00:00');
  return Number.isNaN(d.getTime()) ? String(iso || '') : d.toLocaleDateString('en-IN', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
}

async function homeLoad() { state.home.data = await api('/api/home'); }

function homeWidget(w) {
  const open = w.screen ? ` <button type="button" class="cx-link" data-home="open" data-screen="${esc(w.screen)}">Open</button>` : '';
  if (w.kind === 'metric') {
    const value = w.key === 'cash_bank' ? homeRs(w.value) : esc(w.value);
    return `<section class="panel"><div class="panel-head"><div class="panel-title">${esc(w.title)}</div></div><div class="panel-body"><div class="v-tile"><div class="v-tile-value">${value}</div>` +
      `<div class="v-tile-label">${w.tone ? pill(w.tone === 'good' ? 'All clear' : w.tone === 'critical' ? 'Needs attention' : 'Waiting', HOME_TONE[w.tone] || '') : ''}</div></div>` +
      `${w.detail ? `<p class="muted">${esc(w.detail)}</p>` : ''}${open}</div></section>`;
  }
  const rows = w.rows.map(r => `<li>${r.tone ? pill(r.tone === 'critical' ? 'Needs attention' : r.tone === 'warn' ? 'Waiting' : 'On track', HOME_TONE[r.tone] || '') + ' ' : ''}${r.project_id ? `<button type="button" class="cx-link" data-home-project="${Number(r.project_id)}">${esc(r.label)}</button>` : esc(r.label)}${r.amount_paise !== undefined ? ` <strong class="num">${esc(homeRs(r.amount_paise))}</strong>` : ''}</li>`).join('');
  return `<section class="panel"><div class="panel-head"><div class="panel-title">${esc(w.title)}</div></div><div class="panel-body">${rows ? `<ul>${rows}</ul>` : `<p class="muted">${esc(w.empty)}</p>`}` +
    `${w.more ? `<p class="muted">and ${Number(w.more)} more</p>` : ''}${open}</div></section>`;
}

function siteQuickActions() {
  if (state.user?.role !== 'site_engineer') return '';
  return `<section class="site-quick-actions" aria-label="Site actions">
    <button type="button" class="btn btn-primary" data-action="site">Log site report</button>
    <button type="button" class="btn btn-secondary" data-action="siteexpense">Record expense</button>
    <button type="button" class="btn btn-secondary" data-home="photo">Take photo</button>
    <input type="file" id="homeCamera" accept="image/*" capture="environment" aria-label="Take photo" hidden>
  </section>`;
}

function homeView() {
  if (!state.home.data) {
    homeLoad().then(render).catch(err => { state.home.data = {widgets: [], role: '', date: ''}; notify(err.message, true); render(); });
    return head('Home', 'What needs you today.') + siteQuickActions() + '<div class="loading">Loading…</div>';
  }
  const d = state.home.data;
  const sub = d.role === 'viewer' ? `${esc(homeDate(d.date))} · Your project workspace.` : `${esc(homeDate(d.date))} · What needs you today.`;
  return head('Home', sub) +
    siteQuickActions() +
    (d.owed_to_you_paise ? `<p class="muted">Owed to you <strong>${esc(homeRs(d.owed_to_you_paise))}</strong></p>` : '') +
    (d.widgets.length ? `<div class="home-grid">${d.widgets.map(homeWidget).join('')}</div>` : empty('⌂', 'Nothing to show', 'Nothing is waiting for you.'));
}

const _homeRender = render;
render = function () {
  if (state.view !== 'home') { _homeRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = homeView().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / HOME');
  $('breadcrumb').textContent = 'Home';
  document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === 'home'));
};

document.addEventListener('click', e => {
  if (e.target.closest('[data-view="home"]')) { state.home.data = null; return; }
  if (e.target.closest('[data-home="photo"]')) { $('homeCamera').click(); return; }
  const project = e.target.closest('[data-home-project]');
  if (project) { openProject(Number(project.dataset.homeProject)); return; }
  const b = e.target.closest('[data-home="open"]');
  if (b) switchView(b.dataset.screen);
});

document.addEventListener('change', async event => {
  const input = event.target;
  if (input.id !== 'homeCamera' || !input.files.length) return;
  const photo = input.files[0];
  const session = state.session;
  const btn = document.querySelector('[data-home="photo"]');
  const prevText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Uploading photo…'; }
  try {
    const compressed = await ppShrink(photo);
    const filename = photo.name.replace(/\.[^.]+$/, '') + '.jpg';
    const base64 = await ppBase64(compressed);
    if (session !== state.session) return;
    const saved = await api('/api/intake/upload', {method: 'POST', body: JSON.stringify({filename, base64})});
    if (session !== state.session) return;
    state.ib.open = saved;
    state.ib.items = null;
    state.ib.table = null;
    switchView('inbox');
    notify('Photo added to your inbox.');
  } catch (error) { if (session === state.session) notify(error.message, true); }
  finally {
    input.value = '';
    if (btn && btn.isConnected) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.textContent = prevText; }
  }
});
