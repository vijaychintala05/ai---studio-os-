"""v67: purchase orders and payments of supplier bills, started from a sentence in the chat. The card is the form (required fields
first, the right control for each), the blanks are filled on the card or by chatting, and nothing posts until it is approved."""
import pytest
from sqlalchemy import select

from studioos.db import (FinanceDirectBill, FinanceDirectBillPayment, FinancePurchaseOrder, GLAccount, SessionLocal)
from tests.conftest import write
from tests.test_v0914_chart_of_accounts import approve, books, chat
from tests.test_v098_universal_accounting import propose, save, vendor

VENDOR = 'ABC Fictional Suppliers'


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')


@pytest.fixture
def company(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')      # the shared helper creates a bare project
    pid, entity = books(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    vendor(admin)
    return pid, entity


def fields(reply, index=0):
    return {f['key']: f for f in reply['preview']['items'][index]['fields']}


def post_direct_bill(admin, entity, pid, amount=500_000):
    with SessionLocal() as db:
        supplier = db.scalar(select(GLAccount).where(GLAccount.entity_id == entity, GLAccount.kind == 'expense', GLAccount.posting_allowed.is_(True)))
        from studioos.db import Party
        vendor_id = db.scalar(select(Party.id).where(Party.name == VENDOR))
        account_id = supplier.id
    r = write(admin, 'post', '/api/books/bills', {
        'entity_id': entity, 'supplier_id': vendor_id, 'invoice_number': 'FICT-INV-9', 'bill_date': '2026-11-10', 'due_date': '2026-12-10',
        'payment_terms_days': 30, 'amount_paise': amount,
        'lines': [{'account_id': account_id, 'project_id': pid, 'description': 'Tiles', 'amount_paise': amount}]})
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200


# ------------------------------------------------------------------ purchase orders

def test_a_purchase_order_sentence_gives_the_po_form(admin, company):
    pid, entity = company
    r = chat(admin, f'Raise a purchase order for {VENDOR} for Fictional Project A, 21000')
    assert 'started the purchase order' in r['reply']
    item = r['preview']['items'][0]
    assert item['item_type'] == 'finance_po'
    f = fields(r)
    assert f['supplier_id']['raw'] and f['supplier_id']['display'] == VENDOR
    assert f['project_id']['raw'] == pid and f['po_number']['raw'] == 'PO-0001' and f['amount_paise']['raw'] == 2_100_000
    assert all(f[k]['required'] for k in ('supplier_id', 'project_id', 'po_number', 'amount_paise'))
    assert 'entity_id' not in f                                                     # plumbing, not a field to fill in
    assert not any('MISSING required' in x for x in item['flags'])


def test_an_unfinished_po_is_finished_by_chat_and_then_approved(admin, company):
    pid, entity = company
    r = chat(admin, 'Raise a purchase order for Fictional Project A')
    item = r['preview']['items'][0]
    assert any('MISSING required' in x and 'Vendor' in x and 'Order amount' in x for x in item['flags'])
    assert write(admin, 'post', f"/api/tickets/items/{item['id']}/approve").status_code == 422
    r = chat(admin, f'vendor {VENDOR}, po number PO-777 and amount 25000', r['session_id'])
    after = r['preview']['items'][0]['after']
    assert (after['po_number'], after['amount_paise']) == ('PO-777', 2_500_000) and after['supplier_id']
    done = approve(admin, r)
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        po = db.scalar(select(FinancePurchaseOrder).where(FinancePurchaseOrder.po_number == 'PO-777'))
        assert po is not None and po.amount_paise == 2_500_000 and po.project_id == pid


def test_po_numbers_count_up_and_a_typed_number_is_used(admin, company):
    first = chat(admin, f'Raise a purchase order for {VENDOR} for Fictional Project A, 1000')
    assert fields(first)['po_number']['raw'] == 'PO-0001'
    typed = chat(admin, f'New PO number PO-2026-5 for {VENDOR} for Fictional Project A, 1000')
    assert fields(typed)['po_number']['raw'] == 'PO-2026-5'


# ------------------------------------------------------------------ payments of supplier bills

def test_a_payment_sentence_gives_the_payment_form_for_the_vendors_unpaid_bill(admin, company):
    pid, entity = company
    post_direct_bill(admin, entity, pid)
    r = chat(admin, f'Paid 2000 to {VENDOR} by bank transfer reference UTR55')
    assert 'started the payment' in r['reply']
    item = r['preview']['items'][0]
    assert item['item_type'] == 'finance_direct_bill_payment'
    f = fields(r)
    assert f['bill_id']['raw'] and 'FICT-INV-9' in f['bill_id']['display'] and 'owes ₹5,000.00' in f['bill_id']['display']
    assert f['amount_paise']['raw'] == 200_000 and f['payment_reference']['raw'] == 'UTR55'
    assert f['payment_date']['type'] == 'date' and f['paid_through_id']['required'] and f['paid_through_id']['choices']
    assert 'idempotency_key' not in f


def test_the_payment_is_finished_by_chat_and_posts_against_the_bill(admin, company):
    pid, entity = company
    post_direct_bill(admin, entity, pid)
    r = chat(admin, f'Pay {VENDOR} 2000 reference UTR56')
    assert any('Paid Through' in x for x in r['preview']['items'][0]['flags'])
    assert write(admin, 'post', f"/api/tickets/items/{r['preview']['items'][0]['id']}/approve").status_code == 422
    label = fields(r)['paid_through_id']['choices'][0]['label']
    r = chat(admin, f'paid through {label}', r['session_id'])
    assert not any('MISSING required' in x for x in r['preview']['items'][0]['flags']), r['preview']['items'][0]['flags']
    done = approve(admin, r)
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        pay = db.scalar(select(FinanceDirectBillPayment))
        assert pay is not None and (pay.amount_paise, pay.payment_reference) == (200_000, 'UTR56')


def test_a_payment_with_no_unpaid_bill_is_left_to_the_older_typed_route(admin, company):
    r = chat(admin, f'Paid 3000 to {VENDOR} by cash')
    assert not any(i['item_type'] in ('finance_payment', 'finance_direct_bill_payment') for i in (r.get('preview') or {}).get('items', []))


def test_the_older_project_payment_asks_which_cost_it_pays(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')
    from tests.test_v098_universal_accounting import project
    pid = project(admin)
    cost = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional survey', 'amount': '10000'}).json()
    from tests.conftest import approved_form
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    approve_cost = write(admin, 'post', f"/api/tickets/{cost['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'})
    assert approve_cost.status_code in (200, 409, 422)
    from studioos import chat_forms
    with SessionLocal() as db:
        from studioos.db import User
        spec = next((s for s in chat_forms.specs_for(db, db.query(User).first(), 'record_payment', {}) if s['key'] == 'cost_id'), None)
        assert spec is not None and spec['type'] == 'select' and spec['required']


def test_before_a_company_exists_a_purchase_order_in_chat_is_the_project_trackers_order_form(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')
    from tests.test_v098_universal_accounting import project
    project(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    r = chat(admin, 'Ordered 50 sheets of marine plywood for Fictional Project A for ₹90,000')
    item = r['preview']['items'][0]
    assert item['item_type'] == 'record_cost' and item['after']['kind'] == 'commitment'
    f = fields(r)
    assert f['vendor']['required'] and f['date']['type'] == 'date' and f['amount_paise']['raw'] == 9_000_000
    assert not f['reference_number']['required']                                       # the PO number is optional, as in Zoho Books
    assert any('MISSING required' in x and 'Vendor' in x for x in item['flags'])
