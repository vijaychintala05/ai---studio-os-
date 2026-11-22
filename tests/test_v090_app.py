"""v0.9.0 end to end: decision lines and the saving point in the conversation,
tamper-evident history, building a record type from a waiting request, the
waiting-area check, and records of a built type through the chat.
Fictional data only. Needs FastAPI and SQLAlchemy: python -m pytest -q"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from .conftest import approved_undo, write, approved_form
from studioos.main import app
from studioos.db import (SessionLocal, ChatMessage, Audit, ApprovalTicket, ApprovalTicketItem, FlexibleRecord,
                         RecordType, NewTypeInbox)

REQUEST = 'Record client site-visit feedback: date, who attended, rating out of 5, comments'
ENTRY = ('Client site visit feedback for Mehta Villa: visited yesterday, rating 4/5, '
         'attended by Ravi and client. Comments: liked the kitchen')


def chat(c, msg, sid=''):
    r = write(c, 'post', '/api/chat', {'message': msg, 'session_id': sid})
    assert r.status_code == 200, r.text
    return r.json()


def project(c, name='Mehta Villa'):
    assert approved_form(c,'post','/api/projects', {'name': name, 'budget': '500000'}).status_code == 200


def build_type(admin):
    """Park a request, add one real entry to its waiting list, approve the build."""
    first = chat(admin, REQUEST)
    rid = first['holding_item']['id']
    assert first['build_request']['request_id'] == rid and first['build_request']['state'] == 'waiting_for_approval'
    entry = write(admin, 'post', '/api/new-types/intake', {'text': ENTRY}).json()['holding_item']
    assert entry['state'] == 'reuse_existing_proposal'
    answers = {'purpose': 'Track how clients feel after site visits', 'required_fields': 'approve: visit date, rating'}
    assert write(admin, 'post', f'/api/new-types/{rid}/answers', {'answers': answers}).status_code == 200
    approved = write(admin, 'post', f'/api/new-types/{rid}/approve-structure', {'note': 'ok'})
    assert approved.status_code == 200, approved.text
    return rid, first['session_id'], approved.json()


# ------------------------------------------------------------- conversation record

def test_save_writes_decision_lines_and_freezes_the_conversation(admin):
    project(admin, 'Chat Villa')
    r = chat(admin, 'Log expense 3,200 for Anil Plumbing at Chat Villa, paid by UPI.')
    item = r['preview']['items'][0]
    edit = write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': {**item['after'], 'amount_paise': 300000}})
    assert edit.status_code == 200, edit.text
    fingerprints = {i['id']: i['review_fingerprint'] for i in edit.json()['items']}
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save",
                 {'review_fingerprints': fingerprints}).status_code == 200
    later = chat(admin, 'show tasks', r['session_id'])
    t = admin.get(f"/api/tickets/{r['ticket_id']}").json()
    lines = [m['text'] for m in t['conversation'] if m['decision']]
    assert any('Amount: ₹3,200 → ₹3,000' in x for x in lines)
    assert any(' approved the expense' in x for x in lines)
    assert any(' saved 1 record' in x for x in lines)
    saved = next(m for m in t['conversation'] if m['decision'] and ' saved ' in m['text'])
    assert t['committed_through_message_id'] == saved['id'] and not saved['after_saving']
    assert all(m['after_saving'] for m in t['conversation'] if m['id'] > saved['id'])
    assert any(m['text'] == 'show tasks' and m['after_saving'] for m in t['conversation'])
    h = admin.get('/api/chat/history/' + r['session_id']).json()
    assert any(m['speaker'] == 'system' for m in h['messages']) and later['session_id'] == r['session_id']


def test_reject_and_undo_are_recorded(admin):
    project(admin, 'Undo Villa')
    r = chat(admin, 'Log expense 2,000 for Anil Plumbing at Undo Villa, paid by UPI.')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    assert approved_undo(admin,r['ticket_id'],'Entered twice by mistake').status_code == 200
    t = admin.get(f"/api/tickets/{r['ticket_id']}").json()
    assert any('undid this save: Entered twice by mistake' in m['text'] for m in t['conversation'] if m['decision'])


# ------------------------------------------------------------- tamper evidence

def test_every_message_and_audit_entry_is_fingerprinted_and_verified(admin):
    project(admin, 'Chain Villa')
    chat(admin, 'Log expense 1,500 for Anil Plumbing at Chain Villa, paid by UPI.')
    with SessionLocal() as db:
        assert db.scalars(select(ChatMessage).where(ChatMessage.chain_hash.is_(None))).all() == []
        assert db.scalars(select(Audit).where(Audit.chain_hash.is_(None))).all() == []
    r = admin.get('/api/system/integrity').json()
    assert r['overall'] == 'ok', r
    assert {t['table'] for t in r['tables']} == {'chat_messages', 'audit_events'}


def test_history_cannot_be_edited_through_the_app(admin):
    chat(admin, 'show tasks')
    with SessionLocal() as db:
        m = db.scalars(select(ChatMessage)).first()
        m.content = 'rewritten'
        with pytest.raises(PermissionError):
            db.commit()
        db.rollback()
        with pytest.raises(PermissionError):
            db.delete(db.scalars(select(Audit)).first()); db.commit()


def test_a_change_made_outside_the_app_is_detected(admin):
    chat(admin, 'show tasks')
    with SessionLocal() as db:
        first = db.scalars(select(ChatMessage).order_by(ChatMessage.id)).first().id
        db.execute(text('UPDATE chat_messages SET content = :c WHERE id = :i'), {'c': 'edited directly', 'i': first})
        db.commit()
    r = admin.get('/api/system/integrity').json()
    assert r['overall'] == 'fail'
    assert next(t for t in r['tables'] if t['table'] == 'chat_messages')['first_broken_id'] == first


# ------------------------------------------------------------- record types and waiting area

def test_approving_a_build_creates_a_record_type_and_drafts_waiting_entries(admin):
    project(admin)
    rid, sid, approved = build_type(admin)
    assert approved['record_type'] == 'client_site_visit_feedback'
    check = approved['waiting_check'][0]
    assert check['drafted'] == 1 and check['ready'] == 1   # the description itself holds no values
    with SessionLocal() as db:
        rt = db.get(RecordType, 'client_site_visit_feedback')
        assert rt.status == 'active' and rt.source_inbox_id == rid
        assert db.scalars(select(FlexibleRecord)).all() == []   # drafted, not saved
        item = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == check['ticket_id'])).one()
        assert item.after_data['data']['rating'] == 4 and item.after_data['project'] == 'Mehta Villa'
    w = admin.get('/api/waiting').json()
    g = next(x for x in w['requests'] if x['request_id'] == rid)
    assert g['state'] == 'built' and g['drafted'] == 1 and g['nothing_to_add'] == 1
    assert write(admin, 'post', f"/api/tickets/{check['ticket_id']}/approve-and-save", {}).status_code == 200
    assert admin.get('/api/waiting').json()['requests'][0]['added'] == 1
    records = admin.get('/api/record-types/client_site_visit_feedback/records').json()['records']
    assert len(records) == 1 and records[0]['project'] == 'Mehta Villa'
    h = admin.get('/api/chat/history/' + sid).json()
    assert any('approved building' in m['content'] for m in h['messages'] if m['speaker'] == 'system')


def test_waiting_check_runs_only_once_per_entry(admin):
    project(admin)
    build_type(admin)
    assert write(admin, 'post', '/api/waiting/check', {}).json()['drafted'] == []


def test_chat_drafts_a_record_of_a_built_type_and_asks_for_whats_missing(admin):
    project(admin)
    build_type(admin)
    r = chat(admin, 'Site visit feedback for Mehta Villa today: client loved the kitchen')
    item = r['preview']['items'][0]
    assert item['record_type'] == 'client_site_visit_feedback'
    keys = {f['key']: f for f in item['fields']}
    assert keys['data.rating']['marker'] == 'missing' and keys['project']['display'] == 'Mehta Villa'
    ask = next(a for a in r['ask'] if a['field'] == 'data.rating')
    assert [c['value'] for c in ask['choices']] == [1, 2, 3, 4, 5]
    blocked = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {})
    assert blocked.status_code == 422 and 'Rating' in blocked.json()['detail']
    bad = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item['id'], 'field': 'data.rating', 'value': 'great'})
    assert bad.status_code == 422
    ok = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item['id'], 'field': 'data.rating', 'value': 5, 'label': '5'})
    assert ok.status_code == 200, ok.text
    fingerprints = {i['id']: i['review_fingerprint'] for i in ok.json()['preview']['items']}
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save",
                 {'review_fingerprints': fingerprints}).status_code == 200
    with SessionLocal() as db:
        rec = db.scalars(select(FlexibleRecord)).all()[-1]
        assert rec.record_type == 'client_site_visit_feedback' and rec.data['rating'] == 5


def test_server_rejects_unknown_or_badly_typed_fields(admin):
    project(admin)
    build_type(admin)
    r = chat(admin, 'Site visit feedback for Mehta Villa today: rated 4')
    item = r['preview']['items'][0]
    after = {**item['after'], 'data': {**item['after']['data'], 'budget': 100}}
    assert write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after}).status_code == 422
    after = {**item['after'], 'data': {**item['after']['data'], 'rating': 'excellent'}}
    assert write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after}).status_code == 422


def test_undoing_the_build_retires_the_type_but_keeps_records(admin):
    project(admin)
    rid, sid, approved = build_type(admin)
    with SessionLocal() as db:
        ticket_id = db.get(NewTypeInbox, rid).ticket_id
    assert approved_undo(admin,ticket_id,'Rethink the fields').status_code == 200
    with SessionLocal() as db:
        assert db.get(RecordType, 'client_site_visit_feedback').status == 'retired'
    check = approved['waiting_check'][0]
    r = write(admin, 'post', f"/api/tickets/{check['ticket_id']}/approve-and-save", {})
    assert r.status_code == 422 and 'no longer accepted' in r.json()['detail']


def test_staff_see_only_their_own_waiting_entries(admin):
    chat(admin, REQUEST)
    write(admin, 'post', '/api/users', {'username': 'arch09', 'display_name': 'Architect', 'role': 'architect', 'password': 'fictional-architect-9'})
    other = TestClient(app)
    assert other.post('/api/auth/login', json={'username': 'arch09', 'password': 'fictional-architect-9'}).status_code == 200
    assert other.get('/api/waiting').json()['requests'] == []
    assert other.post('/api/waiting/check', headers={'X-CSRF-Token': other.cookies.get('studioos_csrf', '')}, json={}).status_code == 403
    assert other.get('/api/system/integrity').status_code == 403


def test_new_screens_load_safely(client):
    import re
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    html = (static / 'index.html').read_text()
    assert html.index('/static/chat.js') < html.index('/static/waiting.js')
    assert "label: 'Waiting for a place'" in (static / 'nav.js').read_text()
    for name in ('chat.js', 'waiting.js'):
        js = (static / name).read_text()
        assert 'style="' not in js and not re.search(r'\son[a-z]+="', js)
