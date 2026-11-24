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


def test_fully_paid_historical_expense_migrates_each_payment_source(admin):
    pid = project(admin)
    cost = old_expense(admin, pid, '85.25')
    payments = []
    for i, amount in enumerate(('25.10', '60.15')):
        payment = approved_form(admin, 'post', '/api/payments', {
            'cost_id': cost, 'amount': amount, 'idempotency_key': f'fictional-historical-settlement-{i}',
        })
        assert payment.status_code == 200, payment.text
        payments.append(payment.json()['id'])
    entity = finance_setup(admin)
    source = expense_data(admin, entity)
    accounts = {row['kind']: row['id'] for row in admin.get(f'/api/finance-ledger/paid-through/{entity}').json()}
    mapping = {'cost_id': cost, 'expense_account_id': source['expense_account_id'],
               'vendor_id': source['vendor_id'], 'date': '2026-08-31',
               'payment_mappings': [{'payment_id': payment, 'paid_through_id': accounts[kind], 'date': '2026-08-31'}
                                    for payment, kind in zip(payments, ('bank', 'cash'), strict=True)]}
    url = f'/api/finance-ledger/legacy-expenses/{entity}/preview'
    preview = write(admin, 'post', url, {'entries': [mapping]})
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result['batch']['ready_for_review']
    amounts = {row['account_id']: row['amount_paise'] for row in result['entries'][0]['journal_lines']}
    assert amounts == {source['expense_account_id']: 8_525, accounts['bank']: 2_510, accounts['cash']: 6_015}
    incomplete = write(admin, 'post', url, {'entries': [{**mapping, 'payment_mappings': mapping['payment_mappings'][:1]}]})
    assert incomplete.status_code == 200 and not incomplete.json()['batch']['ready_for_review']
    unnecessary = write(admin, 'post', url, {'entries': [{**mapping, 'carry_balance': True}]})
    assert unnecessary.status_code == 200 and not unnecessary.json()['batch']['ready_for_review']
    proposal = draft(admin, 'finance_migrate_expenses', {
        'entity_id': entity, 'entries': [mapping], 'signoff_reference': 'Fictional accountant payment mapping review',
        'review_fingerprint': result['batch']['review_fingerprint'],
    })
    assert proposal.status_code == 200, proposal.text
    saved = save(admin, proposal.json())
    journal = admin.get(f'/api/finance-ledger/journals/{entity}').json()[0]
    assert all(line['supplier_id'] == source['vendor_id'] for line in journal['lines'])
    assert {line['account_id']: line['amount_paise'] for line in journal['lines']} == amounts
    reverse = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': saved['id'], 'reason': 'Fictional settled migration reversal',
    })
    assert reverse.status_code == 200, reverse.text
    save(admin, reverse.json())
    trial = admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert trial['total_debit_paise'] == trial['total_credit_paise'] == 0
    assert len(admin.get('/api/payments').json()) == 2


