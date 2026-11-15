'use strict';
/* StudioOS v0.11.0 "AI reader" settings (Admin only): the master switch (OFF by default), provider,
   model, monthly spending cap and prices, privacy masking (ON by default), recent model calls, and
   suggestions for other names learnt from corrections. Keys are never typed here.
   Loaded after app.js and graph.js. */

Object.assign(state, {ai: {view: null, calls: null, sugg: null, saving: false}});

const aiApi = (path, method, body) => api(path, body ? {method, body: JSON.stringify(body)} : undefined);

async function aiLoad() {
  const a = state.ai;
  [a.view, a.calls, a.sugg] = await Promise.all([aiApi('/api/ai/settings'), aiApi('/api/ai/calls?limit=30'),
    aiApi('/api/ai/alias-suggestions')]);
}

function aiStatusLine(st) {
  if (st.on) return `<span class="ai-pill ai-on">AI is ON</span> ${esc(st.provider)} · ${esc(st.model)}`;
  const why = [];
  if (!st.admin_switch) why.push('the switch below is off');
  if (!st.server_switch) why.push('the server setting STUDIOOS_ALLOW_LIVE_AI is not true');
  return `<span class="ai-pill ai-off">AI is OFF</span> The offline reader is used (${esc(why.join(' and ') || 'not ready')}).`;
}

