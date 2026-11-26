"""v66: the create forms inside the chat. A sentence makes a draft that shows the whole form (required fields first, the right
control for each), the blanks are filled in on the card or by chatting, and nothing is saved until the draft is approved."""
from datetime import date

import pytest
from sqlalchemy import select

from studioos import chat_forms
from studioos.db import ApprovalTicketItem, FinanceExpense, SessionLocal
from tests.conftest import write
from tests.test_v0914_chart_of_accounts import approve, books, chat
from tests.test_v098_universal_accounting import save, vendor


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')


@pytest.fixture
def company(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')      # the shared helper creates a bare project
    ids = books(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    return ids


def fields(reply, index=0):
    return {f['key']: f for f in reply['preview']['items'][index]['fields']}


def test_dates_are_read_the_way_people_say_them():
    today = date(2026, 11, 25)
    assert chat_forms.parse_date('5 December', today) == '2026-12-05'
    assert chat_forms.parse_date('Dec 5th, 2027', today) == '2027-12-05'
    assert chat_forms.parse_date('05/12/2026', today) == '2026-12-05'          # day first, as in India
    assert chat_forms.parse_date('2026-12-05', today) == '2026-12-05'
    assert chat_forms.parse_date('tomorrow', today) == '2026-11-26'
    assert chat_forms.parse_date('5 January', today) == '2027-01-05'            # said in November: next January
    assert chat_forms.parse_date('friday', today) == '2026-11-27'
    assert chat_forms.parse_date('sometime', today) is None
    assert chat_forms.parse_date('31 February', today) is None


def test_a_project_sentence_keeps_the_name_and_the_client_and_shows_the_whole_form(admin):
    r = chat(admin, 'create a project named Villa 21 client name Srinu')
    f = fields(r)
    assert f['name']['raw'] == 'Villa 21' and f['client']['raw'] == 'Srinu'
    order = list(f)
    assert order.index('manager') < order.index('project_code')                    # required first, optional after
    assert f['manager']['required'] and f['start_date']['required'] and not f['project_code']['required']
    assert f['start_date']['type'] == 'date' and f['stage']['type'] == 'select' and f['manager']['choices']
    assert f['stage']['raw'] == 'Planning'                                           # a form fills in its own default
    item = r['preview']['items'][0]
    assert any('MISSING required' in x and 'Project manager' in x and 'Start date' in x for x in item['flags'])


def test_budget_location_and_start_are_taken_from_the_first_sentence(admin):
    r = chat(admin, 'Create project Villa 23 for client Ravi budget 15 lakh location Gachibowli manager admin starting 5 December 2027')
    after = r['preview']['items'][0]['after']
    assert (after['name'], after['client'], after['amount_paise'], after['location'], after['start_date']) == (
        'Villa 23', 'Ravi', 150_000_000, 'Gachibowli', '2027-12-05')


def test_chatting_changes_any_field_of_the_open_draft(admin):
    first = chat(admin, 'create a project named Villa 24 client name Srinu')
    sid = first['session_id']
    r = chat(admin, 'start date 5 December 2027, manager admin, status Design', sid)
    assert 'Start date' in r['reply'] and 'Project manager' in r['reply']          # "start" is not "start a new project"
    f = fields(r)
    assert f['start_date']['raw'] == '2027-12-05' and f['stage']['raw'] == 'Design' and f['manager']['raw'] == 'StudioOS Administrator'
    r = chat(admin, 'location is Jubilee Hills and budget 20 lakh and project type Residential', sid)
    after = r['preview']['items'][0]['after']
    assert (after['location'], after['amount_paise'], after['project_type']) == ('Jubilee Hills', 200_000_000, 'Residential')
    assert not any('MISSING required' in x for x in r['preview']['items'][0]['flags'])
    audit = admin.get(f"/api/tickets/{first['ticket_id']}").json()
    assert 'Start date' in str(audit)                                               # the change is in the ticket's history


def test_a_value_that_cannot_be_read_is_explained_and_nothing_changes(admin):
    sid = chat(admin, 'create a project named Villa 25 client name Srinu')['session_id']
    r = chat(admin, 'start date sometime', sid)
    assert 'couldn’t read' in r['reply'] and fields(r)['start_date']['raw'] is None
    r = chat(admin, 'status is flying', sid)
    assert 'Choose Status from' in r['reply'] and 'Planning' in r['reply']
    r = chat(admin, 'project manager nobody', sid)
    assert 'Choose Project manager from' in r['reply']


def test_a_new_request_while_a_draft_is_open_is_not_taken_for_an_edit(admin):
    first = chat(admin, 'create a project named Villa 26 client name Srinu')
    second = chat(admin, 'Create project Villa 27 for client Ravi', first['session_id'])
    names = [i['after'].get('name') for i in second['preview']['items']]
    assert 'Villa 27' in names and 'Villa 26' in names


def test_a_task_form_has_owner_due_date_and_priority_with_a_default(admin, company):
    r = chat(admin, 'Add task Issue drawings for Fictional Project A due 2026-12-05 assigned to admin')
    f = fields(r)
    assert f['assignee']['raw'] == 'admin' or f['assignee']['raw'] == 'StudioOS Administrator'
    assert f['due_date']['raw'] == '2026-12-05' and f['priority']['raw'] == 'Medium' and f['priority']['type'] == 'select'


def test_books_expense_in_chat_becomes_a_form_not_a_redirect(admin, company):
    pid, entity = company
    vendor(admin)
    r = chat(admin, 'Record expense Rs 4500 for sand on Fictional Project A paid by cash')
    assert 'started the expense' in r['reply']
    item = r['preview']['items'][0]
    assert item['item_type'] == 'finance_expense'
    f = fields(r)
    assert f['amount_paise']['raw'] == 450_000 and f['paid_through_id']['display'] == 'Cash in Hand'
    assert f['vendor_id']['required'] and f['vendor_id']['raw'] is None and f['vendor_id']['choices']
    assert f['expense_account_id']['choices'] and all(' · ' in c['label'] for c in f['expense_account_id']['choices'][:3])
    assert f['billable']['type'] == 'boolean' and not f['billable']['required']
    assert any('MISSING required' in x and 'Vendor' in x for x in item['flags'])
    approve = write(admin, 'post', f"/api/tickets/items/{item['id']}/approve")
    assert approve.status_code == 422 and 'vendor' in approve.text.lower()          # an unfinished expense cannot be approved


def test_the_unfinished_expense_is_saved_piece_by_piece_then_finished_by_chat_and_posted(admin, company):
    pid, entity = company
    vendor_id = vendor(admin)
    r = chat(admin, 'Record expense Rs 4500 for sand on Fictional Project A paid by cash')
    sid, item = r['session_id'], r['preview']['items'][0]
    choices = {c['label']: c['value'] for c in fields(r)['vendor_id']['choices']}
    name = next(iter(choices))
    # one field at a time, as the card's form or a tap does
    step = write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': {**item['after'], 'vendor_id': choices[name]}, 'note': ''})
    assert step.status_code == 200, step.text
    r = chat(admin, 'invoice number SAND-77 and notes sand for the site wall', sid)
    after = r['preview']['items'][0]['after']
    assert after['reference_number'] == 'SAND-77' and after['note'] == 'sand for the site wall'
    f = fields(r)
    if f['expense_account_id']['raw'] is None:
        label = f['expense_account_id']['choices'][0]['label']
        r = chat(admin, 'expense account ' + label.split(' · ', 1)[-1], sid)
    assert not any('MISSING required' in x for x in r['preview']['items'][0]['flags']), r['preview']['items'][0]['flags']
    done = approve(admin, r)
    assert done.status_code == 200, done.text
    saved = done.json()['committed_records'][0]
    with SessionLocal() as db:
        e = db.get(FinanceExpense, saved['id'])
        assert (e.amount_paise, e.reference_number, e.vendor_id) == (450_000, 'SAND-77', choices[name])


def test_billable_and_not_billable_are_understood(admin, company):
    vendor(admin)
    sid = chat(admin, 'Record expense Rs 100 for tea paid by cash')['session_id']
    r = chat(admin, 'billable', sid)
    assert fields(r)['billable']['raw'] is True
    r = chat(admin, 'not billable', sid)
    assert fields(r)['billable']['raw'] is False


def test_the_card_script_marks_required_fields_folds_the_optional_and_routes_edits_to_the_draft():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    chat_js = (static / 'chat.js').read_text(encoding='utf-8')
    for text in ('required details to fill in', 'More details (optional)', 'cxLooksLikeEdit', "f.marker === 'missing' && f.required === false",
                 'MISSING required:'):
        assert text in chat_js, text
    assert 'cxLooksLikeEdit(text)' in (static / 'views.js').read_text(encoding='utf-8')
