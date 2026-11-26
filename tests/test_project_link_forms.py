"""Run the project-linked form logic with fictional choices and request payloads."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is not installed')
def test_form_controls_apply_approved_project_links():
    static = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
    program = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2];
const load = name => fs.readFileSync(path.join(root, name), 'utf8');
const esc = text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const ctx = vm.createContext({
  assert, esc, inr: n => 'Rs ' + n, state: {}, render() {}, refresh() {}, switchView() {},
  document: {addEventListener() {}, querySelector() { return null; }},
  FormData: class { constructor(form) { return Object.entries(form.values); } },
  async api(url) { assert.equal(url, '/api/finance-ledger/entry-form/2'); return ctx.otherOptions; }
});
const app = load('app.js');
vm.runInContext(app.slice(app.indexOf('function projectOwnerFields'), app.indexOf('function formMarkup')), ctx);
for (const file of ['books.js', 'sales.js', 'money_form.js']) vm.runInContext(load(file), ctx);
vm.runInContext(String.raw`
const owner = {id: 1, name: 'Fictional First Company', accounts:{}};
const second = {id: 2, name: 'Fictional Second Company'};
const client = {id: 13, name: 'Fictional Client'};
const project = {id: 7, name: 'Fictional Project', company_id: 2, client_id: 13};
assert.match(projectOwnerFields({companies:[owner], clients:[client]}, {}, true), /readonly/);
assert.match(projectOwnerFields({companies:[owner, second], clients:[client]}, project), /option value="2" selected/);
assert.equal(projectLinkValues({company_id:'2', client_id:'new', client:'  Fictional Client '}).client, 'Fictional Client');
assert.equal(projectLinkValues({company_id:'2', client_id:'13'}).client_id, 13);
assert.match(bkCompanyProjects([{...project, budget_paise:0, cost_to_date_paise:0}], 'Projects'), /data-project-open="7"/);

const bank = {id: 51, name: 'Fictional Bank'};
const company = {...second, deposit_accounts:[bank], input_tax_accounts:[], output_tax_accounts:[],
                 income_accounts:[], accounts:{}};
const book = {companyId: 1, form:{type:'quote'}, options:{companies:[owner, company], projects:[project]}};
const clientField = {value:'2', disabled:false, dataset:{}};
const form = {
  dataset:{salesForm:'quote'},
  elements:{project_id:{value:'7'}, client_id:clientField},
  querySelector:() => companyNote,
  closest:() => ({querySelector:() => registerCompany})
};
const companyNote = {}, registerCompany = {};
syncSalesProject(form, book);
assert.equal(salesFormCompany(book, form).id, 2);
assert.equal(clientField.value, '13');
assert.ok(clientField.disabled && registerCompany.disabled);
assert.match(companyNote.textContent, /Fictional Second Company/);
form.elements.project_id.value = '';
syncSalesProject(form, book);
assert.equal(clientField.value, '2');
assert.equal(clientField.disabled, false);

const select = {value:'7'};
const account = {value:'10'};
const billForm = {
  entity_id:{value:'1'},
  querySelectorAll:selector => selector.includes('line_project') ? [select] : [account],
  querySelector:() => ({})
};
bkSyncBillCompany(billForm, {projects:[project], accounts:[{id:20, entity_id:2, code:'5000', name:'Materials'}]});
assert.equal(billForm.entity_id.value, '2');
assert.ok(billForm.entity_id.disabled);
assert.match(account.innerHTML, /option value="20"/);
assert.doesNotMatch(account.innerHTML, /option value="10"/);
select.value = '';
bkSyncBillCompany(billForm, {projects:[project], accounts:[]});
assert.equal(billForm.entity_id.disabled, false);

state.projects = [project];
const money = {originalCompanyId:1, options:{entity_id:1}};
state.moneyEntry = money;
globalThis.otherOptions = {entity_id:2, recipes:[{key:'expense'}]};
globalThis.finished = switchMoneyProject(money, {
  isConnected:true, querySelector:() => ({}),
  values:{project_id:'7', amount:'120', recipe:'expense', expense_account_id:'10'}
}, {project_id:'7'}, '').then(() => {
  assert.equal(money.options.entity_id, 2);
  assert.equal(money.values.amount, '120');
  assert.equal(money.values.expense_account_id, '');
});
`, ctx);
ctx.finished.catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(['node', '-', str(static)], input=program, text=True, encoding='utf-8',
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
