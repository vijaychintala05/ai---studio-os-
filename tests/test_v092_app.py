"""v0.9.2 fixes at the API boundary (audit N-02, N-03). Fictional data only.
Needs FastAPI and SQLAlchemy: python -m pytest -q tests/test_v092_app.py"""
from sqlalchemy import select
from .conftest import write, approved_form
from .test_v090_app import chat, project, build_type
from studioos.db import SessionLocal, Task, ApprovalTicketItem


def task(admin, title, project_name='Mehta Villa'):
    r = approved_form(admin,'post','/api/tasks', {'project_id': next(p['id'] for p in admin.get('/api/projects').json() if p['name'] == project_name),
                                            'title': title})
    assert r.status_code == 200, r.text


def test_n03_progress_updates_the_matching_task_only_after_approval(admin):
    project(admin)
    task(admin, 'Bathroom tiling')
    task(admin, 'False ceiling')
    r = chat(admin, 'Tiling at Mehta Villa is 60% done.')
    item = r['preview']['items'][0]
    assert item['item_type'] == 'update_task'
    assert item['before']['progress'] == 0 and item['after']['progress'] == 60 and item['after']['title'] == 'Bathroom tiling'
    with SessionLocal() as db:
        assert db.scalars(select(Task).where(Task.title == 'Bathroom tiling')).one().progress == 0   # not yet
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(Task).where(Task.title == 'Bathroom tiling')).one().progress == 60
        assert db.scalars(select(Task).where(Task.title == 'False ceiling')).one().progress == 0


def test_n03_several_matching_tasks_ask_which(admin):
    project(admin)
    task(admin, 'Bathroom tiling')
    task(admin, 'Kitchen tiling')
    with SessionLocal() as db:
        setup_items = {i.id for i in db.scalars(select(ApprovalTicketItem)).all()}
    r = chat(admin, 'Tiling at Mehta Villa is 80% done')
    ask = next(a for a in r['ask'] if a['id'] == 'task')
    assert sorted(c['label'] for c in ask['choices']) == ['Bathroom tiling', 'Kitchen tiling']
    with SessionLocal() as db:
        # Setup now has approved form tickets; clarification must add none.
        assert {i.id for i in db.scalars(select(ApprovalTicketItem)).all()} == setup_items
    picked = chat(admin, next(c['value'] for c in ask['choices'] if c['label'] == 'Kitchen tiling'))
    assert picked['preview']['items'][0]['after']['title'] == 'Kitchen tiling'


def test_n03_complete_marks_the_task_done(admin):
    project(admin)
    task(admin, 'Wardrobe installation')
    r = chat(admin, 'Wardrobe installation at Mehta Villa is complete')
    after = r['preview']['items'][0]['after']
    assert after['progress'] == 100 and after['status'] == 'done'


def test_n03_no_matching_task_is_a_clearly_labelled_note(admin):
    project(admin)
    r = chat(admin, 'Tiling at Mehta Villa is 60% done.')
    item = r['preview']['items'][0]
    assert item['item_type'] == 'generic_record' and any('no task is changed' in f for f in item['flags'])


def test_n02_garbled_numbers_are_refused_at_the_api(admin):
    project(admin)
    build_type(admin)
    r = chat(admin, 'Site visit feedback for Mehta Villa today: liked the kitchen')
    item = r['preview']['items'][0]
    for bad in ('4.9', '3abc', '4/10'):
        res = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item['id'], 'field': 'data.rating', 'value': bad})
        assert res.status_code == 422, bad
        after = {**item['after'], 'data': {**item['after']['data'], 'rating': bad}}
        assert write(admin, 'patch', f"/api/tickets/items/{item['id']}", {'after': after}).status_code == 422, bad
    ok = write(admin, 'post', '/api/chat/answer', {'session_id': r['session_id'], 'item_id': item['id'], 'field': 'data.rating', 'value': '4'})
    assert ok.status_code == 200
    with SessionLocal() as db:
        ev = db.get(ApprovalTicketItem, item['id']).field_evidence['data.rating']
        assert ev['raw_answer'] == '4' and ev['marker'] == 'answered'
