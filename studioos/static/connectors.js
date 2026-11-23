'use strict';
/* StudioOS v0.9.3: "AI connectors" on My account. Create, see and revoke personal
   keys that let Claude or ChatGPT read StudioOS as you (through /mcp). Admin also
   sees every key and the recent connector requests. Loaded after app.js. */

Object.assign(state, {connectors: null, newConnectorKey: null, connectorCalls: null});

function connectorList() {
  const c = state.connectors;
  if (!c) return '<p class="muted">Loading…</p>';
  const rows = c.tokens.length ? c.tokens.map(t => `<div class="ck-row"><div><strong>${esc(t.name)}</strong> ${pill(t.state === 'active' ? 'Active' : t.state === 'revoked' ? 'Revoked' : 'Expired', t.state === 'active' ? 'good' : '')}
      <div class="muted ck-meta">${esc(t.scope === 'read_draft' ? 'Read and create drafts' : 'Read only')} · ${esc(t.prefix)}… · expires ${esc(time(t.expires_at))}${t.last_used_at ? ' · last used ' + esc(time(t.last_used_at)) : ' · never used'}${t.owner && isAdmin() ? ' · ' + esc(t.owner) : ''}</div></div>
      ${t.state === 'active' ? `<button class="btn btn-danger btn-sm" data-action="ck-revoke" data-id="${Number(t.id)}">Revoke</button>` : ''}</div>`).join('')
    : '<p class="muted">No keys yet.</p>';
  return rows;
}

function connectorSection() {
  const c = state.connectors || {};
  const fresh = state.newConnectorKey;
  const url = location.origin + '/mcp';
  return `<section class="panel section-gap" id="connectorsPanel"><div class="panel-head"><div><div class="panel-title">AI connectors (Claude, ChatGPT)</div>
    <div class="panel-sub">Let an AI assistant read StudioOS as you, with your access only. It can never approve, save, change or delete anything.</div></div>
    ${pill(c.enabled ? 'Connector on' : 'Connector off', c.enabled ? 'good' : '')}</div><div class="panel-body">
    ${c.enabled === false ? '<div class="notice">The Admin has not turned the connector on yet (STUDIOOS_MCP_ENABLED). You can still prepare a key.</div>' : ''}
    ${fresh ? `<div class="notice ck-fresh"><strong>Copy this key now. It will not be shown again.</strong><code class="ck-key" id="ckKey">${esc(fresh.token)}</code>
      <button class="btn btn-secondary btn-sm" data-action="ck-copy">Copy key</button>
      <p>In Claude: Customize → Connectors → Add custom connector. Server address: <code>${esc(url)}</code> (or the public connector address the Admin gives you), and send the key as <code>Authorization: Bearer &lt;key&gt;</code>.</p>
      <button class="btn btn-secondary btn-sm" data-action="ck-done">I have saved it</button></div>` : ''}
    <div class="ck-list">${connectorList()}</div>
    <form id="connectorForm" class="form-grid ck-form"><div class="field"><label for="ck-name">Name (where it is used)</label><input class="form-input" id="ck-name" name="name" required minlength="2" maxlength="80" placeholder="Claude on my phone"></div>
      <div class="field"><label for="ck-scope">What it may do</label><select class="form-input" id="ck-scope" name="scope"><option value="read">Read only (recommended)</option>${state.user?.role !== 'viewer' ? '<option value="read_draft">Read and create drafts for approval</option>' : ''}</select></div>
      <div class="field"><label for="ck-days">Expires after</label><select class="form-input" id="ck-days" name="days"><option value="30">30 days</option><option value="90" selected>90 days</option><option value="180">180 days</option><option value="365">1 year</option></select></div>
      ${accountField('ck', 'Your password (to confirm)', 'password', 'password', 'current-password')}
      ${state.twoFactor?.enabled ? codeField('ck') : ''}
      <button class="btn btn-primary" type="submit">Create key</button></form>
    <p class="muted ck-note">What you ask the AI, and what StudioOS answers, is sent to that AI provider. Use it for questions you are happy to send there.</p>
    ${isAdmin() ? `<details class="ck-calls" data-action="ck-calls"><summary>Recent connector requests (all people)</summary>${state.connectorCalls ? (state.connectorCalls.length ? `<div class="w-table-wrap"><table class="w-table"><thead><tr><th>Time</th><th>Person</th><th>Key</th><th>Request</th><th>Result</th><th>Address</th></tr></thead><tbody>${state.connectorCalls.slice(0, 60).map(r => `<tr><td>${esc(time(r.time))}</td><td>${esc(r.person || '—')}</td><td>${esc(r.key || '—')}</td><td>${esc(r.tool || r.method || '—')}</td><td>${r.ok ? 'OK' : esc('Refused: ' + r.detail)}</td><td>${esc(r.address)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="muted">No requests yet.</p>') : '<p class="muted">Loading…</p>'}</details>` : ''}
    </div></section>`;
}

const _accountView = account;
account = function () {
  if (!state.connectors) loadConnectors();
  return _accountView() + (state.mustSetup2fa ? '' : connectorSection());
};

async function loadConnectors() {
  try { state.connectors = await api('/api/connector-tokens'); } catch (e) { state.connectors = {enabled: false, tokens: []}; }
  if (state.view === 'account') render();
}

document.addEventListener('submit', async e => {
  if (e.target.id !== 'connectorForm') return;
  e.preventDefault(); e.stopImmediatePropagation();
  const v = Object.fromEntries(new FormData(e.target).entries());
  try {
    state.newConnectorKey = await api('/api/connector-tokens', {method: 'POST', body: JSON.stringify({name: v.name, scope: v.scope, days: Number(v.days), password: v.password, code: v.code})});
    state.connectors = await api('/api/connector-tokens');
    render(); document.getElementById('connectorsPanel')?.scrollIntoView();
  } catch (err) { notify(err.message, true); }
}, true);

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-action^="ck-"]');
  if (!b) return;
  const a = b.dataset.action;
  if (a === 'ck-calls') { if (!state.connectorCalls) { try { state.connectorCalls = await api('/api/connector-calls'); } catch (x) { state.connectorCalls = []; } render(); document.querySelector('.ck-calls')?.setAttribute('open', ''); } return; }
  e.stopImmediatePropagation();
  try {
    if (a === 'ck-copy') { await navigator.clipboard.writeText(state.newConnectorKey?.token || ''); notify('Key copied'); return; }
    if (a === 'ck-done') { state.newConnectorKey = null; render(); return; }
    if (a === 'ck-revoke') {
      if (!await askConfirm('Revoke this key? Any AI assistant using it stops working immediately.')) return;
      await api(`/api/connector-tokens/${Number(b.dataset.id)}/revoke`, {method: 'POST', body: '{}'});
      state.connectors = await api('/api/connector-tokens'); render(); notify('Key revoked');
    }
  } catch (err) { notify(err.message, true); }
}, true);