def test_partly_paid_migration_carries_only_reviewed_balance_into_payables(admin, tmp_path, monkeypatch):
    pid = project(admin)
    cost = old_expense(admin, pid, '85.25')
    payment = approved_form(admin, 'post', '/api/payments', {
        'cost_id': cost, 'amount': '25.10', 'idempotency_key': 'fictional-partly-paid-settlement',
    })
    assert payment.status_code == 200, payment.text
    entity = finance_setup(admin)
    source = expense_data(admin, entity)
    accounts = {row['kind']: row['id'] for row in admin.get(f'/api/finance-ledger/paid-through/{entity}').json()}
    bank_id = accounts['bank']
    mapping = {'cost_id': cost, 'expense_account_id': source['expense_account_id'],
               'vendor_id': source['vendor_id'], 'date': '2026-08-31',
               'payment_mappings': [{'payment_id': payment.json()['id'], 'paid_through_id': bank_id, 'date': '2026-08-31'}]}
    url = f'/api/finance-ledger/legacy-expenses/{entity}/preview'
    blocked = write(admin, 'post', url, {'entries': [mapping]}).json()
    assert not blocked['batch']['ready_for_review']
    mapping['carry_balance'] = True
    missing_source = write(admin, 'post', url, {'entries': [{**mapping, 'payment_mappings': []}]})
    assert missing_source.status_code == 200 and not missing_source.json()['batch']['ready_for_review']
    preview = write(admin, 'post', url, {'entries': [mapping]})
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result['batch']['ready_for_review']
    entry = result['entries'][0]
    assert entry['unpaid_paise'] == 6_015
    debit, paid, payable = entry['journal_lines']
    assert (debit['side'], debit['account_id'], debit['amount_paise']) == ('debit', source['expense_account_id'], 8_525)
    assert (paid['side'], paid['account_id'], paid['amount_paise']) == ('credit', bank_id, 2_510)
    assert (payable['side'], payable['amount_paise']) == ('credit', 6_015)
    register = f'/api/finance-ledger/payables/{entity}'
    assert admin.get(register).json()['outstanding_total_paise'] == 0
    pending = draft(admin, 'finance_migrate_expenses', {
        'entity_id': entity, 'entries': [mapping], 'signoff_reference': 'Fictional accountant reviewed carried balance',
        'review_fingerprint': result['batch']['review_fingerprint'],
    })
    assert pending.status_code == 200, pending.text
    assert admin.get(register).json()['outstanding_total_paise'] == 0
    saved = save(admin, pending.json())
    posted = admin.get(register).json()
    assert posted['bills'] == []
    assert posted['outstanding_total_paise'] == 6_015
    assert posted['legacy_payables'][0]['cost_id'] == cost
    company = admin.get('/api/books/home').json()['companies'][0]
    assert company['payable_paise'] == company['owed_by_supplier'][0]['owed_paise'] == sum(company['ageing'].values()) == 6_015
    party = admin.get(f'/api/books/parties/{source["vendor_id"]}').json()
    assert party['owed_paise'] == party['legacy_payables'][0]['owed_paise'] == 6_015
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert integrity['passed'] and integrity['ap_control_credit_paise'] == integrity['supplier_outstanding_paise'] == 6_015

    data = {'opening_journal_id': posted['legacy_payables'][0]['journal_id'], 'paid_through_id': accounts['cash'],
            'amount_paise': 4_000, 'payment_date': '2026-08-31', 'payment_reference': 'FICTIONAL-CARRIED-001'}
    first_payment = draft(admin, 'finance_pay_legacy_balance', data)
    assert first_payment.status_code == 200, first_payment.text
    flags = admin.get(f'/api/tickets/{first_payment.json()["ticket_id"]}').json()['items'][0]['flags']
    assert any('cash account below zero' in flag for flag in flags)
    stale_payment = draft(admin, 'finance_pay_legacy_balance', {**data, 'payment_reference': 'FICTIONAL-CARRIED-002'})
    assert stale_payment.status_code == 200, stale_payment.text
    assert admin.get(register).json()['outstanding_total_paise'] == 6_015
    settled = save(admin, first_payment.json())
    after_payment = admin.get(register).json()
    assert after_payment['outstanding_total_paise'] == 2_015
    assert after_payment['legacy_payments'] == [{
        'journal_id': settled['journal_id'], 'opening_journal_id': data['opening_journal_id'],
        'title': 'Fictional transit', 'amount_paise': 4_000, 'kind': 'cash', 'matched': False,
        'reference': data['payment_reference'], 'payment_date': data['payment_date'],
    }]
    party = admin.get(f'/api/books/parties/{source["vendor_id"]}').json()
    assert party['owed_paise'] == 2_015 and party['legacy_payments'] == after_payment['legacy_payments']
    stale_save = write(admin, 'post', f'/api/tickets/{stale_payment.json()["ticket_id"]}/approve-and-save')
    assert stale_save.status_code in (409, 422), stale_save.text
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert integrity['passed'] and integrity['supplier_outstanding_paise'] == 2_015
    duplicate = draft(admin, 'finance_pay_legacy_balance', {**data, 'amount_paise': 1_000})
    assert duplicate.status_code == 422
    assert 'reference' in duplicate.text.lower()
    migration_has_payment = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': saved['id'], 'reason': 'Fictional migration reversal while payment stands',
    })
    assert migration_has_payment.status_code == 422
    corrected = draft(admin, 'finance_reverse_legacy_balance_payment', {
        'journal_id': settled['journal_id'], 'reason': 'Fictional transfer sent in error',
    })
    assert corrected.status_code == 200, corrected.text
    save(admin, corrected.json())
    assert admin.get(register).json()['outstanding_total_paise'] == 6_015

    reverse = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': saved['id'], 'reason': 'Fictional partly paid migration reversal',
    })
    assert reverse.status_code == 200, reverse.text
    save(admin, reverse.json())
    assert admin.get(register).json()['outstanding_total_paise'] == 0
    assert admin.get(f'/api/finance-ledger/integrity/{entity}').json()['passed']
    assert [p['id'] for p in admin.get('/api/payments').json()] == [payment.json()['id']]

    # A remigration has a new opening journal. An independently approved statement
    # can match a payment of its remaining balance, which then cannot be reversed.
    from .test_finance_intake import imported
    from .test_v0140_intake_app import _up
    from .test_v098_universal_accounting import propose

    again = write(admin, 'post', url, {'entries': [mapping]}).json()
    save(admin, propose(admin, 'finance_migrate_expenses', {
        'entity_id': entity, 'entries': [mapping], 'signoff_reference': 'Fictional accountant approved correction',
        'review_fingerprint': again['batch']['review_fingerprint'],
    }))
    opened = admin.get(register).json()['legacy_payables'][0]['journal_id']
    final_payment = save(admin, propose(admin, 'finance_pay_legacy_balance', {
        **data, 'opening_journal_id': opened, 'paid_through_id': bank_id,
        'amount_paise': 6_015, 'payment_reference': 'FICTIONAL-CARRIED-003',
    }))
    assert admin.get(register).json()['legacy_payables'] == []
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path / 'intake'))
    statement = _up(admin, 'fictional-carried-balance.csv',
                    b'date,reference,signed_amount_paise\n2026-08-31,FICTIONAL-CARRIED-003,-6015\n')
    assert statement.status_code == 200, statement.text
    intake = statement.json()['id']
    save(admin, propose(admin, 'intake_file_accept', {'intake_id': intake, 'name': 'Fictional statement'}))
    bank = admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    line = save(admin, imported(admin, intake, entity, 'bank_statement', bank))['id']
    save(admin, propose(admin, 'finance_reconcile_bank', {
        'statement_line_id': line, 'journal_id': final_payment['journal_id'],
    }))
    assert admin.get(register).json()['legacy_payments'][0]['matched'] is True
    locked = draft(admin, 'finance_reverse_legacy_balance_payment', {
        'journal_id': final_payment['journal_id'], 'reason': 'Fictional attempted reversal of matched payment',
    })
    assert locked.status_code == 422 and 'matched' in locked.text


