'use strict';
/* StudioOS project page (App Flows map): one project's home with a title block, health and the sections its role may see: Tasks, Snags,
   Site, Money, Files, People. Opened from a project card. A thin strip at the top says which project you are looking at, with one tap to
   go back to all projects. Read-only; every change is still a ticket. No inline styles (strict CSP). Loaded after app.js and newwork.js. */

Object.assign(state, {pp: {id: null, data: null, chat: null, accounting: null, tab: 'overview'}});

const PP_HEALTH = {on_track: ['On track', 'good'], at_risk: ['At risk', 'warn'], delayed: ['Delayed', 'critical']};
const PP_TITLES = {tasks: 'Tasks', snags: 'Snags', site: 'Site', money: 'Money & Accounting', files: 'Files', people: 'People'};
const ppRs = p => inr(Number(p || 0) / 100);
const ppContactRole = role => ({vendor:'Vendor', consultant:'Consultant', contractor:'Contractor', 'co-client':'Co-client', client:'Client'})[role] || role;

async function ppLoad(id) {
  state.pp.data = await api(`/api/projects/${Number(id)}/page`);
  state.pp.accounting = null;
  if (['admin', 'accounts', 'manager'].includes(state.user?.role)) {
    try { state.pp.accounting = await api(`/api/books/projects/${Number(id)}/accounting`); } catch (e) { state.pp.accounting = null; }
  }
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
    const base = `<div class="v-tiles"><div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.budget_paise))}</div><div class="v-tile-label">Contract value</div></div>` +
      `<div class="v-tile"><div class="v-tile-value">${esc(ppRs(d.cost_to_date_paise))}</div><div class="v-tile-label">Cost to date · Posted in Books</div></div></div>`;
    const acc = state.pp.accounting;
    if (!acc) return base;
    const netTone = (acc.profit?.net_profit_paise || 0) >= 0 ? 'sense-pos' : 'sense-neg';
    const kpis = `<div class="sense-kpi-grid section-gap">` +
      `<div class="sense-kpi"><div class="sense-kpi-label">PO Committed</div><div class="sense-kpi-val">${esc(ppRs(acc.purchase_orders?.committed_paise))}</div><div class="sense-kpi-sub">Remaining ${esc(ppRs(acc.purchase_orders?.remaining_paise))}</div></div>` +
      `<div class="sense-kpi"><div class="sense-kpi-label">Supplier Bills</div><div class="sense-kpi-val">${esc(ppRs(acc.bills?.total_paise))}</div><div class="sense-kpi-sub">Owed ${esc(ppRs(acc.bills?.owed_paise))}</div></div>` +
      `<div class="sense-kpi"><div class="sense-kpi-label">Client Invoiced</div><div class="sense-kpi-val">${esc(ppRs(acc.invoices?.invoiced_paise))}</div><div class="sense-kpi-sub">Collected ${esc(ppRs(acc.invoices?.collected_paise))}</div></div>` +
      `<div class="sense-kpi"><div class="sense-kpi-label">Net Project Profit</div><div class="sense-kpi-val ${netTone}">${esc(ppRs(acc.profit?.net_profit_paise))}</div><div class="sense-kpi-sub">Gross ${esc(ppRs(acc.profit?.gross_profit_paise))}</div></div>` +
      `</div>`;
    const poRows = (acc.purchase_orders?.items || []).map(po =>
      `<tr><td><span class="code-mono">${esc(po.po_number)}</span></td><td>${esc(po.status)}</td><td class="num">${esc(ppRs(po.committed_paise))}</td><td class="num">${esc(ppRs(po.remaining_paise))}</td><td><a class="btn btn-secondary btn-sm" href="/api/books/purchase-orders/${Number(po.id)}/pdf" target="_blank" rel="noopener">PO PDF</a></td></tr>`
    ).join('');
    const billRows = (acc.bills?.items || []).map(b =>
      `<tr><td><span class="code-mono">${esc(b.invoice_number)}</span></td><td>${esc(b.bill_date || '—')}</td><td class="num">${esc(ppRs(b.amount_paise))}</td><td class="num">${esc(ppRs(b.owed_paise))}</td><td><a class="btn btn-secondary btn-sm" href="/api/books/bills/${Number(b.id)}/pdf" target="_blank" rel="noopener">Bill PDF</a></td></tr>`
    ).join('');
    return base + kpis +
      (poRows ? `<div class="w-sub">Purchase orders</div><div class="w-table-wrap"><table class="w-table"><thead><tr><th>PO</th><th>Status</th><th>Committed</th><th>Remaining</th><th></th></tr></thead><tbody>${poRows}</tbody></table></div>` : '') +
      (billRows ? `<div class="w-sub">Supplier bills</div><div class="w-table-wrap"><table class="w-table"><thead><tr><th>Invoice</th><th>Date</th><th>Total</th><th>Owed</th><th></th></tr></thead><tbody>${billRows}</tbody></table></div>` : '');
  }
  if (key === 'files') {
    return d.items.length ? `<ul class="w-entries">${d.items.map(f => `<li>${esc(f.name)} <span class="muted">${esc(f.type)}</span></li>`).join('')}</ul>` : empty('▥', 'No files indexed', 'Files found on the NAS for this project appear here.');
  }
  if (key === 'people') {
    const m = d.members.map(x => `<li>${esc(x.name)} <span class="muted">${esc(String(x.role).replace('_', ' '))}</span></li>`).join('');
    const o = d.open_tasks_by_person.map(x => `<li>${esc(x.name)}: ${Number(x.open)} open task${x.open === 1 ? '' : 's'}</li>`).join('');
    const team = (m ? `<div class="w-sub">On this project</div><ul>${m}</ul>` : '') +
      (o ? `<div class="w-sub">Open tasks by person</div><ul>${o}</ul>` : '');
    return (team || '<p class="muted">Nobody is assigned yet.</p>') + ppContacts(d);
  }
  return '';
}

