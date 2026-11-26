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


def test_pending_payment_ticket_still_reserves_the_payable_balance(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Reserved Payment Site','budget':'100000'}).json()['id']
    d=write(admin,'post','/api/chat',{'message':'Log expense 2000 for Fictional Transit Contractor at Fictional Reserved Payment Site, paid by UPI.'}).json()
    assert write(admin,'post',f'/api/tickets/{d["ticket_id"]}/approve-and-save',{}).status_code==200
    cost=admin.get('/api/costs').json()[0]['id']
    first=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert first.status_code==200,first.text
    assert first.json().get('ticket_id'),first.text
    assert admin.get('/api/costs').json()[0]['payment_pending']==1500
    too_much=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1000','idempotency_key':'fictional-reserved-payment-02'})
    assert too_much.status_code in (400,409,422),too_much.text
    same=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert same.status_code==200 and same.json()['ticket_id']==first.json()['ticket_id']
    saved=write(admin,'post',f'/api/tickets/{first.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    again=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert again.status_code==200,again.text
    assert len(admin.get('/api/payments').json())==1


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