function aiView() {
  const a = state.ai;
  if (!isAdmin()) return head('AI reader', 'Only the Admin can change AI settings.');
  if (!a.view) return head('AI reader', 'Loading…') + '<div class="loading">Loading…</div>';
  const s = a.view.settings, st = a.view.status;
  const opt = (v, l, cur) => `<option value="${esc(v)}" ${v === cur ? 'selected' : ''}>${esc(l)}</option>`;
  const calls = (a.calls?.calls || []);
  const sugg = (a.sugg?.suggestions || []);
  return head('AI reader', 'How chat messages become draft records. AI only reads; every draft still needs approval.') + `
  <section class="panel"><div class="panel-head"><div><div class="panel-title">Status</div><div class="panel-sub" id="aiStatus">${aiStatusLine(st)}</div></div></div>
    <div class="ai-stats">
      <div class="ai-stat"><span>This month (${esc(st.month)})</span><strong>$${esc(st.spent_usd)}</strong><small>of $${esc(st.cap_usd)} cap · estimated</small></div>
      <div class="ai-stat"><span>Key on the server</span><strong>${st.key_present ? 'Present' : 'Not set'}</strong><small>${esc(a.view.keys_note)}</small></div>
      <div class="ai-stat"><span>Prices entered</span><strong>${st.priced ? 'Yes' : 'No'}</strong><small>Needed to keep to the cap</small></div>
    </div></section>
  <section class="panel"><div class="panel-head"><div><div class="panel-title">Settings</div><div class="panel-sub">Saved for everyone. Changes are recorded in the Activity Log.</div></div></div>
    <form id="aiForm" class="ai-form">
      <label class="ai-switch"><input type="checkbox" name="enabled" ${s.enabled ? 'checked' : ''}> <span>Use an AI model to read chat messages</span></label>
      <label class="ai-switch"><input type="checkbox" name="masking" ${s.masking ? 'checked' : ''}> <span>Hide client names, phone numbers, e-mails and amounts from the AI (recommended)</span></label>
      <label class="ai-switch"><input type="checkbox" name="few_shot" ${s.few_shot ? 'checked' : ''}> <span>Show the AI a few earlier corrections as examples</span></label>
      <div class="ai-grid">
        <label>Provider<select class="form-input" name="provider">${opt('', 'Choose…', s.provider)}${a.view.providers.map(p => opt(p, {openai: 'OpenAI', claude: 'Anthropic Claude', gemini: 'Google Gemini'}[p] || p, s.provider)).join('')}</select></label>
        <label>Model name<input class="form-input" name="model" value="${esc(s.model)}" maxlength="100" autocomplete="off" spellcheck="false"></label>
        <label>Monthly cap (US$)<input class="form-input" name="monthly_cap_usd" value="${esc(s.monthly_cap_usd)}" inputmode="decimal"></label>
        <label>Input price per 1M tokens (US$)<input class="form-input" name="input_usd_per_1m" value="${esc(s.input_usd_per_1m)}" inputmode="decimal"></label>
        <label>Output price per 1M tokens (US$)<input class="form-input" name="output_usd_per_1m" value="${esc(s.output_usd_per_1m)}" inputmode="decimal"></label>
        <label>Longest reply (tokens)<input class="form-input" name="max_output_tokens" value="${Number(s.max_output_tokens)}" inputmode="numeric"></label>
      </div>
      <p class="muted">Prices come from the provider's official price page. The cap is checked before every call using the worst case; the provider's invoice is what counts.</p>
      <button class="btn btn-primary" type="submit" id="aiSave" ${a.saving ? 'disabled' : ''}>Save settings</button>
    </form></section>
  <section class="panel"><div class="panel-head"><div><div class="panel-title">Other names learnt from corrections</div><div class="panel-sub">When people correct the same words to the same choice three times, StudioOS suggests remembering it. Approving opens a ticket.</div></div></div>
    ${sugg.length ? `<ul class="ai-sugg">${sugg.map((x, i) => `<li><span>“${esc(x.data.alias)}” means <strong>${esc(x.data.option || ('#' + x.data.target_id))}</strong> <small>(${esc(x.data.kind)}, corrected ${Number(x.times)} times)</small></span>
      <span><button class="btn btn-secondary btn-sm" data-ai="propose" data-i="${i}">Propose</button> <button class="btn btn-secondary btn-sm" data-ai="dismiss" data-i="${i}">Not this</button></span></li>`).join('')}</ul>`
      : '<p class="muted g-pad">No suggestions yet.</p>'}</section>
  <section class="panel"><div class="panel-head"><div><div class="panel-title">Recent AI calls</div><div class="panel-sub">One line per call or refusal. Messages and replies are never kept here.</div></div></div>
    ${calls.length ? `<div class="w-table-wrap"><table class="w-table ai-calls"><thead><tr><th>When</th><th>Outcome</th><th>Model</th><th>Size</th><th>Time</th><th>Cost</th></tr></thead><tbody>${calls.map(c =>
      `<tr><td>${esc((c.at || '').replace('T', ' ').slice(0, 16))}</td><td><span class="ai-out ai-out-${esc(c.outcome)}">${esc(c.outcome)}</span></td><td>${esc(c.model)}</td><td>${Number(c.prompt_tokens)} → ${Number(c.output_tokens)}</td><td>${Number(c.latency_ms)} ms</td><td>$${esc(c.cost_usd)}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="muted g-pad">No AI calls yet.</p>'}</section>`;
}

const _aiRender = render;
render = function () {
  if (state.view === 'aireader') {
    document.body.classList.remove('chat-mode');   // v0.11.0: coming from the chat, the page must scroll again
    updateIdentity();
    $('mainContent').innerHTML = aiView();
    $('breadcrumb').textContent = 'AI reader';
    document.querySelectorAll('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
    return;
  }
  _aiRender();
};

document.addEventListener('click', async e => {
  if (e.target.closest('[data-view="aireader"]')) {
    state.ai.view = null;
    setTimeout(async () => { try { await aiLoad(); render(); } catch (err) { notify(err.message, true); } }, 0);
    return;
  }
  const b = e.target.closest('[data-ai]');
  if (!b) return;
  e.preventDefault();
  const x = (state.ai.sugg?.suggestions || [])[Number(b.dataset.i)];
  if (!x) return;
  try {
    b.disabled = true;
    if (b.dataset.ai === 'propose') {
      const r = await aiApi('/api/universal/proposals', 'POST', {kind: 'metadata_alias', data: x.data,
        evidence: `Corrected ${x.times} times in drafts`});
      notify(`Ticket #${r.ticket_id} opened. The other name is used once the ticket is approved.`);
    } else {
      await aiApi('/api/ai/alias-suggestions/dismiss', 'POST', {data: x.data});
      notify('StudioOS will not suggest this again.');
    }
    await aiLoad(); render();
  } catch (err) { b.disabled = false; notify(err.message, true); }
});

document.addEventListener('submit', async e => {
  if (e.target.id !== 'aiForm') return;
  e.preventDefault();
  const f = new FormData(e.target);
  const body = {enabled: f.get('enabled') === 'on', masking: f.get('masking') === 'on', few_shot: f.get('few_shot') === 'on',
    provider: f.get('provider') || '', model: String(f.get('model') || '').trim(),
    monthly_cap_usd: String(f.get('monthly_cap_usd') || '0').trim(), input_usd_per_1m: String(f.get('input_usd_per_1m') || '').trim(),
    output_usd_per_1m: String(f.get('output_usd_per_1m') || '').trim(), max_output_tokens: Number(f.get('max_output_tokens') || 0)};
  try {
    state.ai.saving = true;
    state.ai.view = await aiApi('/api/ai/settings', 'PUT', body);
    state.ai.saving = false;
    notify(state.ai.view.status.on ? 'Saved. AI is on.' : 'Saved. AI is off; the offline reader is used.');
    render();
  } catch (err) { state.ai.saving = false; notify(err.message, true); }
});
