'use strict';
/* StudioOS project page (App Flows map): one project's home with a title block, health and the sections its role may see: Tasks, Snags,
   Site, Money, Files, People. Opened from a project card. A thin strip at the top says which project you are looking at, with one tap to
   go back to all projects. Read-only; every change is still a ticket. No inline styles (strict CSP). Loaded after app.js and newwork.js. */

Object.assign(state, {pp: {id: null, data: null, chat: null}});

const PP_HEALTH = {on_track: ['On track', 'good'], at_risk: ['At risk', 'warn'], delayed: ['Delayed', 'critical']};
const PP_TITLES = {tasks: 'Tasks', snags: 'Snags', site: 'Site', money: 'Money', files: 'Files', people: 'People'};
const ppRs = p => inr(Number(p || 0) / 100);

async function ppLoad(id) {
  state.pp.data = await api(`/api/projects/${Number(id)}/page`);
  if (state.user?.role === 'viewer') { state.pp.chat = null; return; }
  try { state.pp.chat = await api(`/api/projects/${Number(id)}/chat`); } catch (e) { state.pp.chat = null; }   // not every role has the chat
}

function ppSection(key, d) {
  if (key === 'tasks') {
    const rows = d.items.map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.assignee || '—')}</td><td>${esc(t.due || '—')}</td><td>${t.overdue ? pill('Overdue', 'critical') : pill(t.status, 'gray')}</td></tr>`).join('');
    return `<p class="muted">${Number(d.open)} open · ${Number(d.overdue)} overdue · ${Number(d.done)} done</p>` +
      (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Task</th><th>Who</th><th>Due</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : empty('☑', 'No tasks yet', 'Tasks added to this project appear here.'));
  }
  if (key === 'snags') {
    const canPhoto = ['admin', 'manager', 'architect', 'site_engineer'].includes(state.user?.role);
    const rows = d.items.map(x => `<tr><td>${esc(x.title)}<div class="pp-photos">${(x.photos || []).map(ph => `<a href="${esc(ph.url)}" target="_blank" rel="noopener"><img class="pp-photo" src="${esc(ph.url)}" alt="${esc(ph.slot || 'Photo')} photo of ${esc(x.title)}" width="64" height="64" loading="lazy"></a>`).join('')}</div>` +
      `${canPhoto ? `<div class="pp-photo-add"><button type="button" class="btn btn-secondary btn-sm" data-pp="photo" data-id="${Number(x.id)}" data-slot="before">Photo before</button> <button type="button" class="btn btn-secondary btn-sm" data-pp="photo" data-id="${Number(x.id)}" data-slot="after">Photo after</button></div>` : ''}</td>` +
      `<td>${esc(x.severity || '—')}</td><td>${esc(x.due || '—')}</td></tr>`).join('');
    return `<p class="muted">${Number(d.open)} open</p>` + (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Snag</th><th>Severity</th><th>Due</th></tr></thead><tbody>${rows}</tbody></table></div><input type="file" id="ppPhotoInput" class="newtype-file-input" accept="image/jpeg,image/png" capture="environment" aria-label="Choose a photo" hidden>` : empty('◇', 'No open snags', 'Defects raised on this project appear here until they are closed.'));
  }
  if (key === 'site') {
    return d.items.length ? `<ul class="w-entries">${d.items.map(r => `<li><strong>${esc(r.date)}</strong> ${esc(r.note)}</li>`).join('')}</ul>` : empty('▧', 'No site reports yet', 'Site reports for this project appear here.');
  }
  if (key === 'money') {
    return `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.budget_paise))}</div><div class="v-tile-label">Contract value</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.cost_to_date_paise))}</div><div class="v-tile-label">Cost to date${d.expense_basis==='posted_books'?' · Expenses from the books':d.expense_basis==='mixed'?' · Books and tracker expenses':''}</div></div></div>`;
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
  const portalPanel = typeof paProjectPanel === 'function' ? paProjectPanel(p.id) : '';       // "Client portal" (staff roles only; portal_admin.js)
  const panels = d.sections.map(k => `<section class="panel section-gap" id="pp-${k}"><div class="panel-head"><div class="panel-title">${PP_TITLES[k]}</div></div><div class="panel-body">${ppSection(k, d.data[k])}</div></section>`).join('');
  const chat = state.pp.chat ? `<section class="panel section-gap" id="pp-chat"><div class="panel-head"><div><div class="panel-title">Team chat</div><div class="panel-sub">Everyone on this project reads this. Messages are not edited or deleted.</div></div></div><div class="panel-body">` +
    (state.pp.chat.messages.length ? `<ul class="w-entries pp-chat">${state.pp.chat.messages.map(m => `<li><strong>${esc(m.author)}</strong> <span class="muted">${esc(time(m.created_at))}</span><br>${esc(m.body)}</li>`).join('')}</ul>` : '<p class="muted">No messages yet.</p>') +
    `<form id="ppChatForm" class="v-ask"><input class="form-input" name="body" maxlength="2000" placeholder="Write to the team" aria-label="Message to the project team" required><button class="btn btn-primary" type="submit">Send</button></form></div></section>` : '';
  return strip + head(p.name, [p.stage, p.client, p.location].filter(Boolean).join(' · ')) +
    `<section class="panel"><div class="panel-body"><p>${pill(hl, tone)}</p>${blocker}<p>${chips}${portalPanel ? ' <a class="tag" href="#pp-portal" data-pp="jump" data-key="portal">Client portal</a>' : ''}${state.pp.chat ? ' <a class="tag" href="#pp-chat" data-pp="jump" data-key="chat">Team chat</a>' : ''}</p></div></section>` + panels + portalPanel + chat;
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
  const opening = e.target.closest('[data-project-open]');
  if (opening || (card && !e.target.closest('button, a'))) {
    const target = opening || card.querySelector('[data-project-open]');
    if (target) { openProject(target.dataset.projectOpen); return; }
  }
  const b = e.target.closest('[data-pp]');
  if (!b) return;
  if (b.dataset.pp === 'all') { state.pp.id = null; state.pp.data = null; switchView('projects'); }
  if (b.dataset.pp === 'jump') { e.preventDefault(); document.getElementById('pp-' + b.dataset.key)?.scrollIntoView({block: 'start'}); }
});

