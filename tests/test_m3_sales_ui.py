"""Fictional fixtures for the Sales screen's read-only form options."""

from sqlalchemy import select

from studioos.db import ApprovalTicket, GLAccount, GLJournal, SessionLocal
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_v018_time_app import staff


def test_sales_options_return_only_posting_choices_for_each_company(admin):
    entity, vendor, _, _, project = _setup_company_and_vendor(admin)
    accounts = _setup_sales_accounts(entity)
    with SessionLocal() as db:
        disabled = GLAccount(entity_id=entity, code='TEST-DISABLED', name='Output IGST',
                             kind='liability', active=False, posting_allowed=True)
        db.add(disabled)
        db.commit()
        tickets = db.scalars(select(ApprovalTicket.id)).all()
        journals = db.scalars(select(GLJournal.id)).all()

    response = admin.get('/api/sales/options')
    assert response.status_code == 200, response.text
    options = response.json()
    company = next(row for row in options['companies'] if row['id'] == entity)
    assert company['state_code'] == '29'
    assert company['accounts']['receivable'] == accounts['ar_id']
    assert company['accounts']['design_income'] == accounts['rev_id']
    assert company['accounts']['igst'] == accounts['igst_id']
    assert company['accounts']['rounding'] == accounts['rnd_id']
    assert company['accounts']['tds_receivable'] is None
    assert accounts['client_id'] in {row['id'] for row in options['clients']}
    assert vendor in {row['id'] for row in options['vendors']}
    assert project in {row['id'] for row in options['projects']}
    assert all(set(row) == {'id', 'name', 'state_code'} for row in options['clients'])
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicket.id)).all() == tickets
        assert db.scalars(select(GLJournal.id)).all() == journals


def test_sales_options_permissions(admin):
    for role in ('manager', 'accounts', 'site_engineer', 'architect', 'viewer'):
        client, _ = staff(admin, f'fictional-sales-ui-{role}', role)
        status = 200 if role in ('manager', 'accounts') else 403
        assert client.get('/api/sales/options').status_code == status


def test_invoice_from_quote_requires_approved_acceptance_and_matching_links(admin):
    entity, _, _, _, project = _setup_company_and_vendor(admin)
    accounts = _setup_sales_accounts(entity)
    line = {'description': 'Fictional consultation', 'rate_paise': 10_000, 'quantity': 1, 'tax_rate_bps': 0}
    common = {'entity_id': entity, 'client_id': accounts['client_id'], 'project_id': project}
    draft = write(admin, 'post', '/api/sales/quotes', {**common, 'quote_number': 'M3-QUOTE-UI',
        'quote_date': '2026-11-01', 'valid_until': '2026-12-01', 'lines': [line]})
    assert draft.status_code == 200, draft.text
    ticket_id = draft.json()['ticket_id']
    approval = write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {})
    assert approval.status_code == 200, approval.text
    quote_id = admin.get('/api/sales/quotes').json()['quotes'][0]['id']
    invoice = {**common, 'quote_id': quote_id, 'invoice_number': 'M3-INVOICE-UI', 'invoice_date': '2026-11-20',
               'due_date': '2026-12-01', 'ar_account_id': accounts['ar_id'],
               'lines': [{**line, 'income_account_id': accounts['rev_id']}]}
    refused = write(admin, 'post', '/api/sales/invoices', invoice)
    assert refused.status_code == 422 and 'Approve acceptance' in refused.text

    acceptance = write(admin, 'post', f'/api/sales/quotes/{quote_id}/accept', {'accepted_date': '2026-11-19'})
    assert acceptance.status_code == 200, acceptance.text
    acceptance_id = acceptance.json()['ticket_id']
    approval = write(admin, 'post', f'/api/tickets/{acceptance_id}/approve-and-save', {})
    assert approval.status_code == 200, approval.text
    refused = write(admin, 'post', '/api/sales/invoices', {**invoice, 'project_id': None})
    assert refused.status_code == 422 and 'company, client, and project' in refused.text

    submitted = write(admin, 'post', '/api/sales/invoices', {**invoice, 'request_key': 'fictional-m3-ui-convert'})
    assert submitted.status_code == 200, submitted.text
    retried = write(admin, 'post', '/api/sales/invoices', {**invoice, 'request_key': 'fictional-m3-ui-convert'})
    assert retried.status_code == 200 and retried.json()['ticket_id'] == submitted.json()['ticket_id']
    assert admin.get('/api/sales/invoices').json()['invoices'] == []
