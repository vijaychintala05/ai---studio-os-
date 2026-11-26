'use strict';
/* StudioOS navigation: one map for the left menu, the tabs inside each section, the top bar trail and the screens that show up in search.
   The left menu has five places (Home, Inbox, Projects, Money, Settings); each opens a section whose screens are tabs across the top.
   Which places a person sees follows the role rules already in the app (ROLE_MENU in interaction.js, and the finance, approver and
   admin checks). Nothing here grants access: it only decides what to show, and the server still checks every request.
   The first half is plain data and functions (tested with node); the second half wires them to the page. No inline styles (strict CSP). */

const NAV_SECTIONS = [
  {id: 'home', label: 'Home', icon: 'home', tabs: [
    {view: 'home', label: 'Home', words: 'start page what needs me'},
    {view: 'today', label: 'Today', words: 'my day to do morning list'},
    {view: 'mytime', label: 'My time', words: 'timesheet hours log time leave holiday'},
    {view: 'overview', label: 'Overview', words: 'summary figures totals'},
    {view: 'insights', label: 'Dashboards', words: 'ask questions charts reports dashboards'},
  ]},
  {id: 'inbox', label: 'Inbox', icon: 'inbox', tabs: [
    {view: 'tickets', label: 'Change requests', words: 'tickets proposals review approve changes'},
    {view: 'approvals', label: 'Approvals', need: 'approver', words: 'approve costs payments money waiting'},
    {view: 'inbox', label: 'Files to sort', words: 'inbox files photos upload intake sort'},
    {view: 'newtypes', tab: 'waiting', label: 'Waiting for a place', words: 'new kinds of information parked unplaced'},
  ]},
  {id: 'projects', label: 'Projects', icon: 'projects', tabs: [
    {view: 'projects', label: 'Projects', words: 'clients sites jobs'},
    {view: 'tasks', label: 'Tasks', words: 'to do assign deadlines'},
    {view: 'work', label: 'Work', words: 'stages dependencies work plan'},
    {view: 'planbudget', label: 'Plan and budget', words: 'baseline slip schedule'},
    {view: 'site', label: 'Site reports', words: 'daily visit photos snag'},
    {view: 'documents', label: 'Documents', words: 'nas files drawings folders'},
    {view: 'savedviews', label: 'Saved views', words: 'filters views'},
    {view: 'recycle', label: 'Templates and recycle bin', need: 'approver', words: 'deleted restore templates recycle'},
  ]},
  {id: 'money', label: 'Money', icon: 'books', tabs: [
    {view: 'books', label: 'Books home', need: 'books', words: 'books accounts bank cash vendors'},
    {view: 'sales', label: 'Sales', need: 'finance', words: 'quotes tax invoices credit notes'},
    {view: 'receipts', label: 'Receipts & retainers', need: 'finance', words: 'client payments advances customer statement'},
    {view: 'reports', label: 'Reports', need: 'books', words: 'profit loss balance sheet cash flow budget actual'},
    {view: 'taxtools', label: 'Tax & Recurring', need: 'books', words: 'gst tds calculator recurring budgets'},
    {view: 'budget', label: 'Budgets and costs', need: 'finance', words: 'expenses bills purchase orders'},
    {view: 'ledger', label: 'Accounting ledger', need: 'finance', words: 'journal entries'},
    {view: 'chart', label: 'Chart of accounts', need: 'finance', words: 'ledger heads'},
    {view: 'activity', label: 'Activity log', need: 'finance', words: 'audit history'},
  ]},
  {id: 'settings', label: 'Settings', icon: 'settings', tabs: [
    {view: 'team', label: 'Team and roles', need: 'admin', words: 'users people permissions'},
    {view: 'settings', label: 'AI settings', need: 'admin', words: 'provider model keys'},
    {view: 'aireader', label: 'AI reader', need: 'admin', words: 'fields extraction'},
    {view: 'agents', label: 'Automatic checks', need: 'approver', words: 'hooks agents'},
    {view: 'newtypes', tab: 'types', label: 'Record types', words: 'fields kinds of record'},
    {view: 'universal', label: 'Other record types', words: 'custom records'},
    {view: 'restructure', label: 'Change a record type', need: 'admin', words: 'rename fields'},
    {view: 'selfcheck', label: 'System check', words: 'health diagnostics'},
    {view: 'safety', label: 'Data safety', need: 'admin', words: 'backups restore recovery'},
  ]},
];

