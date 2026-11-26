"""Posted Books expenses update budget actuals and record breaches on approval."""
from .conftest import write
from .test_finance_expense import expense_data
from .test_money_document_dates import draft
from .test_v098_universal_accounting import finance_setup, project, save


def test_budget_reads_posted_expense_and_records_breach_in_the_approval(admin):
    ledger_project = project(admin)
    p = write(admin, 'post', '/api/budgets/propose', {'kind': 'budget_set', 'data': {
        'project_id': ledger_project, 'scope': 'project', 'amount_paise': 9_000,
    }})
    assert p.status_code == 200, p.text
    save(admin, p.json())
    entity = finance_setup(admin)
    data = expense_data(admin, entity, project_id=ledger_project, amount_paise=10_001)
    first = draft(admin, 'finance_expense', data)
    assert first.status_code == 200, first.text
    health_url = f'/api/budgets/project/{ledger_project}'
    assert admin.get(health_url).json()['budgets'][0]['actual_paise'] == 0
    entry = save(admin, first.json())

    project_totals = {row['id']: row for row in admin.get('/api/budgets').json()}
    assert project_totals[ledger_project]['actual_paise'] == 10_001
    assert project_totals[ledger_project]['basis'] == 'posted_books'
    assert admin.get('/api/summary').json()['costs']['actual_paise'] == 10_001
    health = admin.get(health_url).json()
    assert health['budgets'][0]['actual_paise'] == health['breaches'][0]['actual_paise'] == 10_001
    assert admin.get(health_url + '/money').json()['cost_to_date_paise'] == 10_001
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 10_001

    reversal = draft(admin, 'finance_reverse_expense', {'expense_id': entry['id'], 'reason': 'Fictional correction'})
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    assert admin.get(health_url).json()['budgets'][0]['actual_paise'] == 0
    assert admin.get('/api/summary').json()['costs']['actual_paise'] == 0
