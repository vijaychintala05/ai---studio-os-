'use strict';
/* Settings -> Approval rules (Admin only): who may approve each kind of change. Saved at once by the server
   (PUT /api/tickets/policy), after a confirmation. Kinds the server keeps for the Admin are shown as fixed.
   Loaded after gapkit.js. */

const AR_ROLES = [['manager', 'Manager'], ['accounts', 'Accounts'], ['architect', 'Architect'], ['site_engineer', 'Site engineer']];

/* The same rule the server enforces: schema changes, book entries and reversals of saved changes are Admin only. */
const arAdminOnly = type => type === 'suggest_schema' || type === 'propose_data_type' || type === 'reverse_saved_ticket'
  || type.startsWith('metadata_') || type.startsWith('finance_');

const arName = type => type.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());

/* The policy as it would be saved: what the server has, with the ticked boxes applied. */
function arDraft(policy) {
  const edits = state.gk.ui.arEdits || {};
  const out = {};
  for (const [type, roles] of Object.entries(policy)) {
    const set = new Set(roles);
    for (const [role, on] of Object.entries(edits[type] || {})) { if (on) set.add(role); else set.delete(role); }
    set.add('admin');
    out[type] = [...set].sort();
  }
  return out;
}

function arView() {
  const title = 'Approval rules';
  const sub = 'Who may approve each kind of change. The Admin may always approve.';
  const policy = gkGet('ar:policy', () => api('/api/tickets/policy'));
  if (!policy || policy.gkError) return head(title, sub) + gkWait(policy);
  const draft = arDraft(policy);
  const types = Object.keys(policy).sort();
  const open = types.filter(t => !arAdminOnly(t));
  const locked = types.filter(arAdminOnly);
  const rows = open.map(t => [esc(arName(t)), ...AR_ROLES.map(([role, label]) =>
    `<label class="gk-check"><input type="checkbox" data-gk-change="role" data-type="${esc(t)}" data-role="${role}" aria-label="${esc(label)} may approve ${esc(arName(t))}"${draft[t].includes(role) ? ' checked' : ''}></label>`)]);
  const changed = Object.keys(draft).some(t => draft[t].join() !== [...policy[t]].sort().join());
  return head(title, sub) +
    gkPanel('Changes other roles can approve', 'Tick a box to let that role approve.',
      gkTable(['Kind of change', ...AR_ROLES.map(r => r[1])], rows, 'Nothing to set.') +
      `<div class="row-actions">${gkButton('save', 'Save approval rules', changed ? '' : 'disabled', true)}</div>`) +
    gkPanel('Only the Admin', `${locked.length} kinds of change to the books and record structure cannot be handed to anyone else.`,
      `<details><summary>Show them</summary><ul>${locked.map(t => `<li>${esc(arName(t))}</li>`).join('')}</ul></details>`);
}

async function arSave() {
  const policy = state.gk.data['ar:policy']?.value;
  if (!policy) return;
  if (!await askConfirm('Save these approval rules? They apply at once and the change is kept in the audit history.', 'Save rules')) return;
  await api('/api/tickets/policy', {method: 'PUT', body: JSON.stringify({approvers: arDraft(policy)})});
  state.gk.ui.arEdits = {};
  gkForget('ar:');
  notify('Approval rules saved.');
}

gkScreen('approvalrules', {
  title: 'Approval rules', roles: ['admin'], view: arView,
  change: {role: el => { const edits = state.gk.ui.arEdits ||= {}; (edits[el.dataset.type] ||= {})[el.dataset.role] = el.checked; }},
  click: {save: arSave},
});
