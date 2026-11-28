'use strict';

const FORM_TICKETS = {create_project: 'project', create_task: 'task'};
let createFormOptions;

function loadCreateFormOptions(force = false) {
  const session = state.session;
  if (createFormOptions && createFormOptions.session === session && (!force || !createFormOptions.forms)) {
    return createFormOptions.request;
  }
  const loading = {session, forms: null, request: null};
  createFormOptions = loading;
  loading.request = api('/api/form-fields').then(result => {
    if (state.session === session) loading.forms = result.forms;
    return result.forms;
  }, error => {
    if (createFormOptions === loading) createFormOptions = null;
    throw error;
  });
  return loading.request;
}

function createFields(type) {
  if (type === 'user') type = 'person';
  return createFormOptions?.session === state.session ? createFormOptions?.forms?.[type]?.fields ?? [] : [];
}

function regControl(meta, id, raw, name = 'value') {
  const value = raw == null ? '' : String(raw);
  const attr = `class="form-input" id="${esc(id)}" name="${esc(name)}"` +
    (meta.required ? ' required' : '') + (meta.maxlength ? ` maxlength="${Number(meta.maxlength)}"` : '');
  if (meta.type === 'select') {
    const options = meta.options.map(option => `<option value="${esc(option)}"${option === value ? ' selected' : ''}>${esc(option)}</option>`);
    if (value && !meta.options.includes(value)) options.unshift(`<option value="${esc(value)}" selected>${esc(value)}</option>`);
    return `<select ${attr}><option value="">Choose…</option>${options.join('')}</select>`;
  }
  if (meta.type === 'textarea') return `<textarea ${attr} rows="3">${esc(value)}</textarea>`;
  const type = ['date', 'email', 'tel', 'number', 'text'].includes(meta.type) ? meta.type : null;
  return type ? `<input ${attr} type="${type}" value="${esc(value)}">` : null;
}

function extraCreateFields(type) {
  return createFields(type).filter(field => field.extra).map(field => {
    const id = 'f-' + field.name;
    return `<div class="field"><label for="${esc(id)}">${esc(field.label)}</label>${regControl(field, id, '', field.custom ? 'custom.' + field.name : field.name)}</div>`;
  }).join('');
}

function applyCreateRequirements(type, form) {
  for (const field of createFields(type)) {
    if (field.extra) continue;
    const control = form.elements.namedItem(field.name);
    if (control) control.required = Boolean(field.required);
  }
}

function regCollect(type, values) {
  const custom = {};
  for (const field of createFields(type)) {
    if (!field.custom) continue;
    const name = 'custom.' + field.name;
    const value = values[name];
    delete values[name];
    if (value?.trim()) custom[field.name] = value.trim();
  }
  if (Object.keys(custom).length) values.custom = custom;
}

function ticketFieldKey(field) {
  if (field.custom) return 'custom.' + field.name;
  return field.name === 'project_id' ? 'project' : field.name;
}

function regMeta(item, key) {
  return createFields(FORM_TICKETS[item?.item_type]).find(field => ticketFieldKey(field) === key);
}

function withRequiredFields(item, plan) {
  const fields = createFields(FORM_TICKETS[item?.item_type]);
  if (!fields.length) return plan;
  const updated = plan.map(entry => ({...entry, formField: regMeta(item, entry.key)}));
  for (const field of fields) {
    const key = ticketFieldKey(field);
    if (field.required && !updated.some(entry => entry.key === key)) {
      updated.push({key, kind: field.type === 'project' ? 'project' : 'text', value: '', formField: field});
    }
  }
  return updated;
}

function markRequiredLabels(root) {
  for (const input of root.querySelectorAll('form [required]')) {
    for (const label of input.labels || []) {
      if (label.querySelector('.req-star') || /\*\s*$/.test(label.firstElementChild?.textContent || label.textContent)) continue;
      const marker = document.createElement('span');
      marker.className = 'req-star';
      marker.textContent = ' *';
      marker.setAttribute('aria-hidden', 'true');
      const text = label.firstElementChild;
      if (text?.tagName === 'SPAN') text.append(marker);
      else if (label.contains(input)) label.insertBefore(marker, input);
      else label.append(marker);
    }
  }
}

