"""Fictional direct expense posting and approval tests."""
from sqlalchemy import create_engine, inspect, select

from studioos.db import FinanceExpense, GLAccount, SessionLocal
from studioos.migrations import apply_migrations
from .conftest import write
from .test_money_document_dates import area_lock, draft
from .test_v018_time_app import staff
from .test_v098_universal_accounting import finance_setup, save, vendor


def expense_data(admin, entity, **changes):
    sources = admin.get(f'/api/finance-ledger/paid-through/{entity}').json()
    # The default expense account is available even before the full chart is installed.
    with SessionLocal() as db:
        expense = db.scalar(select(GLAccount.id).where(GLAccount.entity_id == entity,
                                                       GLAccount.kind == 'expense'))
    return {
        'date': '2026-08-31', 'amount_paise': 1_100_000, 'vendor_id': vendor(admin),
        'expense_account_id': expense, 'paid_through_id': next(s['id'] for s in sources if s['kind'] == 'cash'),
        'request_key': 'fictional-expense-2026-08-31', 'note': 'Fictional site supplies', **changes,
    }


def test_direct_expense_posts_only_after_approval_and_retries_once(admin):
    entity = finance_setup(admin)
    data = expense_data(admin, entity)
    first = draft(admin, 'finance_expense', data)
    assert first.status_code == 200, first.text
    card = admin.get(f'/api/tickets/{first.json()["ticket_id"]}').json()['items'][0]
    assert any('No receipt' in flag for flag in card['flags'])
    assert any('₹10,000' in flag for flag in card['flags'])
    assert any('below zero' in flag for flag in card['flags'])
    assert admin.get(f'/api/finance-ledger/journals/{entity}').json() == []
    assert draft(admin, 'finance_expense', data).json()['ticket_id'] == first.json()['ticket_id']
    assert draft(admin, 'finance_expense', {**data, 'amount_paise': 2}).status_code == 409
    saved = save(admin, first.json())
    assert draft(admin, 'finance_expense', data).json()['ticket_id'] == first.json()['ticket_id']
    journals = admin.get(f'/api/finance-ledger/journals/{entity}').json()
    assert [row['id'] for row in journals] == [saved['journal_id']]
    assert journals[0]['source_event'] == 'DIRECT_EXPENSE_POSTED'
    sources = admin.get(f'/api/finance-ledger/paid-through/{entity}').json()
    assert next(row['balance_paise'] for row in sources if row['kind'] == 'cash') == -1_100_000
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 1_100_000
    reversal = draft(admin, 'finance_reverse_expense', {'expense_id': saved['id'], 'reason': 'Fictional duplicate'})
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 0
    assert len(admin.get(f'/api/finance-ledger/journals/{entity}').json()) == 2


def test_expense_validates_source_vendor_account_and_period_at_approval(admin):
    entity = finance_setup(admin)
    data = expense_data(admin, entity)
    for field in ('vendor_id', 'paid_through_id', 'expense_account_id'):
        result = draft(admin, 'finance_expense', {**data, field: None})
        assert result.status_code == 422, result.text
    first = draft(admin, 'finance_expense', data)
    assert first.status_code == 200, first.text
    area_lock(admin, entity, 'purchases')
    saved = write(admin, 'post', f'/api/tickets/{first.json()["ticket_id"]}/approve-and-save', {})
    assert saved.status_code in (409, 422) and '2026-08' in saved.text
    assert admin.get(f'/api/finance-ledger/journals/{entity}').json() == []


def test_only_assigned_staff_can_use_petty_cash(admin):
    entity = finance_setup(admin)
    manager, manager_id = staff(admin, 'fictional-expense-custodian', 'manager')
    outsider, _ = staff(admin, 'fictional-expense-outsider', 'site_engineer')
    account = save(admin, draft(admin, 'finance_open_petty_cash', {'entity_id': entity, 'user_id': manager_id}).json())
    data = expense_data(admin, entity, paid_through_id=account['id'])
    assert draft(outsider, 'finance_expense', data).status_code == 403
    assert draft(admin, 'finance_expense', data).status_code == 422
    first = draft(manager, 'finance_expense', data)
    assert first.status_code == 200, first.text
    save(admin, first.json())
    sources = manager.get(f'/api/finance-ledger/paid-through/{entity}').json()
    assert next(row['balance_paise'] for row in sources if row['id'] == account['id']) == -1_100_000


def test_manager_approval_limits_include_expenses_and_disallow_own_ticket(admin):
    entity = finance_setup(admin)
    data = expense_data(admin, entity, amount_paise=35_000)
    manager, _ = staff(admin, 'fictional-expense-reviewer', 'manager')
    accounts, _ = staff(admin, 'fictional-expense-accounts', 'accounts')
    assert write(admin, 'put', '/api/approval-limits', {
        'manager_per_transaction_paise': 40_000, 'monthly_per_manager_paise': 50_000,
    }).status_code == 200
    own = draft(manager, 'finance_expense', data).json()
    denied = write(manager, 'post', f'/api/tickets/{own["ticket_id"]}/approve-and-save', {})
    assert denied.status_code == 403, denied.text
    first = draft(accounts, 'finance_expense', data)
    assert first.status_code == 200, first.text
    save(manager, first.json())
    second = draft(accounts, 'finance_expense', {**data, 'request_key': 'second-same-month-expense'})
    assert second.status_code == 200, second.text
    denied = write(manager, 'post', f'/api/tickets/{second.json()["ticket_id"]}/approve-and-save', {})
    assert denied.status_code == 403 and 'monthly' in denied.text


def test_direct_expense_form_and_chat_share_the_ticket_type(admin):
    from .test_v0914_chart_of_accounts import books, chat

    _, entity = books(admin)
    options = admin.get(f'/api/finance-ledger/entry-form/{entity}').json()['recipes']
    expense = next(recipe for recipe in options if recipe['key'] == 'expense')
    assert {row['kind'] for row in expense['paid_through']} == {'cash', 'bank'}
    reply = chat(admin, 'Record expense ₹150 cash for office electricity, no vendor.')
    assert reply.get('preview'), reply
    item = reply['preview']['items'][0]
    assert item['item_type'] == 'finance_expense'
    assert item['after']['amount_paise'] == 15_000
    assert item['display_values']['paid_through_id'] == 'Cash in Hand'


def test_expense_schema_matches_new_and_upgraded_databases(monkeypatch):
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    table = FinanceExpense.__tablename__
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    try:
        apply_migrations(old)
        with old.begin() as conn:
            FinanceExpense.__table__.drop(conn)
            conn.exec_driver_sql('DELETE FROM schema_migrations WHERE version > 42')
        apply_migrations(old)
        apply_migrations(fresh)
        upgraded, created = inspect(old), inspect(fresh)
        for schema_read in ('get_indexes', 'get_unique_constraints', 'get_foreign_keys'):
            assert getattr(upgraded, schema_read)(table) == getattr(created, schema_read)(table)
        columns = [[(c['name'], str(c['type']), c['nullable']) for c in schema.get_columns(table)]
                   for schema in (upgraded, created)]
        assert columns[0] == columns[1] and len(columns[0]) == 13
    finally:
        old.dispose()
        fresh.dispose()