// Screens that have no tab of their own but belong to a section (so the menu still shows where you are).
const NAV_BELONGS = {party: 'money', project: 'projects'};
// Screens reached from the top bar or the account block, not from a section.
const NAV_EXTRA = [
  {view: 'assistant', label: 'Ask StudioOS', words: 'chat ai question assistant'},
  {view: 'account', label: 'My account', words: 'password two-factor profile sign out'},
  {view: 'me', label: 'Me and all screens', words: 'menu everything list screens account theme sign out'},
];
const NAV_ALL_VIEWS = [...new Set(NAV_SECTIONS.flatMap(s => s.tabs.map(t => t.view)).concat(NAV_EXTRA.map(t => t.view), Object.keys(NAV_BELONGS)))];
const NAV_NEED = {books: ['admin', 'accounts'], finance: ['admin', 'manager', 'accounts'], approver: ['admin', 'manager'], admin: ['admin']};

function navAllowsFor(role, tab, menu) {
  if (!role) return false;
  if (menu && !menu.includes(tab.view)) return false;
  return !tab.need || NAV_NEED[tab.need].includes(role);
}

function navTabsFor(section, role, menu) {
  return section.tabs.filter(t => navAllowsFor(role, t, menu));
}

// The sections a role sees in the left menu: those with at least one screen it may open.
function navSectionsFor(role, menu) {
  return NAV_SECTIONS.filter(s => navTabsFor(s, role, menu).length > 0);
}

function navSectionOf(view, ntTab) {
  if (NAV_BELONGS[view]) return NAV_BELONGS[view];
  for (const s of NAV_SECTIONS) {
    if (s.tabs.some(t => t.view === view && (!t.tab || t.tab === (ntTab || 'waiting')))) return s.id;
  }
  return '';
}

function tabCount(t) {
  const c = state.inboxCounts || {};
  const n = t.view === 'approvals' ? c.approvals : t.view === 'tickets' ? c.tickets : 0;
  return n ? ` <span class="tab-count" aria-label="${n} waiting">${n}</span>` : '';
}
function navTabIsCurrent(tab, view, ntTab) {
  return tab.view === view && (!tab.tab || tab.tab === (ntTab || 'waiting'));
}

// Every screen a person may open, for search. Only screens the role allows are listed.
function navEntriesFor(role, menu) {
  const out = [];
  NAV_SECTIONS.forEach(s => navTabsFor(s, role, menu).forEach(t => out.push({view: t.view, tab: t.tab || '', label: t.label, section: s.label, words: t.words || ''})));
  NAV_EXTRA.forEach(t => { if (navAllowsFor(role, {view: t.view}, null)) out.push({view: t.view, tab: '', label: t.label, section: '', words: t.words}); });
  return out;
}

function navScore(entry, query) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return 0;
  const label = entry.label.toLowerCase(), hay = (entry.label + ' ' + entry.section + ' ' + entry.words).toLowerCase();
  let score = 0;
  for (const w of words) {
    if (label.startsWith(w)) score += 4;
    else if (label.includes(w)) score += 3;
    else if (hay.includes(w)) score += 1;
    else return 0;                                    // every typed word must match something
  }
  return score;
}

function navSearch(entries, query, limit = 8) {
  return entries.map(e => ({e, s: navScore(e, query)})).filter(x => x.s > 0).sort((a, b) => b.s - a.s).slice(0, limit).map(x => x.e);
}

// What the Me page lists: every screen this person may open, by place (the same map as the menu and the tabs).
function navMeSections(role, menu) {
  return NAV_SECTIONS.map(s => ({id: s.id, label: s.label, items: navTabsFor(s, role, menu).map(t => ({view: t.view, tab: t.tab || '', label: t.label}))}))
    .filter(s => s.items.length > 0);
}

/* --- page wiring (not run by the node tests) --- */

