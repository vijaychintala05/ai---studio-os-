"""Books money forms draft reviewed tickets before creating business rows."""
import pytest
from sqlalchemy import func, select
from studioos.db import FinanceDirectBillPayment, FinanceExpense, FinanceSupplierCashPayment, SessionLocal
from .books_fixtures import draft_project_expense
from .conftest import write,approved_form
from .test_m2_bill_form import _setup_company_and_vendor
from .test_v098_universal_accounting import FICTIONAL_BILL_DATES, finance_setup, propose, save


def _count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _payment_form(admin, *, direct=True):
    company, supplier, account, _, project = _setup_company_and_vendor(admin)
    bill_data = {**FICTIONAL_BILL_DATES, 'invoice_number': 'FICT-PAYMENT-FORM-BILL', 'amount_paise': 200000}
    if direct:
        bill_kind = 'finance_direct_bill'
        bill_data.update(entity_id=company, supplier_id=supplier,
                         lines=[{'project_id': project, 'account_id': account, 'amount_paise': 200000}])
    else:
        bill_kind = 'finance_bill'
        order = save(admin, propose(admin, 'finance_po', {
            'entity_id': company, 'supplier_id': supplier, 'project_id': project,
            'po_number': 'FICT-PAYMENT-FORM-PO', 'amount_paise': 200000,
        }))
        bill_data['po_id'] = order['id']
    bill = save(admin, propose(admin, bill_kind, bill_data))
    source = next(row for row in admin.get(f'/api/finance-ledger/paid-through/{company}').json() if row['kind'] == 'cash')
    return {'kind': 'finance_direct_bill_payment' if direct else 'finance_payment',
            'data': {'bill_id': bill['id'], 'paid_through_id': source['id'], 'amount_paise': 50000,
                     'payment_date': FICTIONAL_BILL_DATES['bill_date'], 'payment_reference': 'FICT-PAYMENT-FORM',
                     'idempotency_key': 'fictional-payment-form-once'}, 'evidence': 'Fictional payment form submission'}


def test_cost_form_does_not_create_business_row_before_ticket_review(admin):
    finance_setup(admin)
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Money Form Site','budget':'100000'}).json()['id']
    before = _count(FinanceExpense)
    p = draft_project_expense(admin, project, 120000, note='Fictional transport')
    assert p.status_code==200,p.text
    assert _count(FinanceExpense) == before
    assert p.json()['ticket_id']
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    assert _count(FinanceExpense) == before + 1
    assert saved.json()['committed_records'][0]['journal_id']


@pytest.mark.parametrize('direct', [False, True], ids=['purchase-order-bill', 'direct-bill'])
def test_payment_form_does_not_create_business_row_before_ticket_review(admin, direct):
    body = _payment_form(admin, direct=direct)
    model = FinanceDirectBillPayment if direct else FinanceSupplierCashPayment
    before = _count(model)
    p = write(admin, 'post', '/api/universal/proposals', body)
    assert p.status_code==200,p.text
    assert _count(model) == before
    assert p.json()['ticket_id']
    retry = write(admin, 'post', '/api/universal/proposals', body)
    assert retry.status_code == 200 and retry.json()['ticket_id'] == p.json()['ticket_id']
    changed = write(admin, 'post', '/api/universal/proposals', {**body, 'data': {**body['data'], 'amount_paise': 1}})
    assert changed.status_code == 409
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    assert _count(model) == before + 1
    retry = write(admin, 'post', '/api/universal/proposals', body)
    assert retry.status_code == 200 and retry.json()['ticket_id'] == p.json()['ticket_id']
    assert _count(model) == before + 1


