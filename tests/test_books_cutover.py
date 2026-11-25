"""The old cost tracker is unavailable while approved ticket history remains readable."""
from sqlalchemy import select

from studioos.db import ApprovalTicket, ApprovalTicketItem, ChatSession, Cost, SessionLocal
from .conftest import approved_form, write


BOOKS_MESSAGE = 'Use the expense, bill, or payment form in Books.'


def test_tracker_routes_and_ticket_kinds_refuse_new_entries(admin):
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Books Cut-over'}).json()['id']
    requests = [
        ('post', '/api/costs', {'project_id': project_id, 'kind': 'expense', 'title': 'Fictional fittings', 'amount': '100'}),
        ('post', '/api/payments', {'cost_id': 1, 'amount': '100', 'idempotency_key': 'fictional-old-payment'}),
        ('patch', '/api/costs/1/recognize', {}),
        ('post', '/api/costs/1/approve', {}),
        ('post', '/api/costs/1/reject', {'reason': 'Fictional correction'}),
        ('post', '/api/costs/1/correct', {'reason': 'Fictional correction', 'new_amount': '50'}),
        ('post', '/api/payments/1/approve', {}),
        ('post', '/api/payments/1/reject', {'reason': 'Fictional correction'}),
        ('post', '/api/payments/1/reverse', {'reason': 'Fictional correction'}),
        ('post', '/api/finance-ledger/legacy-expenses/1/preview', {'entries': [{'cost_id': 1}]}),
    ]
    before = {ticket['id'] for ticket in admin.get('/api/tickets').json()}
    for method, path, payload in requests:
        response = write(admin, method, path, payload)
        assert response.status_code == 410 and response.json()['detail'] == BOOKS_MESSAGE, (path, response.text)
    for kind in ('record_cost', 'update_cost', 'record_payment', 'legacy_money_action',
                 'finance_migrate_expenses', 'finance_reverse_expense_migration'):
        response = write(admin, 'post', '/api/universal/proposals', {
            'kind': kind, 'data': {}, 'evidence': 'Fictional old tracker request',
        })
        assert response.status_code == 422 and response.json()['detail'] == BOOKS_MESSAGE, (kind, response.text)
    assert admin.get('/api/costs').json() == admin.get('/api/payments').json() == []
    assert {ticket['id'] for ticket in admin.get('/api/tickets').json()} == before


def test_pre_cutover_ticket_stays_readable_but_cannot_write_to_the_tracker(admin):
    assert approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Earlier Project'}).status_code == 200
    owner_id = admin.get('/api/auth/me').json()['user']['id']
    with SessionLocal() as db:
        session = ChatSession(id='fictional-old-tracker-draft', user_id=owner_id)
        db.add(session)
        db.flush()
        ticket = ApprovalTicket(session_id=session.id, submitter_id=owner_id)
        db.add(ticket)
        db.flush()
        db.add(ApprovalTicketItem(ticket_id=ticket.id, item_type='record_cost', after_data={
            'project': 'Fictional Earlier Project', 'kind': 'expense',
            'title': 'Fictional Old Expense', 'amount_paise': 10000,
        }))
        db.commit()
        ticket_id = ticket.id

    response = admin.get(f'/api/tickets/{ticket_id}')
    assert response.status_code == 200
    assert response.json()['items'][0]['after']['title'] == 'Fictional Old Expense'
    result = write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {})
    assert result.status_code in (400, 409, 422) and BOOKS_MESSAGE in result.text, result.text
    with SessionLocal() as db:
        assert db.scalar(select(Cost.id)) is None


def test_site_expense_requires_books_even_for_the_old_form(admin):
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Unconfigured Site'}).json()['id']
    response = write(admin, 'post', '/api/site-expenses', {
        'project_id': project_id, 'amount': '100', 'title': 'Fictional Site Supplies', 'ledger': False,
    })
    assert response.status_code == 400
    assert response.json()['detail'] == 'Set up the company in Books first.'
