'use strict';

function plainChangeCopy(value) {
  return String(value ?? '')
    .replace(/\btickets\b/gi, 'change requests')
    .replace(/\bticket\b/gi, 'change request')
    .replace(/\bcommitted\b/gi, 'saved')
    .replace(/\bcommitting\b/gi, 'saving')
    .replace(/\bcommit\b/gi, 'save')
    .replace(/\breversed\b/gi, 'undone')
    .replace(/\brevers(?:al|e)\b/gi, 'undo')
    .replace(/\btransactions?\b/gi, 'entries')
    .replace(/\s+atomically\b/gi, '')
    .replace(/\bquarantin(?:e|ed)\b/gi, 'set aside')
    .replace(/\bstage a\b/gi, 'design review')
    .replace(/\bjson\b/gi, 'structured details')
    .replace(/\bportfolio sum\b/gi, 'across all projects')
    .replace(/\bknown costs\b/gi, 'expenses and orders');
}

function requestDialog(message, {initial, action = 'Continue'} = {}) {
  const dialog = document.getElementById('actionDialog');
  if (dialog.open) return Promise.resolve(null);
  const title = document.getElementById('actionDialogTitle');
  const holder = document.getElementById('actionDialogField');
  title.textContent = plainChangeCopy(message);
  holder.replaceChildren();
  document.getElementById('actionDialogSubmit').textContent = action;
  let field;
  if (initial !== undefined) {
    field = document.createElement(/^[\[{]|\n/.test(initial) ? 'textarea' : 'input');
    field.className = 'form-input';
    field.setAttribute('aria-labelledby', title.id);
    field.value = initial;
    holder.appendChild(field);
  }
  dialog.returnValue = '';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      resolve(dialog.returnValue === 'continue' ? (field ? field.value : true) : null);
      holder.replaceChildren();
    }, {once: true});
    dialog.showModal();
    (field || document.getElementById('actionDialogCancel')).focus();
  });
}

function askText(message, initial = '', action = 'Continue') {
  return requestDialog(message, {initial, action});
}

async function askConfirm(message, action = 'Continue') {
  return (await requestDialog(message, {action})) === true;
}

function plainRequestError(status, detail) {
  if (status >= 500) return 'StudioOS could not finish the request. Try again in a moment.';
  if (Array.isArray(detail)) {
    const fields = [...new Set(detail.map(issue => issue?.loc?.at(-1)).filter(name => typeof name === 'string')
      .map(name => document.getElementById('f-' + name)?.labels?.[0]?.textContent?.trim())
      .filter(Boolean))];
    return fields.length ? 'Check ' + fields.join(', ') + ' and try again.' : 'Check the highlighted or required details and try again.';
  }
  const reason = typeof detail === 'string' ? plainChangeCopy(detail).trim() : '';
  if (status === 401) return reason || 'Check your sign-in details and try again.';
  if (status === 403) return reason ? reason + ' Ask the owner if you need access.' : 'Ask the owner if you need access.';
  if (status === 404) return 'This could not be found. Refresh and try again.';
  if (status === 429) return reason || 'Wait a few minutes and try again.';
  return reason ? reason.replace(/[.!?]$/, '') + '. Check the details and try again.'
                : 'StudioOS could not finish the request. Check the details and try again.';
}

const ROLE_MENU = {
  site_engineer: ['home', 'assistant', 'projects', 'inbox', 'tickets', 'work', 'today', 'mytime', 'tasks', 'site', 'documents', 'account'],
  architect: ['home', 'assistant', 'projects', 'inbox', 'tickets', 'work', 'today', 'mytime', 'tasks', 'site', 'documents', 'savedviews', 'account'],
  accounts: ['home', 'assistant', 'projects', 'inbox', 'tickets', 'chart', 'ledger', 'books', 'bankfeed', 'moneyfiles', 'sales', 'receipts', 'reports', 'taxtools', 'budget', 'activity', 'account'],
  viewer: ['home', 'assistant', 'projects', 'tasks', 'documents', 'account'],
};

function applyRoleMenu() {
  // The left menu follows the same role rules, but nav.js builds it from one map (navRefresh), so there is nothing to hide here.
}

function markCurrentNavigation() {
  const links = [...document.querySelectorAll('#sidebar .nav-link[data-view]')];
  const active = links.find(link => link.classList.contains('active') && !link.hidden);
  links.forEach(link => {
    if (link === active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  document.querySelectorAll('.nav-icon,.stat-icon,.empty-big,.activity-symbol,.message-avatar').forEach(
    icon => icon.setAttribute('aria-hidden', 'true'));
}

const ENTRY_DRAFT_TYPES = new Set(['cost', 'siteexpense', 'task', 'payment']);

function entryDraftKey(type) {
  return 'studioos-entry-draft:' + state.user?.username + ':' + type;
}

function rememberEntryDraft(event) {
  const dialog = document.getElementById('entryDialog');
  const type = dialog.dataset.type;
  if (!dialog.open || !state.user || !ENTRY_DRAFT_TYPES.has(type) || !event.target.closest('#entryForm')) return;
  const form = document.getElementById('entryForm');
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    localStorage.setItem(entryDraftKey(type), JSON.stringify({values, requestKey: dialog.dataset.requestKey}));
  } catch (_) { /* The current form remains available if storage is full or disabled. */ }
}

function restoreEntryDraft(dialog) {
  const type = dialog.dataset.type;
  if (!state.user || !ENTRY_DRAFT_TYPES.has(type)) return;
  try {
    const draft = JSON.parse(localStorage.getItem(entryDraftKey(type)) || 'null');
    if (!draft) return;
    for (const [name, value] of Object.entries(draft.values)) {
      const field = document.getElementById('entryForm').elements[name];
      if (field && (field.tagName !== 'SELECT' || [...field.options].some(option => option.value === value))) field.value = value;
    }
    if (draft.requestKey) dialog.dataset.requestKey = draft.requestKey;
  } catch (_) { /* Ignore an unreadable draft. */ }
}

function clearEntryDraft(type) {
  if (!state.user || !ENTRY_DRAFT_TYPES.has(type)) return;
  try { localStorage.removeItem(entryDraftKey(type)); } catch (_) {}
}

document.addEventListener('input', rememberEntryDraft);
document.addEventListener('change', rememberEntryDraft);
