"""The Record expense form reads back fictional rupee amounts before submission."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_money_form_shows_the_amount_and_registers_for_live_updates():
    static = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
    app = (static / 'app.js').read_text(encoding='utf-8')
    formatter = [line for line in app.splitlines() if line.startswith(('function inr(', 'function amountEcho('))]
    listener = next(line for line in app.splitlines() if line.startswith("document.addEventListener('input',e=>{const el=e.target;"))
    field = app[app.index('function moneyAmountField('):app.index('function rupeesToPaise(')]
    script = """
const assert = require('node:assert/strict');
const state = {projects: []};
const listeners = [];
const document = {addEventListener(type, handler) { if (type === 'input') listeners.push(handler); }};
const esc = value => String(value ?? '');
const head = () => '';
let render = () => {};
""" + '\n'.join(formatter) + '\n' + field + listener + '\n' + (static / 'money_form.js').read_text(encoding='utf-8') + r"""
state.moneyEntry = {
  options: {recipes: [{key: 'expense', title: 'Expense', items: [], parties: [], paid_through: [], receipts: []}]},
  values: {recipe: 'expense', amount: '1,25,000.50'},
};
const html = moneyEntryView();
assert.match(html, /aria-describedby="money-entry-amount-echo"/);
assert.match(html, /data-amount-for="amount"[^>]*>₹1,25,000\.5 \(1\.25 lakh\)/);
const output = {textContent: ''};
const input = {tagName: 'INPUT', name: 'amount', value: '1,250.51', getAttribute: () => 'decimal',
  form: {querySelector(selector) { assert.equal(selector, '[data-amount-for="amount"]'); return output; }}};
listeners[0]({target: input});
assert.equal(output.textContent, '₹1,250.51');
input.value = '1,2,500';
listeners[0]({target: input});
assert.match(output.textContent, /^Check the commas/);
"""
    result = subprocess.run(['node', '-'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
