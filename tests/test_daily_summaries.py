"""The sectioned morning and evening summaries use the owner's headings, say Nothing under an empty one, include what StudioOS
holds, and show money only to roles that may see money. Fictional data."""
import datetime as dt

from sqlalchemy import select

from studioos import rhythm_core as c
from studioos.chart_of_accounts import local_today
from studioos.db import FlexibleRecord, SessionLocal, SummaryDelivery, Task, User
from tests.books_fixtures import draft_project_expense
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_v098_universal_accounting import finance_setup, save

TODAY = dt.date(2026, 11, 20)


def test_headings_are_the_owners_and_empty_sections_say_nothing():
    assert c.MORNING_HEADINGS == ('Urgent & Critical Issues', "Today's Priorities", 'Overdue Tasks', 'Meetings & Follow-ups',
                                  'Pending Approvals', 'Payments & Purchases', 'Project Plans & Dependencies')
    assert c.EVENING_HEADINGS == ('Critical Unresolved Issues', 'Tasks Completed', 'Pending & Overdue Tasks', 'Project & Site Progress',
                                  'Decisions & Approvals', 'Financial Transactions', "Tomorrow's Priorities")
    text = c.render_summary('Good morning Asha.', TODAY, c.MORNING_HEADINGS, {"Today's Priorities": ['#1 Pour slab (Villa A) due 2026-11-20']})
    lines = text.split(chr(10))
    assert lines[0] == 'Good morning Asha. (2026-11-20)' and [l for l in lines if l.endswith(':')] == [h + ':' for h in c.MORNING_HEADINGS]
    assert '  - #1 Pour slab (Villa A) due 2026-11-20' in lines and text.count('  Nothing.') == 6


def test_long_sections_are_cut_with_a_count():
    text = c.render_summary('Hi.', TODAY, ('Overdue Tasks',), {'Overdue Tasks': [f'#{i}' for i in range(12)]}, per_section=8)
    assert '... and 4 more' in text and text.count('  - #') == 8


def test_urgent_means_critical_snags_and_tasks_a_week_late():
    todos = [{'reason': 'overdue', 'task_id': 1, 'title': 'Old', 'due': '2026-11-10', 'blocked_by': []},
             {'reason': 'overdue', 'task_id': 2, 'title': 'Recent', 'due': '2026-11-18', 'blocked_by': []},
             {'reason': 'snag', 'task_id': None, 'snag_id': 5, 'title': 'Crack', 'due': '', 'blocked_by': [], 'severity': 'Critical'},
             {'reason': 'snag', 'task_id': None, 'snag_id': 6, 'title': 'Paint', 'due': '', 'blocked_by': [], 'severity': 'Low'}]
    assert [i.get('task_id') or i['snag_id'] for i in c.urgent(todos, TODAY)] == [1, 5]


def _deliver(admin, job):
    r = write(admin, 'post', f'/api/rhythm/run/{job}').json()
    assert r['outcome'] == 'ok', r
    with SessionLocal() as db:
        return {(d.summary_key, d.user_id): d.text for d in db.scalars(select(SummaryDelivery))}


def test_morning_and_evening_include_what_the_system_holds(admin):
    admin_name = 'StudioOS Administrator'
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Summaries', 'budget': '100000'}).json()
    today = local_today().isoformat()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': admin_name, 'due_date': '2020-01-01'})
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Order tiles', 'assignee': admin_name, 'due_date': today})
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == 'admin'))
        db.add(FlexibleRecord(record_type='work_issue', project_id=p['id'], data={'title': 'Crack in wall', 'owner': uid, 'issue_status': 'Open', 'severity': 'Critical'}))
        db.add(FlexibleRecord(record_type='meeting_note', project_id=p['id'], data={'meeting_date': today, 'meeting_type': 'Site', 'attendees': admin_name, 'decisions': 'Tiles approved'}))
        db.commit()
    morning = _deliver(admin, 'rhythm_morning')
    text = next(v for (k, u), v in morning.items() if k == 'rhythm_morning' and u == uid)

    def section(heading):
        return text.split(heading + ':')[1].split(chr(10))[1:3]
    assert any('Crack in wall' in l for l in section('Urgent & Critical Issues'))
    assert any('Pour slab' in l for l in section('Urgent & Critical Issues'))           # years overdue counts as urgent
    assert any('Order tiles' in l for l in section("Today's Priorities"))
    assert any('Site today' in l for l in section('Meetings & Follow-ups'))
    evening = _deliver(admin, 'rhythm_evening')
    etext = next(v for (k, u), v in evening.items() if k == 'rhythm_evening' and u == uid)
    assert etext.startswith('Good evening') and all(h + ':' in etext for h in c.EVENING_HEADINGS)
    assert 'Villa Summaries' in etext.split('Project & Site Progress:')[1]
    assert 'Crack in wall' in etext.split('Critical Unresolved Issues:')[1].split('Tasks Completed')[0]
    assert write(admin, 'post', '/api/rhythm/run/rhythm_evening').json()['detail'].startswith('0 message')   # kept once a day


def test_money_sections_are_for_money_roles_only(admin):
    site, sid = staff(admin, 'site.sum', 'site_engineer')
    try:
        finance_setup(admin)
        p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Money', 'budget': '100000'}).json()
        draft = draft_project_expense(admin, p['id'], 500000, note='Fictional cement')
        assert draft.status_code == 200, draft.text
        with SessionLocal() as db:
            owner = db.scalar(select(User.id).where(User.username == 'admin'))
            db.add(Task(project_id=p['id'], title='Site job', assignee='Site.Sum', due_date=local_today().isoformat()))
            db.commit()
        morning = _deliver(admin, 'rhythm_morning')
        assert '1 expense waiting for approval, Rs 5,000' in morning['rhythm_morning', owner]
        assert 'Rs 5,000' not in morning['rhythm_morning', sid]
        before = draft.json()
        record = save(admin, before)
        evening = _deliver(admin, 'rhythm_evening')
        assert f'Direct expense posted #{record["journal_id"]}: Rs 5,000' in evening['rhythm_evening', owner]
        mine = next((v for (k, u), v in evening.items() if k == 'rhythm_evening' and u == sid), '')
        assert 'Financial Transactions:' in mine and 'cement' not in mine.lower() and 'Rs' not in mine
    finally:
        site.close()
