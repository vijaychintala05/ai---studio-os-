"""Out-of-pocket claims and paybacks with fictional staff and amounts."""
from sqlalchemy import create_engine, inspect

from studioos.migrations import apply_migrations
from .conftest import write
from .test_finance_expense import expense_data
from .test_money_document_dates import draft
from .test_v018_time_app import staff
from .test_v025_site_expense_flow import site
from .test_v098_universal_accounting import finance_setup, save


def test_claim_waits_for_another_approver_and_payback_clears_the_liability(admin):
    company = finance_setup(admin)
    manager, _ = staff(admin, 'fictional-reimbursement-manager', 'manager')
    outsider, _ = staff(admin, 'fictional-other-staff', 'site_engineer')
    data = expense_data(admin, company, personal_payment=True, paid_through_id=None, amount_paise=10_001)
    assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 20_000}).status_code == 200
    proposal = draft(manager, 'finance_expense', data)
    assert proposal.status_code == 200, proposal.text
    ticket = proposal.json()
    assert manager.get('/api/reimbursements/mine').json() == {'owed_paise': 0, 'claims': []}
    assert write(manager, 'post', f'/api/tickets/{ticket["ticket_id"]}/approve-and-save', {}).status_code == 403
    claim = save(admin, ticket)
    assert manager.get('/api/reimbursements/mine').json()['owed_paise'] == 10_001
    assert outsider.get('/api/reimbursements/mine').json() == {'owed_paise': 0, 'claims': []}
    assert outsider.get(f'/api/finance-ledger/staff-claims/{company}').status_code == 403
    sources = admin.get(f'/api/finance-ledger/paid-through/{company}').json()
    bank = next(row['id'] for row in sources if row['kind'] == 'bank')
    pay = {'claim_id': claim['id'], 'paid_through_id': bank, 'amount_paise': 10_001,
           'payment_date': '2026-09-01', 'request_key': 'fictional-claim-payback'}
    result = draft(admin, 'finance_reimburse_staff', pay)
    assert result.status_code == 200, result.text
    payment = save(admin, result.json())
    assert manager.get('/api/reimbursements/mine').json()['owed_paise'] == 0
    duplicate = draft(admin, 'finance_reimburse_staff', {**pay, 'request_key': 'fictional-claim-repeat'})
    assert duplicate.status_code == 422
    trial = admin.get(f'/api/finance-ledger/trial-balance/{company}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 10_001
    assert next(row for row in trial['accounts'] if row['kind'] == 'liability')['credit_paise'] == 0
    claim_reversal = draft(admin, 'finance_reverse_expense', {'expense_id': claim['id'], 'reason': 'Fictional correction'})
    assert claim_reversal.status_code == 422, claim_reversal.text
    reversal = draft(admin, 'finance_reverse_staff_payment', {'payment_id': payment['id'], 'reason': 'Fictional payment returned'})
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    assert manager.get('/api/reimbursements/mine').json()['owed_paise'] == 10_001
    repost = draft(admin, 'finance_reimburse_staff', {**pay, 'request_key': 'fictional-reissued-claim'})
    assert repost.status_code == 200, repost.text
    save(admin, repost.json())
    assert manager.get('/api/reimbursements/mine').json()['owed_paise'] == 0


def test_site_engineer_can_claim_with_no_petty_cash_account(admin, site):
    mine, _, engineer, _, _ = site
    company = finance_setup(admin)
    proposal = write(engineer, 'post', '/api/site-expenses', {
        'project_id': mine, 'title': 'Fictional project brushes', 'amount': '75.01',
        'ledger': True, 'personal_payment': True, 'no_vendor': True, 'no_vendor_name': 'Fictional taxi driver',
        'request_key': 'fictional-site-claim',
    })
    assert proposal.status_code == 200, proposal.text
    save(admin, proposal.json())
    assert engineer.get('/api/reimbursements/mine').json()['owed_paise'] == 7_501
    assert engineer.get('/api/home').json()['owed_to_you_paise'] == 7_501
    assert engineer.get(f'/api/finance-ledger/staff-claims/{company}').status_code == 403
    assert admin.get(f'/api/budgets/project/{mine}/money').json()['cost_to_date_paise'] == 7_501


def test_staff_account_schema_matches_fresh_and_upgraded(monkeypatch):
    from studioos.db import FinanceStaffAccount, FinanceStaffReimbursement

    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    tables = (FinanceStaffReimbursement.__table__, FinanceStaffAccount.__table__)
    try:
        apply_migrations(old)
        with old.begin() as conn:
            for table in tables:
                table.drop(conn)
            conn.exec_driver_sql('DELETE FROM schema_migrations WHERE version > 43')
        apply_migrations(old)
        apply_migrations(fresh)
        for table in tables:
            schemas = [inspect(engine) for engine in (old, fresh)]
            assert schemas[0].get_foreign_keys(table.name) == schemas[1].get_foreign_keys(table.name)
            columns = [[(col['name'], str(col['type']), col['nullable'])
                        for col in schema.get_columns(table.name)] for schema in schemas]
            assert columns[0] == columns[1] and columns[0]
    finally:
        old.dispose()
        fresh.dispose()