def test_unpaid_historical_expense_requires_explicit_choice_and_no_pending_payment(admin):
    pid = project(admin)
    cost = old_expense(admin, pid, '41.27')
    unresolved = old_expense(admin, pid, '15.00')
    pending = write(admin, 'post', '/api/payments', {
        'cost_id': unresolved, 'amount': '5.00', 'idempotency_key': 'fictional-unpaid-opening-pending',
    })
    assert pending.status_code == 200, pending.text
    entity = finance_setup(admin)
    source = expense_data(admin, entity)
    mapping = {'cost_id': cost, 'expense_account_id': source['expense_account_id'],
               'vendor_id': source['vendor_id'], 'date': '2026-08-31'}
    url = f'/api/finance-ledger/legacy-expenses/{entity}/preview'

    def preview(data):
        response = write(admin, 'post', url, {'entries': [data]})
        assert response.status_code == 200, response.text
        return response.json()

    assert not preview(mapping)['batch']['ready_for_review']
    assert not preview({**mapping, 'carry_balance': True, 'paid_through_id': source['paid_through_id']})['batch']['ready_for_review']
    waiting = preview({**mapping, 'cost_id': unresolved, 'carry_balance': True})
    assert not waiting['batch']['ready_for_review']
    assert any('pending payment tickets' in issue for issue in waiting['entries'][0]['issues'])

    mapping['carry_balance'] = True
    reviewed = preview(mapping)
    assert reviewed['batch']['ready_for_review']
    entry = reviewed['entries'][0]
    assert entry['unpaid_paise'] == 4_127 and entry['payments'] == []
    assert [(line['side'], line['amount_paise']) for line in entry['journal_lines']] == [('debit', 4_127), ('credit', 4_127)]
    assert entry['journal_lines'][1]['carried_balance'] is True
    assert all(line['account_id'] != source['paid_through_id'] for line in entry['journal_lines'])
    proposal = draft(admin, 'finance_migrate_expenses', {
        'entity_id': entity, 'entries': [mapping], 'signoff_reference': 'Fictional accountant confirmed outstanding invoice',
        'review_fingerprint': reviewed['batch']['review_fingerprint'],
    })
    assert proposal.status_code == 200, proposal.text
    saved = save(admin, proposal.json())
    register = f'/api/finance-ledger/payables/{entity}'
    assert admin.get(register).json()['outstanding_total_paise'] == 4_127
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert integrity['passed'] and integrity['ap_control_credit_paise'] == 4_127
    assert integrity['banks'][0]['bank_book_signed_debit_paise'] == 0
    reverse = draft(admin, 'finance_reverse_expense_migration', {
        'batch_ticket_id': saved['id'], 'reason': 'Fictional correction after review',
    })
    assert reverse.status_code == 200, reverse.text
    save(admin, reverse.json())
    assert admin.get(register).json()['outstanding_total_paise'] == 0
    assert admin.get(f'/api/budgets/project/{pid}/money').json()['cost_to_date_paise'] == 5_627
