"""Open snags (the Work pack's issue record) appear in the owner-of-the-snag's morning list. Fictional data."""
import datetime as dt

from studioos import rhythm_core as c
from sqlalchemy import select

from studioos.db import FlexibleRecord, SessionLocal, User

TODAY = dt.date(2026, 11, 20)


def rec(i, **data):
    return {'id': i, 'project': 'Villa A', 'data': data}


def test_snag_items_are_the_persons_open_snags_oldest_first():
    records = [rec(1, title='Crack in wall', owner=7, issue_status='Open', due_date='2026-11-25'),
               rec(2, title='Leaking tap', owner=7, issue_status='In progress'),
               rec(3, title='Paint patch', owner=7, issue_status='Closed', due_date='2026-11-01'),
               rec(4, title='Other person', owner=8, issue_status='Open'),
               rec(5, title='Door gap', owner=7, issue_status='Open', due_date='2026-11-18')]
    got = c.snag_items(records, 7, TODAY)
    assert [x['snag_id'] for x in got] == [5, 1, 2]                      # dated first, undated last; closed and others' snags left out
    assert all(x['reason'] == 'snag' and x['task_id'] is None and x['blocked_by'] == [] for x in got)
    assert c.snag_items([], 7, TODAY) == []


def test_morning_text_names_the_snag():
    items = c.snag_items([rec(9, title='Crack in wall', owner=7, issue_status='Open')], 7, TODAY)
    assert 'snag #9 Crack in wall: open snag' in c.morning_text('Asha', items, TODAY)


def test_the_api_lists_the_signed_in_persons_snags(admin):
    with SessionLocal() as db:
        me = db.scalar(select(User.id).where(User.username == 'admin'))
        db.add(FlexibleRecord(record_type='work_issue', data={'title': 'Fictional crack', 'owner': me, 'issue_status': 'Open'}))
        db.add(FlexibleRecord(record_type='work_issue', data={'title': 'Fictional closed', 'owner': me, 'issue_status': 'Closed'}))
        db.commit()
    items = admin.get('/api/rhythm/mine').json()['items']
    assert [i['title'] for i in items if i['reason'] == 'snag'] == ['Fictional crack']
