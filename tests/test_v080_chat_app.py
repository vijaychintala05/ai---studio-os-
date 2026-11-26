"""v0.8.0 chat endpoints: natural replies, tap-to-answer, one-step approve and save,
conversation history. Fictional data only."""
import re
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select
from .conftest import write, approved_form
from .test_v098_universal_accounting import finance_setup, vendor
from studioos.main import app
from studioos.db import SessionLocal, FinanceExpense, GLJournal, Task, ApprovalTicket, ApprovalTicketItem, ChatMessage

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def chat(c, msg, sid=''):
    r = write(c, 'post', '/api/chat', {'message': msg, 'session_id': sid})
    assert r.status_code == 200, r.text
    return r.json()


def expense(admin, project='Chat Villa'):
    finance_setup(admin)
    assert approved_form(admin,'post','/api/projects', {'name': project, 'budget': '500000'}).status_code == 200
    vendor(admin)
    return chat(admin, f'Log expense 3,200 for ABC Fictional Suppliers at {project}, paid by cash.')


def test_draft_reply_is_natural_and_card_shows_rupees(admin):
    r = expense(admin)
    assert r['reply'].startswith("I've drafted this") and '₹3,200' in r['reply']
    item = r['preview']['items'][0]
    amount = next(f for f in item['fields'] if f['key'] == 'amount_paise')
    assert amount['display'] == '₹3,200' and amount['label'] == 'Amount'
    assert r['preview']['can_approve'] is True and isinstance(r['ask'], list)
    with SessionLocal() as db:
        stored = db.scalars(select(ChatMessage).where(ChatMessage.speaker == 'assistant').order_by(ChatMessage.id)).all()[-1]
        assert stored.content.startswith("I've drafted this")   # history shows the same words


def test_plain_question_has_no_card(admin):
    r = chat(admin, 'show tasks')
    assert 'preview' not in r and r['ask'] == []


def test_ambiguous_project_asks_with_buttons_and_answer_fills_it(admin):
    for name in ('Sharma Residence', 'Sharma Showroom'):
        assert approved_form(admin,'post','/api/projects', {'name': name, 'budget': '100000'}).status_code == 200
    r = chat(admin, 'Ask Anil to finish bathroom plumbing rough-in at Sharma by next Friday.')
    ask = next(a for a in r['ask'] if a['id'] == 'project')
    assert [c['value'] for c in ask['choices']] == ['Sharma Residence', 'Sharma Showroom'] and ask['field'] == 'project'
    a = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': ask['item_id'],
                                                 'field': 'project', 'value': 'Sharma Residence', 'label': 'Sharma Residence'})
    assert a.status_code == 200, a.text
    item = a.json()['preview']['items'][0]
    assert item['after']['project'] == 'Sharma Residence'
    assert next(f for f in item['fields'] if f['key'] == 'project')['marker'] == 'answered'
    with SessionLocal() as db:
        assert db.scalars(select(Task)).all() == []   # still only a draft


def test_answers_are_validated_and_owned(admin):
    r = expense(admin)
    item_id = r['preview']['items'][0]['id']
    bad = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item_id, 'field': 'amount_paise', 'value': 'maybe'})
    assert bad.status_code == 422
    wrong_field = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item_id, 'field': 'phone', 'value': '9800000011'})
    assert wrong_field.status_code == 422
    ok = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item_id, 'field': 'amount_paise', 'value': 337000, 'label': '₹3,370'})
    assert ok.status_code == 200 and ok.json()['preview']['items'][0]['after']['amount_paise'] == 337000
    write(admin, 'post', '/api/users', {'username': 'acc01', 'display_name': 'Accounts', 'role': 'accounts', 'password': 'fictional-accounts-p1'})
    other = TestClient(app)
    assert other.post('/api/auth/login', json={'username': 'acc01', 'password': 'fictional-accounts-p1'}).status_code == 200
    stolen = write(other, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item_id, 'field': 'amount_paise', 'value': 1})
    assert stolen.status_code == 404


def test_approve_and_save_in_one_step(admin):
    r = expense(admin)
    s = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {})
    assert s.status_code == 200, s.text
    assert s.json()['status'] == 'committed'
    with SessionLocal() as db:
        cost = db.scalars(select(FinanceExpense)).one()
        assert cost.amount_paise == 320000 and db.get(GLJournal, cost.journal_id).ticket_id == r['ticket_id']
        assert db.get(ApprovalTicket, r['ticket_id']).status == 'committed'
    h = admin.get('/api/chat/history/' + r['session_id']).json()
    assert h['card']['status'] == 'committed' and h['card']['can_approve'] is False
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 409


