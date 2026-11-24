"""Fictional company cash and petty cash approval and access tests."""
from sqlalchemy import create_engine, inspect

from studioos.migrations import apply_migrations
from .test_money_document_dates import draft
from .test_v018_time_app import staff
from .test_v098_universal_accounting import finance_setup, propose, save
from .conftest import write


def test_existing_company_cash_requires_approval_and_is_not_duplicated(admin, monkeypatch):
    # Model an earlier company whose chart did not reserve the current cash code.
    with monkeypatch.context() as old_setup:
        old_setup.setattr('studioos.accounting_kernel.CASH_CODE', 'OLD_CASH')
        company = finance_setup(admin)
    url = f'/api/finance-ledger/paid-through/{company}'
    assert not any(row['kind'] == 'cash' for row in admin.get(url).json())
    outsider, _ = staff(admin, 'fictional-cash-setup-outsider', 'site_engineer')
    data = {'entity_id': company}
    assert draft(outsider, 'finance_enable_cash', data).status_code == 403
    first = draft(admin, 'finance_enable_cash', data)
    second = draft(admin, 'finance_enable_cash', data)
    assert first.status_code == second.status_code == 200, first.text
    assert not any(row['kind'] == 'cash' for row in admin.get(url).json())
    save(admin, first.json())
    assert write(admin, 'post', f'/api/tickets/{second.json()["ticket_id"]}/approve-and-save', {}).status_code in (409, 422)
    cash = [row for row in admin.get(url).json() if row['kind'] == 'cash']
    assert len(cash) == 1 and cash[0]['balance_paise'] == 0
    assert draft(admin, 'finance_enable_cash', data).status_code == 422
    save(admin, propose(admin, 'finance_install_chart', {'entity_id': company, 'standard': 'india_interiors'}))
    assert [row for row in admin.get(url).json() if row['kind'] == 'cash'] == cash
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 0


def test_cash_sources_and_petty_cash_are_scoped(admin):
    company = finance_setup(admin)
    url = f'/api/finance-ledger/paid-through/{company}'
    initial = admin.get(url)
    assert initial.status_code == 200
    assert {row['kind'] for row in initial.json()} == {'bank', 'cash'}
    cash = next(row for row in initial.json() if row['kind'] == 'cash')
    save(admin, propose(admin, 'finance_install_chart', {
        'entity_id': company, 'standard': 'india_interiors',
    }))
    assert [row for row in admin.get(url).json() if row['kind'] == 'cash'] == [cash]

    engineer, engineer_id = staff(admin, 'fictional-cash-custodian', 'site_engineer')
    outsider, _ = staff(admin, 'fictional-cash-outsider', 'site_engineer')
    data = {'entity_id': company, 'user_id': engineer_id}
    result = draft(admin, 'finance_open_petty_cash', data)
    assert result.status_code == 200, result.text
    assert engineer.get(url).json() == []
    assert draft(outsider, 'finance_open_petty_cash', data).status_code == 403
    save(admin, result.json())
    assert draft(admin, 'finance_open_petty_cash', data).status_code == 422
    accounts = engineer.get(url).json()
    assert len(accounts) == 1 and accounts[0]['kind'] == 'petty_cash'
    assert accounts[0]['balance_paise'] == 0
    assert outsider.get(url).json() == []
    assert {row['kind'] for row in admin.get(url).json()} == {'bank', 'cash', 'petty_cash'}
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 0
    chart = {row['code']: row for row in admin.get(f'/api/finance-ledger/chart/{company}').json()['accounts']}
    opening = draft(admin, 'finance_opening_balances', {
        'entity_id': company, 'as_of': '2026-01-01',
        'balances': [
            {'account_id': accounts[0]['id'], 'signed_paise': 25_000},
            {'account_id': cash['id'], 'signed_paise': 75_000},
            {'account_id': chart['OWNER_CAPITAL']['id'], 'signed_paise': -100_000},
        ],
    })
    assert opening.status_code == 200, opening.text
    assert engineer.get(url).json()[0]['balance_paise'] == 0
    save(admin, opening.json())
    assert engineer.get(url).json()[0]['balance_paise'] == 25_000
    assert outsider.get(url).json() == []
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 100_000


def test_petty_cash_schema_matches_fresh_and_upgraded(monkeypatch):
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    table = 'finance_petty_cash_accounts'
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    try:
        apply_migrations(old)
        with old.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS {table}')
            conn.exec_driver_sql('DELETE FROM schema_migrations WHERE version > 41')
        apply_migrations(old)
        apply_migrations(fresh)
        schemas = [inspect(engine) for engine in (old, fresh)]
        columns = [[{**column, 'type': str(column['type'])} for column in schema.get_columns(table)]
                   for schema in schemas]
        assert columns[0] == columns[1]
        for shape in ('get_foreign_keys', 'get_unique_constraints'):
            actual, expected = [getattr(schema, shape)(table) for schema in schemas]
            assert actual == expected and actual
    finally:
        old.dispose()
        fresh.dispose()
