"""M1-1 acceptance tests with fictional bills, payments and periods."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect

from studioos.db import FinanceSupplierBill, FinanceSupplierPayment, SessionLocal
from studioos.migrations import apply_migrations
from .conftest import write
from .test_v018_time_app import staff
from .test_v0910_inventory_reconciliation import policy, receipt
from .test_v0913_finance_assurance import _start
from .test_v098_universal_accounting import save


def draft(client, kind, data):
    return write(client, 'post', '/api/finance-ledger/proposals', {
        'kind': kind, 'data': data, 'evidence': 'Fictional approved-source test',
    })


def bill_data(po, **dates):
    return {'po_id': po, 'invoice_number': 'FICT-DATED-BILL', 'amount_paise': 5_000_000,
            'bill_date': '2026-08-31', 'due_date': '2026-09-30', 'payment_terms_days': 30,
            **dates}


def area_lock(admin, entity, area):
    result = write(admin, 'post', '/api/period/propose', {
        'kind': 'period_area_lock', 'data': {'entity_id': entity, 'year_month': '2026-08',
                                              'area': area, 'reason': 'Fictional month end'},
    })
    assert result.status_code == 200, result.text
    save(admin, result.json())


@pytest.mark.parametrize('kind', ['finance_bill', 'finance_inventory_bill'])
def test_bill_checks_its_document_month_at_draft_and_commit(admin, kind):
    _, _, entity, po, _, _ = _start(admin)
    if kind == 'finance_inventory_bill':
        policy(admin, entity)
        receipt(admin, po, qty=100, rate=50_000)
    data = bill_data(po)
    first = draft(admin, kind, data)
    assert first.status_code == 200, first.text
    area_lock(admin, entity, 'purchases')
    retry = draft(admin, kind, data)
    assert retry.status_code == 422 and '2026-08' in retry.text
    saved = write(admin, 'post', f'/api/tickets/{first.json()["ticket_id"]}/approve-and-save', {})
    assert saved.status_code in (409, 422) and '2026-08' in saved.text
    assert admin.get(f'/api/finance-ledger/payables/{entity}').json()['bills'] == []


def test_dates_survive_approval_and_only_finance_roles_can_read_them(admin):
    pid, supplier, entity, po, bank, _ = _start(admin)
    data = bill_data(po)
    undated = draft(admin, 'finance_bill', {k: v for k, v in data.items() if k != 'bill_date'})
    assert undated.status_code == 422 and 'Bill date' in undated.text
    bad_terms = draft(admin, 'finance_bill', {**data, 'payment_terms_days': 31})
    assert bad_terms.status_code == 422 and 'terms' in bad_terms.text.lower()
    proposed = draft(admin, 'finance_bill', data)
    assert proposed.status_code == 200, proposed.text
    bill = save(admin, proposed.json())
    bill_path = f'/api/finance-ledger/bills/{bill["id"]}'
    for field in ('bill_date', 'due_date', 'payment_terms_days'):
        assert admin.get(bill_path).json()[field] == data[field]

    payment = {'bill_id': bill['id'], 'bank_id': bank, 'amount_paise': 2_000_000,
               'payment_reference': 'FICT-DATED-PAYMENT', 'idempotency_key': 'fictional-dated-payment'}
    rejected = draft(admin, 'finance_payment', payment)
    assert rejected.status_code == 422 and 'Payment date' in rejected.text
    area_lock(admin, entity, 'bank')
    rejected = draft(admin, 'finance_payment', {**payment, 'payment_date': '2026-08-31'})
    assert rejected.status_code == 422 and '2026-08' in rejected.text
    dated = draft(admin, 'finance_payment', {**payment, 'payment_date': '2026-09-01'})
    assert dated.status_code == 200, dated.text
    posted = save(admin, dated.json())
    with SessionLocal() as db:
        assert str(db.get(FinanceSupplierPayment, posted['id']).payment_date) == '2026-09-01'
    party_path = f'/api/books/parties/{supplier}'
    assert admin.get(party_path).json()['payments'][0]['payment_date'] == '2026-09-01'
    balance = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert balance['total_debit_paise'] == balance['total_credit_paise'] == 5_000_000

    outsider, uid = staff(admin, 'fictional.date.outsider', 'architect')
    try:
        assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [uid]}).status_code == 200
        assert outsider.get(bill_path).status_code == 403
        assert 'bills' not in outsider.get(party_path).json()
        assert draft(outsider, 'finance_bill', data).status_code == 403
    finally:
        outsider.close()


@pytest.mark.parametrize('stamp', ['2026-08-31T18:30:00+00:00', '2026-09-01T18:29:00+00:00'])
def test_september_documents_are_valid_at_both_ends_of_the_ist_day(admin, monkeypatch, stamp):
    from studioos import runtime_clock

    _, _, _, po, _, _ = _start(admin)
    monkeypatch.setenv('STUDIOOS_TIMEZONE', 'Asia/Kolkata')
    monkeypatch.setattr(runtime_clock, 'utc_now', lambda: datetime.fromisoformat(stamp))
    from studioos.chart_of_accounts import local_today
    assert str(local_today()) == '2026-09-01'
    result = draft(admin, 'finance_bill', bill_data(po, bill_date='2026-09-01', due_date='2026-10-01'))
    assert result.status_code == 200, result.text


def test_upgraded_and_fresh_columns_match_and_legacy_dates_stay_unknown(monkeypatch):
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    try:
        with old.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE finance_supplier_bills (id INTEGER PRIMARY KEY, po_id INTEGER)')
            conn.exec_driver_sql('CREATE TABLE finance_supplier_payments (id INTEGER PRIMARY KEY, bill_id INTEGER, journal_id INTEGER)')
            conn.exec_driver_sql('INSERT INTO finance_supplier_bills (id) VALUES (7)')
            conn.exec_driver_sql('INSERT INTO finance_supplier_payments (id,bill_id) VALUES (9,7)')
        apply_migrations(old)
        apply_migrations(fresh)
        for model, fields in (
            (FinanceSupplierBill, {'bill_date', 'due_date', 'payment_terms_days'}),
            (FinanceSupplierPayment, {'payment_date'}),
        ):
            shapes = [{c['name']: (str(c['type']), c['nullable']) for c in
                       inspect(engine).get_columns(model.__tablename__) if c['name'] in fields}
                      for engine in (old, fresh)]
            assert shapes[0] == shapes[1] and shapes[0].keys() == fields
        with old.connect() as conn:
            assert conn.exec_driver_sql('SELECT id,bill_date,due_date,payment_terms_days FROM finance_supplier_bills').one() == (7, None, None, None)
            assert conn.exec_driver_sql('SELECT id,bill_id,payment_date FROM finance_supplier_payments').one() == (9, 7, None)
    finally:
        old.dispose()
        fresh.dispose()
