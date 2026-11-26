"""v0.23.1: a double tap or a retry of the same form gives back the first ticket
instead of opening a second one. Fictional data only."""
from sqlalchemy import select, func
from studioos.chart_of_accounts import local_today
from studioos.db import SessionLocal, ApprovalTicket
from .conftest import write, approved_form
from .test_finance_expense import expense_data
from .test_v098_universal_accounting import finance_setup


def _tickets():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(ApprovalTicket))


def _project(admin):
    return approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Twice Site', 'budget': '100000'}).json()['id']


def _expense_form(admin, request_key):
    company_id = finance_setup(admin)
    data = expense_data(admin, company_id, project_id=_project(admin), note='Fictional transport', amount_paise=120000,
                        date=local_today().isoformat(), request_key=request_key)
    return {'kind': 'finance_expense', 'data': data, 'evidence': 'Fictional expense form submission'}


def test_books_expense_form_sent_twice_opens_one_ticket(admin):
    body = _expense_form(admin, 'form-cost-0001-abcd')
    before = _tickets()
    a = write(admin, 'post', '/api/universal/proposals', body)
    b = write(admin, 'post', '/api/universal/proposals', body)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()['ticket_id'] == b.json()['ticket_id']
    assert _tickets() == before + 1


def test_new_form_key_still_opens_a_new_ticket(admin):
    body = _expense_form(admin, 'form-cost-0002-abcd')
    new_request = {**body, 'data': {**body['data'], 'request_key': 'form-cost-0003-abcd'}}
    before = _tickets()
    a = write(admin, 'post', '/api/universal/proposals', body)
    b = write(admin, 'post', '/api/universal/proposals', new_request)
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()['ticket_id'] != b.json()['ticket_id']
    assert _tickets() == before + 2


def test_task_and_site_report_forms_sent_twice_open_one_ticket(admin):
    pid = _project(admin)
    before = _tickets()
    task = {'project_id': pid, 'title': 'Fictional shutters', 'request_key': 'form-task-0001-abcd'}
    site = {'project_id': pid, 'note': 'Fictional slab poured', 'request_key': 'form-site-0001-abcd'}
    for url, body in (('/api/tasks', task), ('/api/site-reports', site)):
        a = write(admin, 'post', url, body); b = write(admin, 'post', url, body)
        assert a.status_code == b.status_code == 200, (a.text, b.text)
        assert a.json()['ticket_id'] == b.json()['ticket_id']
    assert _tickets() == before + 2


def test_same_key_cannot_be_reused_for_a_different_form_kind(admin):
    pid = _project(admin)
    key = 'form-shared-0001-abcd'
    a = write(admin, 'post', '/api/tasks', {'project_id': pid, 'title': 'Fictional shutters', 'request_key': key})
    b = write(admin, 'post', '/api/site-reports', {'project_id': pid, 'note': 'Fictional slab poured', 'request_key': key})
    assert a.json()['ticket_id'] != b.json()['ticket_id']


def test_asking_twice_to_complete_a_task_gives_the_same_waiting_ticket(admin):
    pid = _project(admin)
    t = approved_form(admin, 'post', '/api/tasks', {'project_id': pid, 'title': 'Fictional plaster'}).json()
    task_id = admin.get('/api/tasks').json()[0]['id']
    a = write(admin, 'patch', f'/api/tasks/{task_id}/complete'); b = write(admin, 'patch', f'/api/tasks/{task_id}/complete')
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()['ticket_id'] == b.json()['ticket_id']


def test_payment_form_keeps_one_key_per_opened_form():
    js = open('studioos/static/app.js').read()
    assert "values.idempotency_key=crypto.randomUUID()" not in js   # a new key per tap defeated the duplicate check
    assert 'formRequestKey' in js


def test_save_button_is_disabled_while_saving():
    js = open('studioos/static/app.js').read()
    assert "saveButton.disabled=true" in js


def test_review_screen_hides_the_request_key():
    js = open('studioos/static/app.js').read()
    assert "k!=='idempotency_key'" in js