function ppContacts(data) {
  const options = data.contact_options;
  const edit = state.pp.contactEdit;
  const contacts = data.contacts || [];
  const mayOpen = ['admin', 'manager', 'architect'].includes(state.pp.data?.as_role || state.user?.role);
  const rows = contacts.map(contact => {
    const name = mayOpen
      ? `<button type="button" class="cx-link" data-bk="party" data-id="${Number(contact.party_id)}">${esc(contact.name)}</button>`
      : esc(contact.name);
    const remove = options ? ` <button type="button" class="btn btn-secondary btn-sm" data-pp="contact-remove" data-link="${Number(contact.id)}" aria-label="Remove ${esc(contact.name)}">Remove</button>` : '';
    return `<li>${name} ${pill(ppContactRole(contact.role), 'gray')}${remove}</li>`;
  }).join('');
  const removing = contacts.find(contact => contact.id === edit?.linkId);
  let form = '';
  if (options && edit) {
    const fields = removing
      ? `<p>Remove ${esc(removing.name)} as ${esc(ppContactRole(removing.role))}.</p><label class="g-field"><span>Reason</span><input class="form-input" name="reason" minlength="3" maxlength="400" required></label>`
      : `<div class="form-grid"><label class="g-field"><span>Contact</span><select name="party_id" class="form-input" required><option value="">Choose a contact</option>${options.map(p => `<option value="${Number(p.id)}">${esc(p.name)}</option>`).join('')}</select></label><label class="g-field"><span>Role</span><select name="role" class="form-input" required><option value="">Choose a contact first</option></select></label></div>`;
    form = `<form id="ppContactForm" class="section-gap">${fields}<div class="row-actions"><button type="submit" class="btn btn-primary">Send for approval</button><button type="button" class="btn btn-secondary" data-pp="contact-cancel">Cancel</button></div></form>`;
  }
  const add = options?.length ? '<button type="button" class="btn btn-secondary btn-sm" data-pp="contact-add" aria-label="Add project contact">Add</button>' : '';
  return `<div class="row-actions section-gap"><div class="w-sub">Vendors &amp; consultants</div>${add}</div>` +
    (rows ? `<ul class="w-entries">${rows}</ul>` : '<p class="muted">No contacts linked.</p>') + form;
}

