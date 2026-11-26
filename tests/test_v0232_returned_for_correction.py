"""Owner decision 8: a reviewer can send an item back "for correction" with a reason; the submitter fixes and sends it again.
Fictional data only."""
import pytest
from fastapi.testclient import TestClient
from studioos.db import Party, SessionLocal
from studioos.main import app
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_v098_universal_accounting import finance_setup


def login(name, pw):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': name, 'password': pw}).status_code == 200
    return c


@pytest.fixture
def setup(admin):
    finance_setup(admin)
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Return Site', 'budget': '10000000'}).json()['id']
    write(admin, 'post', '/api/users', {'username': 'ret_acc', 'display_name': 'Fictional Accounts', 'role': 'accounts', 'password': 'fictional-accounts-ret-1'})
    acc = login('ret_acc', 'fictional-accounts-ret-1')
    r = draft_project_expense(acc, pid, 120000, note='Fictional tiles')
    assert r.status_code == 200, r.text
    return pid, acc, r.json()['ticket_id'], r.json()['item_id']


def item_status(c, ticket_id, item_id):
    t = c.get(f'/api/tickets/{ticket_id}').json()
    return next(i for i in t['items'] if i['id'] == item_id)


def test_reviewer_returns_an_item_with_a_reason(admin, setup):
    pid, acc, ticket, item = setup
    r = write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': 'Please add the bill number'})
    assert r.status_code == 200, r.text
    got = item_status(admin, ticket, item)
    assert got['status'] == 'returned' and 'bill number' in got['note']


def test_a_reason_is_required(admin, setup):
    pid, acc, ticket, item = setup
    assert write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': ''}).status_code == 400
    assert item_status(admin, ticket, item)['status'] == 'pending'


def test_the_submitter_cannot_return_their_own_item_or_anyone_unauthorised(admin, setup):
    pid, acc, ticket, item = setup
    assert write(acc, 'post', f'/api/tickets/items/{item}/return', {'note': 'Please add the bill number'}).status_code == 403


def test_a_returned_item_cannot_be_approved_until_it_is_sent_again(admin, setup):
    pid, acc, ticket, item = setup
    write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': 'Please add the bill number'})
    assert write(admin, 'post', f'/api/tickets/{ticket}/approve-and-save', {}).status_code in (409, 422)
    assert write(admin, 'post', f'/api/tickets/items/{item}/approve', {}).status_code in (409, 422)


def test_submitter_sends_it_again_unchanged_and_it_can_then_be_approved(admin, setup):
    pid, acc, ticket, item = setup
    write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': 'Please add the bill number'})
    assert write(acc, 'post', f'/api/tickets/items/{item}/resubmit', {}).status_code == 200
    assert item_status(admin, ticket, item)['status'] == 'pending'
    assert write(admin, 'post', f'/api/tickets/{ticket}/approve-and-save', {}).status_code == 200


def test_submitter_can_fix_the_item_which_sends_it_again(admin, setup):
    pid, acc, ticket, item = setup
    write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': 'Wrong vendor'})
    after = item_status(admin, ticket, item)['after']
    with SessionLocal() as db:
        supplier = Party(kind='vendor', name='Fictional Ceramics Ltd')
        db.add(supplier)
        db.flush()
        after['vendor_id'] = supplier.id
        db.commit()
    r = write(acc, 'patch', f'/api/tickets/items/{item}', {'after': after, 'note': 'Fixed the vendor'})
    assert r.status_code == 200, r.text
    updated = item_status(admin, ticket, item)
    assert updated['status'] == 'pending' and updated['after']['vendor_id'] == after['vendor_id']


def test_only_a_returned_item_can_be_sent_again(admin, setup):
    pid, acc, ticket, item = setup
    assert write(acc, 'post', f'/api/tickets/items/{item}/resubmit', {}).status_code == 409


def test_somebody_else_cannot_resubmit_for_the_submitter(admin, setup):
    pid, acc, ticket, item = setup
    write(admin, 'post', f'/api/tickets/items/{item}/return', {'note': 'Please add the bill number'})
    write(admin, 'post', '/api/users', {'username': 'ret_other', 'display_name': 'Fictional Other', 'role': 'accounts', 'password': 'fictional-accounts-ret-2'})
    other = login('ret_other', 'fictional-accounts-ret-2')
    assert write(other, 'post', f'/api/tickets/items/{item}/resubmit', {}).status_code in (403, 404)


def test_screens_show_plain_words_and_the_buttons():
    import pathlib
    js = pathlib.Path('studioos/static/app.js').read_text()
    assert "returned:'Returned for correction'" in js
    assert 'data-action="return-item"' in js and 'data-action="resubmit-item"' in js
