"""Project-linked Books and Sales requests must match the approved project."""
from sqlalchemy import select

from studioos.db import GLAccount, SessionLocal

from .conftest import write
from .test_finance_expense import expense_data
from .test_project_company import _client, _project_draft
from .test_v098_universal_accounting import finance_setup, propose, save


def _setup(admin):
    company = finance_setup(admin)
    client = _client(admin, 'Fictional Project Client')
    project = save(admin, _project_draft(admin, client_id=client).json())['id']
    other = save(admin, propose(admin, 'finance_setup', {'entity_name': 'Fictional Other Company',
                 'expense_code': '5000', 'ap_code': '2100', 'bank_code': '1000',
                 'bank_name': 'Fictional Bank', 'bank_masked': '****1234'}))['id']
    return company, client, project, other


def _draft(admin, kind, data):
    return write(admin, 'post', '/api/universal/proposals',
                 {'kind': kind, 'data': data, 'evidence': 'Fictional project validation'})


def _quote(**inputs):
    return {'quote_number': 'FICT-Q-1', 'quote_date': '2026-11-01', 'valid_until': '2026-11-30',
            'lines': [{'description': 'Fictional drafting', 'quantity': 1, 'rate_paise': 5000,
                       'tax_rate_bps': 0}], **inputs}


def test_project_company_must_match_books_writes(admin):
    _, _, project, other = _setup(admin)
    expense = expense_data(admin, other, project_id=project)
    supplier = expense['vendor_id']
    base = {'entity_id': other, 'project_id': project, 'supplier_id': supplier, 'amount_paise': 5000}
    with SessionLocal() as db:
        account = db.scalar(select(GLAccount.id).where(GLAccount.entity_id == other, GLAccount.kind == 'expense'))
    line = {'account_id': account, 'project_id': project, 'amount_paise': 5000}
    bill = {'entity_id': other, 'supplier_id': supplier, 'invoice_number': 'FICT-B-1',
            'bill_date': '2026-11-01', 'due_date': '2026-11-01', 'payment_terms_days': 0, 'amount_paise': 5000,
            'lines': [line]}
    cases = {
        'finance_expense': expense,
        'finance_po': {**base, 'po_number': 'FICT-PO-1'},
        'finance_advance': {**base, 'payment_reference': 'FICT-ADV-1', 'idempotency_key': 'fictional-advance-1'},
        'finance_direct_bill': bill,
        'finance_manual_journal': {'entity_id': other, 'entry_date': '2026-11-01', 'narration': 'Fictional adjustment',
                                   'idempotency_key': 'fictional-journal-1',
                                   'lines': [{**line, 'side': 'debit'}, {**line, 'side': 'credit'}]},
        'finance_text_entry': {'entity_id': other, 'project_id': project, 'recipe': 'expense',
                               'slots': {}, 'accounts': {}, 'idempotency_key': 'fictional-text-entry-1'},
        'finance_vendor_credit': base,
        'finance_recurring_entry': {'entity_id': other, 'entry_kind': 'direct_bill', 'title': 'Fictional monthly bill',
                                    'next_run_date': '2026-11-01', 'payload_json': bill},
    }
    for kind, data in cases.items():
        result = _draft(admin, kind, data)
        assert result.status_code == 422 and 'belongs to Fictional Constructions' in result.text, (kind, result.text)


def test_project_company_and_client_must_match_sales_writes(admin):
    company, client, project, other = _setup(admin)
    other_client = _client(admin, 'Cedar Household')
    for kind in ('sales_quote', 'sales_invoice', 'sales_advance', 'sales_credit_note'):
        wrong_company = _draft(admin, kind, _quote(entity_id=other, project_id=project, client_id=client))
        assert wrong_company.status_code == 422 and 'belongs to Fictional Constructions' in wrong_company.text, (kind, wrong_company.text)
        wrong_client = _draft(admin, kind, _quote(entity_id=company, project_id=project, client_id=other_client))
        assert wrong_client.status_code == 422 and "project's client is Fictional Project Client" in wrong_client.text, (kind, wrong_client.text)


def test_quote_previews_the_project_client_and_rechecks_it_at_approval(admin):
    company, client, project, _ = _setup(admin)
    response = _draft(admin, 'sales_quote', _quote(entity_id=company, project_id=project))
    assert response.status_code == 200, response.text
    ticket = response.json()['ticket_id']
    item = admin.get(f'/api/tickets/{ticket}').json()['items'][0]
    assert item['after']['client_id'] == client
    assert item['display_values']['client_id'] == 'Fictional Project Client'

    other = _client(admin, 'Marigold Studio Owner')
    edit = write(admin, 'post', '/api/tickets/proposals', {'kind': 'update_project',
                 'data': {'id': project, 'client_id': other}, 'evidence': 'Fictional change'})
    assert edit.status_code == 200, edit.text
    save(admin, edit.json())

    attempted = write(admin, 'post', f'/api/tickets/{ticket}/approve-and-save', {})
    assert attempted.status_code in (400, 409, 422) and 'Marigold Studio Owner' in attempted.text


def test_books_groups_projects_by_owner_even_before_the_first_post(admin):
    company, _, project, other = _setup(admin)
    second = save(admin, _project_draft(admin, name='Juniper Pavilion', company_id=other).json())['id']
    response = admin.get('/api/books/home').json()
    groups = {row['entity_id']: row['projects'] for row in response['companies']}
    assert {key: [p['id'] for p in rows] for key, rows in groups.items()} == {company: [project], other: [second]}
    assert groups[company][0]['cost_to_date_paise'] == 0
    assert response['projects_without_company'] == []
