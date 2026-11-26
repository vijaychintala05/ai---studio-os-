'use strict';
/* Settings -> Try before proposing (Admin): check a saved view's history, try a view, report, workflow or record
   type change without saving anything, and see or suggest record layouts. Only "Draft for approval" creates a change
   request. The definitions are the same ones the chat builds; this is for checking them. Loaded after gapkit.js. */

const TO_KEY = /^[A-Za-z0-9_.-]{1,80}$/;

function toJson(text, what) {
  let value;
  try { value = JSON.parse(text); } catch (_) { throw new Error(`The ${what} is not valid JSON. Check brackets and quotes.`); }
  if (value === null || typeof value !== 'object') throw new Error(`The ${what} should be a JSON object or list.`);
  return value;
}

const toArea = (label, name, rows = 6) => `<label class="g-field"><span>${esc(label)}</span><textarea class="form-input" name="${name}" rows="${rows}" required></textarea></label>`;
const toShow = key => state.gk.ui[key] === undefined ? '' : `<pre class="gk-result">${esc(JSON.stringify(state.gk.ui[key], null, 2))}</pre>`;

function toViews() {
  const ui = state.gk.ui;
  const views = gkGet('to:views', () => api('/api/viewspecs'));
  const primitives = gkGet('to:primitives', () => api('/api/viewspecs/primitives'));
  let history = gkWait(views);
  if (Array.isArray(views)) {
    if (!views.some(v => v.key === ui.toView)) ui.toView = views[0]?.key || null;
    history = views.length ? `<div class="g-form">${gkSelect('Saved view', 'view', views.map(v => [v.key, v.name || v.key]), ui.toView, 'data-gk-change="view"')}</div>` : '<p class="muted">No saved view yet.</p>';
    if (ui.toView) {
      const detail = gkGet(`to:view:${ui.toView}`, () => api(`/api/viewspecs/${encodeURIComponent(ui.toView)}`));
      history += detail && detail.versions
        ? gkTable(['Version', 'By', 'When', ''], detail.versions.map(v => [Number(v.version), esc(v.created_by), esc(v.created_at),
          gkButton('version', 'Open', `data-version="${Number(v.version)}"`)]), 'No version.') + toShow('toVersion')
        : gkWait(detail);
    }
  }
  const allowed = primitives && primitives.primitives
    ? `<p class="muted">You can build: ${esc(primitives.primitives.join(', '))}. Field kinds: ${esc(primitives.field_kinds.join(', '))}. Colours: ${esc(primitives.colour_tokens.join(', '))}.</p>`
    : gkWait(primitives);
  const check = gkForm('validate', toArea('View definition (JSON)', 'spec'), 'Check this view') + toShow('toValid') +
    (ui.toValid && ui.toValid.valid ? gkButton('proposeView', 'Draft this new view for approval', '', true) : '');
  return gkPanel('View history', 'Older versions of saved views.', history) + gkPanel('Check a view', 'Nothing is saved while checking.', allowed + check);
}

function toOthers() {
  const ui = state.gk.ui;
  const types = gkGet('to:types', () => api('/api/universal/types'));
  const list = Array.isArray(types) ? types : (types && types.types) || [];
  let layout = gkWait(types);
  if (types && !types.gkError) {
    if (!list.some(t => t.key === ui.toType)) ui.toType = list[0]?.key || null;
    if (!ui.toType) layout = '<p class="muted">No record type yet.</p>';
    else {
      const current = gkGet(`to:layout:${ui.toType}`, () => api(`/api/views/layout/${encodeURIComponent(ui.toType)}`));
      layout = `<div class="g-form">${gkSelect('Record type', 'type', list.map(t => [t.key, t.label || t.name || t.key]), ui.toType, 'data-gk-change="type"')}</div>` +
        (current && !current.gkError ? `<div class="w-sub">Current layout</div><pre class="gk-result">${esc(JSON.stringify(current.layout, null, 2))}</pre>` : gkWait(current)) +
        gkButton('suggest', 'Suggest a layout') + toShow('toSuggested');
    }
  }
  return layout;
}

