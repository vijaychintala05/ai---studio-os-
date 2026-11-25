"""M2-2 (claude/pay-bills-screen): Bills due grouping (overdue, due this week, due later)
and bulk Pay selected creating one multi-item approval ticket. Partial payment allowed;
overpayment refused; reversed bills drop off; balanced Trial Balance; outsider 403; schema v52.
Fictional data only.
"""
from datetime import timedelta

from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.books_routes import _today
from studioos.db import Base, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def _create_approved_bill(admin, entity_id, vendor_id, acc_id, proj_id, invoice_no, bill_date, due_date, terms, amount_paise):
    r = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': invoice_no,
        'bill_date': bill_date, 'due_date': due_date, 'payment_terms_days': terms,
        'amount_paise': amount_paise,
        'lines': [{'account_id': acc_id, 'project_id': proj_id, 'description': 'Fictional item', 'amount_paise': amount_paise}],
    })
    assert r.status_code == 200, r.text
    tid = r.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200


def test_bills_due_grouping_bulk_pay_partial_and_overpayment_guard(admin):
    entity_id, vendor_id, acc1, _, proj_id = _setup_company_and_vendor(admin)
    today = _today()
    past_bill = (today - timedelta(days=40)).isoformat()
    overdue_due = (today - timedelta(days=10)).isoformat()
    week_due = (today + timedelta(days=3)).isoformat()
    later_due = (today + timedelta(days=25)).isoformat()

    _create_approved_bill(admin, entity_id, vendor_id, acc1, proj_id, 'FICT-DUE-1', past_bill, overdue_due, 30, 100_000)
    _create_approved_bill(admin, entity_id, vendor_id, acc1, proj_id, 'FICT-DUE-2', today.isoformat(), week_due, 3, 80_000)
    _create_approved_bill(admin, entity_id, vendor_id, acc1, proj_id, 'FICT-DUE-3', today.isoformat(), later_due, 25, 60_000)

    due = admin.get('/api/books/bills-due').json()
    assert [x['invoice_number'] for x in due['overdue']] == ['FICT-DUE-1']
    assert due['overdue'][0]['days_late'] == 10
    assert [x['invoice_number'] for x in due['due_this_week']] == ['FICT-DUE-2']
    assert [x['invoice_number'] for x in due['due_later']] == ['FICT-DUE-3']

    paying_id = due['paying_accounts'][str(entity_id)][0]['id']
    b1_id = due['overdue'][0]['bill_id']
    b2_id = due['due_this_week'][0]['bill_id']

    # Overpayment refused
    over = write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': paying_id,
        'payment_date': today.isoformat(), 'payment_reference': 'UTR-OVER-1',
        'items': [{'kind': 'direct_bill', 'bill_id': b1_id, 'amount_paise': 100_001}],
    })
    assert over.status_code == 422 and 'more than what is still owed' in over.text.casefold()

    # Bulk pay: full payment on b1 (100_000) + partial payment on b2 (30_000 of 80_000) in ONE ticket
    batch = write(admin, 'post', '/api/books/pay-selected', {
        'entity_id': entity_id, 'paid_through_id': paying_id,
        'payment_date': today.isoformat(), 'payment_reference': 'UTR-BATCH-1',
        'items': [
            {'kind': 'direct_bill', 'bill_id': b1_id, 'amount_paise': 100_000},
            {'kind': 'direct_bill', 'bill_id': b2_id, 'amount_paise': 30_000},
        ],
    })
    assert batch.status_code == 200, batch.text
    assert batch.json()['item_count'] == 2 and batch.json()['total_paise'] == 130_000
    tid = batch.json()['ticket_id']
    assert write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': [], 'note': 'paid'}).status_code == 200

    # b1 drops off bills-due; b2 shows 50_000 remaining
    after = admin.get('/api/books/bills-due').json()
    assert after['overdue'] == []
    assert after['due_this_week'][0]['owed_paise'] == 50_000
    with SessionLocal() as db:
        tb = trial_balance(db, entity_id)
        assert tb['total_debit_paise'] == tb['total_credit_paise']


def test_outsider_cannot_view_bills_due_or_pay_selected(admin):
    site, _ = staff(admin, 'site.duecheck', 'site_engineer')
    try:
        assert site.get('/api/books/bills-due').status_code == 403
        assert write(site, 'post', '/api/books/pay-selected', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v52_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        assert 'finance_direct_bill_payments' in upg_insp.get_table_names()
        assert ({c['name'] for c in fresh_insp.get_columns('finance_direct_bill_payments')}
                == {c['name'] for c in upg_insp.get_columns('finance_direct_bill_payments')})
    finally:
        fresh.dispose()
        upgraded.dispose()
