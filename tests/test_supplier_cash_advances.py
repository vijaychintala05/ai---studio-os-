"""Fictional supplier advances paid from approved cash accounts."""
from sqlalchemy import create_engine, inspect, text

from studioos.migrations import LATEST_VERSION, apply_migrations
from .test_money_document_dates import area_lock, bill_data, draft
from .test_v018_time_app import staff
from .test_v0913_finance_assurance import _start
from .test_v098_universal_accounting import save


def test_cash_advance_posts_and_allocates_without_bank_matching(admin):
    project, vendor, entity, po, _, _ = _start(admin)
    assert save(admin, draft(admin, 'finance_enable_advances', {
        'entity_id': entity, 'advance_code': 'FICT-ADVANCE',
    }).json())['type'] == 'supplier_advance_policy'
    bill = save(admin, draft(admin, 'finance_bill', bill_data(po)).json())
    sources = admin.get(f'/api/finance-ledger/paid-through/{entity}').json()
    cash = next(row for row in sources if row['kind'] == 'cash')
    area_lock(admin, entity, 'bank')
    data = {'entity_id': entity, 'supplier_id': vendor, 'project_id': project, 'paid_through_id': cash['id'],
            'payment_date': '2026-08-31', 'amount_paise': 200_000, 'payment_reference': 'FICT-CASH-ADV',
            'idempotency_key': 'fictional-cash-advance-01'}
    proposal = draft(admin, 'finance_advance', data)
    assert proposal.status_code == 200, proposal.text
    assert any('below zero' in line for line in proposal.json()['accounting_preview']['warnings'])
    advance = save(admin, proposal.json())
    assert advance['type'] == 'supplier_cash_advance'
    register = admin.get(f'/api/finance-ledger/advances/{entity}').json()['advances']
    assert register[0]['bank_id'] is None and register[0]['unallocated_paise'] == 200_000
    allocation = {'cash_advance_id': advance['id'], 'bill_id': bill['id'], 'amount_paise': 125_000,
                  'idempotency_key': 'fictional-cash-advance-allocation'}
    applied = draft(admin, 'finance_allocate_advance', allocation)
    assert applied.status_code == 200, applied.text
    save(admin, applied.json())
    assert draft(admin, 'finance_allocate_advance', {
        **allocation, 'amount_paise': 80_000, 'idempotency_key': 'fictional-unavailable-cash-advance',
    }).status_code == 422
    register = admin.get(f'/api/finance-ledger/advances/{entity}').json()['advances']
    assert register[0]['unallocated_paise'] == 75_000
    payables = admin.get(f'/api/finance-ledger/payables/{entity}').json()
    assert payables['outstanding_total_paise'] == 4_875_000
    home = admin.get('/api/books/home').json()['companies'][0]
    assert home['payable_paise'] == 4_875_000 and home['unmatched_payments']['count'] == 0
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 5_075_000
    later_payment = draft(admin, 'finance_payment', {
        'bill_id': bill['id'], 'paid_through_id': cash['id'], 'payment_date': data['payment_date'],
        'amount_paise': 810_000, 'payment_reference': 'FICT-LATER-CASH',
        'idempotency_key': 'fictional-later-cash-payment',
    })
    assert later_payment.status_code == 200, later_payment.text
    assert any('10,000' in line for line in later_payment.json()['accounting_preview']['warnings'])
    outsider, _ = staff(admin, 'fictional-cash-advance-outsider', 'site_engineer')
    assert draft(outsider, 'finance_advance', data).status_code == 403
    assert outsider.get(f'/api/finance-ledger/advances/{entity}').status_code == 403


def test_cash_advance_schema_matches_v46_upgrade(monkeypatch):
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    tables = ('finance_cash_advance_allocations', 'finance_supplier_cash_advances')
    try:
        apply_migrations(old)
        with old.begin() as conn:
            for table in tables:
                conn.execute(text(f'DROP TABLE {table}'))
            conn.execute(text('ALTER TABLE finance_supplier_advances DROP COLUMN payment_date'))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 46'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
            assert conn.scalar(text('SELECT version FROM schema_migrations WHERE version = 47')) == 47
        upgraded, current = inspect(old), inspect(fresh)
        for table in (*tables, 'finance_supplier_advances'):
            for shape in ('get_foreign_keys', 'get_unique_constraints', 'get_indexes', 'get_check_constraints'):
                assert getattr(upgraded, shape)(table) == getattr(current, shape)(table)
            columns = [{(c['name'], str(c['type']), c['nullable']) for c in schema.get_columns(table)}
                       for schema in (upgraded, current)]
            assert columns[0] == columns[1]
    finally:
        old.dispose()
        fresh.dispose()
