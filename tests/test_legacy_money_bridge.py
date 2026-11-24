"""Fictional project totals and the read-only accounting migration preview."""
from sqlalchemy import select

from studioos.chain import verify
from studioos.db import Base, SessionLocal

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


def test_batch_preview_preserves_unmigrated_costs_and_flags_existing_books(admin):
    pid = project(admin)
    first = old_expense(admin, pid, '82.51')
    second = old_expense(admin, pid, '5.49')
    company = finance_setup(admin)
    data = expense_data(admin, company)
    url = f'/api/finance-ledger/legacy-expenses/{company}/preview'
    mapping = {'cost_id': first, 'expense_account_id': data['expense_account_id'],
               'paid_through_id': data['paid_through_id'], 'vendor_id': data['vendor_id'], 'date': '2026-08-31'}

    partial = write(admin, 'post', url, {'entries': [mapping]})
    assert partial.status_code == 200, partial.text
    batch = partial.json()['batch']
    assert batch['ready_for_review'] is True
    assert batch['total_debit_paise'] == batch['total_credit_paise'] == 8_251
    assert batch['projects'][0]['current_actual_paise'] == 8_800
    assert batch['projects'][0]['projected_actual_paise'] == 8_800
    assert batch['projects'][0]['difference_paise'] == 0

    full = write(admin, 'post', url, {'entries': [mapping, {**mapping, 'cost_id': second}]})
    assert full.status_code == 200, full.text
    batch = full.json()['batch']
    assert batch['ready_for_review'] is True
    assert batch['total_debit_paise'] == batch['total_credit_paise'] == 8_800
    assert batch['projects'][0]['difference_paise'] == 0
    assert admin.get(f'/api/finance-ledger/journals/{company}').json() == []
    duplicate = write(admin, 'post', url, {'entries': [mapping, mapping]})
    assert duplicate.status_code == 422

    posted = draft(admin, 'finance_expense', {**data, 'project_id': pid})
    assert posted.status_code == 200, posted.text
    save(admin, posted.json())
    with_existing = write(admin, 'post', url, {'entries': [mapping, {**mapping, 'cost_id': second}]})
    assert with_existing.status_code == 200, with_existing.text
    batch = with_existing.json()['batch']
    assert not batch['ready_for_review']
    assert batch['projects'][0]['current_actual_paise'] == data['amount_paise']
    assert batch['projects'][0]['difference_paise'] == 8_800
    assert len(admin.get(f'/api/finance-ledger/journals/{company}').json()) == 1


def test_approved_migration_preserves_remaining_costs_and_can_be_reversed(admin):
    pid = project(admin)
    first = old_expense(admin, pid, '82.51')
    second = old_expense(admin, pid, '5.49')
    company = finance_setup(admin)
    source = expense_data(admin, company)
    entries = [{'cost_id': first, 'expense_account_id': source['expense_account_id'],
                'paid_through_id': source['paid_through_id'], 'vendor_id': source['vendor_id'], 'date': '2026-08-31'}]
    preview = write(admin, 'post', f'/api/finance-ledger/legacy-expenses/{company}/preview', {'entries': entries})
    assert preview.status_code == 200, preview.text
    data = {'entity_id': company, 'entries': entries, 'signoff_reference': 'Fictional accountant review',
            'review_fingerprint': preview.json()['batch'].get('review_fingerprint', 'missing')}
    outsider, _ = staff(admin, 'fictional-migration-outsider', 'site_engineer')
    assert draft(outsider, 'finance_migrate_expenses', data).status_code == 403
    assert draft(admin, 'finance_migrate_expenses', {**data, 'review_fingerprint': '0' * 64}).status_code == 422
    proposal = draft(admin, 'finance_migrate_expenses', data)
    assert proposal.status_code == 200, proposal.text
    old_draft = write(admin, 'post', '/api/costs', {
        'project_id': pid, 'kind': 'expense', 'title': 'Fictional unposted tracker draft',
        'vendor': 'ABC Fictional Suppliers', 'amount': '42',
    })
    assert old_draft.status_code == 200, old_draft.text
    url = f'/api/finance-ledger/trial-balance/{company}'
    assert admin.get(url).json()['total_debit_paise'] == 0
    result = save(admin, proposal.json())
    stale = write(admin, 'post', f'/api/tickets/{old_draft.json()["ticket_id"]}/approve-and-save', {})
    assert stale.status_code in (409, 422) and 'Use Record expense' in stale.text
    trial = admin.get(url).json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 8_251
    health = admin.get(f'/api/budgets/project/{pid}/money').json()
    assert health['cost_to_date_paise'] == 8_800
    assert draft(admin, 'finance_migrate_expenses', data).status_code == 422
    correction = write(admin, 'post', f'/api/costs/{first}/correct', {
        'new_amount': '90.00', 'reason': 'Fictional correction to a migrated cost',
    })
    assert correction.status_code == 409 and 'Reverse its migration batch' in correction.text
    second_entries = [{**entries[0], 'cost_id': second}]
    second_preview = write(admin, 'post', f'/api/finance-ledger/legacy-expenses/{company}/preview', {'entries': second_entries})
    assert second_preview.status_code == 200, second_preview.text
    second_batch = draft(admin, 'finance_migrate_expenses', {
        **data, 'entries': second_entries, 'review_fingerprint': second_preview.json()['batch']['review_fingerprint'],
    })
    assert second_batch.status_code == 200, second_batch.text
    second_saved = save(admin, second_batch.json())
    assert admin.get(f'/api/budgets/project/{pid}/money').json()['cost_to_date_paise'] == 8_800
    reverse = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': result['id'], 'reason': 'Fictional accountant correction',
    })
    assert reverse.status_code == 200, reverse.text
    save(admin, reverse.json())
    assert admin.get(f'/api/budgets/project/{pid}/money').json()['cost_to_date_paise'] == 8_800
    assert len(admin.get('/api/costs').json()) == 2
    trial = admin.get(url).json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 549
    reverse_second = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': second_saved['id'], 'reason': 'Fictional second reversal',
    })
    assert reverse_second.status_code == 200, reverse_second.text
    save(admin, reverse_second.json())
    trial = admin.get(url).json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 0
    new_cost = write(admin, 'post', '/api/costs', {
        'project_id': pid, 'kind': 'expense', 'title': 'Fictional new tracker cost',
        'vendor': 'ABC Fictional Suppliers', 'amount': '39',
    })
    assert new_cost.status_code in (400, 409, 422) and 'Use Record expense' in new_cost.text
    with SessionLocal() as db:
        for name in ('audit_events', 'chat_messages'):
            table = Base.metadata.tables[name]
            assert verify(name, db.execute(select(table).order_by(table.c.id)).mappings())['ok']
