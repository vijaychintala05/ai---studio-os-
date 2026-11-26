'use strict';
/* Money -> Tax rules: the dated rules the books use (rates, thresholds, codes), what applies on a given date, and
   drafts to add or retire a rule. The app does not decide what a rule means; the accountant does. Loaded after gapkit.js. */

const TR_KINDS = [['rate', 'Rate'], ['threshold', 'Threshold'], ['section_alias', 'Section name'], ['code', 'Code'], ['category', 'Category']];
const trKindName = k => (TR_KINDS.find(x => x[0] === k) || [0, k])[1];
const trValueText = v => Object.entries(v || {}).map(([k, x]) => `${k} = ${typeof x === 'object' ? JSON.stringify(x) : x}`).join('; ');

/* "name = value" lines. Whole numbers stay numbers; decimals are refused so nothing is rounded silently. */
function trParseValue(text) {
  const out = {};
  for (const line of String(text || '').split('\n').map(l => l.trim()).filter(Boolean)) {
    const at = line.indexOf('=');
    if (at < 1) throw new Error(`Write each line as name = value (got "${line}").`);
    const key = line.slice(0, at).trim(), raw = line.slice(at + 1).trim();
    if (!raw) throw new Error(`"${key}" has no value.`);
    if (/^-?\d+\.\d+$/.test(raw)) throw new Error(`Use whole numbers for "${key}": rates in basis points (18% is 1800), money in paise.`);
    out[key] = /^-?\d{1,15}$/.test(raw) ? Number(raw) : raw;
  }
  if (!Object.keys(out).length) throw new Error('Give at least one value.');
  return out;
}

function trView() {
  const title = 'Tax rules';
  const sub = 'Dated rules used for tax. A new rule starts on its date; older entries keep the rule that applied then.';
  const rules = gkGet('tr:rules', () => api('/api/tax-rules'));
  let list = gkWait(rules);
  const mayChange = ['admin', 'accounts'].includes(state.user?.role);
  if (Array.isArray(rules)) {
    list = gkTable(['Kind', 'Rule', 'Applies to', 'Value', 'From', ''], rules.map(r => [esc(trKindName(r.kind)), esc(r.key), esc(r.scope || 'Everyone'),
      esc(trValueText(r.value)), esc(r.effective_from), mayChange ? gkButton('retire', 'Retire', `data-id="${Number(r.id)}"`) : '']), 'No tax rule has been recorded yet.');
  }
  const found = state.gk.ui.trFound;
  const answer = found === undefined ? '' : found === null ? '<p class="muted">No rule applies for that name and date.</p>'
    : `<p>Applies: <strong>${esc(trValueText(found.value))}</strong> from ${esc(found.effective_from)}${found.scope ? ' for ' + esc(found.scope) : ''}.</p>`;
  const ask = gkForm('resolve', gkSelect('Kind', 'kind', TR_KINDS, 'rate') + gkInput('Rule name', 'key', 'required maxlength="60"') +
    gkInput('Date', 'on_date', 'required', 'date') + gkInput('For (optional, like vendor:12)', 'scope', 'maxlength="60"'), 'Show what applies') + answer;
  const add = mayChange ? gkPanel('Add a rule', 'Ask the accountant before adding. Rates are in basis points (18% is 1800), money in paise.',
    gkForm('add', gkSelect('Kind', 'kind', TR_KINDS, 'rate') + gkInput('Rule name (lower case)', 'key', 'required pattern="[a-z][a-z0-9_]{1,59}"') +
      gkInput('For (empty = everyone, or like vendor:12)', 'scope', 'maxlength="60"') +
      '<label class="g-field"><span>Value, one "name = value" per line</span><textarea class="form-input" name="value" required rows="3"></textarea></label>' +
      gkInput('Applies from', 'effective_from', 'required', 'date'), 'Draft new rule')) : '';
  return head(title, sub) + gkPanel('Current rules', '', list) + gkPanel('What applies on a date', 'Check before entering a bill or invoice.', ask) + add;
}

const trPropose = (kind, data) => gkDraft('/api/tax-rules/propose', {kind, data});

gkScreen('taxrules', {
  title: 'Tax rules', roles: ['admin', 'accounts', 'manager'], view: trView,
  click: {retire: async el => { if (await askConfirm('Draft retiring this tax rule? It stays in force until approved.', 'Draft retirement')) await trPropose('tax_rule_retire', {rule_id: Number(el.dataset.id)}); }},
  submit: {
    resolve: async form => {
      const v = gkValues(form);
      const qs = new URLSearchParams({kind: v.kind, key: v.key, on_date: v.on_date, scope: v.scope || ''});
      state.gk.ui.trFound = (await api(`/api/tax-rules/resolve?${qs}`)).rule;
    },
    add: async form => {
      const v = gkValues(form);
      await trPropose('tax_rule_add', {kind: v.kind, key: v.key, scope: v.scope || '', value: trParseValue(v.value), effective_from: v.effective_from});
      gkForget('tr:');
    },
  },
});