@pytest.mark.parametrize('direct', [False, True], ids=['purchase-order-bill', 'direct-bill'])
def test_pending_payment_ticket_still_reserves_the_payable_balance(admin, direct):
    single = _payment_form(admin, direct=direct)
    data = single['data']
    bill_kind = 'direct_bill' if direct else 'po_bill'
    wrapper = admin.get('/api/books/bills-due').json()
    company_id = next(iter(wrapper['paying_accounts']))
    reverse_kind = 'finance_reverse_direct_bill' if direct else 'finance_reverse_bill'
    reversal = propose(admin, reverse_kind, {'bill_id': data['bill_id'], 'reason': 'Fictional bill filed in error'})

    first = write(admin, 'post', '/api/universal/proposals', {**single, 'data': {**data, 'amount_paise': 150000}})
    assert first.status_code == 200, first.text
    batch = {'entity_id': int(company_id), 'paid_through_id': data['paid_through_id'],
             'payment_date': data['payment_date'], 'payment_reference': 'FICT-RESERVATION-BATCH',
             'request_key': 'fictional-reservation-batch-reference-2026-with-a-long-stable-request-key',
             'items': [{'kind': bill_kind, 'bill_id': data['bill_id'], 'amount_paise': 100000}]}
    too_much = write(admin, 'post', '/api/books/pay-selected', batch)
    assert too_much.status_code == 422 and 'awaiting approval' in too_much.text

    def balances():
        register = admin.get(f'/api/finance-ledger/payables/{company_id}').json()
        bill = next(row for row in register['direct_bills' if direct else 'bills'] if row['bill_id'] == data['bill_id'])
        return bill['outstanding_paise'], bill['pending_payment_paise'], bill['available_payment_paise']

    assert balances() == (200000, 150000, 50000)
    reversal_url = f'/api/tickets/{reversal["ticket_id"]}/approve-and-save'
    blocked = write(admin, 'post', reversal_url, {})
    assert blocked.status_code == 422 and 'awaiting approval' in blocked.text
    returned = write(admin, 'post', f'/api/tickets/items/{first.json()["item_id"]}/reject', {'note': 'Fictional transfer cancelled'})
    assert returned.status_code == 200, returned.text
    assert balances() == (200000, 0, 200000)
    next_draft = write(admin, 'post', '/api/books/pay-selected', batch)
    assert next_draft.status_code == 200, next_draft.text
    assert balances() == (200000, 100000, 100000)
    retry = write(admin, 'post', '/api/books/pay-selected', batch)
    assert retry.status_code == 200 and retry.json()['ticket_id'] == next_draft.json()['ticket_id']
    altered = write(admin, 'post', '/api/books/pay-selected', {**batch, 'payment_reference': 'FICT-WRONG-REFERENCE'})
    assert altered.status_code == 409
    save(admin, next_draft.json())
    assert balances() == (100000, 0, 100000)
    blocked = write(admin, 'post', reversal_url, {})
    assert blocked.status_code == 422 and 'Reverse every payment' in blocked.text


def test_selected_books_path_refuses_parallel_legacy_expenses_and_payments(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Cutover Site','budget':'100000'}).json()['id']
    entity = finance_setup(admin)
    save(admin,propose(admin,'finance_install_chart',{'entity_id':entity,'standard':'india_interiors'}))
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    c=write(admin,'post','/api/costs',{'project_id':project,'kind':'expense','title':'Fictional parallel expense','amount':'1200'})
    p=write(admin,'post','/api/payments',{'cost_id':1,'amount':'500','idempotency_key':'fictional-cutover-payment-01'})
    assert c.status_code == p.status_code == 410
    assert admin.get('/api/costs').json() == admin.get('/api/payments').json() == []


@pytest.mark.parametrize('direct', [False, True], ids=['purchase-order-bill', 'direct-bill'])
def test_payment_draft_cannot_change_its_idempotency_identity(admin, direct):
    drafted = write(admin, 'post', '/api/universal/proposals', _payment_form(admin, direct=direct))
    assert drafted.status_code == 200, drafted.text
    p = drafted.json()
    item=admin.get(f'/api/tickets/{p["ticket_id"]}').json()['items'][0]
    after={**item['after'],'idempotency_key':'fictional-payment-identity-02'}
    r=write(admin,'patch',f'/api/tickets/items/{p["item_id"]}',{'after':after})
    assert r.status_code==422,r.text
    assert _count(FinanceDirectBillPayment if direct else FinanceSupplierCashPayment) == 0
