'use strict';
/* StudioOS project page (App Flows map): one project's home with a title block, health and the sections its role may see: Tasks, Snags,
   Site, Money, Files, People. Opened from a project card. A thin strip at the top says which project you are looking at, with one tap to
   go back to all projects. Read-only; every change is still a ticket. No inline styles (strict CSP). Loaded after app.js and newwork.js. */

Object.assign(state, {pp: {id: null, data: null}});

const PP_HEALTH = {on_track: ['On track', 'good'], at_risk: ['At risk', 'warn'], delayed: ['Delayed', 'critical']};
const PP_TITLES = {tasks: 'Tasks', snags: 'Snags', site: 'Site', money: 'Money', files: 'Files', people: 'People'};
const ppRs = p => inr(Number(p || 0) / 100);

async function ppLoad(id) {
  state.pp.data = await api(`/api/projects/${Number(id)}/page`);
}

function ppSection(key, d) {
  if (key === 'tasks') {
    const rows = d.items.map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.assignee || '—')}</td><td>${esc(t.due || '—')}</td><td>${t.overdue ? pill('Overdue', 'critical') : pill(t.status, 'gray')}</td></tr>`).join('');
    return `<p class="muted">${Number(d.open)} open · ${Number(d.overdue)} overdue · ${Number(d.done)} done</p>` +
      (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Task</th><th>Who</th><th>Due</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('☑', 'No tasks yet', 'Tasks added to this project appear here.'));
  }
  if (key === 'snags') {
    const rows = d.items.map(x => `<tr><td>${esc(x.title)}</td><td>${esc(x.severity || '—')}</td><td>${esc(x.due || '—')}</td></tr>`).join('');
    return `<p class="muted">${Number(d.open)} open</p>` + (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Snag</th><th>Severity</th><th>Due</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('◇', 'No open snags', 'Defects raised on this project appear here until they are closed.'));
  }
  if (key === 'site') {
    return d.items.length ? `<ul class="w-entries">${d.items.map(r => `<li><strong>${esc(r.date)}</strong> ${esc(r.note)}</li>`).join('')}</ul>` : empty('▧', 'No site reports yet', 'Site reports for this project appear here.');
  }
  if (key === 'money') {
    return `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.budget_paise))}</div><div class="v-tile-label">Contract value</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.cost_to_date_paise))}</div><div class="v-tile-label">Cost to date</div></div></div>`;
  }
  if (key === 'files') {
    return d.items.length ? `<ul class="w-entries">${d.items.map(f => `<li>${esc(f.name)} <span class="muted">${esc(f.type)}</span></li>`).join('')}</ul>` : empty('▥', 'No files indexed', 'Files found on the NAS for this project appear here.');
  }
  if (key === 'people') {
    const m = d.members.map(x => `<li>${esc(x.name)} <span class="muted">${esc(String(x.role).replace('_', ' '))}</span></li>`).join('');
    const o = d.open_tasks_by_person.map(x => `<li>${esc(x.name)}: ${Number(x.open)} open task${x.open === 1 ? '' : 's'}</li>`).join('');
    return (m ? `<div class="w-sub">On this project</div><ul>${m}</ul>` : '') + (o ? `<div class="w-sub">Open tasks by person</div><ul>${o}</ul>` : '') || '<p class="muted">Nobody is assigned yet.</p>';
  }
  return '';
}

function ppView() {
  if (!state.pp.id) return head('Project', 'Choose a project from Projects.') + empty('▤', 'No project chosen', 'Open one from the Projects screen.');
  if (!state.pp.data || state.pp.data.project.id !== state.pp.id) {
    const id = state.pp.id;
    ppLoad(id).then(render).catch(err => { notify(err.message, true); state.pp.id = null; state.pp.data = null; state.view = 'projects'; render(); });
    return head('Project', 'Loading…') + '<div class="loading">Loading…</div>';
  }
  const d = state.pp.data, p = d.project, [hl, tone] = PP_HEALTH[d.health.status] || [d.health.status, 'gray'];
  const strip = `<div class="notice"><span>Showing <strong>${esc(p.name)}</strong></span><button class="btn btn-secondary btn-sm" data-pp="all">All projects</button></div>`;
  const blocker = d.health.blocking ? `<p class="muted">Blocking: #${Number(d.health.blocking.task_id)} ${esc(d.health.blocking.title)} (${esc(d.health.blocking.reason)})</p>` : '';
  const chips = d.sections.map(k => `<a class="tag" href="#pp-${k}" data-pp="jump" data-key="${k}">${PP_TITLES[k]}</a>`).join(' ');
  const panels = d.sections.map(k => `<section class="panel section-gap" id="pp-${k}"><div class="panel-head"><div class="panel-title">${PP_TITLES[k]}</div></div><div class="panel-body">${ppSection(k, d.data[k])}</div></section>`).join('');
  return strip + head(p.name, [p.stage, p.client, p.location].filter(Boolean).join(' · ')) +
    `<section class="panel"><div class="panel-body"><p>${pill(hl, tone)}</p>${blocker}<p>${chips}</p></div></section>` + panels;
}

const _ppRender = render;
render = function () {
  if (state.view !== 'project') { _ppRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = ppView().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / PROJECT');
  $('breadcrumb').textContent = state.pp.data ? state.pp.data.project.name : 'Project';
  document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === 'projects'));
};

function openProject(id) {
  state.pp.id = Number(id);
  state.pp.data = null;
  switchView('project');
}

document.addEventListener('click', e => {
  const card = e.target.closest('.project-card');
  if (card && !e.target.closest('button, a')) {
    const name = card.querySelector('.project-name')?.textContent.trim();
    const p = ((state.budgets || []).concat(state.projects || [])).find(x => x.name === name);
    if (p) { openProject(p.id); return; }
  }
  const b = e.target.closest('[data-pp]');
  if (!b) return;
  if (b.dataset.pp === 'all') { state.pp.id = null; state.pp.data = null; switchView('projects'); }
  if (b.dataset.pp === 'jump') { e.preventDefault(); document.getElementById('pp-' + b.dataset.key)?.scrollIntoView({block: 'start'}); }
});
