'use strict';
/* StudioOS Home, by role (App Flows map): the widgets this person's role gets, each a figure or a short list that opens its screen.
   Read-only. Money widgets exist only for roles that may see money. No inline styles (strict CSP). Loaded after app.js. */

Object.assign(state, {home: {data: null}});

const HOME_TONE = {good: 'good', warn: 'warn', critical: 'critical'};
const homeRs = p => inr(Number(p || 0) / 100);

async function homeLoad() { state.home.data = await api('/api/home'); }

function homeWidget(w) {
  const open = w.screen ? ` <button type="button" class="cx-link" data-home="open" data-screen="${esc(w.screen)}">Open</button>` : '';
  if (w.kind === 'metric') {
    const value = w.key === 'cash_bank' ? homeRs(w.value) : esc(w.value);
    return `<section class="panel"><div class="panel-head"><div class="panel-title">${esc(w.title)}</div></div><div class="panel-body"><div class="v-tile"><div class="v-tile-value">${value}</div>` +
      `<div class="v-tile-label">${w.tone ? pill(w.tone === 'good' ? 'Fine' : w.tone === 'critical' ? 'Needs attention' : 'Waiting', HOME_TONE[w.tone] || '') : ''}</div></div>` +
      `${w.detail ? `<p class="muted">${esc(w.detail)}</p>` : ''}${open}</div></section>`;
  }
  const rows = w.rows.map(r => `<li>${r.tone ? pill(r.tone === 'critical' ? '!' : '•', HOME_TONE[r.tone] || '') + ' ' : ''}${esc(r.label)}${r.amount_paise !== undefined ? ` <strong class="num">${esc(homeRs(r.amount_paise))}</strong>` : ''}</li>`).join('');
  return `<section class="panel"><div class="panel-head"><div class="panel-title">${esc(w.title)}</div></div><div class="panel-body">${rows ? `<ul>${rows}</ul>` : `<p class="muted">${esc(w.empty)}</p>`}` +
    `${w.more ? `<p class="muted">and ${Number(w.more)} more</p>` : ''}${open}</div></section>`;
}

function homeView() {
  if (!state.home.data) {
    homeLoad().then(render).catch(err => { state.home.data = {widgets: [], role: '', date: ''}; notify(err.message, true); render(); });
    return head('Home', 'What needs you today.') + '<div class="loading">Loading…</div>';
  }
  const d = state.home.data;
  return head('Home', `${esc(d.date)}. What needs you today, for ${esc(String(d.role).replace('_', ' '))}.`) +
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
  const b = e.target.closest('[data-home="open"]');
  if (b) switchView(b.dataset.screen);
});