const NAV_RAIL_KEY = 'studioos-menu-narrow';

function navRole() { return state.user && state.user.role; }
function navMenu() { return typeof ROLE_MENU !== 'undefined' ? ROLE_MENU[navRole()] : undefined; }

// True when the signed-in person may open this screen (used by other screens for shortcuts).
function navCanOpen(view) {
  return NAV_SECTIONS.some(s => s.tabs.some(t => t.view === view && navAllowsFor(navRole(), t, navMenu())));
}

function navUpdateTabFade(strip) {
  if (!strip || strip.hidden) return;
  strip.classList.toggle('can-scroll-right', strip.scrollWidth - strip.scrollLeft - strip.clientWidth > 4);
}
window.addEventListener('resize', () => navUpdateTabFade(document.getElementById('sectionTabs')));

function navFillIcons() {
  document.querySelectorAll('#mainNav [data-section]').forEach(btn => {
    const sec = NAV_SECTIONS.find(s => s.id === btn.dataset.section);
    const slot = btn.querySelector('.nav-icon');
    if (sec && slot && !slot.firstChild) slot.innerHTML = icon(sec.icon, 24);
  });
  const collapse = document.querySelector('#navCollapse .nav-icon');
  if (collapse && !collapse.firstChild) collapse.innerHTML = icon('chevron', 24);
  const a = document.querySelector('.ask-icon'); if (a && !a.firstChild) a.innerHTML = icon('capture', 16);
}

function navRefresh() {
  const nav = document.getElementById('mainNav');
  if (!nav) return;
  navFillIcons();
  navUserMenuFill();
  const role = navRole(), menu = navMenu();
  const active = navSectionOf(state.view, state.ntTab);
  NAV_SECTIONS.forEach(sec => {
    const btn = nav.querySelector('[data-section="' + sec.id + '"]');
    if (!btn) return;
    const tabs = navTabsFor(sec, role, menu);
    btn.hidden = !tabs.length;
    if (tabs.length) btn.dataset.view = tabs[0].view;
    btn.classList.toggle('active', sec.id === active);
    if (sec.id === active) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
  });
  const divider = nav.querySelector('.nav-divider');
  const settingsShown = nav.querySelector('[data-section="settings"]') && !nav.querySelector('[data-section="settings"]').hidden;
  if (divider) divider.hidden = !settingsShown;
  const account = document.querySelector('.foot-user');
  if (account) { account.classList.toggle('active', state.view === 'account'); if (state.view === 'account') account.setAttribute('aria-current', 'page'); else account.removeAttribute('aria-current'); }

  // the count on Inbox: everything waiting for this person
  const badge = document.getElementById('approvalBadge');
  if (badge) {
    let n = 0, requests = 0;
    const money = isApprover() ? (state.approvals?.costs?.length || 0) + (state.approvals?.payments?.length || 0) : 0;   // money approvals wait here too
    try { const c = waitingCounts(state); requests = (c.tickets || 0) + (c.parked || 0) + (c.toSave || 0) + (c.returned || 0); n = requests + money; } catch (e) { n = money; }
    badge.textContent = String(n); badge.hidden = !n;
    badge.setAttribute('aria-label', n + ' waiting for you');
    state.inboxCounts = {tickets: requests, approvals: money};
    // Opening Inbox lands where something is waiting: money approvals when no change request needs this person
    const inboxBtn = nav.querySelector('[data-section="inbox"]');
    if (inboxBtn) inboxBtn.dataset.view = !requests && money ? 'approvals' : 'tickets';
  }

  // the trail in the top bar: Section › Screen (the screen name is written by each screen's own code)
  const sec = NAV_SECTIONS.find(s => s.id === active);
  const crumb = document.getElementById('crumbSection'), dash = document.getElementById('crumbDash');
  const leaf = document.getElementById('breadcrumb');
  const same = Boolean(sec && leaf && leaf.textContent.trim() === sec.label);          // 'Home › Home' says nothing twice
  if (crumb) { crumb.textContent = sec ? sec.label : ''; crumb.hidden = !sec || same; }
  if (dash) dash.hidden = !sec || same;
  const ask = document.getElementById('askBtn');
  if (ask) { ask.hidden = !role || state.view === 'assistant'; }

  // the tabs of the current section
  const strip = document.getElementById('sectionTabs');
  if (!strip) return;
  const tabs = sec ? navTabsFor(sec, role, menu) : [];
  if (!sec || tabs.length < 2 || state.view === 'assistant') { strip.hidden = true; strip.innerHTML = ''; return; }
  strip.hidden = false;
  strip.setAttribute('aria-label', sec.label + ' screens');
  strip.innerHTML = tabs.map(t => {
    const current = navTabIsCurrent(t, state.view, state.ntTab);
    return `<button type="button" class="section-tab" data-view="${esc(t.view)}"${t.tab ? ` data-tab="${esc(t.tab)}"` : ''}${current ? ' aria-current="page"' : ''}>${esc(t.label)}${tabCount(t)}</button>`;
  }).join('');
  if (!strip.dataset.scrollBound) {
    strip.dataset.scrollBound = '1';
    strip.addEventListener('scroll', () => navUpdateTabFade(strip), {passive: true});
  }
  const activeTab = strip.querySelector('[aria-current="page"]');
  if (activeTab && typeof activeTab.scrollIntoView === 'function') activeTab.scrollIntoView({inline: 'nearest', block: 'nearest'});
  navUpdateTabFade(strip);
}

