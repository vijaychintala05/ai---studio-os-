'use strict';
/* StudioOS v0.13.0 "Change a type" (Admin): say the change in words ("rename field severity to
   priority in work issue"), see everything it touches and anything that blocks it, then propose it
   as a ticket. Every applied change can be undone by another ticket. Business pack upgrades too.
   Loaded after app.js and graph.js. */

Object.assign(state, {rs: {draft: null, history: null, packs: null, upgrade: null, text: ''}});

const rsApi = (path, body) => api(path, body ? {method: 'POST', body: JSON.stringify(body)} : undefined);
const RS_OPS = {rename_field: 'Rename a field', retype_field: 'Change a field\'s kind', remove_field: 'Hide a field',
  rename_type: 'Rename a kind of record', merge_types: 'Merge two kinds of record', split_type: 'Split a kind of record', undo: 'Undo'};

async function rsLoad() {
  const [h, c] = await Promise.all([rsApi('/api/restructure/changes'), rsApi('/api/graph/catalog')]);
  state.rs.history = h.changes;
  state.rs.packs = (c.packs || []).filter(p => p.installed_version && p.installed_version < p.version);
}

function rsDraftPanel() {
  const d = state.rs.draft;
  if (!d) return '';
  const imp = d.impact || {};
  const rows = Object.entries(imp).filter(([k, v]) => (Array.isArray(v) ? v.length : v)).map(([k, v]) =>
    `<li><strong>${esc(Array.isArray(v) ? new Set(v).size : v)}</strong> ${esc(k)}${Array.isArray(v) ? ': ' + esc([...new Set(v)].slice(0, 6).join(', ')) : ''}</li>`).join('');
  return `<section class="panel rs-draft"><div class="panel-head"><div><div class="panel-title">${esc(RS_OPS[d.change.op] || d.change.op)}</div>
    <div class="panel-sub" id="rsSummary">${esc(d.summary)}</div></div></div><div class="v-pad">
    <pre class="rs-change">${esc(JSON.stringify(d.change, null, 1))}</pre>
    ${rows ? `<ul class="rs-impact">${rows}</ul>` : ''}
    ${d.blockers.length ? `<div class="notice fail"><div><strong>Cannot be approved yet</strong><ul class="rs-blockers">${d.blockers.map(b => `<li>${esc(b)}</li>`).join('')}</ul></div></div>` : ''}
    ${d.unconvertible_total ? `<details class="rs-bad"><summary>${Number(d.unconvertible_total)} record(s) that cannot be converted</summary><ul>${d.unconvertible.map(u => `<li>Record #${Number(u.record_id)}: “${esc(u.value)}”</li>`).join('')}</ul></details>` : ''}
    <p class="muted">A backup is taken just before the change is applied. It can be undone later with another ticket.</p>
    <button class="btn btn-primary btn-sm" data-rs="propose" ${d.blockers.length ? 'disabled' : ''}>Propose this change</button></div></section>`;
}

