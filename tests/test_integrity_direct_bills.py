"""The ledger integrity check must count direct supplier bills and vendor credits when it works out what suppliers are owed.
Before this, an unpaid direct bill made it report AP_CONTROL_MISMATCH even though the books were right, and that false finding
also blocked closing the month. Fictional data only."""
from sqlalchemy import select

from studioos.db import ClosedAccountingPeriod, SessionLocal
from .conftest import write
from .test_v098_universal_accounting import propose, save
from .test_zoho_bookkeeping import _acc_by_code, _approve_ticket, _setup_with_chart


def _bill(admin, entity, vid, pid, cement, number='INT-001', taxable=2_000_000, tds=20_000, date='2026-04-10'):
    gst = taxable * 18 // 100
    r = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vid, 'invoice_number': number, 'bill_date': date, 'due_date': '2026-05-10',
        'payment_terms_days': 30, 'supply_type': 'intra', 'tds_section': '194C', 'tds_paise': tds, 'amount_paise': taxable + gst - tds,
        'lines': [{'account_id': cement.id, 'project_id': pid, 'description': 'Fictional cement', 'amount_paise': taxable, 'tax_rate_bps': 1800}],
    })
    assert r.status_code == 200, r.text
    return _approve_ticket(admin, r.json()['ticket_id'])['committed_records'][0]['id']


def _integrity(admin, entity):
    r = admin.get(f'/api/finance-ledger/integrity/{entity}')
    assert r.status_code == 200, r.text
    return r.json()


def _assert_clean(admin, entity, owed):
    body = _integrity(admin, entity)
    assert body['passed'] is True, body['findings']
    assert body['ap_control_credit_paise'] == owed and body['supplier_outstanding_paise'] == owed


def test_an_unpaid_direct_bill_is_counted_in_what_suppliers_are_owed(admin):
    entity, pid, vid = _setup_with_chart(admin)
    _bill(admin, entity, vid, pid, _acc_by_code(entity, 'CEMENT'))
    _assert_clean(admin, entity, 2_340_000)                      # 20,000 + 18% GST - 200 TDS


def test_a_part_paid_direct_bill_is_counted_at_what_is_still_owed(admin):
    entity, pid, vid = _setup_with_chart(admin)
    bill = _bill(admin, entity, vid, pid, _acc_by_code(entity, 'CEMENT'))
    save(admin, propose(admin, 'finance_direct_bill_payment', {
        'bill_id': bill, 'paid_through_id': _acc_by_code(entity, '1000').id, 'amount_paise': 1_000_000,
        'payment_reference': 'UTR-INT-1', 'payment_date': '2026-04-15', 'idempotency_key': 'int-pay-1'}))
    _assert_clean(admin, entity, 1_340_000)


def test_a_credit_note_on_a_bill_and_a_standalone_vendor_credit_reduce_what_is_owed(admin):
    entity, pid, vid = _setup_with_chart(admin)
    cement, ap = _acc_by_code(entity, 'CEMENT'), _acc_by_code(entity, '2100')
    bill = _bill(admin, entity, vid, pid, cement)
    save(admin, propose(admin, 'finance_vendor_credit', {
        'entity_id': entity, 'supplier_id': vid, 'bill_id': bill, 'project_id': pid, 'note_number': 'DN-INT-1', 'note_date': '2026-04-12',
        'ap_account_id': ap.id, 'expense_account_id': cement.id, 'taxable_paise': 500_000, 'tax_paise': 0, 'reason': 'Fictional return'}))
    _assert_clean(admin, entity, 2_340_000 - 500_000)             # a credit tied to the bill
    save(admin, propose(admin, 'finance_vendor_credit', {
        'entity_id': entity, 'supplier_id': vid, 'project_id': pid, 'note_number': 'DN-INT-2', 'note_date': '2026-04-13',
        'ap_account_id': ap.id, 'expense_account_id': cement.id, 'taxable_paise': 300_000, 'tax_paise': 0, 'reason': 'Fictional unallocated credit'}))
    _assert_clean(admin, entity, 2_340_000 - 500_000 - 300_000)   # a credit not yet used against any bill


def test_a_month_can_be_closed_while_a_direct_bill_is_unpaid(admin):
    entity, pid, vid = _setup_with_chart(admin)
    _bill(admin, entity, vid, pid, _acc_by_code(entity, 'CEMENT'))
    close = propose(admin, 'finance_close_period', {'entity_id': entity, 'year_month': '2026-04', 'reason': 'Fictional month end with an open bill'})
    done = write(admin, 'post', f'/api/tickets/{close["ticket_id"]}/approve-and-save', {})
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        assert db.scalar(select(ClosedAccountingPeriod).where(ClosedAccountingPeriod.entity_id == entity, ClosedAccountingPeriod.year_month == '2026-04'))