const bookReceiptDrafts = new WeakMap();

function receiptDraft(form) {
  const owner = form.id === 'moneyEntryForm' ? (state.moneyEntry || form) : form;
  let draft = bookReceiptDrafts.get(owner);
  if (!draft) {
    draft = {files: [], pending: 0};
    bookReceiptDrafts.set(owner, draft);
  }
  return draft;
}

function filePreviewsHtml(draft) {
  if (!draft) return '';
  return draft.files.map(file => `<span class="file-chip">${file.is_image
    ? `<img src="/api/expense-images/${Number(file.id)}" alt="" loading="lazy">`
    : '<span class="file-pdf">PDF</span>'}<span class="file-name">${esc(file.filename)}</span>
    <button type="button" class="icon-btn file-remove" data-remove-receipt="${Number(file.id)}"
      aria-label="Remove ${esc(file.filename)}">✕</button></span>`).join('') +
    (draft.pending ? '<span class="muted">Uploading receipt…</span>' : '');
}

function moneyFilePreviewsHtml() {
  return filePreviewsHtml(state.moneyEntry && bookReceiptDrafts.get(state.moneyEntry));
}

function formReceiptIds(form) {
  const draft = receiptDraft(form);
  if (draft.pending) throw new Error('Wait for the receipt upload to finish.');
  return draft.files.map(file => file.id);
}

function updateReceiptPreviews(form, draft) {
  const current = form.isConnected ? form : form.id === 'moneyEntryForm' ? document.getElementById(form.id) : null;
  if (!current || receiptDraft(current) !== draft) return;
  const previews = current.querySelector('.file-previews');
  if (previews) previews.innerHTML = filePreviewsHtml(draft);
}

async function uploadFormReceipts(form, files) {
  const draft = receiptDraft(form);
  for (const file of files) {
    if (draft.pending + draft.files.length >= 5) {
      notify('Attach up to five files per entry.', true);
      break;
    }
    draft.pending += 1;
    updateReceiptPreviews(form, draft);
    try {
      const {filename, base64} = await encodeFile(file);
      const receipt = await api('/api/expense-images', {method: 'POST', body: JSON.stringify({filename, base64})});
      draft.files.push(receipt);
    } catch (error) {
      notify(error.message || 'The receipt could not be added.', true);
    } finally {
      draft.pending -= 1;
      updateReceiptPreviews(form, draft);
    }
  }
}

document.addEventListener('change', event => {
  const input = event.target;
  if (!input.matches?.('input[data-upload-files]') || !input.form) return;
  const files = Array.from(input.files || []);
  input.value = '';
  uploadFormReceipts(input.form, files);
});
document.addEventListener('click', event => {
  const button = event.target.closest?.('[data-remove-receipt]');
  if (!button?.form) return;
  const draft = receiptDraft(button.form);
  draft.files = draft.files.filter(file => file.id !== Number(button.dataset.removeReceipt));
  updateReceiptPreviews(button.form, draft);
});
document.addEventListener('dragover', event => {
  if (event.target.closest?.('[data-drop-files]') && Array.from(event.dataTransfer.types).includes('Files')) event.preventDefault();
});
document.addEventListener('drop', event => {
  const form = event.target.closest?.('[data-drop-files]')?.closest('form');
  if (!form) return;
  event.preventDefault();
  uploadFormReceipts(form, Array.from(event.dataTransfer.files || []));
});

onAfterRender(() => {
  if (state.user && (!createFormOptions || createFormOptions.session !== state.session)) {
    loadCreateFormOptions().catch(() => {});
  }
});
let formMarkerFrame;
new MutationObserver(() => {
  if (formMarkerFrame) return;
  formMarkerFrame = requestAnimationFrame(() => {
    formMarkerFrame = undefined;
    markRequiredLabels(document);
  });
}).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['required']});
