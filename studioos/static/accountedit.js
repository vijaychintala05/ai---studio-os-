'use strict';
/* Chart of accounts: change an account's description or archive it, as a change request (POST /api/books/accounts/update).
   Loaded after chart.js and gapkit.js. */

function aeRows(nodes, out = []) {
  for (const n of nodes || []) { out.push(n); aeRows(n.children, out); }
  return out;
}

function aePanel() {
  const c = state.coa;
  if (!c?.entity || !['admin', 'manager', 'accounts'].includes(state.user?.role)) return '';
  const list = aeRows(c.chart?.tree || c.chart?.accounts || []).filter(a => a.id);
  if (!list.length) return '';
  return gkPanel('Change an account', 'The change waits for approval; past entries are not rewritten.',
    gkForm('account', gkSelect('Account', 'account_id', list.map(a => [a.id, `${a.code || ''} ${a.name}`.trim()]), list[0].id) +
      gkInput('New description (leave empty to keep)', 'description', 'maxlength="300"') +
      gkSelect('State', 'is_active', [['', 'Keep as it is'], ['false', 'Archive'], ['true', 'Make active again']], '') +
      gkInput('Why', 'why', 'required maxlength="400"'), 'Draft account change'));
}

Object.assign(GK_SCREENS._any.submit, {
  account: async form => {
    const v = gkValues(form);
    if (!v.description && !v.is_active) throw new Error('Change the description or the state.');
    await gkDraft('/api/books/accounts/update', {entity_id: state.coa.entity.id, account_id: Number(v.account_id),
      ...(v.description ? {description: v.description} : {}), ...(v.is_active ? {is_active: v.is_active === 'true'} : {}),
      why: v.why, request_key: gkKey()}, 'Account change drafted');
  },
});

const _aeRender = render;
render = function () {
  _aeRender();
  if (state.view !== 'chart') return;
  const main = $('mainContent');
  const panel = aePanel();
  if (panel && main?.insertAdjacentHTML) main.insertAdjacentHTML('beforeend', panel);
};
