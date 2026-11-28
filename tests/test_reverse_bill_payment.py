"""N10 from the blind audit (MNY-05): a posted supplier bill payment can be reversed from the vendor page.

The server already accepted `finance_reverse_direct_bill_payment`, but no screen offered it. The vendor page now
marks direct bill payments and shows "Reverse payment" to roles that may write to the books. The reversal is drafted
for approval like every other money change. Fictional data only.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from studioos.accounting_kernel import trial_balance
from studioos.books_routes import _today
from studioos.db import SessionLocal
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m2_pay_bills import _create_approved_bill


def test_vendor_page_marks_direct_payments_and_reversal_restores_the_bill(admin):
    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)
    today = _today().isoformat()
    _create_approved_bill(admin, entity_id, vendor_id, acc1, proj_id, 'FICT-REV-1', today, today, 0, 100_000)
    due = admin.get('/api/books/bills-due').json()
    bill = (due['overdue'] + due['due_this_week'] + due['due_later'])[0]
    paying_id = due['paying_accounts'][str(entity_id)][0]['id']

    paid = write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': paying_id, 'payment_date': today,
        'payment_reference': 'FICT-UTR-REV-1',
        'items': [{'kind': 'direct_bill', 'bill_id': bill['bill_id'], 'amount_paise': 40_000}],
    })
    assert paid.status_code == 200, paid.text
    assert write(admin, 'post', f"/api/tickets/{paid.json()['ticket_id']}/approve-and-save",
                 {'confirmed': [], 'note': 'paid'}).status_code == 200

    payments = admin.get(f'/api/books/parties/{vendor_id}').json()['payments']
    row = next(p for p in payments if p['reference'] == 'FICT-UTR-REV-1')
    assert row['direct'] is True
    assert row['amount_paise'] == 40_000

    draft = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'finance_reverse_direct_bill_payment', 'evidence': 'Fictional payment posted by mistake',
        'data': {'payment_id': row['id'], 'reason': 'Posted by mistake (fictional)'},
    })
    assert draft.status_code == 200, draft.text
    assert write(admin, 'post', f"/api/tickets/{draft.json()['ticket_id']}/approve-and-save",
                 {'confirmed': [], 'note': 'reverse'}).status_code == 200

    after = admin.get(f'/api/books/parties/{vendor_id}').json()
    assert all(p['reference'] != 'FICT-UTR-REV-1' for p in after['payments'])
    owed = admin.get('/api/books/bills-due').json()
    still = next(b for b in owed['overdue'] + owed['due_this_week'] + owed['due_later'] if b['bill_id'] == bill['bill_id'])
    assert still['owed_paise'] == 100_000
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['total_debit_paise'] == tb['total_credit_paise']


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is not installed')
def test_reverse_button_shows_only_on_direct_payments_for_writers_and_drafts_a_reversal():
    static = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
    program = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2];
const esc = text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const sent = [];
const ctx = vm.createContext({
  assert, esc, state: {}, render() {}, refresh() {}, switchView() {}, notify() {},
  document: {addEventListener() {}, querySelector() { return null; }},
  async api(url, options) { sent.push([url, JSON.parse(options.body)]); return {ticket_id: 9}; },
});
vm.runInContext(fs.readFileSync(path.join(root, 'books.js'), 'utf8'), ctx);
vm.runInContext(String.raw`
const direct = {id: 5, direct: true, reference: 'FICT-UTR-1'};
assert.match(bkPaymentActions(direct, 'accounts'), /data-bk="reverse-payment" data-id="5"/);
assert.match(bkPaymentActions(direct, 'admin'), /Reverse payment/);
assert.match(bkPaymentActions(direct, 'accounts'), /Voucher PDF/);
assert.doesNotMatch(bkPaymentActions({...direct, direct: false}, 'accounts'), /reverse-payment/);
assert.doesNotMatch(bkPaymentActions(direct, 'site_engineer'), /reverse-payment/);
assert.doesNotMatch(bkPaymentActions(direct, 'architect'), /reverse-payment/);
globalThis.done = bkProposePaymentReversal('5', 'Posted by mistake').then(res => {
  assert.equal(res.ticket_id, 9);
});
`, ctx);
ctx.done.then(() => {
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], '/api/universal/proposals');
  assert.equal(sent[0][1].kind, 'finance_reverse_direct_bill_payment');
  assert.deepEqual(sent[0][1].data, {payment_id: 5, reason: 'Posted by mistake'});
});
"""
    result = subprocess.run(['node', '-', str(static)], input=program, text=True, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
