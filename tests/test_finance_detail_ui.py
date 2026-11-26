"""Money -> Stock and purchases and Home -> My claims (findetail.js), with fictional bills and orders."""
from tests.gk_harness import STATIC, assert_wired, needs_node, run

SETUP = r"""
replies['/api/books/home'] = {companies: [{entity_id: 2, name: 'Fictional Studio'}]};
replies['/api/finance-ledger/payables/2'] = {bills: [{bill_id: 9, po_id: 4, invoice_number: 'FICT-9', gross_paise: 5000, outstanding_paise: 2000, reversed: false}]};
replies['/api/finance-ledger/bills/9'] = {bill_id: 9, po_id: 4, supplier_id: 6, amount_paise: 5000, outstanding_paise: 2000, posted_journal_id: 31, bill_date: '2026-10-01', due_date: null};
replies['/api/sales/options'] = {vendors: [{id: 6, name: 'Fictional Vendor'}]};
replies['/api/books/parties/6'] = {orders: [{id: 4, po_number: 'FPO-4', amount_paise: 100000}]};
replies['/api/finance-ledger/inventory/po/4'] = {po_id: 4, receipts: [{quantity: 10, value_paise: 5000}], issues: []};
replies['/api/projects'] = [{id: 7, name: 'Fictional Villa'}];
replies['/api/finance-ledger/project-costs/7'] = {posted_material_expense_net_paise: 5000, entries: [{journal_id: 31, account_code: '5000', side: 'debit', amount_paise: 5000}], basis: 'Posted lines only', truncated: false};
replies['/api/finance-ledger/purchase-path/2'] = {path: null, how: 'nothing yet'};
replies['/api/finance-ledger/proposals'] = {ticket_id: 81};
replies['/api/reimbursements/mine'] = {claims: [{id: 1, date: '2026-10-02', amount_paise: 1500, note: 'Fictional tiles taxi'}], owed_paise: 1500};
state.view = 'findetail';
"""


@needs_node
def test_shows_bill_detail_stock_costs_and_path_without_typing_ids():
    got = run(['findetail.js'], SETUP + r"""
(async () => {
  await settle(fdView);
  GK_SCREENS.findetail.click.bill({dataset: {id: '9'}});
  console.log(JSON.stringify(await settle(fdView)));
})();
""")
    for text in ('FICT-9', 'journal 31', 'Not recorded', 'FPO-4', 'Received', 'Fictional Villa', 'Not chosen yet', 'Draft goods receipt', 'turn stock tracking on'):
        assert text in got, text


@needs_node
def test_stock_drafts_use_the_ledger_field_names():
    got = run(['findetail.js'], SETUP + r"""
(async () => {
  await settle(fdView);
  const s = GK_SCREENS.findetail.submit;
  await s.grn({values: {quantity: '5', unit: '350.50', reference: 'DN-1'}});
  await s.invbill({values: {invoice: 'INV-1', amount: '1752.50', bill_date: '', due_date: '', terms: ''}});
  await s.issue({values: {quantity: '2', reference: 'IS-1'}});
  await s.enable({values: {inventory_code: '1400', grni_code: '2200'}});
  let bad = '';
  try { await s.grn({values: {quantity: '1.5', unit: '10', reference: 'x'}}); } catch (e) { bad = e.message; }
  console.log(JSON.stringify({bad, sent: calls.filter(c => c[0] === '/api/finance-ledger/proposals').map(c => c[2])}));
})();
""")
    kinds = [d['kind'] for d in got['sent']]
    assert kinds == ['finance_goods_receipt', 'finance_inventory_bill', 'finance_material_issue', 'finance_enable_inventory']
    grn, bill, issue, enable = (d['data'] for d in got['sent'])
    assert set(grn) == {'po_id', 'quantity', 'unit_cost_paise', 'receipt_reference', 'idempotency_key'} and grn['unit_cost_paise'] == 35050
    assert bill == {'po_id': 4, 'invoice_number': 'INV-1', 'amount_paise': 175250}
    assert set(issue) == {'po_id', 'quantity', 'issue_reference', 'idempotency_key'}
    assert set(enable) == {'entity_id', 'inventory_code', 'grni_code'}
    assert 'whole number' in got['bad']


@needs_node
def test_my_claims():
    got = run(['findetail.js'], SETUP + r"""
state.view = 'myclaims';
(async () => { console.log(JSON.stringify(await settle(claimsView))); })();
""")
    assert 'Rs 15 owed to you' in got and 'Fictional tiles taxi' in got


def test_stock_buttons_no_longer_ask_for_typed_ids():
    js = (STATIC / 'universal.js').read_text(encoding='utf-8')
    for word in ('finance_goods_receipt', 'finance_material_issue', 'finance_inventory_bill', 'finance_enable_inventory'):
        assert word not in js
    assert "switchView('findetail')" in js


def test_wired():
    assert_wired('findetail.js', 'findetail')
    assert_wired('findetail.js', 'myclaims')
