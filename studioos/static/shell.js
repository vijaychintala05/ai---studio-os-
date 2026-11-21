'use strict';
/* StudioOS phone shell (App Flows map): five tabs at the bottom of the screen on a phone: Home, Inbox, Capture, Projects and Me.
   Accounts has Books in place of Projects. Each tab opens a screen that already exists; Home depends on the role. Tapping the tab you
   are on goes back to that tab's top screen. The desktop sidebar is unchanged and the bar is hidden above phone width (shell.css).
   Loaded after app.js and the screen modules. No inline styles (strict CSP). */

const SHELL_HOME = {site_engineer: 'home', architect: 'home', manager: 'home', admin: 'home', accounts: 'home', viewer: 'home'};   // the Home screen builds each role's own widgets

function shellTabs(role) {
  const home = SHELL_HOME[role] || 'overview';
  const tabs = [
    {key: 'home', label: 'Home', icon: 'home', top: home, views: ['home', 'today', 'overview', 'insights']},
    {key: 'inbox', label: 'Inbox', icon: 'inbox', top: 'tickets', views: ['tickets', 'approvals', 'inbox', 'newtypes']},
    {key: 'capture', label: 'Capture', icon: 'capture', top: 'assistant', views: ['assistant']},
  ];
  if (role === 'accounts') {
    tabs.push({key: 'books', label: 'Books', icon: 'books', top: 'books', views: ['books', 'party', 'ledger', 'chart', 'budget', 'activity']});
  } else {
    tabs.push({key: 'projects', label: 'Projects', icon: 'projects', top: 'projects', views: ['projects', 'project', 'planbudget', 'tasks', 'work', 'site', 'documents', 'recycle', 'savedviews']});
  }
  tabs.push({key: 'me', label: 'Me', icon: 'me', top: 'account', views: ['account', 'mytime', 'settings', 'team', 'agents', 'aireader', 'restructure', 'selfcheck', 'safety', 'universal']});
  return tabs;
}

function shellActive(tabs, view) {
  const hit = tabs.find(t => t.views.includes(view));
  return hit ? hit.key : 'me';
}

function shellRefresh() {
  let bar = document.getElementById('tabBar');
  const role = state.user && state.user.role;
  if (!role || state.mustSetup2fa) { if (bar) bar.hidden = true; return; }
  if (!bar) {
    bar = document.createElement('nav');
    bar.id = 'tabBar';
    bar.className = 'tab-bar';
    bar.setAttribute('aria-label', 'Main tabs');
    document.body.appendChild(bar);
  }
  const tabs = shellTabs(role);
  const active = shellActive(tabs, state.view);
  bar.hidden = false;
  bar.innerHTML = tabs.map(t => `<button type="button" class="tab-btn tab-${t.key}" data-shell-tab="${t.key}" aria-label="${esc(t.label)}"` +
    `${t.key === active ? ' aria-current="page"' : ''}><span class="tab-icon" aria-hidden="true">${icon(t.icon, 24)}</span><span class="tab-label">${esc(t.label)}</span></button>`).join('');
}

const _shellRender = render;
render = function () {
  _shellRender();
  shellRefresh();
};

document.addEventListener('click', e => {
  const b = e.target.closest('[data-shell-tab]');
  if (!b || !state.user) return;
  const tabs = shellTabs(state.user.role);
  const tab = tabs.find(t => t.key === b.dataset.shellTab);
  if (tab) switchView(tab.top);        // from another tab: its top; on the same tab: back to its top
});
