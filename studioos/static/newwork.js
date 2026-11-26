'use strict';
/* StudioOS v0.23.0: screens for the v0.17 to v0.21 work: "Today" (your morning list), "My time" (timer, entries,
   leave), "Plan and budget" (stages, links, baseline slip, budgets and the money view for one project).
   Read screens plus the timer; every change is still a ticket. No inline styles (strict CSP); reuses the existing
   panel, table, button and tag styles. Loaded after app.js. */

Object.assign(state, {nw: {today: null, time: null, plan: null, projectId: null, busy: false, views: null, openView: null, ran: null}});

const nwApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const NW_REASON = {overdue: ['Overdue', 'critical'], due_today: ['Due today', 'warn'], ready: ['Ready to start', 'good'], snag: ['Open snag', 'warn']};
const NW_STATUS = {draft: 'Waiting for approval', submitted: 'Waiting for approval', approved: 'Approved', rejected: 'Rejected', sent_back: 'Sent back'};
const NW_HEALTH = {on_track: ['On track', 'good'], at_risk: ['At risk', 'warn'], overrun: ['Over budget', 'critical']};
const nwMins = m => { m = Number(m) || 0; return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`; };
const nwRs = p => p === null || p === undefined ? '—' : inr(Number(p) / 100);
function nwElapsedMinutes(startedAt) {
  if (!startedAt) return 0;
  const raw = String(startedAt).trim();
  const iso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(raw) ? raw.replace(' ', 'T') + 'Z' : raw;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 0 : Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
}
setInterval(() => {
  const el = document.getElementById('nwTimerElapsed');
  if (el && el.dataset.started) el.textContent = nwMins(nwElapsedMinutes(el.dataset.started));
}, 15000);

// ------------------------------------------------------------------ Today
async function nwLoadToday() {
  state.nw.today = await nwApi('/api/rhythm/mine');
}

function nwTodayView() {
  if (!state.nw.today) {
    nwLoadToday().then(render).catch(err => { state.nw.today = {items: [], date: ''}; notify(err.message, true); render(); });
    return head('Today', 'Your list for the day.') + '<div class="loading">Loading…</div>';
  }
  const t = state.nw.today;
  const rows = t.items.map(i => {
    const [label, tone] = NW_REASON[i.reason] || [i.reason, ''];
    return `<tr><td>${pill(label, tone)}</td><td>${esc(i.title)}</td><td>${esc(i.project)}</td><td>${esc(i.due || '—')}</td>` +
      `<td>${i.blocked_by.length ? `<span class="muted">Waiting on task${i.blocked_by.length === 1 ? '' : 's'} ${i.blocked_by.map(Number).join(', ')}</span>` : ''}</td></tr>`;
  }).join('');
  return head('Today', `Overdue first, then due today, then ready to start. ${esc(t.date)}`) +
    nwStatusPanel() + `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Your list</div><div class="panel-sub">${t.items.length} task${t.items.length === 1 ? '' : 's'}. Closing a task still needs everything it depends on to be done.</div></div></div>` +
    (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>When</th><th>Task</th><th>Project</th><th>Due</th><th>Blocked</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : empty('☑', 'Nothing needs you today', 'No overdue or due-today tasks, and nothing newly ready to start.')) + '</section>';
}

// ------------------------------------------------------------------ Evening status (the 7 pm reply, sorted under the evening headings)
function nwStatusPanel() {
  if (state.user?.role === 'viewer') return '';
  const r = state.nw.status;
  const rows = !r ? '' : `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>You said</th><th>Filed under</th><th>What happened</th></tr></thead><tbody>${r.pieces.map(p =>
    `<tr><td>${esc(p.text)}</td><td>${p.needs_review ? pill('Not sure', 'warn') : pill(p.label, 'gray')}</td><td>${esc(p.detail || '')}${p.ticket_id ? ` <span class="muted">(change request #${Number(p.ticket_id)})</span>` : ''}</td></tr>`).join('')}</tbody></table></div>` +
    `<p class="muted">${Number(r.drafts)} draft${r.drafts === 1 ? '' : 's'} opened for approval. Nothing is saved until it is approved.</p>`;
  return `<section class="panel"><div class="panel-head"><div><div class="panel-title">Evening status</div><div class="panel-sub">Say what happened today in your own words. It is sorted under the evening headings; clear matches become drafts for approval.</div></div></div><div class="panel-body">` +
    `<form id="nwStatusForm"><textarea class="form-input" name="text" rows="4" maxlength="4000" placeholder="e.g. Slab pour completed at Villa B. Paid Rs 25,000 to the tile vendor. Will visit tomorrow." aria-label="Your evening status" required></textarea>` +
    `<button class="btn btn-primary" type="submit">Sort my reply</button></form>${rows}</div></section>`;
}

// ------------------------------------------------------------------ My time
async function nwLoadTime() {
  const [timer, entries, cal, settings] = await Promise.all([nwApi('/api/time/timer'), nwApi('/api/time/entries'), nwApi('/api/time/calendar'), nwApi('/api/time/settings')]);
  state.nw.time = {timer, entries, cal, settings};
}

function nwTimerPanel(tm) {
  if (tm.running) {
    const tObj = tm.task_id ? (state.tasks || []).find(t => Number(t.id) === Number(tm.task_id)) : null;
    const targetLabel = tm.task_id ? (tObj ? esc(tObj.title) : 'task ' + Number(tm.task_id)) : esc(tm.activity);
    return `<div class="panel-body"><p><strong>Timer running</strong> on ${targetLabel}, since ${esc(time(tm.started_at))} · Elapsed: <strong id="nwTimerElapsed" data-started="${esc(tm.started_at)}">${esc(nwMins(nwElapsedMinutes(tm.started_at)))}</strong>.</p>` +
      `<button class="btn btn-primary" data-nw="stop">Stop and draft the entry</button> <button class="btn btn-secondary" data-nw="discard">Discard</button>` +
      `<p class="muted">Stopping drafts a time entry. Nothing is recorded until it is approved.</p></div>`;
  }
  const openTasks = (state.tasks || []).filter(t => t.status !== 'done');
  const taskControl = openTasks.length
    ? `<select class="form-input" name="task_id" aria-label="Task"><option value="">Choose a task (optional)</option>${openTasks.map(t => `<option value="${Number(t.id)}">#${Number(t.id)} · ${esc(t.title)}${t.project ? ' (' + esc(t.project) + ')' : ''}</option>`).join('')}</select>`
    : `<input class="form-input" name="task_id" inputmode="numeric" placeholder="Task number" aria-label="Task number">`;
  return `<form class="panel-body" id="nwTimerForm"><div class="v-ask">${taskControl}` +
    `<input class="form-input" name="activity" maxlength="80" placeholder="or a general activity, e.g. site visit" aria-label="General activity">` +
    `<button class="btn btn-primary" type="submit">Start timer</button></div><p class="muted">Pick one: a task, or a named activity.</p></form>`;
}

function nwWorkloadPanel() {
  if (!['admin', 'manager', 'architect'].includes(state.user?.role)) return '';
  const r = state.nw.workload;
  const out = !r ? '' : `<div class="w-sub">Result</div>` + (r.warnings.length ? `<ul>${r.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '<p>No load or leave problem found.</p>') +
    `<p class="muted">Busiest day: ${esc(nwMins(r.peak_minutes))}.${r.overloaded_days.length ? ' Over capacity on ' + r.overloaded_days.map(esc).join(', ') + '.' : ''}${r.person_known ? '' : ' That person was not found, so leave is not considered.'}</p>`;
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Check workload before assigning</div><div class="panel-sub">Warns about load and leave. It never blocks.</div></div></div><div class="panel-body">` +
    `<form id="nwWorkloadForm" class="v-ask"><input class="form-input" name="assignee" maxlength="80" placeholder="Person" aria-label="Person" required>` +
    `<input class="form-input" name="due" type="date" aria-label="Due date" required><input class="form-input" name="start" type="date" aria-label="Start date (optional)">` +
    `<input class="form-input" name="hours" inputmode="decimal" placeholder="Estimate in hours" aria-label="Estimate in hours"><button class="btn btn-secondary" type="submit">Check</button></form>${out}</div></section>`;
}

function nwTimeView() {
  if (!state.nw.time) {
    nwLoadTime().then(render).catch(err => { state.nw.time = {timer: {running: false}, entries: [], cal: {holidays: [], leave: []}, settings: {}}; notify(err.message, true); render(); });
    return head('My time', 'Timer, entries and leave.') + '<div class="loading">Loading…</div>';
  }
  const {timer, entries, cal, settings} = state.nw.time;
  const money = entries.some(e => 'cost_paise' in e);
  const rows = entries.slice(0, 40).map(e => `<tr><td>${esc(e.work_date)}</td><td>${e.task_id ? 'Task ' + Number(e.task_id) : esc(e.activity)}</td><td class="num">${esc(nwMins(e.minutes))}</td>` +
    `<td>${pill(NW_STATUS[e.status] || e.status, e.status === 'approved' ? 'good' : e.status === 'rejected' ? 'critical' : 'warn')}</td>${money ? `<td class="num">${esc(nwRs(e.cost_paise))}</td>` : ''}</tr>`).join('');
  const approved = entries.filter(e => e.status === 'approved').reduce((t, e) => t + e.minutes, 0);
  const leave = (cal.leave || []).map(l => `<li>${esc(l.start_date)} to ${esc(l.end_date)}${l.kind ? ' · ' + esc(l.kind) : ''}</li>`).join('');
  const hol = (cal.holidays || []).map(h => `<li>${esc(h.date)} · ${esc(h.name)}</li>`).join('');
  return head('My time', `Approved so far: ${esc(nwMins(approved))}. Limits: ${esc(nwMins(settings.time_daily_limit_minutes))} a day, ${esc(nwMins(settings.time_weekly_limit_minutes))} a week.`) +
    `<section class="panel"><div class="panel-head"><div><div class="panel-title">Timer</div><div class="panel-sub">One timer at a time.</div></div></div>${nwTimerPanel(timer)}</section>` +
    `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Time entries</div><div class="panel-sub">Newest first. Nobody approves their own time.</div></div></div>` +
    (rows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Date</th><th>On</th><th>Time</th><th>Status</th>${money ? '<th>Cost</th>' : ''}</tr></thead><tbody>${rows}</tbody></table></div>`
      : empty('◷', 'No time recorded yet', 'Start the timer, or ask in the chat to log time.')) + '</section>' +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Leave and holidays</div></div><div class="panel-body">` +
    (leave ? `<div class="w-sub">Leave</div><ul>${leave}</ul>` : '<p class="muted">No leave recorded.</p>') +
    (hol ? `<div class="w-sub">Holidays</div><ul>${hol}</ul>` : '') + '</div></section>' + nwWorkloadPanel();
}

// ------------------------------------------------------------------ Plan and budget (one project)
async function nwLoadPlan(pid) {
  const calls = [nwApi(`/api/work/projects/${pid}/structure`), nwApi(`/api/budgets/project/${pid}`).catch(() => null), nwApi(`/api/budgets/project/${pid}/money`).catch(() => null), nwApi('/api/work/templates').catch(() => [])];
  const [structure, budgets, money, templates] = await Promise.all(calls);
  state.nw.plan = {structure, budgets, money, templates: templates || [], projectId: pid};
}

function nwPlanBody(p) {
  const s = p.structure, stageName = id => (s.stages.find(x => x.id === id) || {}).name || 'No stage';
  const byStage = {};
  s.tasks.forEach(t => { (byStage[t.stage_id ?? 'none'] = byStage[t.stage_id ?? 'none'] || []).push(t); });
  const order = s.stages.map(x => x.id).concat(byStage.none ? ['none'] : []);
  const stages = order.filter(k => byStage[k]).map(k => `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">${esc(k === 'none' ? 'No stage' : stageName(k) + ' (stage ' + k + ')')}</div></div><div class="w-table-wrap"><table class="w-table"><thead><tr><th>Task</th><th>Status</th><th>Due</th><th>Slipped</th><th>Blocked by</th></tr></thead><tbody>${byStage[k].map(t =>
    `<tr><td>${esc(t.title)}</td><td>${esc(t.status)}</td><td>${esc(t.due_date || '—')}</td><td>${t.slipped_days ? pill(t.slipped_days + ' day' + (t.slipped_days === 1 ? '' : 's'), 'warn') : '—'}</td>` +
    `<td>${t.blocked_by.length ? esc(t.blocked_by.join(', ')) : '—'}</td></tr>`).join('')}</tbody></table></div></section>`).join('');
  const b = p.budgets, m = p.money;
  const budgetRows = b ? b.budgets.map(x => `<tr><td>${esc(x.scope === 'project' ? 'Whole project' : x.scope + ' ' + (x.ref_id ?? ''))}</td><td class="num">${esc(nwRs(x.budget_paise))}</td><td class="num">${esc(nwRs(x.actual_paise))}${x.expense_basis==='posted_books'?'<div class="muted">Expenses from the books</div>':x.expense_basis==='mixed'?'<div class="muted">Books and expenses still in the tracker</div>':''}</td><td class="num">${esc(nwRs(x.forecast_paise))}</td><td>${pill(NW_HEALTH[x.tag][0], NW_HEALTH[x.tag][1])}</td></tr>`).join('') : '';
  const open = b ? b.breaches.filter(x => x.open).length : 0;
  return (s.baseline ? `<p class="muted">Compared with baseline “${esc(s.baseline.label)}”, frozen ${esc(time(s.baseline.frozen_at))}.</p>` : '<p class="muted">No baseline frozen yet, so slip is not shown.</p>') +
    (stages || empty('◈', 'No tasks on this project', 'Add tasks and group them into stages.')) +
    (m ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Money view</div><div class="panel-sub">Invoiced and received are not shown until the books supply them.</div></div></div><div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(nwRs(m.contract_value_paise))}</div><div class="v-tile-label">Contract value</div></div><div class="v-tile"><div class="v-tile-value">${esc(nwRs(m.cost_to_date_paise))}</div><div class="v-tile-label">Cost to date</div></div></div></section>` : '') +
    (b ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Budgets</div><div class="panel-sub">${open} open breach${open === 1 ? '' : 'es'}. Rule: ${esc(b.breach_rule)}.</div></div></div>` +
      (budgetRows ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Budget</th><th>Planned</th><th>Actual</th><th>Forecast</th><th>State</th></tr></thead><tbody>${budgetRows}</tbody></table></div>` : empty('◫', 'No budgets set', 'Budgets are proposed as change requests.')) + '</section>' : '');
}

function nwPlanForms(pid) {
  if (!['admin', 'manager'].includes(state.user?.role)) return '';
  const plan = state.nw.plan || {};
  const tasks = (plan.structure && plan.structure.tasks) || [];
  const stages = (plan.structure && plan.structure.stages) || [];
  const templates = plan.templates || [];
  const taskOpts = tasks.map(t => `<option value="${Number(t.id)}">#${Number(t.id)} · ${esc(t.title)}</option>`).join('');
  const predCtrl = tasks.length ? `<select class="form-input" name="pred" aria-label="Task that must come first" required><option value="">Task that must come first…</option>${taskOpts}</select>` : `<input class="form-input" name="pred" inputmode="numeric" placeholder="Task that must come first (number)" aria-label="Predecessor task number" required>`;
  const succCtrl = tasks.length ? `<select class="form-input" name="succ" aria-label="Task that depends on it" required><option value="">Task that depends on it…</option>${taskOpts}</select>` : `<input class="form-input" name="succ" inputmode="numeric" placeholder="Task that depends on it (number)" aria-label="Successor task number" required>`;
  const moveTaskCtrl = tasks.length ? `<select class="form-input" name="task" aria-label="Task" required><option value="">Choose a task…</option>${taskOpts}</select>` : `<input class="form-input" name="task" inputmode="numeric" placeholder="Task number" aria-label="Task number" required>`;
  const stageCtrl = stages.length ? `<select class="form-input" name="stage" aria-label="Stage" required><option value="">Choose a stage…</option>${stages.map(s => `<option value="${Number(s.id)}">${esc(s.name)}</option>`).join('')}</select>` : `<input class="form-input" name="stage" inputmode="numeric" placeholder="Stage number (see list above)" aria-label="Stage number" required>`;
  const tplCtrl = templates.length ? `<select class="form-input" name="template" aria-label="Project template" required><option value="">Choose a template…</option>${templates.map(t => `<option value="${esc(t.key)}">${esc(t.name)}</option>`).join('')}</select>` : `<input class="form-input" name="template" maxlength="60" placeholder="Template key (see Recycle and templates)" aria-label="Template key" required>`;
  return `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Propose a change</div><div class="panel-sub">Each opens a change request. Nothing changes until it is approved.</div></div></div><div class="panel-body">` +
    `<form id="nwLinkForm" class="v-ask">${predCtrl}${succCtrl}` +
    `<select class="form-input" name="kind" aria-label="Kind of link"><option value="hard">Hard: must finish first</option><option value="soft">Soft: should finish first</option><option value="related">Related</option><option value="duplicate">Duplicate</option></select>` +
    `<button class="btn btn-secondary" type="submit">Propose link</button></form>` +
    `<form id="nwStageForm" class="v-ask"><input class="form-input" name="name" maxlength="80" placeholder="New stage name" aria-label="Stage name" required><button class="btn btn-secondary" type="submit">Propose stage</button></form>` +
    `<form id="nwBaselineForm" class="v-ask"><input class="form-input" name="label" maxlength="80" placeholder="Baseline label, e.g. Approved plan" aria-label="Baseline label" required><button class="btn btn-secondary" type="submit">Propose baseline</button></form>` +
    `<form id="nwMoveForm" class="v-ask">${moveTaskCtrl}${stageCtrl}<button class="btn btn-secondary" type="submit">Propose move to stage</button></form>` +
    `<form id="nwTemplateForm" class="v-ask">${tplCtrl}` +
    `<input class="form-input" name="start" type="date" aria-label="Start date" required><button class="btn btn-secondary" type="submit">Propose applying the template</button></form>` +
    `</div></section>`;
}

function nwPlanView() {
  const projects = state.projects || [];
  const sel = `<select class="form-input" id="nwProject" aria-label="Project"><option value="">Choose a project</option>${projects.map(x => `<option value="${Number(x.id)}"${Number(state.nw.projectId) === Number(x.id) ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select>`;
  let body = '<p class="muted v-pad">Choose a project to see its stages, dependencies, budgets and money view.</p>';
  if (state.nw.projectId) {
    if (state.nw.plan && state.nw.plan.projectId === state.nw.projectId) body = nwPlanBody(state.nw.plan) + nwPlanForms(state.nw.projectId);
    else {
      const pid = state.nw.projectId;
      nwLoadPlan(pid).then(render).catch(err => { state.nw.plan = null; state.nw.projectId = null; notify(err.message, true); render(); });
      body = '<div class="loading">Loading…</div>';
    }
  }
  return head('Plan and budget', 'Stages, task dependencies, slip against the baseline, budgets and the money view.') + `<section class="panel v-pad">${sel}</section>` + body;
}

// ------------------------------------------------------------------ Recycle list and templates (admin, manager)
async function nwLoadRecycle() {
  const [recycle, templates, workflows] = await Promise.all([nwApi('/api/work/recycle'), nwApi('/api/work/templates'), nwApi('/api/work/workflows')]);
  state.nw.recycle = {recycle, templates, workflows};
}

function nwRecycleView() {
  if (!['admin', 'manager'].includes(state.user?.role)) return head('Recycle and templates', 'Only the Admin and managers can see this.');
  if (!state.nw.recycle) {
    nwLoadRecycle().then(render).catch(err => { state.nw.recycle = {recycle: {items: [], restore_days: 0}, templates: [], workflows: []}; notify(err.message, true); render(); });
    return head('Recycle and templates', 'Deleted tasks, project templates and workflows.') + '<div class="loading">Loading…</div>';
  }
  const {recycle, templates, workflows} = state.nw.recycle;
  const del = recycle.items.map(i => `<tr><td>Task ${Number(i.task_id)}</td><td>${esc(i.deleted_by)}</td><td>${esc(time(i.deleted_at))}</td><td>${esc(time(i.restore_until))}</td><td>${esc(i.reason || '—')}</td>` +
    `<td><button class="btn btn-secondary btn-sm" data-nw="restore" data-id="${Number(i.task_id)}">Propose restore</button></td></tr>`).join('');
  const list = (rows, noun) => rows.length ? `<ul>${rows.map(r => `<li><strong>${esc(r.name)}</strong> <span class="muted">${esc(r.key)} · version ${Number(r.version)}</span></li>`).join('')}</ul>` : `<p class="muted">No ${noun} yet. They are proposed as change requests.</p>`;
  return head('Recycle and templates', `A deleted task can be restored for ${Number(recycle.restore_days)} days.`) +
    `<section class="panel"><div class="panel-head"><div><div class="panel-title">Deleted tasks</div><div class="panel-sub">Restoring opens a change request; the task returns when it is approved.</div></div></div>` +
    (del ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Task</th><th>Deleted by</th><th>When</th><th>Restorable until</th><th>Reason</th><th></th></tr></thead><tbody>${del}</tbody></table></div>`
      : empty('♻', 'Nothing in the recycle list', 'Deleted tasks appear here until the restore window ends.')) + '</section>' +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Project templates</div></div><div class="panel-body">${list(templates, 'templates')}</div></section>` +
    `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">Workflows</div></div><div class="panel-body">${list(workflows, 'workflows')}</div></section>`;
}

// ------------------------------------------------------------------ Saved views (stored view specs, run through the report engine)
async function nwLoadViews() {
  state.nw.views = await nwApi('/api/viewspecs');
  try { state.nw.templates = await nwApi('/api/viewspecs/templates'); } catch (e) { state.nw.templates = []; }
}

function nwFeed(shown) {
  const res = (shown && shown.result) || {rows: [], column_labels: []};
  const rows = (res.rows || []).slice().reverse();                      // the report is oldest first; a feed shows the newest first
  if (!rows.length) return '<p class="muted">Nothing yet.</p>';
  return `<ul class="w-entries nw-feed">${rows.map(x => `<li><strong>${esc(x.cells[0])}</strong> ${x.cells.slice(1).map(c => esc(c)).join(' · ')}</li>`).join('')}</ul>`;
}

function nwViewsView() {
  if (!state.nw.views) {
    nwLoadViews().then(render).catch(err => { state.nw.views = []; notify(err.message, true); render(); });
    return head('Saved views', 'Views people have set up.') + '<div class="loading">Loading…</div>';
  }
  const list = state.nw.views.map(v => `<button class="w-type${state.nw.openView === v.key ? ' current' : ''}" data-nw="run-view" data-key="${esc(v.key)}"><strong>${esc(v.name)}</strong>` +
    `<span class="muted">${esc(v.primitive)} · version ${Number(v.version)} · ${esc(v.scope)}</span></button>`).join('');
  const r = state.nw.ran;
  const plain = r => `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">${esc(r.name)}</div><div class="panel-sub">Version ${Number(r.version)}. Only records you may see are shown.</div></div></div>` +
    `<div class="v-pad">${r.error ? `<p class="muted">${esc(r.error)}</p>` : r.primitive === 'feed' ? nwFeed(r.shown) : vRender(r.shown)}</div></section>`;
  // viewbar.js adds the filter bar, the look switcher and the builder; a feed, an error or a missing script keeps the plain panel
  const body = !r ? '' : (r.error || r.primitive === 'feed' || typeof fbRunPanel !== 'function') ? plain(r) : fbRunPanel(r);
  const tpl = (state.nw.templates || []).map(t => `<div class="approval-card ticket-list-row"><div><strong>${esc(t.title)}</strong> <span class="muted">${esc(t.primitive)}</span>${t.in_use ? ' ' + pill('In use', 'good') : ''}<p>${esc(t.about)}</p></div>` +
    `<div><button type="button" class="btn btn-secondary btn-sm" data-nw="use-template" data-key="${esc(t.key)}" data-scope="user">Add for me</button>` +
    `${['admin', 'manager'].includes(state.user?.role) && !t.in_use ? ` <button type="button" class="btn btn-primary btn-sm" data-nw="use-template" data-key="${esc(t.key)}" data-scope="system">Add for everyone</button>` : ''}</div></div>`).join('');
  const readyMade = tpl ? `<section class="panel section-gap"><div class="panel-head"><div><div class="panel-title">Ready-made views</div><div class="panel-sub">Adding one opens a change request; it appears once it is approved.</div></div></div><div class="panel-body">${tpl}</div></section>` : '';
  return head('Saved views', 'Views set up by your team, run for you with your own access. New views and changes go through a change request.') + (typeof fbBuilderPanel === 'function' ? fbBuilderPanel() : '') + readyMade +
    `<section class="panel"><div class="panel-head"><div class="panel-title">Views you can see</div></div><div class="w-types">${list || empty('◔', 'No saved views yet', 'A view is made by proposing it; an AI client can draft one for you to approve.')}</div></section>` + body;
}

// ------------------------------------------------------------------ wiring
const NW_VIEWS = {today: ['Today', nwTodayView], mytime: ['My time', nwTimeView], planbudget: ['Plan and budget', nwPlanView], recycle: ['Recycle and templates', nwRecycleView], savedviews: ['Saved views', nwViewsView]};
const _nwRender = render;
render = function () {
  const v = NW_VIEWS[state.view];
  if (!v) { _nwRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = v[1]().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / ' + v[0].toUpperCase());
  $('breadcrumb').textContent = v[0];
  document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
};

document.addEventListener('change', e => {
  if (e.target.id !== 'nwProject') return;
  state.nw.projectId = Number(e.target.value) || null;
  state.nw.plan = null;
  render();
});

document.addEventListener('submit', async e => {
  if (e.target.id !== 'nwTimerForm') return;
  e.preventDefault();
  const f = new FormData(e.target), tid = Number(f.get('task_id')) || 0, act = String(f.get('activity') || '').trim();
  try { await nwApi('/api/time/timer/start', tid ? {task_id: tid} : {activity: act}); state.nw.time = null; } catch (err) { notify(err.message, true); }
  render();
});

document.addEventListener('click', async e => {
  const nav = e.target.closest('[data-view="today"],[data-view="mytime"],[data-view="planbudget"],[data-view="recycle"],[data-view="savedviews"]');
  if (nav) { state.nw.views = null; state.nw.ran = null; state.nw.recycle = null; state.nw.today = null; state.nw.time = null; state.nw.plan = null; return; }
  const b = e.target.closest('[data-nw]');
  if (!b) return;
  e.preventDefault();
  try {
    b.disabled = true;
    if (b.dataset.nw === 'stop') {
      const r = await nwApi('/api/time/timer/stop', {});
      notify(`Drafted a ${nwMins(r.minutes)} entry (change request #${r.ticket_id}). It is recorded when approved.`);
    } else if (b.dataset.nw === 'restore') {
      const r = await nwApi('/api/work/propose', {kind: 'work_task_restore', data: {task_id: Number(b.dataset.id)}});
      notify(`Change request #${r.ticket_id} opened to restore task ${b.dataset.id}. It returns when approved.`);
      state.nw.recycle = null;
    } else if (b.dataset.nw === 'use-template') {
      const r = await nwApi(`/api/viewspecs/templates/${encodeURIComponent(b.dataset.key)}/propose`, {scope: b.dataset.scope});
      notify(`Change request #${r.ticket_id} opened. The view appears once it is approved.`);
      render();
      return;
    } else if (b.dataset.nw === 'run-view') {
      state.nw.openView = b.dataset.key;
      if (typeof fbReset === 'function') fbReset();
      try { state.nw.ran = await nwApi(`/api/viewspecs/${encodeURIComponent(b.dataset.key)}/run`); }
      catch (err) { state.nw.ran = {name: b.dataset.key, version: '', error: err.message}; }
      render();
      return;
    } else if (b.dataset.nw === 'discard') {
      if (typeof askConfirm === 'function' && !await askConfirm('Discard this running timer? The tracked time will not be saved.', 'Discard')) { b.disabled = false; return; }
      await nwApi('/api/time/timer/discard', {});
      notify('Timer discarded.');
    }
    state.nw.time = null;
    render();
  } catch (err) { b.disabled = false; notify(err.message, true); }
});

document.addEventListener('submit', async e => {
  const id = e.target.id;
  if (!['nwLinkForm', 'nwStageForm', 'nwBaselineForm', 'nwMoveForm', 'nwTemplateForm'].includes(id)) return;
  e.preventDefault();
  const f = new FormData(e.target), pid = state.nw.projectId;
  const body = id === 'nwLinkForm' ? {kind: 'work_link', data: {predecessor_id: Number(f.get('pred')), successor_id: Number(f.get('succ')), kind: String(f.get('kind'))}}
    : id === 'nwStageForm' ? {kind: 'work_stage', data: {project_id: pid, name: String(f.get('name')).trim(), client_visible: false}}
    : id === 'nwMoveForm' ? {kind: 'work_task_structure', data: {task_id: Number(f.get('task')), stage_id: Number(f.get('stage'))}}
    : id === 'nwTemplateForm' ? {kind: 'work_apply_template', data: {template_key: String(f.get('template')).trim(), project_id: pid, start_date: String(f.get('start'))}}
    : {kind: 'work_baseline', data: {project_id: pid, label: String(f.get('label')).trim()}};
  try {
    const r = await nwApi('/api/work/propose', body);
    notify(`Change request #${r.ticket_id} opened. Nothing changes until it is approved.`);
    e.target.reset();
  } catch (err) { notify(err.message, true); }
});

document.addEventListener('submit', async e => {
  if (e.target.id !== 'nwWorkloadForm') return;
  e.preventDefault();
  const f = new FormData(e.target);
  const q = new URLSearchParams({assignee: String(f.get('assignee')).trim(), due_date: String(f.get('due')), start_date: String(f.get('start') || ''),
    estimate_minutes: String(Math.round((Number(f.get('hours')) || 0) * 60))});
  try { state.nw.workload = await nwApi('/api/time/workload?' + q.toString()); } catch (err) { state.nw.workload = null; notify(err.message, true); }
  render();
});

// ------------------------------------------------------------------ view tickets: what the draft would show, and as another role (owner)
const _nwTicketDetail = ticketDetail;
ticketDetail = function (t) {
  const html = _nwTicketDetail(t);
  const views = (t.items || []).filter(i => String(i.item_type).startsWith('view_'));
  if (!views.length) return html;
  state.nw.vp = state.nw.vp || {};
  views.forEach(i => { state.nw.vp[i.id] = i.after; });
  return html + views.map(i => `<section class="panel section-gap vp-panel"><div class="panel-head"><div><div class="panel-title">Preview of item #${Number(i.id)}</div>` +
    `<div class="panel-sub">What this view would show, and what changes. ${state.user?.role === 'admin' ? 'Choose a role to see it as they would.' : ''}</div></div></div>` +
    `<div class="panel-body">${state.user?.role === 'admin' ? `<div class="ov-chips">${['', 'manager', 'architect', 'site_engineer', 'accounts'].map(r => `<button type="button" class="ov-chip" data-nw="vp-role" data-item="${Number(i.id)}" data-role="${r}" aria-pressed="${(state.nw.vpRole || '') === r}">${r ? esc(r.replace('_', ' ')) : 'Me'}</button>`).join('')}</div>` : ''}` +
    `<div class="vp-box" data-vp="${Number(i.id)}"><p class="muted">Loading the preview…</p></div></div></section>`).join('');
};

async function nwLoadPreviews() {
  for (const box of document.querySelectorAll('.vp-box[data-vp]')) {
    const id = box.dataset.vp, after = (state.nw.vp || {})[id];
    if (!after || box.dataset.loaded === (state.nw.vpRole || '') + '!') continue;
    box.dataset.loaded = (state.nw.vpRole || '') + '!';
    const body = after.spec ? {spec: after.spec} : {view_id: after.view_id, to_version: after.to_version};
    if (state.nw.vpRole) body.as_role = state.nw.vpRole;
    try {
      const r = await nwApi('/api/viewspecs/preview', body);
      box.innerHTML = (r.valid ? '' : `<div class="notice fail"><div><strong>Not valid</strong><ul>${r.errors.map(e => `<li>${esc(e.path)}: ${esc(e.message)}</li>`).join('')}</ul></div></div>`) +
        (r.diff.length ? `<div class="w-sub">Changes</div><ul>${r.diff.slice(0, 40).map(d => `<li><code>${esc(d)}</code></li>`).join('')}</ul>` : '') +
        (r.warnings.map(w => `<p class="preview-flag">⚑ ${esc(w)}</p>`).join('')) +
        (r.shown ? `<div class="w-sub">${r.as_role ? 'As ' + esc(r.as_role.replace('_', ' ')) + ' would see it' : 'What you would see'}</div>${vRender(r.shown)}` : '');
    } catch (err) { box.innerHTML = `<p class="muted">${esc(err.message)}</p>`; }
  }
}
onAfterRender(() => { setTimeout(nwLoadPreviews, 0); });
document.addEventListener('click', e => {
  const b = e.target.closest('[data-nw="vp-role"]');
  if (!b) return;
  state.nw.vpRole = b.dataset.role;
  document.querySelectorAll('.vp-box').forEach(x => { delete x.dataset.loaded; });
  document.querySelectorAll('[data-nw="vp-role"]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.role === (state.nw.vpRole || ''))));
  nwLoadPreviews();
});
document.addEventListener('submit', async e => {
  if (e.target.id !== 'nwStatusForm') return;
  e.preventDefault();
  const text = String(new FormData(e.target).get('text') || '').trim();
  try { state.nw.status = await nwApi('/api/rhythm/status/reply', {text}); } catch (err) { state.nw.status = null; notify(err.message, true); }
  render();
});