function toLayouts() { return gkPanel('Record layouts', 'A suggestion changes nothing until it is proposed and approved.', toOthers()); }
const toReportPanel = () => gkPanel('Try a report', 'Runs on the records you may see. Nothing is saved.', gkForm('report', toArea('Report definition (JSON)', 'definition'), 'Preview report') + toShow('toReport'));
const toChangePanel = () => gkPanel('Try a record type change', 'See what would change before proposing it.', gkForm('restructure', toArea('Change (JSON)', 'change'), 'Preview change') + toShow('toRestructure'));
const toWorkflowPanel = () => gkPanel('Try a workflow', 'Walk sample steps through a workflow. Nothing is saved.', gkForm('dryrun', toArea('Workflow definition (JSON)', 'definition') +
    toArea('Sample steps (JSON list)', 'path', 3), 'Walk the steps') + toShow('toDry')) +
  gkPanel('Workflow next steps and history', '', gkForm('available', gkInput('Workflow key', 'key', 'required maxlength="80"') + gkInput('Current status', 'status', 'required maxlength="60"'), 'Show allowed next steps') + toShow('toNext') +
    gkForm('history', gkInput('Workflow key', 'key', 'required maxlength="80"') + gkInput('Record number', 'target', 'required inputmode="numeric"'), 'Show history') + toShow('toHistory'));

const toView_ = () => head('Try before proposing', 'Check definitions without changing anything.') + gkSections('toSection', [
  ['views', 'Views', toViews], ['layouts', 'Layouts', toLayouts], ['reports', 'Reports', toReportPanel],
  ['changes', 'Type changes', toChangePanel], ['workflows', 'Workflows', toWorkflowPanel]]);
const toPost = (url, body) => api(url, {method: 'POST', body: JSON.stringify(body)});

gkScreen('tryout', {
  title: 'Try before proposing', roles: ['admin'], view: toView_,
  change: {
    view: el => { state.gk.ui.toView = el.value; state.gk.ui.toVersion = undefined; },
    type: el => { state.gk.ui.toType = el.value; state.gk.ui.toSuggested = undefined; },
  },
  click: {
    version: async el => { state.gk.ui.toVersion = await api(`/api/viewspecs/${encodeURIComponent(state.gk.ui.toView)}/versions/${Number(el.dataset.version)}`); },
    suggest: async () => { state.gk.ui.toSuggested = await toPost(`/api/views/layout/${encodeURIComponent(state.gk.ui.toType)}/suggest`, {}); },
    proposeView: async () => { await gkDraft('/api/viewspecs/propose', {kind: 'view_create', data: {spec: state.gk.ui.toSpec, scope: 'user'}}, 'View drafted'); },
  },
  submit: {
    validate: async form => { state.gk.ui.toSpec = toJson(gkValues(form).spec, 'view definition'); state.gk.ui.toValid = await toPost('/api/viewspecs/validate', {spec: state.gk.ui.toSpec}); },
    report: async form => { state.gk.ui.toReport = await toPost('/api/graph/reports/preview', {definition: toJson(gkValues(form).definition, 'report definition')}); },
    restructure: async form => { state.gk.ui.toRestructure = await toPost('/api/restructure/preview', {change: toJson(gkValues(form).change, 'change')}); },
    dryrun: async form => { const v = gkValues(form); state.gk.ui.toDry = await toPost('/api/work/workflows/dry-run', {definition: toJson(v.definition, 'workflow definition'), path: toJson(v.path, 'sample steps')}); },
    available: async form => {
      const v = gkValues(form);
      if (!TO_KEY.test(v.key)) throw new Error('That workflow key has characters it cannot have.');
      state.gk.ui.toNext = await api(`/api/work/workflows/${encodeURIComponent(v.key)}/available?status=${encodeURIComponent(v.status)}`);
    },
    history: async form => {
      const v = gkValues(form);
      state.gk.ui.toHistory = await api(`/api/work/transitions?workflow_key=${encodeURIComponent(v.key)}&target_id=${Number(v.target)}`);
    },
  },
});
