"""The old cost tracker is unavailable while approved ticket history remains readable."""
from sqlalchemy import select

from studioos.db import (
    ApprovalTicket, ApprovalTicketItem, ChatSession, Cost, FinanceDirectBill, FinanceDirectBillPayment,
    FinanceExpense, FinancePurchaseOrder, SessionLocal,
)
from .conftest import approved_form, write
from .test_v098_universal_accounting import finance_setup, save


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


def test_chat_purchase_and_order_propose_books_items(admin):
    entity_id = finance_setup(admin)
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Cedar Pavilion'}).json()['id']
    vendor = write(admin, 'post', '/api/tickets/proposals', {
        'kind': 'create_vendor', 'data': {'name': 'Fictional Fixtures'}, 'evidence': 'Fictional supplier fixture',
    })
    assert vendor.status_code == 200, vendor.text
    vendor_id = save(admin, vendor.json())['id']
    messages = (
        ('Bought wiring material from Fictional Fixtures at Cedar Pavilion for ₹1250 cash today.',
         'finance_expense', 125000, 'vendor_id'),
        ('Spent ₹75 cash at Cedar Pavilion for Fictional Fixtures.',
         'finance_expense', 7500, 'vendor_id'),
        ('Ordered from Fictional Fixtures for Cedar Pavilion, PO #FICT-27, amount ₹2400.',
         'finance_po', 240000, 'supplier_id'),
    )
    for message, kind, amount, party_field in messages:
        response = write(admin, 'post', '/api/chat', {'message': message})
        assert response.status_code == 200, response.text
        item = admin.get(f'/api/tickets/{response.json()["ticket_id"]}').json()['items'][0]
        assert item['item_type'] == kind
        assert item['after']['project_id'] == project_id
        assert item['after'][party_field] == vendor_id
        assert item['after']['amount_paise'] == amount
        if kind == 'finance_po':
            assert item['after']['entity_id'] == entity_id
            assert item['after']['po_number'] == 'FICT-27'
        else:
            assert item['after']['paid_through_id'] is not None
    with SessionLocal() as db:
        assert db.scalar(select(FinanceExpense.id)) is None
        assert db.scalar(select(FinancePurchaseOrder.id)) is None


def test_ask_drafts_a_supplier_bill_and_its_payment(admin):
    company_id = finance_setup(admin)
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Cedar Pavilion'}).json()['id']
    supplier = write(admin, 'post', '/api/tickets/proposals', {
        'kind': 'create_vendor', 'data': {'name': 'Fictional Fixtures'}, 'evidence': 'Fictional supplier fixture',
    })
    supplier_id = save(admin, supplier.json())['id']
    response = write(admin, 'post', '/api/chat', {'message': (
        'Supplier bill #FICT-55 from Fictional Fixtures for Cedar Pavilion, ₹2400, '
        'dated 2026-09-05, due 2026-09-12.'
    )})
    assert response.status_code == 200 and response.json().get('ticket_id'), response.text
    ticket = response.json()
    item = admin.get(f'/api/tickets/{ticket["ticket_id"]}').json()['items'][0]
    assert item['item_type'] == 'finance_direct_bill'
    bill = item['after']
    assert (bill['entity_id'], bill['supplier_id'], bill['invoice_number']) == (company_id, supplier_id, 'FICT-55')
    assert (bill['bill_date'], bill['due_date'], bill['payment_terms_days']) == ('2026-09-05', '2026-09-12', 7)
    assert bill['amount_paise'] == 240000 and bill['lines'][0]['project_id'] == project_id
    with SessionLocal() as db:
        assert db.scalar(select(FinanceDirectBill.id)) is None
    bill_id = save(admin, ticket)['id']

    response = write(admin, 'post', '/api/chat', {'message': (
        'Paid bill #FICT-55 ₹500 cash on 2026-09-13, reference #TXN-10.'
    )})
    assert response.status_code == 200 and response.json().get('ticket_id'), response.text
    item = admin.get(f'/api/tickets/{response.json()["ticket_id"]}').json()['items'][0]
    assert item['item_type'] == 'finance_direct_bill_payment'
    payment = item['after']
    assert (payment['bill_id'], payment['amount_paise'], payment['payment_date'], payment['payment_reference']) == (
        bill_id, 50000, '2026-09-13', 'TXN-10',
    )
    assert payment['paid_through_id'] is not None
    with SessionLocal() as db:
        assert db.scalar(select(FinanceDirectBillPayment.id)) is None
