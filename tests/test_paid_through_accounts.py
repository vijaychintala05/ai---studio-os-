"""Fictional company cash and petty cash approval and access tests."""
from sqlalchemy import create_engine, inspect

from studioos.migrations import apply_migrations
from .test_money_document_dates import draft
from .test_v018_time_app import staff
from .test_v098_universal_accounting import finance_setup, project, propose, save
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


def test_staff_can_request_only_their_own_petty_cash_topup(admin):
    company = finance_setup(admin)
    staff_client, staff_id = staff(admin, 'fictional-top-up-custodian', 'site_engineer')
    other, _ = staff(admin, 'fictional-top-up-outsider', 'site_engineer')
    assigned = save(admin, draft(admin, 'finance_open_petty_cash', {'entity_id': company, 'user_id': staff_id}).json())
    data = {'account_id': assigned['id'], 'amount_paise': 16_500, 'request_key': 'fictional-petty-topup-001'}
    mine = '/api/petty-cash/mine'
    action = '/api/petty-cash/proposals'
    assert other.get(mine).json() == {'accounts': []}
    assert write(other, 'post', action, data).status_code == 422
    proposed = write(staff_client, 'post', action, data)
    assert proposed.status_code == 200, proposed.text
    ticket = proposed.json()
    assert write(staff_client, 'post', action, data).json()['ticket_id'] == ticket['ticket_id']
    assert write(staff_client, 'post', action, {**data, 'amount_paise': 11_100}).status_code == 409
    assert staff_client.get(mine).json()['accounts'][0]['balance_paise'] == 0
    assert write(staff_client, 'post', f'/api/tickets/{ticket["ticket_id"]}/approve-and-save', {}).status_code == 403
    saved = save(admin, ticket)
    info = staff_client.get(mine).json()['accounts']
    assert len(info) == 1 and info[0]['balance_paise'] == 16_500
    assert info[0]['missing_receipt_count'] == 0
    assert other.get(mine).json() == {'accounts': []}
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 16_500
    reversal = draft(admin, 'finance_reverse_petty_cash_topup', {
        'journal_id': saved['journal_id'], 'reason': 'Fictional cash returned',
    })
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    assert staff_client.get(mine).json()['accounts'][0]['balance_paise'] == 0
    assert draft(admin, 'finance_reverse_petty_cash_topup', {
        'journal_id': saved['journal_id'], 'reason': 'Fictional second reversal request',
    }).status_code == 422

    pid = project(admin)
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [staff_id]}).status_code == 200
    expense = write(staff_client, 'post', '/api/site-expenses', {
        'project_id': pid, 'amount': '25.50', 'title': 'Fictional transit',
        'no_vendor': True, 'no_vendor_name': 'Fictional bus service', 'request_key': 'fictional-topup-test-expense',
    })
    assert expense.status_code == 200, expense.text
    save(admin, expense.json())
    assert staff_client.get(mine).json()['accounts'][0]['missing_receipt_count'] == 1
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': []}).status_code == 200
    assert staff_client.get(mine).json()['accounts'][0]['missing_receipt_count'] == 0