function ppOverviewPanel(d, hl, tone, blocker) {
  const money = d.data?.money;
  const tasks = d.data?.tasks;
  const snags = d.data?.snags;
  const acc = state.pp.accounting;
  const kpis = `<div class="sense-kpi-grid">` +
    (tasks ? `<div class="sense-kpi"><div class="sense-kpi-label">Tasks</div><div class="sense-kpi-val">${Number(tasks.open)} open</div><div class="sense-kpi-sub">${Number(tasks.overdue)} overdue · ${Number(tasks.done)} done</div></div>` : '') +
    (snags ? `<div class="sense-kpi"><div class="sense-kpi-label">Open snags</div><div class="sense-kpi-val">${Number(snags.open)}</div><div class="sense-kpi-sub">Active site defects</div></div>` : '') +
    (money ? `<div class="sense-kpi"><div class="sense-kpi-label">Contract value</div><div class="sense-kpi-val">${esc(ppRs(money.budget_paise))}</div><div class="sense-kpi-sub">Cost ${esc(ppRs(money.cost_to_date_paise))}</div></div>` : '') +
    (acc ? `<div class="sense-kpi"><div class="sense-kpi-label">Net profit</div><div class="sense-kpi-val ${(acc.profit?.net_profit_paise || 0) >= 0 ? 'sense-pos' : 'sense-neg'}">${esc(ppRs(acc.profit?.net_profit_paise))}</div><div class="sense-kpi-sub">POs ${esc(ppRs(acc.purchase_orders?.committed_paise))}</div></div>` : '') +
    `</div>`;
  const people = d.data?.people ? `<section class="panel section-gap"><div class="panel-head"><div class="panel-title">People</div></div><div class="panel-body">${ppSection('people', d.data.people)}</div></section>` : '';
  return `<section class="panel"><div class="panel-head"><div class="panel-title">Overview</div><div>${pill(hl, tone)}</div></div><div class="panel-body">${blocker}${kpis}</div></section>${people}`;
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
  const portalPanel = typeof paProjectPanel === 'function' ? paProjectPanel(p.id) : '';       // "Client portal" (staff roles only; portal_admin.js)
  const chat = state.pp.chat ? `<section class="panel section-gap" id="pp-chat"><div class="panel-head"><div><div class="panel-title">Team chat</div><div class="panel-sub">Everyone on this project reads this. Messages are not edited or deleted.</div></div><button type="button" class="btn btn-secondary btn-sm" data-pp="chat-refresh">Refresh</button></div><div class="panel-body">` +
    (state.pp.chat.messages.length ? `<div class="pp-chat-list">${state.pp.chat.messages.map(m => {
      const mine = state.user && Number(m.user_id) === Number(state.user.id);
      return `<div class="pp-chat-msg${mine ? ' pp-chat-me' : ''}"><div class="pp-chat-bubble"><div class="pp-chat-meta"><strong>${esc(mine ? 'You' : m.author)}</strong> <span>${esc(time(m.created_at))}</span></div><div class="pp-chat-body">${esc(m.body)}</div></div></div>`;
    }).join('')}</div>` : '<p class="muted">No messages yet.</p>') +
    `<form id="ppChatForm" class="v-ask"><input class="form-input" name="body" maxlength="2000" placeholder="Write to the team" aria-label="Message to the project team" required><button class="btn btn-primary" type="submit">Send</button></form></div></section>` : '';

  // 5-Tab Project Workspace (Overview · Tasks · Site & Snags · Money & Accounting · Files & Portal · Chat)
  const tabs = [{key: 'overview', label: 'Overview'}];
  if (d.sections.includes('tasks')) tabs.push({key: 'tasks', label: 'Tasks'});
  if (d.sections.includes('site') || d.sections.includes('snags')) tabs.push({key: 'site', label: 'Site & Snags'});
  if (d.sections.includes('money')) tabs.push({key: 'money', label: 'Accounting'});
  if (d.sections.includes('files') || portalPanel) tabs.push({key: 'files', label: 'Files & Portal'});
  if (state.pp.chat) tabs.push({key: 'chat', label: 'Team chat'});

  const activeTab = tabs.some(t => t.key === state.pp.tab) ? state.pp.tab : 'overview';
  const tabBar = `<div class="sense-tabs" role="tablist" aria-label="Project workspace">` +
    tabs.map(t => `<button type="button" class="sense-tab" role="tab" aria-selected="${t.key === activeTab}" data-pp="tab" data-tab="${t.key}">${esc(t.label)}</button>`).join('') + `</div>`;

  let bodyPanel = '';
  if (activeTab === 'overview') {
    bodyPanel = ppOverviewPanel(d, hl, tone, blocker);
  } else if (activeTab === 'tasks') {
    bodyPanel = `<section class="panel" id="pp-tasks"><div class="panel-head"><div class="panel-title">Tasks</div></div><div class="panel-body">${ppSection('tasks', d.data.tasks)}</div></section>`;
  } else if (activeTab === 'site') {
    bodyPanel = (d.sections.includes('snags') ? `<section class="panel" id="pp-snags"><div class="panel-head"><div class="panel-title">Snags</div></div><div class="panel-body">${ppSection('snags', d.data.snags)}</div></section>` : '') +
      (d.sections.includes('site') ? `<section class="panel section-gap" id="pp-site"><div class="panel-head"><div class="panel-title">Site reports</div></div><div class="panel-body">${ppSection('site', d.data.site)}</div></section>` : '');
  } else if (activeTab === 'money') {
    bodyPanel = `<section class="panel" id="pp-money"><div class="panel-head"><div class="panel-title">Money &amp; Accounting</div></div><div class="panel-body">${ppSection('money', d.data.money)}</div></section>`;
  } else if (activeTab === 'files') {
    bodyPanel = (d.sections.includes('files') ? `<section class="panel" id="pp-files"><div class="panel-head"><div class="panel-title">Files</div></div><div class="panel-body">${ppSection('files', d.data.files)}</div></section>` : '') + portalPanel;
  } else if (activeTab === 'chat') {
    bodyPanel = chat;
  }

  const client = p.client_name ? (p.client_id && ['admin', 'accounts', 'manager', 'architect'].includes(d.as_role || state.user?.role)
    ? '<button type="button" class="cx-link" data-bk="party" data-id="'+Number(p.client_id)+'">'+esc(p.client_name)+'</button>'
    : esc(p.client_name)) : '';
  const company = p.company_name ? '<span>Company: '+esc(p.company_name)+'</span>' : '';
  const canEdit = !d.as_role && ['admin', 'manager'].includes(state.user?.role) && state.projectFormOptions?.companies.length;
  const links = company || client || canEdit ? '<div class="row-actions section-gap">'+company+
    (client?'<span>Client: '+client+'</span>':'')+
    (canEdit?'<button type="button" class="btn btn-secondary btn-sm" data-pp="links">Change company or client</button>':'')+'</div>' : '';
  const editor = canEdit && state.pp.editLinks ? '<section class="panel section-gap"><form class="panel-body" id="ppLinksForm"><div class="form-grid">'+
    projectOwnerFields(state.projectFormOptions, p)+'</div><div class="row-actions"><button type="submit" class="btn btn-primary">Send for approval</button>'+
    '<button type="button" class="btn btn-secondary" data-pp="links-cancel">Cancel</button></div></form></section>' : '';
  return strip + head(p.name, [p.stage, p.location].filter(Boolean).join(' · ')) + links + editor + tabBar + bodyPanel;
}

