"""v0.9.1 fixes for the independent v0.9.0 audit (F-01 to F-08). Fictional data only.
Needs FastAPI and SQLAlchemy: python -m pytest -q tests/test_v091_audit_fixes.py"""
from sqlalchemy import select, text
from .conftest import write
from .test_v080_chat_app import expense as books_expense
from .test_v090_app import chat, project, build_type, REQUEST
from studioos.db import SessionLocal, ApprovalTicketItem, NewTypeInbox, RecordType, FlexibleRecord, ChatSession, ChatMessage


def test_f01_same_kind_of_information_joins_the_earlier_request(admin):
    first = chat(admin, REQUEST)
    entry = write(admin, 'post', '/api/new-types/intake',
                  {'text': 'Client site visit feedback for Sharma Residence: rating 3, kitchen too dark'}).json()['holding_item']
    assert entry['state'] == 'reuse_existing_proposal'
    assert entry['match_review']['existing_proposals'][0]['inbox_id'] == first['holding_item']['id']


def test_f02_progress_on_work_is_not_a_new_kind_of_information(admin):
    project(admin)
    r = chat(admin, 'Tiling at Mehta Villa is 60% done.')
    assert not r.get('holding_item')
    with SessionLocal() as db:
        assert db.scalars(select(NewTypeInbox)).all() == []
        item = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id'])).one()
        assert item.item_type == 'generic_record' and item.after_data['record_type'] == 'task_update'


def _proposal(admin, kind, data):
    from studioos.tickets import add_proposal
    with SessionLocal() as db:
        s = ChatSession(id='audit-f03-' + kind[:20], user_id=1, pending=None); db.add(s); db.flush()
        m = ChatMessage(session_id=s.id, user_id=1, speaker='user', content='fictional'); db.add(m); db.flush()
        ticket, item = add_proposal(db, s, 'generic_record', {'record_type': kind, 'project': 'Mehta Villa', 'data': data}, m.id)
        db.commit()
        return ticket.id, item.id


def test_f03_unknown_record_types_are_refused(admin):
    project(admin)
    ticket_id, item_id = _proposal(admin, 'unapproved_arbitrary_type', {'whatever': True})
    r = write(admin, 'post', f'/api/tickets/items/{item_id}/approve', {})
    assert r.status_code == 422 and 'not an approved kind of record' in r.text
    assert write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {}).status_code == 422
    with SessionLocal() as db:
        assert db.scalars(select(FlexibleRecord)).all() == []


def test_f03_built_in_reference_notes_still_work(admin):
    project(admin)
    ticket_id, _ = _proposal(admin, 'site_observation', {'note': 'Grid uneven near entrance'})
    assert write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save', {}).status_code == 200


def test_f03_a_tampered_record_type_is_refused(admin):
    project(admin)
    build_type(admin)
    with SessionLocal() as db:
        rt = db.get(RecordType, 'client_site_visit_feedback')
        design = dict(rt.design); design['fields'] = [f for f in design['fields'] if f['name'] != 'rating']
        rt.design = design; db.commit()
    r = chat(admin, 'Site visit feedback for Mehta Villa today: liked the kitchen')
    s = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {})
    assert s.status_code == 422 and 'differs from its approved design' in s.text


def test_f06_rating_must_be_in_range(admin):
    project(admin)
    build_type(admin)
    r = chat(admin, 'Site visit feedback for Mehta Villa today: liked the kitchen')
    item = r['preview']['items'][0]
    bad = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item['id'], 'field': 'data.rating', 'value': 9})
    assert bad.status_code == 422 and '1 to 5' in bad.text
    after = {**item['after'], 'data': {**item['after']['data'], 'rating': 9}}
    assert write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after}).status_code == 422


def test_f07_changing_an_approved_ticket_afterwards_is_detected(admin):
    r = books_expense(admin, 'Fingerprint Villa')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    assert admin.get('/api/system/integrity').json()['overall'] == 'ok'
    with SessionLocal() as db:
        item = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == r['ticket_id'])).one()
        data = dict(item.after_data); data['amount_paise'] = 40000
        db.execute(text('UPDATE approval_ticket_items SET after_data = :d WHERE id = :i'),
                   {'d': __import__('json').dumps(data), 'i': item.id})
        db.commit()
    result = admin.get('/api/system/integrity').json()
    assert result['overall'] == 'fail' and result['approved_ticket_mismatches'] == [{'ticket_id': r['ticket_id']}]


def test_f08_unapproved_record_types_in_storage_are_reported(admin):
    with SessionLocal() as db:
        db.add(FlexibleRecord(record_type='made_up_type', project_id=None, data={'x': 1})); db.commit()
    result = admin.get('/api/system/integrity').json()
    assert result['overall'] == 'warn' and result['unapproved_record_types'] == ['made_up_type']