document.addEventListener('submit', async e => {
  if (e.target.id !== 'ppChatForm' || !state.pp.id) return;
  e.preventDefault();
  const body = String(new FormData(e.target).get('body') || '').trim();
  if (!body) return;
  try {
    await api(`/api/projects/${Number(state.pp.id)}/chat`, {method: 'POST', body: JSON.stringify({body})});
    state.pp.chat = await api(`/api/projects/${Number(state.pp.id)}/chat`);
  } catch (err) { notify(err.message, true); }
  render();
});

// a photo is shrunk on the phone (about 1600 px, JPEG) before it is sent, so it uploads fast on site
function ppShrink(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement('canvas');
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob(b => b ? resolve(b) : reject(new Error('The photo could not be read')), 'image/jpeg', 0.8);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('The photo could not be read')); };
    img.src = url;
  });
}
function ppBase64(blob) {
  return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(',')[1]); r.onerror = () => reject(new Error('The photo could not be read')); r.readAsDataURL(blob); });
}
let ppPhotoFor = null;
document.addEventListener('click', e => {
  const b = e.target.closest('[data-pp="photo"]');
  if (!b) return;
  ppPhotoFor = {id: Number(b.dataset.id), slot: b.dataset.slot};
  document.getElementById('ppPhotoInput')?.click();
});
document.addEventListener('change', async e => {
  if (e.target.id !== 'ppPhotoInput' || !ppPhotoFor || !e.target.files.length) return;
  const file = e.target.files[0], target = ppPhotoFor;
  e.target.value = '';
  try {
    const blob = await ppShrink(file);
    await api(`/api/snags/${target.id}/photos`, {method: 'POST', body: JSON.stringify({filename: 'snag-photo.jpg', base64: await ppBase64(blob), slot: target.slot})});
    await ppLoad(state.pp.id);
    notify('Photo added.');
  } catch (err) { notify(err.message, true); }
  render();
});