const _ppRender = render;
render = function () {
  if (state.view !== 'project') { _ppRender(); return; }
  document.body.classList.remove('chat-mode');
  updateIdentity();
  $('mainContent').innerHTML = ppView().replace(/STUDIOOS \/ [A-Z]+/, 'STUDIOOS / PROJECT');
  $('breadcrumb').textContent = state.pp.data ? state.pp.data.project.name : 'Project';
  document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === 'projects'));
  const chatList = document.querySelector('.pp-chat-list');
  if (chatList) chatList.scrollTop = chatList.scrollHeight;
};

function openProject(id) {
  state.pp.id = Number(id);
  state.pp.data = null;
  state.pp.tab = 'overview';
  state.pp.editLinks = false;
  state.pp.contactEdit = null;
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
  if (b.dataset.pp === 'links' || b.dataset.pp === 'links-cancel') {
    state.pp.editLinks = b.dataset.pp === 'links';
    render();
    document.querySelector(state.pp.editLinks ? '#ppLinksForm select' : '[data-pp="links"]')?.focus();
  }
  if (b.dataset.pp === 'contact-add' || b.dataset.pp === 'contact-remove' || b.dataset.pp === 'contact-cancel') {
    const linkId = Number(b.dataset.link || 0);
    state.pp.contactEdit = b.dataset.pp === 'contact-cancel' ? null : {linkId};
    render();
    const focus = state.pp.contactEdit ? '#ppContactForm select, #ppContactForm input' : '[data-pp="contact-add"]';
    document.querySelector(focus)?.focus();
  }
  if (b.dataset.pp === 'tab') { state.pp.tab = b.dataset.tab || 'overview'; render(); return; }
  if (b.dataset.pp === 'jump') { e.preventDefault(); document.getElementById('pp-' + b.dataset.key)?.scrollIntoView({block: 'start'}); }
  if (b.dataset.pp === 'chat-refresh' && state.pp.id) {
    const msgs = state.pp.chat?.messages || [];
    const after = msgs.length ? Number(msgs[msgs.length - 1].id || 0) : 0;
    const url = `/api/projects/${Number(state.pp.id)}/chat` + (after ? `?after=${after}` : '');
    api(url).then(res => {
      if (!state.pp.chat) state.pp.chat = res;
      else if (after && res.messages?.length) state.pp.chat.messages = [...state.pp.chat.messages, ...res.messages];
      else if (!after) state.pp.chat = res;
      if (after && !res.messages?.length) notify('Team chat is up to date.');
      render();
    }).catch(err => notify(err.message, true));
  }
});

