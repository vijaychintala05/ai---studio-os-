'use strict';
/* StudioOS v0.15.0 "Self-check": what needs attention (backups, scheduled jobs, waiting tickets,
   unknown senders, AI spending, disk, OCR), this week's suggestions with their evidence (accept =
   a ticket, "Not useful" = never again), your summaries, and a weekly review draft from the week's
   records (facts only; the manager writes the judgement). Loaded after app.js and graph.js. */

Object.assign(state, {im: {health: null, sugg: null, mine: null, staff: null, facts: null, reviewTicketId: null}});

const imApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const IM_LEVEL = {ok: 'OK', warn: 'Look at this', fail: 'Needs action'};
const IM_JOBS = {
  daily_rules: 'Daily rule checks',
  email_poll: 'Check incoming e-mail',
  summaries_daily: 'Daily summaries',
  suggestions: 'Weekly suggestions',
};

function imLocalDate(d) {
  const dt = d || new Date();
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
}

async function imLoad() {
  const im = state.im;
  const jobs = [imApi('/api/improve/summaries/mine').then(x => { im.mine = x.summaries; })];
  if (isAdmin()) jobs.push(imApi('/api/improve/health').then(x => { im.health = x; }), imApi('/api/improve/suggestions').then(x => { im.sugg = x.suggestions; }));
  if (['admin', 'manager'].includes(state.user?.role)) jobs.push(api('/api/graph/targets/system.user').then(x => { im.staff = x; }).catch(() => { im.staff = []; }));
  await Promise.all(jobs);
  im.loaded = true;
}

function imEvidence(e) {
  if (!e) return '';
  if (e.values) return 'Seen: ' + Object.entries(e.values).map(([k, v]) => `“${esc(k)}” ${Number(v)}×`).join(', ');
  if (e.records !== undefined) return `Empty in ${Number(e.empty)} of ${Number(e.records)} records`;
  if (e.asked) return `Asked ${Number(e.asked)} times, e.g. ${(e.examples || []).map(x => '“' + esc(x) + '”').join(', ')}`;
  if (e.times) return `Corrected ${Number(e.times)} times`;
  return '';
}

