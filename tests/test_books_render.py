"""Run Books' two JavaScript view functions with fictional account data."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


BOOKS_SCRIPT = Path(__file__).resolve().parents[1] / 'studioos' / 'static' / 'books.js'


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_historical_balances_render_on_supplier_page_and_books_home():
    script = """
const state = {user: {role: 'admin'}};
const document = {addEventListener() {}};
let render = () => {};
let homeAtNavigation;
let switchView = view => { if (view === 'books') homeAtNavigation = state.bk.home; };
const esc = value => String(value ?? '');
const head = title => `<h1>${title}</h1>`;
const empty = () => '';
const inr = value => `Rs ${value}`;
""" + BOOKS_SCRIPT.read_text(encoding='utf-8') + """
const ageing = {current: 4127, days_31_60: 0, days_61_90: 0, over_90: 0};
state.bk.home = {companies: [{name: 'Fictional Company', open_bills: 0, open_legacy_payables: 1, posted_expense_paise: 8173,
  payable_paise: 4127, ageing, banks: [], closed_months: [], unmatched_payments: {count: 0, paise: 0},
  owed_by_supplier: [{party_id: 7, name: 'Fictional Supplier', owed_paise: 4127}]}]};
const home = bkHomeView();
state.bk.partyId = 7;
state.bk.party = {party: {id: 7, name: 'Fictional Supplier', kind: 'vendor'}, amounts: true,
  projects: [], bills: [], payments: [], ageing, owed_paise: 4127,
  legacy_payables: [{title: 'Fictional Old Expense', posted_date: '2026-08-31', owed_paise: 4127,
    entity_id: 2, journal_id: 11}]};
const supplier = bkPartyView();
switchView('books');
console.log(JSON.stringify([home, supplier, homeAtNavigation]));
"""
    result = subprocess.run(['node', '-'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    home, supplier, home_at_navigation = json.loads(result.stdout)
    assert '1 historical expense balance' in home and 'Fictional Supplier' in home
    assert 'Posted expenses' in home and 'Rs 81.73' in home
    assert 'Fictional Old Expense' in supplier and 'Rs 41.27' in supplier
    assert home_at_navigation is None


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_books_loads_once_and_ignores_responses_for_a_previous_contact():
    script = """
const assert = require('node:assert/strict');
const state = {user: {role: 'admin'}, view: 'overview'};
const document = {addEventListener() {}, querySelectorAll: () => [], body: {classList: {remove() {}}}};
const requests = [];
const notifications = [];
const api = path => new Promise((resolve, reject) => requests.push({path, resolve, reject}));
const notify = message => notifications.push(message);
const $ = () => ({});
const updateIdentity = () => {};
const esc = value => String(value ?? '');
const head = () => '';
const empty = () => '';
let render = () => {};
let switchView = view => { state.view = view; render(); };
""" + BOOKS_SCRIPT.read_text(encoding='utf-8') + """
const tick = () => new Promise(resolve => setImmediate(resolve));
async function check() {
  switchView('books');
  render();
  assert.equal(requests.filter(request => request.path === '/api/books/home').length, 1);
  const home = requests[0];
  openParty(7);
  render();
  assert.equal(requests.filter(request => request.path.endsWith('/7')).length, 1);
  const older = requests[1];
  openParty(8);
  home.resolve({companies: [], note: ''});
  older.reject(new Error('The old contact could not load.'));
  await tick();
  assert.equal(notifications.length, 0);
  assert.equal(state.bk.home, null);
  assert.equal(state.view, 'party');
  assert.equal(state.bk.partyId, 8);
  requests[2].resolve({party: {id: 8, name: 'Fictional Supplier', kind: 'vendor'}, projects: []});
  await tick();
  assert.equal(state.bk.party.party.id, 8);
  openParty(9);
  const retired = requests[3];
  state.bk = {home: null, party: null, partyId: null};
  state.view = 'overview';
  retired.resolve({party: {id: 9, name: 'Fictional Prior Session Supplier'}, projects: []});
  await tick();
  assert.equal(state.bk.party, null);
}
check().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(['node', '-'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