function rsView() {
  if (!isAdmin()) return head('Change a type', 'Only the Admin can change kinds of record.');
  if (!state.rs.history) { rsLoad().then(render).catch(err => notify(err.message, true)); return head('Change a type', 'Loading…') + '<div class="loading">Loading…</div>'; }
  const h = state.rs.history;
  const packs = state.rs.packs || [];
  return head('Change a type', 'Rename, retype, hide, merge or split fields and kinds of record, with every report, rule and layout updated in the same ticket.') +
    `<section class="panel v-pad"><form id="rsForm" class="v-ask"><input class="form-input" name="text" id="rsText" maxlength="300" value="${esc(state.rs.text)}"
      placeholder="e.g. rename field severity to priority in work issue" aria-label="The change in words"><button class="btn btn-primary" type="submit">Preview</button></form>
      <p class="muted">Also: “remove resolution from work issue”, “make hours in timesheet entry a whole number”, “rename type work issue to Snag”.</p></section>` +
    rsDraftPanel() +
    (packs.length ? `<section class="panel"><div class="panel-head"><div class="panel-title">Business pack upgrades</div></div><div class="v-pad">${packs.map(p =>
      `<div class="rs-pack"><span>${esc(p.title)}: version ${Number(p.installed_version)} → ${Number(p.version)}</span> <button class="btn btn-secondary btn-sm" data-rs="upgrade" data-key="${esc(p.key)}">Review upgrade</button></div>`).join('')}
      ${state.rs.upgrade ? `<ul class="rs-impact">${state.rs.upgrade.items.map(i => `<li>${esc(i.kind)}: ${esc(i.data.type_key || i.data.key || '')}${i.data.op ? ' (' + esc(i.data.op) + ')' : ''}</li>`).join('')}</ul>
        <button class="btn btn-primary btn-sm" data-rs="propose-upgrade">Propose the upgrade</button>` : ''}</div></section>` : '') +
    `<section class="panel"><div class="panel-head"><div><div class="panel-title">Changes made</div><div class="panel-sub">Newest first. Undo opens a ticket that puts everything back exactly.</div></div></div>
    ${h.length ? `<ul class="rs-history">${h.map(c => `<li><span><strong>${esc(RS_OPS[c.op] || c.op)}</strong> · ${esc(c.type_key)} · ticket #${Number(c.ticket_id)}${c.undone ? ' · <em>undone</em>' : ''}</span>
      ${!c.undone && !c.undo_of ? `<button class="btn btn-secondary btn-sm" data-rs="undo" data-id="${Number(c.id)}">Undo</button>` : ''}</li>`).join('')}</ul>` : '<p class="muted v-pad">No changes yet.</p>'}</section>`;
}

const _rsRender = render;
render = function () {
  if (state.view === 'restructure') {
    document.body.classList.remove('chat-mode');
    updateIdentity();
    $('mainContent').innerHTML = rsView();
    $('breadcrumb').textContent = 'Change a type';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _rsRender();
};

document.addEventListener('submit', async e => {
  if (e.target.id !== 'rsForm') return;
  e.preventDefault();
  const text = String(new FormData(e.target).get('text') || '').trim();
  state.rs.text = text;
  try { state.rs.draft = await rsApi('/api/restructure/draft', {text}); } catch (err) { state.rs.draft = null; notify(err.message, true); }
  render();
});

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="restructure"]')) { state.rs.history = null; return; }
  const b = e.target.closest('[data-rs]');
  if (!b) return;
  e.preventDefault();
  const rs = state.rs;
  try {
    b.disabled = true;
    if (b.dataset.rs === 'propose') {
      const r = await rsApi('/api/universal/proposals', {kind: 'metadata_type_change', data: rs.draft.change, evidence: 'Asked: ' + rs.text});
      notify(`Ticket #${r.ticket_id} opened. Nothing changes until the Admin approves it.`); rs.draft = null;
    } else if (b.dataset.rs === 'undo') {
      const r = await rsApi('/api/universal/proposals', {kind: 'metadata_type_change_undo', data: {change_id: Number(b.dataset.id)}, evidence: 'Undo change #' + b.dataset.id});
      notify(`Ticket #${r.ticket_id} opened to undo change #${b.dataset.id}.`);
    } else if (b.dataset.rs === 'upgrade') {
      rs.upgrade = await rsApi('/api/restructure/pack-upgrade/' + encodeURIComponent(b.dataset.key));
    } else if (b.dataset.rs === 'propose-upgrade') {
      const u = rs.upgrade;
      const r = await rsApi('/api/universal/proposals', {kind: 'metadata_pack_upgrade', data: {pack: u.pack, version: u.version, sha256: u.sha256}, evidence: `Upgrade ${u.pack} to version ${u.version}`});
      notify(`Ticket #${r.ticket_id} opened for the pack upgrade.`); rs.upgrade = null;
    }
    render();
  } catch (err) { b.disabled = false; notify(err.message, true); }
});
