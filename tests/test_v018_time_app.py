"""v0.18 through the real approval path: time, leave, rates, timer and the workload warning. Fictional data only."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from studioos.db import SessionLocal
from studioos.main import app
from studioos.time_models import TimeEntry, TimerRun
from studioos.time_rules import studio_today
from tests.conftest import approved_form, write

PASSWORD = 'FictionalStaffPassword2026'


def workday(back=0):
    """A recent date that is not a Sunday and not in the future."""
    d = studio_today() - dt.timedelta(days=back)
    while d.weekday() == 6:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def propose(client, kind, data):
    return write(client, 'post', '/api/time/propose', {'kind': kind, 'data': data})


def save(owner, client, kind, data):
    """client proposes, the owner approves the ticket."""
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    s = write(owner, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text
    return s.json()


def staff(admin, username, role):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.title(), 'role': role, 'password': PASSWORD})
    assert r.status_code == 200, r.text
    c = TestClient(app)
    login = c.post('/api/auth/login', json={'username': username, 'password': PASSWORD})
    assert login.status_code == 200, login.text
    return c, r.json()['id']


@pytest.fixture
def team(admin):
    manager, manager_id = staff(admin, 'mgr.fict', 'manager')
    site, site_id = staff(admin, 'site.fict', 'site_engineer')
    yield {'manager': manager, 'manager_id': manager_id, 'site': site, 'site_id': site_id}
    manager.close()
    site.close()


def log(admin, who, minutes=120, date=None, activity='Site visit'):
    save(admin, who, 'time_log', {'activity': activity, 'work_date': date or workday(), 'minutes': minutes})
    rows = who.get('/api/time/entries').json()
    return rows[0]['id']


def test_full_cycle_with_rate_frozen_at_approval(admin, team):
    me = team['site_id']
    save(admin, admin, 'rate_set', {'user_id': me, 'rate_paise_per_hour': 60000, 'effective_from': '2020-01-01'})
    eid = log(admin, team['site'], 90)
    save(admin, team['site'], 'time_submit', {'entry_id': eid})
    assert propose(team['site'], 'time_approve', {'entry_id': eid}).status_code == 400    # a site engineer cannot review time
    mine = log(admin, admin, 30)
    save(admin, admin, 'time_submit', {'entry_id': mine})
    save(admin, admin, 'time_approve', {'entry_id': mine})                  # the owner may approve their own time (owner decision)
    assert next(e for e in admin.get('/api/time/entries').json() if e['id'] == mine)['status'] == 'approved'
    mgr_own = log(admin, team['manager'], 20)
    save(admin, team['manager'], 'time_submit', {'entry_id': mgr_own})
    refused = propose(team['manager'], 'time_approve', {'entry_id': mgr_own})
    assert refused.status_code == 400 and 'logged it' in refused.text       # a manager still cannot approve their own
    save(admin, team['manager'], 'time_approve', {'entry_id': eid})
    row = next(e for e in team['manager'].get('/api/time/entries').json() if e['id'] == eid)
    assert row['status'] == 'approved' and row['rate_paise_per_hour'] == 60000 and row['cost_paise'] == 90000
    save(admin, admin, 'rate_set', {'user_id': me, 'rate_paise_per_hour': 90000, 'effective_from': workday(0)})
    row = next(e for e in team['manager'].get('/api/time/entries').json() if e['id'] == eid)
    assert row['cost_paise'] == 90000                                        # earlier entry keeps the old rate


def test_approved_time_is_frozen_until_sent_back_with_a_reason(admin, team):
    eid = log(admin, team['site'])
    save(admin, team['site'], 'time_submit', {'entry_id': eid})
    save(admin, team['manager'], 'time_approve', {'entry_id': eid})
    edit = propose(team['site'], 'time_edit', {'entry_id': eid, 'minutes': 60})
    assert edit.status_code == 400 and 'cannot be edited' in edit.text
    no_reason = propose(team['manager'], 'time_send_back', {'entry_id': eid, 'reason': ''})
    assert no_reason.status_code == 400
    save(admin, team['manager'], 'time_send_back', {'entry_id': eid, 'reason': 'Hours were entered wrongly'})
    save(admin, team['site'], 'time_edit', {'entry_id': eid, 'minutes': 60})
    row = next(e for e in team['site'].get('/api/time/entries').json() if e['id'] == eid)
    assert row['status'] == 'draft' and row['minutes'] == 60


def test_reject_needs_a_reason_and_frees_the_limit(admin, team):
    eid = log(admin, team['site'], 500)
    save(admin, team['site'], 'time_submit', {'entry_id': eid})
    assert propose(team['manager'], 'time_reject', {'entry_id': eid, 'reason': 'x'}).status_code == 400
    save(admin, team['manager'], 'time_reject', {'entry_id': eid, 'reason': 'Wrong project selected'})
    save(admin, team['site'], 'time_log', {'activity': 'Site visit', 'work_date': workday(), 'minutes': 500})   # limit freed


def test_leave_holiday_day_off_and_limits_refuse_entries(admin, team):
    day = workday(1)
    save(admin, team['site'], 'leave_record', {'user_id': team['site_id'], 'start_date': day, 'end_date': day})
    r = propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': day, 'minutes': 60})
    assert r.status_code == 400 and 'on leave' in r.text
    other = workday(2)
    save(admin, admin, 'holiday_add', {'date': other, 'name': 'Fictional festival'})
    r = propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': other, 'minutes': 60})
    assert r.status_code == 400 and 'holiday' in r.text
    sunday = studio_today() - dt.timedelta(days=(studio_today().weekday() + 1) % 7 or 7)
    r = propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': sunday.isoformat(), 'minutes': 60})
    assert r.status_code == 400 and 'day off' in r.text
    future = (studio_today() + dt.timedelta(days=2)).isoformat()
    assert propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': future, 'minutes': 60}).status_code == 400
    ok = workday(3)
    save(admin, team['site'], 'time_log', {'activity': 'Site visit', 'work_date': ok, 'minutes': 500})
    r = propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': ok, 'minutes': 200})
    assert r.status_code == 400 and 'daily limit' in r.text


def test_leave_cannot_cover_days_that_already_have_time(admin, team):
    day = workday(4)
    save(admin, team['site'], 'time_log', {'activity': 'Site visit', 'work_date': day, 'minutes': 60})
    r = propose(team['site'], 'leave_record', {'user_id': team['site_id'], 'start_date': day, 'end_date': day})
    assert r.status_code == 400 and 'already logged' in r.text


def test_site_engineer_never_sees_rates_or_costs_or_others_time(admin, team):
    save(admin, admin, 'rate_set', {'user_id': team['site_id'], 'rate_paise_per_hour': 50000, 'effective_from': '2020-01-01'})
    eid = log(admin, team['site'])
    admin_entry = log(admin, admin, 30)
    mine = team['site'].get('/api/time/entries').json()
    assert [e['id'] for e in mine] == [eid]
    assert all('rate_paise_per_hour' not in e and 'cost_paise' not in e for e in mine)
    assert team['site'].get('/api/time/rates').status_code == 403
    manager_view = team['manager'].get('/api/time/entries').json()
    assert {eid, admin_entry} <= {e['id'] for e in manager_view}
    assert 'rate_paise_per_hour' in manager_view[0]
    assert propose(team['site'], 'rate_set', {'user_id': team['site_id'], 'rate_paise_per_hour': 1, 'effective_from': '2026-01-01'}).status_code == 400


def test_timer_drafts_one_entry_and_only_after_approval(admin, team, monkeypatch):
    # The weekly day off is Sunday, so on a Sunday the timer would (correctly) refuse to log time. Run this test with no day off then, so it
    # checks the timer flow on any day of the week. (The day-off rule itself is tested elsewhere.)
    import sys
    from studioos import time_routes as tr
    if tr.studio_now().weekday() == 6:
        real_week_off = tr.week_off
        for module in list(sys.modules.values()):
            if getattr(module, 'week_off', None) is real_week_off:
                monkeypatch.setattr(module, 'week_off', lambda db: set())
    site = team['site']
    assert write(site, 'post', '/api/time/timer/start', {'activity': 'Site visit'}).status_code == 200
    assert write(site, 'post', '/api/time/timer/start', {'activity': 'Other'}).status_code == 400
    assert site.get('/api/time/timer').json()['running'] is True
    stopped = write(site, 'post', '/api/time/timer/stop')
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()['minutes'] == 1
    with SessionLocal() as db:
        assert db.scalars(select(TimeEntry)).all() == []                     # no entry without approval
    write(admin, 'post', f"/api/tickets/{stopped.json()['ticket_id']}/approve-and-save", {'confirmed': []})
    rows = site.get('/api/time/entries').json()
    assert len(rows) == 1 and rows[0]['status'] == 'draft' and rows[0]['source'] == 'timer'
    assert site.get('/api/time/timer').json()['running'] is False


def test_timer_can_be_discarded(admin, team):
    site = team['site']
    write(site, 'post', '/api/time/timer/start', {'activity': 'Site visit'})
    assert write(site, 'post', '/api/time/timer/discard').status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(TimerRun)).all()[0].discarded is True
    assert write(site, 'post', '/api/time/timer/stop').status_code == 400


def test_workload_warning_overload_and_leave_and_only_warns(admin, team):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa L', 'budget': '10000'}).json()
    d1, d2 = workday(0), workday(0)
    due = (studio_today() + dt.timedelta(days=1)).isoformat()
    task = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Detail drawings', 'assignee': 'Mgr.Fict', 'due_date': due}).json()
    save(admin, admin, 'task_estimate', {'task_id': task['id'], 'minutes': 5000})
    q = f"/api/time/workload?assignee=Mgr.Fict&due_date={due}&estimate_minutes=300"
    r = admin.get(q)
    assert r.status_code == 200 and any('Overloaded' in w for w in r.json()['warnings']) and r.json()['person_known'] is True
    save(admin, team['manager'], 'leave_record', {'user_id': team['manager_id'], 'start_date': due, 'end_date': due})
    r = admin.get(q)
    assert any(w.startswith('On leave on') for w in r.json()['warnings'])
    assert admin.get('/api/time/workload?assignee=Nobody&due_date=' + due).status_code == 200
    assert team['site'].get(q).status_code == 403


def test_settings_and_calendar(admin, team):
    save(admin, admin, 'time_setting', {'key': 'time_daily_limit_minutes', 'value': 240})
    assert admin.get('/api/time/settings').json()['time_daily_limit_minutes'] == 240
    r = propose(team['manager'], 'time_setting', {'key': 'time_daily_limit_minutes', 'value': 720})
    assert r.status_code == 400
    assert propose(admin, 'time_setting', {'key': 'time_daily_limit_minutes', 'value': 5}).status_code == 400
    r = propose(team['site'], 'time_log', {'activity': 'Site visit', 'work_date': workday(), 'minutes': 300})
    assert r.status_code == 400 and 'daily limit' in r.text
    save(admin, admin, 'holiday_add', {'date': workday(6), 'name': 'Fictional day'})
    assert any(h['name'] == 'Fictional day' for h in team['site'].get('/api/time/calendar').json()['holidays'])


def test_time_changes_cannot_be_undone_generically(admin, team):
    out = write(admin, 'post', '/api/time/propose', {'kind': 'time_log', 'data': {'activity': 'Site visit', 'work_date': workday(), 'minutes': 30}})
    tid = out.json()['ticket_id']
    write(admin, 'post', f'/api/tickets/{tid}/approve-and-save', {'confirmed': []})
    r = write(admin, 'post', f'/api/tickets/{tid}/reverse', {'reason': 'try to undo the time entry'})
    assert r.status_code in (400, 409) and 'generic undo' in r.text
