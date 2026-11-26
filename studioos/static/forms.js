'use strict';
/* StudioOS create forms built from one field list (GET /api/form-fields, see form_fields.py on the server).
   Each field says whether it is required; the label shows "Required" or "Optional" so nobody has to guess.
   Money follows Zoho Books (Expense, Purchase order, Payments made). Loaded after app.js. No inline styles (strict CSP). */

Object.assign(state, {formFields: null});

async function loadFormFields(force) {
  if (state.formFields && !force) return state.formFields;
  const r = await api('/api/form-fields');
  state.formFields = r.forms || {};
  state.booksActive = Boolean(r.books_active);
  state.chartMissing = Boolean(r.chart_missing);
  state.setupMessage = r.setup_message || 'Set up your company and its chart of accounts first.';
  return state.formFields;
}

function fieldTag(required) {   // the usual marker: a red * after the label; optional fields carry no mark
  return required ? '<span class="req-star" aria-hidden="true">*</span>' : '';
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function regInputName(f) { return f.custom ? 'custom.' + f.name : f.name; }

function regField(f) {
  const name = regInputName(f), id = 'f-' + name.replace(/[^a-zA-Z0-9_-]/g, '_');
  const req = f.required ? ' required aria-required="true"' : '';
  const label = `<label for="${esc(id)}">${esc(f.label)}${fieldTag(f.required)}</label>`;
  const max = f.maxlength ? ` maxlength="${Number(f.maxlength)}"` : '';
  const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : '';
  const value = f.default === 'today' ? todayIso() : '';
  if (f.type === 'files') {
    return `<div class="field files-field">${label}<input type="file" class="form-input" id="${esc(id)}" data-upload-files accept="image/jpeg,image/png,application/pdf" multiple>` +
      `<div class="file-previews" id="${esc(id)}-list" aria-live="polite">${filePreviewsHtml()}</div><small class="muted">Up to 5 photos (JPG or PNG) or PDFs, 8 MB each.</small></div>`;
  }
  if (f.type === 'project') {
    return `<div class="field">${label}<select name="${esc(name)}" class="form-input" id="${esc(id)}"${req}>${optionsHtml()}</select></div>`;
  }
  if (f.type === 'cost') {
    const open = (state.costs || []).filter(c => c.status === 'approved' && Number(c.outstanding) - Number(c.payment_pending || 0) > 0);
    return `<div class="field">${label}<select name="${esc(name)}" class="form-input" id="${esc(id)}"${req}>${open.map(c => `<option value="${Number(c.id)}">#${Number(c.id)} – ${esc(c.title)} (${inr(c.outstanding)} outstanding)</option>`).join('')}</select></div>`;
  }
  if (f.type === 'person') {
    const people = (state.users || []).filter(u => u.active !== false && u.role !== 'viewer');
    if (!people.length) return `<div class="field">${label}<input class="form-input" id="${esc(id)}" name="${esc(name)}" type="text"${req}${max} placeholder="e.g. Ravi"></div>`;
    return `<div class="field">${label}<select name="${esc(name)}" class="form-input" id="${esc(id)}"${req}><option value="">Choose a person…</option>${people.map(u => { const n = u.display_name || u.username; return `<option value="${esc(n)}">${esc(n)} · ${esc(String(u.role).replaceAll('_', ' '))}</option>`; }).join('')}</select></div>`;
  }
  if (f.type === 'select') {
    const opts = (f.options || []).map(o => Array.isArray(o) ? o : [o, o]);
    const first = f.default ? '' : `<option value="">Choose…</option>`;
    return `<div class="field">${label}<select name="${esc(name)}" class="form-input" id="${esc(id)}"${req}>${first}${opts.map(([v, l]) => `<option value="${esc(v)}"${v === f.default ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></div>`;
  }
  if (f.type === 'checkbox') {
    return `<div class="field"><label class="checkbox-row" for="${esc(id)}"><input type="checkbox" id="${esc(id)}" name="${esc(name)}" value="true"> <span>${esc(f.label)}</span></label></div>`;
  }
  if (f.type === 'textarea') {
    return `<div class="field">${label}<textarea class="form-input" id="${esc(id)}" name="${esc(name)}" rows="3"${req}${max}${ph}></textarea></div>`;
  }
  if (f.type === 'amount') {
    return `<div class="field">${label}<input class="form-input" id="${esc(id)}" name="${esc(name)}" type="text" inputmode="decimal" autocomplete="off"${req}${ph || ' placeholder="e.g. 9,500"'}><small class="muted amount-echo" data-amount-for="${esc(name)}" aria-live="polite"></small></div>`;
  }
  const type = ['date', 'email', 'tel', 'number', 'password'].includes(f.type) ? f.type : 'text';
  const extra = type === 'tel' ? ' inputmode="tel" pattern="[6-9][0-9]{9}" title="Enter a 10-digit Indian mobile number (e.g. 9876543210)"' : type === 'number' ? ' step="any"' : type === 'password' ? ' minlength="12" autocomplete="new-password"' : '';
  return `<div class="field">${label}<input class="form-input" id="${esc(id)}" name="${esc(name)}" type="${type}"${req}${max}${ph}${extra}${value ? ` value="${value}"` : ''}></div>`;
}

/* Required fields first, then a clearly marked "More details (optional)" group, the way Zoho lays out its forms. */
function regFormHtml(form) {
  const spec = (state.formFields || {})[form];
  if (!spec) return '<p class="muted">Loading the form…</p>';
  const req = spec.fields.filter(f => f.required), opt = spec.fields.filter(f => !f.required);
  return req.map(regField).join('') +
    (opt.length ? `<details class="form-more"><summary>More details (optional)</summary><div class="form-grid">${opt.map(regField).join('')}</div></details>` : '') +
    `<p class="muted form-legend"><span class="req-star" aria-hidden="true">*</span> Required</p>`;
}

function costFormHtml(kind) {
  return `<div class="field"><label for="f-kind">Type${fieldTag(true)}</label><select name="kind" class="form-input" id="f-kind" required>` +
    `<option value="expense"${kind !== 'commitment' ? ' selected' : ''}>Expense (already spent)</option><option value="commitment"${kind === 'commitment' ? ' selected' : ''}>Purchase order (to be billed)</option></select></div>` +
    `<div id="costKindFields" class="form-grid">${regFormHtml(kind === 'commitment' ? 'commitment' : 'expense')}</div>`;
}

const REG_FORMS = {project: 'project', task: 'task', payment: 'payment', user: 'person'};

/* images attached to the form being filled: uploaded as soon as they are chosen, linked when the request is approved */
Object.assign(state, {formFiles: [], formFilesUploading: 0});
function filePreviewsHtml() {
  const chips = (state.formFiles || []).map(f => `<span class="file-chip">${f.is_image ? `<img src="/api/expense-images/${Number(f.id)}" alt="${esc(f.filename)}" loading="lazy">` : '<span class="file-pdf" aria-hidden="true">PDF</span>'}` +
    `<span class="file-name">${esc(f.filename)}</span><button type="button" class="icon-btn file-remove" data-remove-file="${Number(f.id)}" aria-label="Remove ${esc(f.filename)}">✕</button></span>`).join('');
  return chips + (state.formFilesUploading > 0 ? '<span class="file-chip muted">Uploading…</span>' : '');
}
function refreshFilePreviews() {
  document.querySelectorAll('.file-previews').forEach(el => { el.innerHTML = filePreviewsHtml(); });
}
async function uploadFormFiles(files) {
  for (const file of files) {
    if ((state.formFiles || []).length >= 5) { notify('Up to 5 files per entry.', true); break; }
    state.formFilesUploading = (state.formFilesUploading || 0) + 1;
    refreshFilePreviews();
    try {
      const enc = await encodeFile(file);
      const saved = await api('/api/expense-images', {method: 'POST', body: JSON.stringify({filename: enc.filename, base64: enc.base64})});
      state.formFiles.push(saved);
    } catch (err) { notify(err.message || 'That file could not be added.', true); }
    finally {
      state.formFilesUploading = Math.max(0, (state.formFilesUploading || 1) - 1);
      refreshFilePreviews();
    }
  }
}
document.addEventListener('change', async e => {
  const input = e.target;
  if (!input || !input.matches || !input.matches('input[data-upload-files]')) return;
  const files = Array.from(input.files || []);
  input.value = '';
  await uploadFormFiles(files);
});
/* drag a photo onto the receipt box (Zoho Books: "Drag or drop your receipts here") */
document.addEventListener('dragover', e => {
  const box = e.target.closest && e.target.closest('[data-drop-files]');
  if (!box) return;
  e.preventDefault();
  box.classList.add('over');
});
document.addEventListener('dragleave', e => {
  const box = e.target.closest && e.target.closest('[data-drop-files]');
  if (box && !box.contains(e.relatedTarget)) box.classList.remove('over');
});
document.addEventListener('drop', async e => {
  const box = e.target.closest && e.target.closest('[data-drop-files]');
  if (!box) return;
  e.preventDefault();
  box.classList.remove('over');
  await uploadFormFiles(Array.from(e.dataTransfer?.files || []));
});
document.addEventListener('click', e => {
  const b = e.target.closest && e.target.closest('[data-remove-file]');
  if (!b) return;
  state.formFiles = (state.formFiles || []).filter(f => String(f.id) !== b.dataset.removeFile);
  refreshFilePreviews();
});

function regModalHtml(type) {
  state.formFiles = [];
  if (type === 'cost') return costFormHtml('expense');
  return REG_FORMS[type] ? regFormHtml(REG_FORMS[type]) : null;
}

/* turn "custom.x" inputs into {custom: {x: ...}} and checkboxes into true/false before sending */
function regCollect(type, values) {
  const custom = {};
  for (const k of Object.keys(values)) {
    if (k.startsWith('custom.')) { if (String(values[k]).trim()) custom[k.slice(7)] = values[k]; delete values[k]; }
  }
  if (Object.keys(custom).length) values.custom = custom;
  if (type === 'cost') values.gst_included = values.gst_included === 'true' ? true : undefined;
  if (['cost', 'payment'].includes(type) && (state.formFiles || []).length) values.attachment_ids = state.formFiles.map(f => Number(f.id));
  for (const k of Object.keys(values)) if (values[k] === '' || values[k] === undefined) delete values[k];
  return values;
}

document.addEventListener('change', e => {
  if (e.target && e.target.id === 'f-kind' && $('costKindFields')) {
    const holder = $('costKindFields');
    const kept = {};
    holder.querySelectorAll('input, select, textarea').forEach(el => {
      if (!el.name || el.type === 'file') return;
      kept[el.name] = el.type === 'checkbox' ? el.checked : el.value;
    });
    holder.innerHTML = regFormHtml(e.target.value === 'commitment' ? 'commitment' : 'expense');
    holder.querySelectorAll('input, select, textarea').forEach(el => {
      if (!el.name || !(el.name in kept)) return;
      if (el.type === 'checkbox') el.checked = Boolean(kept[el.name]);
      else if (el.tagName !== 'SELECT' || [...el.options].some(o => o.value === kept[el.name])) el.value = kept[el.name];
      if (el.getAttribute('inputmode') === 'decimal' && el.value && typeof amountEcho === 'function') {
        const echo = holder.querySelector('[data-amount-for="' + el.name + '"]');
        if (echo) echo.textContent = amountEcho(el.value);
      }
    });
  }
});
document.addEventListener('focusout', e => {
  const el = e.target;
  if (!el || el.tagName !== 'INPUT' || el.type !== 'tel') return;
  const cleaned = String(el.value || '').replace(/[\s()-]/g, '').replace(/^(?:\+?91|0)/, '');
  if (cleaned !== el.value) el.value = cleaned;
});

/* Every other form on a screen (bills, invoices, receipts...) gets the same "Required" marker on its labels. */
function markRequiredLabels(root) {
  (root || document).querySelectorAll('main form [required], #entryForm [required]').forEach(el => {
    const label = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    const target = label || el.closest('label');
    if (!target || target.querySelector('.req-star')) return;
    const span = document.createElement('span');
    span.className = 'req-star';
    span.setAttribute('aria-hidden', 'true');   // the control itself is marked required for screen readers
    span.textContent = '*';
    // a label that wraps its control keeps the words in its first <span>; put the marker next to them
    const words = target.contains(el) && target.firstElementChild && target.firstElementChild.tagName === 'SPAN' ? target.firstElementChild : target;
    if (words === target && target.contains(el)) target.insertBefore(span, el); else words.appendChild(span);
  });
}
onAfterRender(() => markRequiredLabels());

/* Inbox: a chat draft may lack fields the form requires. The item editor shows them, empty, so the approver can fill
   them in (the server will not approve the item until they are). Names follow the ticket: project, amount_paise... */
const TICKET_FORM = {create_project: 'project', create_task: 'task', record_payment: 'payment'};
const TICKET_KEY = {project: {budget: 'amount_paise'}, task: {project_id: 'project'}, expense: {project_id: 'project', amount: 'amount_paise'},
  commitment: {project_id: 'project', amount: 'amount_paise'}, payment: {amount: 'amount_paise'}};
function withRequiredFields(item, plan) {
  const type = item && item.item_type, after = (item && item.after) || {};
  const form = type === 'record_cost' ? (after.kind === 'commitment' ? 'commitment' : 'expense') : TICKET_FORM[type];
  const spec = form && (state.formFields || {})[form];
  if (!spec) return plan;
  const have = new Set(plan.map(f => f.key));
  const out = plan.map(f => {
    const meta = spec.fields.find(x => (TICKET_KEY[form] || {})[x.name] === f.key || x.name === f.key);
    if (!meta || f.kind !== 'text') return meta ? {...f, label: meta.label, required: meta.required} : f;
    if (meta.type === 'select') return {...f, kind: 'choice', options: meta.options, label: meta.label, required: meta.required};
    if (meta.type === 'date') return {...f, kind: 'date', label: meta.label, required: meta.required};
    if (meta.type === 'person') return {...f, kind: 'person', label: meta.label, required: meta.required};
    return {...f, label: meta.label, required: meta.required};
  });
  for (const x of spec.fields) {
    const key = (TICKET_KEY[form] || {})[x.name] || x.name;
    if (!x.required || x.custom || have.has(key) || ['password', 'checkbox'].includes(x.type)) continue;
    const kind = x.type === 'select' ? 'choice' : x.type === 'date' ? 'date' : x.type === 'person' ? 'person' : x.type === 'amount' ? 'amount' : 'text';
    out.push({key, kind, value: x.type === 'select' ? '' : '', options: x.options, label: x.label, required: true});
  }
  return out;
}

/* Some screens add their forms after the screen is drawn (a button opens a bill or setup form in place).
   Watch the main area and mark those labels too, at most once per frame. */
(function watchForms() {
  const main = document.getElementById('mainContent');
  if (!main || typeof MutationObserver !== 'function') return;
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; markRequiredLabels(main); });
  }).observe(main, {childList: true, subtree: true});
})();

/* The Inbox item editor needs the field list at hand, so load it once after sign-in. */
onAfterRender(() => {
  if (state.user && !state.formFields && !state.formFieldsLoading) {
    state.formFieldsLoading = true;
    loadFormFields().catch(() => null).finally(() => { state.formFieldsLoading = false; });
  }
});

/* The right control for a field of a draft, from the same field list: calendar for dates, drop-down for fixed choices,
   people list for owners and managers. Used by the chat card and the Inbox editor. */
function regMeta(item, key) {
  const type = item && item.item_type, after = (item && item.after) || {};
  const form = type === 'record_cost' ? (after.kind === 'commitment' ? 'commitment' : 'expense') : TICKET_FORM[type];
  const spec = form && (state.formFields || {})[form];
  if (!spec) return null;
  return spec.fields.find(x => ((TICKET_KEY[form] || {})[x.name] || x.name) === key) || null;
}

function regControl(meta, id, raw, name = 'value') {
  const val = raw == null ? '' : String(raw);
  const base = `class="form-input" id="${esc(id)}" name="${esc(name)}"`;
  if (meta.type === 'date') return `<input ${base} type="date" value="${esc(val)}">`;
  if (meta.type === 'select') {
    const opts = (meta.options || []).map(o => Array.isArray(o) ? o : [o, o]);
    return `<select ${base}>${val ? '' : '<option value="">Choose…</option>'}${opts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === val ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  }
  if (meta.type === 'person') {
    const people = (state.users || []).filter(u => u.active !== false && u.role !== 'viewer');
    if (!people.length) return `<input ${base} type="text" value="${esc(val)}">`;
    return `<select ${base}><option value="">Choose a person…</option>${people.map(u => { const n = u.display_name || u.username; return `<option value="${esc(n)}"${n === val ? ' selected' : ''}>${esc(n)} · ${esc(String(u.role).replaceAll('_', ' '))}</option>`; }).join('')}</select>`;
  }
  if (meta.type === 'textarea') return `<textarea ${base} rows="3">${esc(val)}</textarea>`;
  if (meta.type === 'tel') return `<input ${base} type="tel" inputmode="tel" pattern="[6-9][0-9]{9}" title="Enter a 10-digit Indian mobile number (e.g. 9876543210)" maxlength="16" value="${esc(val)}">`;
  if (meta.type === 'email') return `<input ${base} type="email" value="${esc(val)}">`;
  return null;
}
