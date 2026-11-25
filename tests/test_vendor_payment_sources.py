"""Fictional vendor payments through the shared paid-through accounts."""
import pytest
from sqlalchemy import create_engine, inspect, text

from studioos.migrations import LATEST_VERSION, apply_migrations
from .test_money_document_dates import area_lock, bill_data, draft
from .test_v018_time_app import staff
from .test_v0913_finance_assurance import _start
from .test_v098_universal_accounting import save


@pytest.mark.parametrize('kind', ['cash', 'bank'])
def test_paid_through_vendor_payment_keeps_books_and_payables_aligned(admin, kind):
    _, supplier, entity, po, _, _ = _start(admin)
    bill = save(admin, draft(admin, 'finance_bill', bill_data(po)).json())
    options = admin.get(f'/api/finance-ledger/paid-through/{entity}').json()
    source = next(row for row in options if row['kind'] == kind)
    data = {'bill_id': bill['id'], 'paid_through_id': source['id'], 'amount_paise': 100_000,
            'payment_date': '2026-08-31', 'idempotency_key': f'fictional-vendor-{kind}-01',
            'payment_reference': f'FICT-VENDOR-{kind}-01'}
    if kind == 'cash':
        area_lock(admin, entity, 'bank')
    proposal = draft(admin, 'finance_payment', data)
    assert proposal.status_code == 200, proposal.text
    if kind == 'cash':
        assert any('below zero' in warning for warning in proposal.json()['accounting_preview']['warnings'])
    posted = save(admin, proposal.json())
    party = admin.get(f'/api/books/parties/{supplier}').json()
    assert party['owed_paise'] == 4_900_000
    assert party['payments'][0]['amount_paise'] == 100_000
    home = admin.get('/api/books/home').json()['companies'][0]
    assert home['payable_paise'] == party['owed_paise']
    assert home['unmatched_payments']['count'] == (1 if kind == 'bank' else 0)
    remaining = admin.get(f'/api/finance-ledger/paid-through/{entity}').json()
    assert next(row['balance_paise'] for row in remaining if row['id'] == source['id']) == -100_000
    field = 'payment_id' if kind == 'bank' else 'cash_payment_id'
    reversal = draft(admin, 'finance_reverse_payment', {field: posted['id'], 'reason': 'Fictional correction'})
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    assert admin.get(f'/api/books/parties/{supplier}').json()['owed_paise'] == 5_000_000


def test_cash_payment_uses_only_the_submitters_petty_cash(admin):
    _, _, entity, po, _, _ = _start(admin)
    bill = save(admin, draft(admin, 'finance_bill', bill_data(po)).json())
    accounts, accounts_id = staff(admin, 'fictional-supplier-cash-custodian', 'accounts')
    _, other_id = staff(admin, 'fictional-supplier-cash-other', 'accounts')
    accounts_by_owner = {}
    for uid in (accounts_id, other_id):
        accounts_by_owner[uid] = save(admin, draft(
            admin, 'finance_open_petty_cash', {'entity_id': entity, 'user_id': uid},
        ).json())['id']
    data = {'bill_id': bill['id'], 'amount_paise': 1_000_100, 'payment_date': '2026-08-31',
            'idempotency_key': 'fictional-petty-payment', 'payment_reference': 'FICT-PETTY-PAY'}
    assert draft(accounts, 'finance_payment', {**data, 'paid_through_id': accounts_by_owner[other_id]}).status_code == 422
    proposal = draft(accounts, 'finance_payment', {**data, 'paid_through_id': accounts_by_owner[accounts_id]})
    assert proposal.status_code == 200, proposal.text
    assert any('10,000' in warning for warning in proposal.json()['accounting_preview']['warnings'])
    save(admin, proposal.json())
    balance = accounts.get(f'/api/finance-ledger/paid-through/{entity}').json()
    assert next(row['balance_paise'] for row in balance if row['id'] == accounts_by_owner[accounts_id]) == -1_000_100


def test_cash_payment_schema_matches_v44_upgrade(monkeypatch):
    table = 'finance_supplier_cash_payments'
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = [create_engine('sqlite://') for _ in range(2)]
    try:
        apply_migrations(old)
        with old.begin() as conn:
            conn.execute(text(f'DROP TABLE {table}'))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 44'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
            assert conn.scalar(text('SELECT version FROM schema_migrations WHERE version = 45')) == 45
        upgraded, current = [inspect(engine) for engine in (old, fresh)]
        for shape in ('get_foreign_keys', 'get_unique_constraints', 'get_indexes', 'get_check_constraints'):
            assert getattr(upgraded, shape)(table) == getattr(current, shape)(table)
        columns = [[(c['name'], str(c['type']), c['nullable']) for c in schema.get_columns(table)]
                   for schema in (upgraded, current)]
        assert columns[0] == columns[1]
    finally:
        old.dispose()
        fresh.dispose()
