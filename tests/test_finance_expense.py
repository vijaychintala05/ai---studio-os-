"""Fictional direct expense posting and approval tests."""
import pytest
from sqlalchemy import create_engine, inspect, select, text

from studioos.db import FinanceExpense, GLAccount, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from .conftest import approved_form, write
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


def test_unregistered_payee_name_is_verified_and_retained(admin):
    entity = finance_setup(admin)
    data = expense_data(admin, entity, vendor_id=None, no_vendor=True, amount_paise=25_050)
    missing = draft(admin, 'finance_expense', data)
    assert missing.status_code == 422 and 'who was paid' in missing.text.lower()
    data['no_vendor_name'] = '  Fictional   tea stall  '
    proposal = draft(admin, 'finance_expense', data)
    assert proposal.status_code == 200, proposal.text
    ticket = proposal.json()
    card = admin.get(f'/api/tickets/{ticket["ticket_id"]}').json()['items'][0]
    assert card['display_values']['vendor_id'] == 'No vendor: Fictional tea stall'
    changed = draft(admin, 'finance_expense', {**data, 'no_vendor_name': 'Fictional different stall'})
    assert changed.status_code == 409
    entry = save(admin, ticket)
    with SessionLocal() as db:
        posted = db.get(FinanceExpense, entry['id'])
        assert posted.no_vendor_name == 'Fictional tea stall' and posted.vendor_id is None
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 25_050


def test_chat_records_named_unregistered_payee(admin):
    from .test_v0914_chart_of_accounts import books, chat

    books(admin)
    refused = chat(admin, 'Record expense Rs 120 for transport by cash, no vendor.')
    assert not refused.get('ticket_id') and 'who was paid' in refused['reply'].lower()
    reply = chat(admin, 'Record expense Rs 120 for transport by cash; No vendor: Fictional street taxi')
    assert reply.get('ticket_id'), reply
    item = admin.get(f'/api/tickets/{reply["ticket_id"]}').json()['items'][0]
    assert item['item_type'] == 'finance_expense'
    assert item['after']['no_vendor_name'] == 'Fictional street taxi'
    saved = save(admin, reply)
    with SessionLocal() as db:
        assert db.get(FinanceExpense, saved['id']).no_vendor_name == 'Fictional street taxi'


def test_unregistered_payee_column_matches_v48_upgrade(monkeypatch):
    table = 'finance_expenses'
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    try:
        apply_migrations(old)
        with old.begin() as conn:
            conn.execute(text(f'ALTER TABLE {table} DROP COLUMN no_vendor_name'))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 48'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        for schema in (inspect(old), inspect(fresh)):
            column = next(c for c in schema.get_columns(table) if c['name'] == 'no_vendor_name')
            assert column['nullable'] and str(column['type']) == 'VARCHAR(120)'
    finally:
        old.dispose()
        fresh.dispose()


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


@pytest.mark.parametrize('direct', [False, True], ids=['purchase-order-bill', 'direct-bill'])
def test_direct_expense_warning_includes_same_day_cash_bill_payment(admin, direct):
    from .test_money_document_dates import bill_data
    from .test_v0913_finance_assurance import _start

    project, supplier, entity, po, _, _ = _start(admin)
    expense = expense_data(admin, entity, vendor_id=supplier, project_id=project, amount_paise=450_000)
    details = bill_data(po)
    if direct:
        details.pop('po_id')
        details.update(entity_id=entity, supplier_id=supplier, lines=[{
            'project_id': project, 'account_id': expense['expense_account_id'], 'amount_paise': details['amount_paise'],
        }])
    bill_kind = 'finance_direct_bill' if direct else 'finance_bill'
    pay_kind = 'finance_direct_bill_payment' if direct else 'finance_payment'
    bill = save(admin, draft(admin, bill_kind, details).json())
    payment = save(admin, draft(admin, pay_kind, {
        'bill_id': bill['id'], 'paid_through_id': expense['paid_through_id'], 'amount_paise': 600_000,
        'payment_date': expense['date'], 'payment_reference': 'FICTIONAL-CASH-LIMIT-BILL',
        'idempotency_key': 'fictional-cash-limit-bill',
    }).json())
    proposal = draft(admin, 'finance_expense', expense)
    assert proposal.status_code == 200, proposal.text
    ticket = f'/api/tickets/{proposal.json()["ticket_id"]}'
    assert any('₹10,000' in flag for flag in admin.get(ticket).json()['items'][0]['flags'])
    other_project = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Separate Cash Site', 'budget': '10000',
    }).json()['id']
    from studioos.expense_entry import warnings

    with SessionLocal() as db:
        assert any('₹10,000' in flag for flag in warnings(db, {**expense, 'site_expense': True}))
        assert not any('₹10,000' in flag for flag in warnings(db, {
            **expense, 'site_expense': True, 'project_id': other_project,
        }))
    other_day = draft(admin, 'finance_expense', {
        **expense, 'date': '2026-08-30', 'request_key': 'fictional-cash-limit-other-day',
    })
    assert other_day.status_code == 200, other_day.text
    other_flags = admin.get(f'/api/tickets/{other_day.json()["ticket_id"]}').json()['items'][0]['flags']
    assert not any('₹10,000' in flag for flag in other_flags)
    reversal = 'finance_reverse_direct_bill_payment' if direct else 'finance_reverse_payment'
    key = 'payment_id' if direct else 'cash_payment_id'
    save(admin, draft(admin, reversal, {
        key: payment['id'], 'reason': 'Fictional cash payment correction',
    }).json())
    assert not any('₹10,000' in flag for flag in admin.get(ticket).json()['items'][0]['flags'])
    assert save(admin, proposal.json())['journal_id']


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
    reply = chat(admin, 'Record expense ₹150 cash for office electricity; No vendor: Fictional electricity counter')
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
        assert columns[0] == columns[1] and len(columns[0]) == 15
    finally:
        old.dispose()
        fresh.dispose()