def test_possible_duplicate_needs_an_explicit_confirmation(admin):
    finance_setup(admin)
    vendor(admin)
    assert approved_form(admin,'post','/api/projects', {'name': 'Duplicate Residence', 'budget': '300000'}).status_code == 200
    message = 'Paid 12,500 cash to ABC Fictional Suppliers for wiring material at Duplicate Residence today.'
    old = chat(admin, message)
    approved = write(admin, 'post', f"/api/tickets/{old['ticket_id']}/approve-and-save", {'confirmed': ['amount']})
    assert approved.status_code == 200, approved.text
    r = chat(admin, message)
    assert 'duplicate' in r['preview']['items'][0]['needs_confirmation']
    first = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {})
    assert first.status_code == 409 and first.json()['needs_confirmation'] == 'duplicate'
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id'])).one().status == 'pending'   # nothing half-approved
        assert len(db.scalars(select(FinanceExpense)).all()) == 1
    ok = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {'confirmed': ['duplicate']})
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        assert 'duplicate reviewed' in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id'])).one().review_note


def test_staff_see_waiting_and_cannot_self_approve_money(admin):
    finance_setup(admin)
    vendor(admin)
    assert approved_form(admin,'post','/api/projects', {'name': 'Manager Villa', 'budget': '300000'}).status_code == 200
    assert write(admin, 'put', '/api/approval-limits', {'manager_per_transaction_paise': 500000}).status_code == 200
    write(admin, 'post', '/api/users', {'username': 'mgr01', 'display_name': 'Manager', 'role': 'manager', 'password': 'fictional-manager-p1'})
    m = TestClient(app)
    assert m.post('/api/auth/login', json={'username': 'mgr01', 'password': 'fictional-manager-p1'}).status_code == 200
    r = chat(m, 'Log expense 2,100 for ABC Fictional Suppliers at Manager Villa, paid by cash.')
    assert r['preview']['can_approve'] is False and 'someone else' in r['preview']['reason']
    assert write(m, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 403
    with SessionLocal() as db:
        assert db.scalars(select(FinanceExpense)).all() == []


def test_failed_save_rolls_back_the_approval_too(admin, monkeypatch):
    import studioos.main as main
    r = expense(admin)
    monkeypatch.setattr(main, 'apply_item', lambda *a, **k: (_ for _ in ()).throw(ValueError('Injected failure')))
    s = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {})
    assert s.status_code == 409
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id'])).one().status == 'pending'
        assert db.scalars(select(FinanceExpense)).all() == []


def test_conversation_history_lists_only_your_chats(admin):
    first = expense(admin, 'History Villa')
    second = chat(admin, 'show tasks')
    rows = admin.get('/api/chat/sessions').json()
    assert [x['id'] for x in rows][:2] == [second['session_id'], first['session_id']]
    assert rows[1]['title'].startswith('Log expense') and rows[1]['ticket_id'] == first['ticket_id']
    write(admin, 'post', '/api/users', {'username': 'arch05', 'display_name': 'Architect', 'role': 'architect', 'password': 'fictional-architect-5'})
    other = TestClient(app)
    assert other.post('/api/auth/login', json={'username': 'arch05', 'password': 'fictional-architect-5'}).status_code == 200
    assert other.get('/api/chat/sessions').json() == []
    assert other.get('/api/chat/history/' + first['session_id']).status_code == 404


def test_chat_is_the_landing_page_and_loads_safely(client):
    html = (STATIC / 'index.html').read_text()
    assert '<script src="/static/chat.js"></script>' in html
    app = (STATIC / 'app.js').read_text()
    assert "||'assistant'" in app.split('function homeViewFor')[1].split('\n')[0]       # owners and managers still land on the chat
    assert 'data-view="assistant"' in html and 'id="askBtn"' in html                    # and the Ask button is always one click away
    js = (STATIC / 'chat.js').read_text()
    assert "view: 'assistant'" in js and 'style="' not in js
    assert not re.search(r'\son[a-z]+="', js)
    assert 'microphone=(self)' in client.get('/').headers['permissions-policy']
