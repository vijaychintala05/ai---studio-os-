"""Fictional project totals and the read-only accounting migration preview."""
from .conftest import approved_form, write
from .test_finance_expense import expense_data
from .test_money_document_dates import draft
from .test_v018_time_app import staff
from .test_v098_universal_accounting import finance_setup, project, save, vendor


def old_expense(admin, project_id, amount):
    return approved_form(admin, 'post', '/api/costs', {
        'project_id': project_id, 'kind': 'expense', 'title': 'Fictional transit',
        'vendor': 'ABC Fictional Suppliers', 'amount': amount,
    }).json()['id']


def test_budget_reads_posted_expense_and_records_breach_in_the_approval(admin):
    ledger_project = project(admin)
    tracker_project = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Tracker Project', 'budget': '2000',
    }).json()['id']
    old_expense(admin, tracker_project, '12.25')
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
    assert project_totals[tracker_project]['actual_paise'] == 1_225
    assert project_totals[tracker_project]['basis'] == 'earlier_tracker'
    assert admin.get('/api/summary').json()['costs']['actual_paise'] == 11_226
    health = admin.get(health_url).json()
    assert health['budgets'][0]['actual_paise'] == health['breaches'][0]['actual_paise'] == 10_001
    assert admin.get(health_url + '/money').json()['cost_to_date_paise'] == 10_001
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 10_001

    reversal = draft(admin, 'finance_reverse_expense', {'expense_id': entry['id'], 'reason': 'Fictional correction'})
    assert reversal.status_code == 200, reversal.text
    save(admin, reversal.json())
    assert admin.get(health_url).json()['budgets'][0]['actual_paise'] == 0
    assert admin.get('/api/summary').json()['costs']['actual_paise'] == 1_225


def test_migration_preview_uses_reviewed_links_and_leaves_the_ledger_unchanged(admin):
    pid = project(admin)
    cost_id = old_expense(admin, pid, '82.51')
    company = finance_setup(admin)
    data = expense_data(admin, company)
    url = f'/api/finance-ledger/legacy-expenses/{company}/preview'
    mapping = {'cost_id': cost_id, 'expense_account_id': data['expense_account_id'],
               'paid_through_id': data['paid_through_id'], 'vendor_id': data['vendor_id'], 'date': '2026-08-31'}
    outsider, _ = staff(admin, 'fictional-preview-outsider', 'site_engineer')
    assert write(outsider, 'post', url, {'entries': [mapping]}).status_code == 403
    result = write(admin, 'post', url, {'entries': [mapping]})
    assert result.status_code == 200, result.text
    preview = result.json()['entries'][0]
    assert preview['cost_id'] == cost_id and preview['project_id'] == pid
    assert preview['ready_for_review'] and not preview['issues']
    assert [(line['side'], line['amount_paise']) for line in preview['journal_lines']] == [
        ('debit', 8_251), ('credit', 8_251),
    ]
    missing = write(admin, 'post', url, {'entries': [{'cost_id': cost_id}]})
    assert not missing.json()['entries'][0]['ready_for_review']
    assert not missing.json()['entries'][0]['journal_lines']
    assert admin.get(f'/api/finance-ledger/journals/{company}').json() == []
    assert admin.get('/api/costs').json()[0]['amount'] == 82.51