const _navRender = render;
render = function () {
  _navRender();
  navRefresh();
};

/* The Me page (the phone's last tab): who you are, the colour theme, and every screen you may open, by place. */
function navMeView() {
  const u = state.user || {};
  const name = u.display_name || u.username || 'StudioOS', role = String(u.role || '').replace('_', ' ');
  const sections = navMeSections(navRole(), navMenu()).map(sec => `<section class="panel me-panel"><div class="panel-head"><div class="panel-title">${esc(sec.label)}</div></div>` +
    `<div class="panel-body me-list">${sec.items.map(i => `<button type="button" class="me-link" data-view="${esc(i.view)}"${i.tab ? ` data-tab="${esc(i.tab)}"` : ''}>${esc(i.label)}</button>`).join('')}</div></section>`).join('');
  return head('Me', 'Your account, the colour theme and every screen you can open.') +
    `<section class="panel me-panel"><div class="panel-body me-who"><span class="avatar" aria-hidden="true">${esc(name.slice(0, 1).toUpperCase())}</span>` +
    `<div><strong>${esc(name)}</strong><div class="muted">${esc(role)}</div></div></div>` +
    `<div class="panel-body me-actions"><div class="theme-switch" role="group" aria-label="Colour theme">` +
    `${[['light', 'Light', 'sun'], ['dark', 'Dark', 'moon'], ['sunlight', 'Sunlight (high contrast)', 'contrast']].map(([k, label, ic]) => `<button class="icon-btn" type="button" data-theme-set="${k}" aria-pressed="${document.documentElement.getAttribute('data-theme') === k}" aria-label="${label} theme" title="${label}">${icon(ic, 24)}</button>`).join('')}</div>` +
    `<button type="button" class="btn btn-secondary" data-nav="refresh">Refresh data</button>` +
    `<button type="button" class="btn btn-secondary" data-view="account">My account</button>` +
    `<button type="button" class="btn btn-secondary" data-nav="signout">Sign out</button></div></section>` + sections;
}

const _navRenderBase = render;
render = function () {
  if (state.view === 'me' && state.user) {
    document.body.classList.remove('chat-mode');
    updateIdentity();
    $('mainContent').innerHTML = navMeView();
    $('breadcrumb').textContent = 'Me';
    navRefresh();
    if (typeof shellRefresh === 'function') shellRefresh();
    ovChrome();
    outboxPaint();
    return;
  }
  _navRenderBase();
};

