'use strict';
/* Projects -> Status and links (Admin, Manager): status across projects, documents due and outgoing links.
   Settings -> Admin tools (Admin): history check, scheduled jobs and rules, mail intake, record systems and
   correcting an older cost. Settings -> Record designer tools (Admin): field dictionary, approved designs and the
   checks on a waiting record design. Loaded after gapkit.js. */

const MT_JOBS = [['rhythm_morning', 'Morning to-do lists'], ['rhythm_status', 'Evening status question'], ['rhythm_owner', 'Owner summary'], ['rhythm_evening', 'Evening summary']];
const MT_LEVELS = [['optional', 'Optional'], ['draft', 'Required to save a draft'], ['approve', 'Required to approve'], ['close', 'Required to close']];
const mtPost = (url, body) => api(url, {method: 'POST', body: JSON.stringify(body || {})});
const mtShow = key => state.gk.ui[key] === undefined ? '' : `<pre class="gk-result">${esc(JSON.stringify(state.gk.ui[key], null, 2))}</pre>`;
const mtList = value => Array.isArray(value) ? value : (value && (value.records || value.items || value.types)) || [];
const mtJson = (key, url) => { const v = gkGet(key, () => api(url)); return v === undefined || (v && v.gkError) ? gkWait(v) : `<pre class="gk-result">${esc(JSON.stringify(v, null, 2))}</pre>`; };

