"""v0.19 daily rhythm through the app: morning list, owner summary, scheduler timing, and nothing changed by it."""
import datetime as dt

from sqlalchemy import select

from studioos import improve_wiring as W
from studioos import rhythm
from studioos import universal_engine as u
from studioos.db import SessionLocal, SummaryDelivery, Task
from tests.conftest import approved_form, write
from tests.test_v017_work_rules_app import save as save_work


def setup(admin):
    today = u._today()
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa R', 'budget': '10000'}).json()
    late = (today - dt.timedelta(days=3)).isoformat()
    a = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Slab pour', 'assignee': 'Admin', 'due_date': late}).json()
    b = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Plaster', 'assignee': 'Admin', 'due_date': today.isoformat()}).json()
    save_work(admin, 'work_link', {'predecessor_id': a['id'], 'successor_id': b['id'], 'kind': 'hard'})
    return p, a, b


def me(admin):
    return admin.get('/api/auth/me').json()['user']


def test_my_list_and_project_health(admin):
    p, a, b = setup(admin)
    name = me(admin)['display_name'] or me(admin)['username']
    with SessionLocal() as db:
        for t in db.scalars(select(Task)):
            t.assignee = name
        db.commit()
    mine = admin.get('/api/rhythm/mine').json()['items']
    assert [(i['task_id'], i['reason']) for i in mine] == [(a['id'], 'overdue'), (b['id'], 'due_today')]
    assert mine[1]['blocked_by'] == [a['id']]
    health = admin.get('/api/rhythm/projects').json()['projects']
    assert health[0]['status'] == 'delayed' and health[0]['blocking']['task_id'] == a['id']


def test_jobs_keep_messages_once_and_change_nothing(admin):
    p, a, b = setup(admin)
    name = me(admin)['display_name'] or me(admin)['username']
    with SessionLocal() as db:
        for t in db.scalars(select(Task)):
            t.assignee = name
        db.commit()
        before = [(t.id, t.status, t.progress, t.due_date) for t in db.scalars(select(Task))]
    first = write(admin, 'post', '/api/rhythm/run/rhythm_morning').json()
    assert first['outcome'] == 'ok' and first['detail'].startswith('1 message')
    again = write(admin, 'post', '/api/rhythm/run/rhythm_morning').json()
    assert again['detail'].startswith('0 message')
    assert write(admin, 'post', '/api/rhythm/run/rhythm_owner').json()['detail'].startswith('1 message')
    with SessionLocal() as db:
        keys = sorted(d.summary_key for d in db.scalars(select(SummaryDelivery)))
        assert keys == ['rhythm_morning', f"rhythm_owner_p{p['id']}"]
        assert [(t.id, t.status, t.progress, t.due_date) for t in db.scalars(select(Task))] == before
        text = next(d.text for d in db.scalars(select(SummaryDelivery)) if d.summary_key == 'rhythm_morning')
        assert 'Slab pour' in text and 'overdue' in text
    assert write(admin, 'post', '/api/rhythm/run/not_a_job').status_code == 404


def test_scheduler_runs_rhythm_jobs_at_the_right_time_only(admin):
    assert rhythm.due_jobs(dt.datetime(2026, 3, 18, 8, 0), {}) == []
    assert rhythm.due_jobs(dt.datetime(2026, 3, 18, 8, 45), {}) == ['rhythm_morning']
    assert rhythm.due_jobs(dt.datetime(2026, 3, 18, 20, 5), {'rhythm_morning': dt.datetime(2026, 3, 18, 8, 40)}) == ['rhythm_owner']
    assert rhythm.due_jobs(dt.datetime(2026, 3, 18, 21, 5), {}) == []
    out = W.tick('test-holder', dt.datetime(2026, 3, 18, 8, 45))
    assert 'rhythm_morning' in [r['job'] for r in out]


def test_site_engineer_cannot_see_project_health(admin):
    from tests.test_v018_time_app import staff
    site, _ = staff(admin, 'site.rhythm', 'site_engineer')
    try:
        assert site.get('/api/rhythm/projects').status_code == 403
        assert site.get('/api/rhythm/mine').status_code == 200
    finally:
        site.close()