function imView() {
  const im = state.im;
  if (!im.loaded) { imLoad().then(render).catch(err => notify(err.message, true)); return head('Self-check', 'Loading…') + '<div class="loading">Loading…</div>'; }
  const h = im.health;
  const today = imLocalDate();
  return head('Self-check', 'What needs attention, what StudioOS suggests, and your summaries.') +
    (h ? `<section class="panel"><div class="panel-head"><div><div class="panel-title">Health <span class="im-badge im-${esc(h.overall)}">${esc(IM_LEVEL[h.overall] || h.overall)}</span></div></div></div>
      <ul class="im-checks">${h.checks.map(c => `<li class="im-${esc(c.level)}"><span class="im-dot" aria-hidden="true"></span><span><strong>${esc(c.title)}</strong><br><span class="muted">${esc(c.detail)}${c.action ? ' · ' + esc(c.action) : ''}</span></span></li>`).join('')}</ul>
      ${h.failures.length ? `<details class="rs-bad v-pad"><summary>Recent failed jobs</summary><ul>${h.failures.map(f => `<li>${esc(IM_JOBS[f.job] || f.job)} · ${esc((f.at || '').slice(0, 16))}: ${esc(f.detail)}</li>`).join('')}</ul></details>` : ''}
      <div class="v-pad im-jobs">${['daily_rules', 'email_poll', 'summaries_daily', 'suggestions'].map(j => `<button class="btn btn-secondary btn-sm" data-im="run" data-job="${j}">Run ${esc(IM_JOBS[j] || j.replace(/_/g, ' '))}</button>`).join(' ')}</div></section>` : '') +
    (im.sugg ? `<section class="panel"><div class="panel-head"><div><div class="panel-title">Suggestions</div><div class="panel-sub">At most 5 a week, each with its evidence. Accepting opens a ticket; nothing changes until it is approved.</div></div></div>
      ${im.sugg.filter(s => s.status === 'open').length ? `<ul class="rs-history">${im.sugg.filter(s => s.status === 'open').map(s => `<li><span><strong>${esc(s.title)}</strong><br><span class="muted">${imEvidence(s.evidence)}</span></span>
        <span><button class="btn btn-primary btn-sm" data-im="accept" data-id="${Number(s.id)}">Propose</button> <button class="btn btn-secondary btn-sm" data-im="dismiss" data-id="${Number(s.id)}">Not useful</button></span></li>`).join('')}</ul>`
        : '<p class="muted v-pad">No open suggestions.</p>'}</section>` : '') +
    (im.staff ? `<section class="panel v-pad"><div class="panel-title">Weekly review draft</div><p class="muted">Facts from attendance, timesheets, issues and SOP runs. Achievements, improvements and rating are left for you.</p>
      <form id="imReview" class="ib-actions"><label>Staff member<select class="form-input" name="employee">${im.staff.map(s => `<option value="${Number(s.id)}">${esc(s.label)}</option>`).join('')}</select></label>
      <label>Week of<input class="form-input" type="date" name="week" value="${today}"></label><button class="btn btn-primary btn-sm" type="submit">Prepare draft</button></form>
      ${im.reviewTicketId ? `<p class="muted">Change request #${Number(im.reviewTicketId)} opened. <button class="cx-link" type="button" data-im="open-ticket" data-id="${Number(im.reviewTicketId)}">Open change request</button></p>` : ''}
      ${im.facts ? `<pre class="rs-change">${esc(im.facts)}</pre>` : ''}</section>` : '') +
    `<section class="panel"><div class="panel-head"><div class="panel-title">My summaries</div></div>${(im.mine || []).length ? `<ul class="rs-history">${im.mine.map(m =>
      `<li><details><summary>${esc(m.summary)} · ${esc(m.period)}</summary><pre class="rs-change">${esc(m.text)}</pre></details></li>`).join('')}</ul>` : '<p class="muted v-pad">No summaries yet.</p>'}</section>`;
}

const _imRender = render;
render = function () {
  if (state.view === 'selfcheck') {
    document.body.classList.remove('chat-mode');
    updateIdentity();
    $('mainContent').innerHTML = imView();
    $('breadcrumb').textContent = 'Self-check';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _imRender();
};

document.addEventListener('submit', async e => {
  if (e.target.id !== 'imReview') return;
  e.preventDefault();
  const f = new FormData(e.target);
  const btn = e.target.querySelector('[type="submit"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Preparing…'; }
  try {
    const r = await imApi('/api/improve/review-draft', {employee_id: Number(f.get('employee')), week_start: String(f.get('week'))});
    state.im.facts = r.facts.text;
    state.im.reviewTicketId = r.ticket_id;
    notify(`Change request #${r.ticket_id} opened with the week's facts. Add your judgement on the draft before approving.`);
    render();
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = 'Prepare draft'; }
    notify(err.message, true);
  }
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="selfcheck"]')) { state.im.loaded = false; state.im.facts = null; state.im.reviewTicketId = null; return; }
  const b = e.target.closest('[data-im]');
  if (!b) return;
  e.preventDefault();
  try {
    if (b.dataset.im === 'open-ticket') {
      state.ticketDetail = await api('/api/tickets/' + Number(b.dataset.id));
      state.view = 'tickets';
      render();
      document.getElementById('ticketReview')?.scrollIntoView({behavior: 'smooth'});
      return;
    }
    b.disabled = true;
    if (b.dataset.im === 'accept') {
      const r = await imApi(`/api/improve/suggestions/${b.dataset.id}/accept`, {});
      notify(`Change request #${r.ticket_id} opened.`);
    } else if (b.dataset.im === 'dismiss') {
      await imApi(`/api/improve/suggestions/${b.dataset.id}/dismiss`, {});
      notify('StudioOS will not suggest this again.');
    } else if (b.dataset.im === 'run') {
      const r = await imApi(`/api/improve/jobs/${b.dataset.job}/run`, {});
      notify(`${IM_JOBS[r.job] || r.job.replace(/_/g, ' ')}: ${r.outcome} (${r.detail})`, r.outcome !== 'ok');
    }
    await imLoad(); render();
  } catch (err) { b.disabled = false; notify(err.message, true); }
});