/* ------------------------------------------------------------ Status and links ------------------------ */
function mtStatusView() {
  const ui = state.gk.ui;
  const health = gkGet('mt:health', () => api('/api/rhythm/projects'));
  let status = gkWait(health);
  if (health && health.projects) {
    status = gkTable(['Project', 'Health'], health.projects.map(p => {
      const {project, project_id: id, ...rest} = p;
      return [esc(project || `Project ${id}`), esc(Object.entries(rest).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · '))];
    }), 'No project to report on.');
  }
  const projects = gkGet('mt:projects', () => api('/api/projects'));
  let due = gkWait(projects);
  if (Array.isArray(projects) && projects.length) {
    if (!projects.some(p => p.id === ui.mtProject)) ui.mtProject = projects[0].id;
    const found = gkGet(`mt:due:${ui.mtProject}`, () => api(`/api/universal/documents/due?project_id=${Number(ui.mtProject)}`));
    due = `<div class="g-form">${gkSelect('Project', 'project', projects.map(p => [p.id, p.name]), ui.mtProject, 'data-gk-change="project"')}</div>` +
      (found && found.due ? gkTable(['Document', 'How often', 'Due', 'State'], found.due.map(d => [esc(d.template_key), esc(d.cadence), esc(String(d.due_at).slice(0, 10)),
        d.is_due ? pill('Due now', 'warn') : pill('Not yet', 'good')]), 'No repeating document is set up.') : gkWait(found));
  } else if (Array.isArray(projects)) due = '<p class="muted">No project yet.</p>';
  const tasks = (state.tasks || []).map(t => [`system.task:${t.id}`, `Task: ${t.title}`]);
  const people = (state.users || []).map(u => [`system.user:${u.id}`, `Person: ${u.display_name}`]);
  const targets = [...tasks, ...people];
  const links = targets.length ? gkForm('linksFrom', gkSelect('Start from', 'from', targets, targets[0][0]), 'Show its links') + mtShow('mtLinks')
    : '<p class="muted">No task or person to start from.</p>';
  const types = gkGet('mt:types', () => api('/api/universal/types'));
  let records = gkWait(types);
  const typeList = mtList(types);
  if (types && !types.gkError) {
    if (!typeList.some(t => t.key === ui.mtType)) ui.mtType = typeList[0]?.key || null;
    if (!ui.mtType) records = '<p class="muted">No other record type yet.</p>';
    else {
      const rows = gkGet(`mt:records:${ui.mtType}`, () => api(`/api/universal/records/${encodeURIComponent(ui.mtType)}`));
      const list = mtList(rows);
      records = `<div class="g-form">${gkSelect('Record type', 'type', typeList.map(t => [t.key, t.label || t.name || t.key]), ui.mtType, 'data-gk-change="type"')}</div>` +
        (rows === undefined || (rows && rows.gkError) ? gkWait(rows) : list.length
          ? gkForm('recordLinks', gkSelect('Record', 'record', list.map(r => [r.id, r.title || r.label || r.name || `Record ${r.id}`]), list[0].id), 'Show its links') + mtShow('mtRecordLinks')
          : '<p class="muted">No record of this type.</p>');
    }
  }
  return head('Status and links', 'Where projects stand, what is due, and what connects to what.') + gkPanel('Status across projects', '', status) +
    gkPanel('Documents due', 'Repeating documents are never issued by themselves.', due) + gkPanel('Links from a task or person', '', links) +
    gkPanel('Links from a record', '', records);
}

gkScreen('projectstatus', {
  title: 'Status and links', roles: ['admin', 'manager'], view: mtStatusView,
  change: {project: el => { state.gk.ui.mtProject = Number(el.value); }, type: el => { state.gk.ui.mtType = el.value; state.gk.ui.mtRecordLinks = undefined; }},
  submit: {
    linksFrom: async form => { const [kind, id] = gkValues(form).from.split(':'); state.gk.ui.mtLinks = await api(`/api/graph/links-from/${encodeURIComponent(kind)}/${Number(id)}`); },
    recordLinks: async form => { state.gk.ui.mtRecordLinks = await api(`/api/universal/links/from/${Number(gkValues(form).record)}`); },
  },
});

/* ------------------------------------------------------------ Admin tools ----------------------------- */
function mtAdminView() {
  const ui = state.gk.ui;
  const costs = (state.costs || []).slice(0, 200);
  const people = (state.users || []).filter(u => u.active !== false);
  const catalog = gkGet('mt:catalog', () => api('/api/graph/catalog'));
  const packs = (catalog && !catalog.gkError && catalog.packs ? (Array.isArray(catalog.packs) ? catalog.packs : Object.values(catalog.packs)) : []).filter(p => p.key);
  const correct = costs.length ? gkForm('correct', gkSelect('Cost', 'cost', costs.map(c => [c.id, `${c.title} · Rs ${c.amount ?? ''}`]), costs[0].id) +
    gkInput('Correct amount (₹)', 'amount', 'required inputmode="decimal"') + gkInput('Why (at least 5 characters)', 'reason', 'required minlength="5" maxlength="300"'), 'Draft correction')
    : '<p class="muted">No older cost to correct.</p>';
  return head('Admin tools', 'Checks and one-off jobs.') +
    gkPanel('Check history has not been changed', 'Looks for edited, removed or inserted conversation and audit entries.',
      gkButton('integrity', 'Check now', '', true) + (ui.mtIntegrity === undefined ? '' : mtShow('mtIntegrity'))) +
    gkPanel('Run a scheduled job now', 'Jobs normally run by themselves.', `<div class="row-actions">${MT_JOBS.map(([k, label]) => gkButton('job', label, `data-job="${k}"`)).join(' ')}</div>` +
      `<div class="row-actions">${gkButton('rules', 'Run daily record rules')}</div>` + mtShow('mtRan')) +
    gkPanel('E-mail and WhatsApp intake', 'Only listed senders are accepted.', (people.length ? gkForm('sender', gkInput('E-mail address or phone number', 'address', 'required minlength="5" maxlength="120"') +
      gkSelect('Belongs to', 'user_id', people.map(u => [u.id, u.display_name]), people[0].id), 'Allow this sender') : '') + gkButton('poll', 'Check e-mail now') + mtShow('mtMail')) +
    gkPanel('Correct an older cost', 'From Budgets and costs. The old entry is kept; the correction needs approval.', correct) +
    gkPanel('Record systems and packs', '', mtJson('mt:systems', '/api/graph/systems') +
      (packs.length ? gkForm('pack', gkSelect('Pack', 'key', packs.map(p => [p.key, p.title || p.key]), packs[0].key), 'Show pack') + mtShow('mtPack') : ''));
}

gkScreen('admintools', {
  title: 'Admin tools', roles: ['admin'], view: mtAdminView,
  click: {
    integrity: async () => { state.gk.ui.mtIntegrity = await api('/api/system/integrity'); },
    job: async el => {
      if (!await askConfirm('Run this job now? It may send messages or create summaries again.', 'Run now')) return;
      state.gk.ui.mtRan = await mtPost(`/api/rhythm/run/${encodeURIComponent(el.dataset.job)}`);
    },
    rules: async () => { if (await askConfirm('Run the daily record rules now?', 'Run now')) state.gk.ui.mtRan = await mtPost('/api/graph/rules/run'); },
    poll: async () => { state.gk.ui.mtMail = await mtPost('/api/intake/email/poll'); },
  },
  submit: {
    sender: async form => { const v = gkValues(form); await mtPost('/api/intake/senders', {address: v.address, user_id: Number(v.user_id)}); notify('Sender allowed.'); },
    correct: async form => { const v = gkValues(form); await gkDraft(`/api/costs/${Number(v.cost)}/correct`, {new_amount: v.amount, reason: v.reason}, 'Correction drafted'); },
    pack: async form => { state.gk.ui.mtPack = await api(`/api/graph/packs/${encodeURIComponent(gkValues(form).key)}`); },
  },
});

/* ------------------------------------------------------------ Record designer tools ------------------- */
function mtTypesView() {
  const ui = state.gk.ui;
  const inbox = gkGet('mt:inbox', () => api('/api/new-types/inbox'));
  const items = mtList(inbox);
  let waiting = gkWait(inbox);
  if (inbox && !inbox.gkError) {
    if (!items.some(x => x.id === ui.mtItem)) ui.mtItem = items[0]?.id || null;
    if (!ui.mtItem) waiting = '<p class="muted">Nothing is waiting for a place.</p>';
    else {
      const item = items.find(x => x.id === ui.mtItem);
      const files = (item.attachments || []).map(f => `<li><a class="cx-link" href="/api/new-types/${Number(ui.mtItem)}/attachments/${encodeURIComponent(f.sha256)}" target="_blank" rel="noopener">${esc(f.filename)}</a></li>`).join('');
      const fields = (item.proposal?.fields || []).map(f => [f.name, f.name]);
      waiting = `<div class="g-form">${gkSelect('Waiting item', 'item', items.map(x => [x.id, `#${x.id} ${String(x.raw_payload?.text || x.raw_payload || x.state || '').slice(0, 60)}`]), ui.mtItem, 'data-gk-change="item"')}</div>` +
        (files ? `<ul>${files}</ul>` : '') + gkButton('capability', 'Show proposed capability') + mtShow('mtCapability') +
        gkForm('record', '<label class="g-field"><span>Sample record (JSON)</span><textarea class="form-input" name="record" rows="4">{}</textarea></label>' +
          gkSelect('Check', 'mode', [['validate-record', 'Strict check before approval'], ['capability-preview', 'Preview the capability']], 'validate-record'), 'Run check') + mtShow('mtChecked') +
        (fields.length ? gkForm('rule', gkSelect('Field', 'field', fields, fields[0][0]) + gkSelect('Should be', 'required_level', MT_LEVELS, 'approve') +
          gkInput('What this affects (at least 20 characters)', 'impact_plan', 'required minlength="20" maxlength="4000"'), 'Draft required-field change') : '');
    }
  }
  return head('Record designer tools', 'Help for designing new kinds of records. Nothing here changes data by itself.') +
    gkPanel('What could this information do?', 'Describe it; this only analyses.', gkForm('analyse', gkInput('Describe the information', 'text', 'required maxlength="10000"'), 'Analyse') + mtShow('mtAnalysis')) +
    gkPanel('Waiting items', '', waiting) + gkPanel('Field dictionary', 'Reuse these names.', mtJson('mt:dictionary', '/api/new-types/dictionary')) +
    gkPanel('Approved designs', '', mtJson('mt:designs', '/api/new-types/approved-designs'));
}

gkScreen('typetools', {
  title: 'Record designer tools', roles: ['admin'], view: mtTypesView,
  change: {item: el => Object.assign(state.gk.ui, {mtItem: Number(el.value), mtCapability: undefined, mtChecked: undefined})},
  click: {capability: async () => { state.gk.ui.mtCapability = await api(`/api/new-types/${Number(state.gk.ui.mtItem)}/capability`); }},
  submit: {
    analyse: async form => { state.gk.ui.mtAnalysis = await mtPost('/api/new-types/analyze-capability', {text: gkValues(form).text}); },
    record: async form => {
      const v = gkValues(form);
      let record;
      try { record = JSON.parse(v.record || '{}'); } catch (_) { throw new Error('The sample record is not valid JSON.'); }
      const mode = v.mode === 'capability-preview' ? 'capability-preview' : 'validate-record';
      state.gk.ui.mtChecked = await mtPost(`/api/new-types/${Number(state.gk.ui.mtItem)}/${mode}`, {record, phase: 'approve'});
    },
    rule: async form => {
      const v = gkValues(form);
      const r = await mtPost(`/api/new-types/${Number(state.gk.ui.mtItem)}/propose-required-rule-change`, {field: v.field, required_level: v.required_level, impact_plan: v.impact_plan});
      refresh();
      notify(r.ticket_id ? `Drafted as change request #${r.ticket_id}. Existing rules are unchanged until it is approved.` : 'Change proposed. Existing rules are unchanged.');
    },
  },
});
