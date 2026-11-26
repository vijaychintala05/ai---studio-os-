'use strict';
/* Adds the new screens' common actions to the top bar's + New menu. Loaded after sense_ux.js. */

const GK_QUICK = {
  'gk-bank': {roles: ['admin', 'accounts'], group: 'Books & Purchases', title: 'Bank statement', hint: 'Import · Match', view: 'bankfeed'},
  'gk-time': {roles: ['admin', 'manager', 'architect', 'site_engineer'], group: 'Studio & Site', title: 'Time or leave', hint: 'Timesheet', view: 'mytime'},
  'gk-lock': {roles: ['admin', 'accounts'], group: 'Books & Purchases', title: 'Close a month', hint: 'Period lock', view: 'periodclose'},
};

const _gkQuickItems = senseQuickItemsForRole;
senseQuickItemsForRole = function (role) {
  const groups = _gkQuickItems(role);
  for (const [id, item] of Object.entries(GK_QUICK)) {
    const group = groups.find(g => g.label === item.group);
    if (group && item.roles.includes(role)) group.items.push({id, title: item.title, hint: item.hint});
  }
  return groups;
};

const _gkOpenAction = senseOpenAction;
senseOpenAction = async function (actionId) {
  const item = GK_QUICK[actionId];
  if (!item) return _gkOpenAction(actionId);
  senseCloseQuickMenu();
  switchView(item.view);
};