document.addEventListener('change', e => {
  if (e.target.form?.id !== 'ppContactForm' || e.target.name !== 'party_id') return;
  const person = state.pp.data?.data.people.contact_options?.find(row => row.id === Number(e.target.value));
  e.target.form.elements.role.innerHTML = '<option value="">Choose a role</option>' +
    (person?.roles || []).map(role => `<option value="${esc(role)}">${esc(ppContactRole(role))}</option>`).join('');
});

document.addEventListener('submit', async e => {
  if (e.target.id === 'ppContactForm' && state.pp.contactEdit) {
    e.preventDefault();
    const button = e.submitter;
    if (button?.disabled) return;
    if (button) button.disabled = true;
    const projectId = state.pp.id;
    const linkId = state.pp.contactEdit.linkId;
    const values = new FormData(e.target);
    const data = linkId ? {project_id: projectId, link_id: linkId, reason: String(values.get('reason') || '').trim()}
      : {project_id: projectId, party_id: Number(values.get('party_id')), role: values.get('role')};
    try {
      const ticket = await api('/api/tickets/proposals', {method:'POST', body:JSON.stringify({
        kind: linkId ? 'remove_project_party' : 'add_project_party', data,
        evidence: 'Project contact change requested on the project page',
      })});
      if (state.pp.id === projectId) { state.pp.contactEdit = null; render(); }
      notify(`Project contact change #${ticket.ticket_id} sent for approval.`);
    } catch (error) { notify(error.message, true); }
    finally { if (button) button.disabled = false; }
    return;
  }
  if (e.target.id === 'ppLinksForm' && state.pp.id) {
    e.preventDefault();
    const button = e.submitter;
    if (button?.disabled) return;
    if (button) button.disabled = true;
    const projectId = state.pp.id;
    const values = Object.fromEntries(new FormData(e.target));
    try {
      await api('/api/tickets/proposals', {method: 'POST', body: JSON.stringify({
        kind: 'update_project', data: {id: projectId, ...projectLinkValues(values)},
        evidence: 'Company and client selected on the project page',
      })});
      if (state.pp.id === projectId) state.pp.editLinks = false;
      await refresh();
      notify('Project change sent for approval.');
    } catch (error) { notify(error.message, true); }
    finally { if (button) button.disabled = false; }
    return;
  }
  if (e.target.id !== 'ppChatForm' || !state.pp.id) return;
  e.preventDefault();
  const form = e.target;
  const body = String(new FormData(form).get('body') || '').trim();
  if (!body) return;
  const btn = form.querySelector('button[type="submit"]');
  if (btn && btn.disabled) return;
  const prevText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Sending…'; }
  try {
    await api(`/api/projects/${Number(state.pp.id)}/chat`, {method: 'POST', body: JSON.stringify({body})});
    state.pp.chat = await api(`/api/projects/${Number(state.pp.id)}/chat`);
    render();
  } catch (err) {
    notify(err.message, true);
  } finally {
    if (btn && btn.isConnected) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.textContent = prevText; }
  }
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
  const btn = document.querySelector(`[data-pp="photo"][data-id="${target.id}"][data-slot="${target.slot}"]`);
  const prevText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.textContent = 'Uploading…'; }
  try {
    const blob = await ppShrink(file);
    await api(`/api/snags/${target.id}/photos`, {method: 'POST', body: JSON.stringify({filename: 'snag-photo.jpg', base64: await ppBase64(blob), slot: target.slot})});
    await ppLoad(state.pp.id);
    notify('Photo added.');
    render();
  } catch (err) {
    notify(err.message, true);
  } finally {
    if (btn && btn.isConnected) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.textContent = prevText; }
  }
});