/* The account menu in the top bar: name, colour theme, My account and Sign out (this replaced three theme buttons and Sign out on the bar). */
function navUserMenuClose(focusButton) {
  const panel = document.getElementById('userMenuPanel'), btn = document.getElementById('userMenuBtn');
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  if (btn) { btn.setAttribute('aria-expanded', 'false'); if (focusButton) btn.focus(); }
}
function navUserMenuFill() {
  const u = state.user || {};
  const name = u.display_name || u.username || 'StudioOS';
  const av = document.getElementById('userMenuAvatar'), nm = document.getElementById('userMenuName'), rl = document.getElementById('userMenuRole');
  if (av) av.textContent = name.slice(0, 1).toUpperCase();
  if (nm) nm.textContent = name;
  if (rl) rl.textContent = String(u.role || '').replace('_', ' ');
}
document.addEventListener('click', e => {
  const btn = e.target.closest('#userMenuBtn'), panel = document.getElementById('userMenuPanel');
  if (btn && panel) {
    const open = panel.hidden;
    navUserMenuFill();
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    if (open) panel.querySelector('button')?.focus();
    return;
  }
  if (e.target.closest('[data-nav="refresh"]')) { navUserMenuClose(false); document.getElementById('refreshBtn')?.click(); return; }
  if (e.target.closest('[data-nav="signout"]')) { document.getElementById('logoutBtn')?.click(); return; }
  if (panel && !panel.hidden && (!e.target.closest('#userMenuPanel') || e.target.closest('[data-view], #logoutBtn'))) navUserMenuClose(false);
});
document.addEventListener('focusout', e => {
  const panel = document.getElementById('userMenuPanel'), btn = document.getElementById('userMenuBtn');
  if (!panel || panel.hidden) return;
  if (e.target.closest && e.target.closest('#userMenu') && e.relatedTarget && !panel.contains(e.relatedTarget) && e.relatedTarget !== btn) {
    navUserMenuClose(false);
  }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') navUserMenuClose(true); });

/* The menu can be made narrower (icons only); the choice is remembered on this device. */
function navSetNarrow(on) {
  const bar = document.getElementById('sidebar');
  if (!bar) return;
  bar.classList.toggle('rail', on);
  const b = document.getElementById('navCollapse');
  if (b) { b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', on ? 'Make the menu wider' : 'Make the menu narrower'); }
  try { localStorage.setItem(NAV_RAIL_KEY, on ? '1' : '0'); } catch (e) { /* storage may be blocked: the menu still works */ }
}
document.addEventListener('DOMContentLoaded', () => {
  let narrow = false;
  try { narrow = localStorage.getItem(NAV_RAIL_KEY) === '1'; } catch (e) { narrow = false; }
  navSetNarrow(narrow);
});
document.addEventListener('click', e => {
  if (e.target.closest('#navCollapse')) navSetNarrow(!document.getElementById('sidebar').classList.contains('rail'));
});

/* Search: screens that match what is typed are listed first in the one search box (overlays.js), then projects, tasks and files.
   Only screens this person may open are listed. Ctrl+K opens the search from anywhere; the / key already does too. */
function ovScreenRows(q) {
  const query = String(q || '').trim();
  if (query.length < 2) return '';
  const found = navSearch(navEntriesFor(navRole(), navMenu()), query, 5);
  if (!found.length) return '';
  return '<div class="w-sub">Screens</div>' + found.map(e => `<button type="button" class="ov-row" data-nav-go data-go-view="${esc(e.view)}"` +
    `${e.tab ? ` data-go-tab="${esc(e.tab)}"` : ''}><strong>${esc(e.label)}</strong><span class="muted">${esc(e.section)}</span></button>`).join('');
}

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && state.user && typeof ovOpen === 'function' && !state.ov) { e.preventDefault(); ovOpen('search'); }
});
document.addEventListener('click', e => {
  const row = e.target.closest('[data-nav-go]');
  if (!row) return;
  if (typeof ovClose === 'function') ovClose();
  if (row.dataset.goTab) state.ntTab = row.dataset.goTab;
  switchView(row.dataset.goView);
});

const renderScreen = render;
render = function () {
  if (state.mustSetup2fa) state.view = 'account';
  renderScreen();
  addTableSearch();
  if (state.user && !$('refreshBanner') && state.refreshFailed?.length && state.view !== 'assistant') {
    $('mainContent').insertAdjacentHTML('afterbegin', refreshBanner());
  }
};
