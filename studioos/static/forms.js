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
