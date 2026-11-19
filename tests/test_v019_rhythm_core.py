"""v0.19 pure rules: morning list, project health, job timing. No database. Fictional data only."""
import datetime as dt

from studioos import rhythm_core as c

TODAY = dt.date(2026, 3, 18)


def L(a, b, kind='hard'):
    return {'predecessor_id': a, 'successor_id': b, 'kind': kind}


def T(i, due, status='open', title=None):
    return {'id': i, 'title': title or f'Task {i}', 'due': due, 'status': status, 'project': 'Villa'}


def test_morning_list_orders_overdue_due_today_and_ready_and_names_blockers():
    tasks = [T(1, '2026-03-18'), T(2, '2026-03-10'), T(3, ''), T(4, '2026-03-25'), T(5, '2026-03-30')]
    links = [L(9, 3), L(8, 4)]
    status = {1: 'open', 2: 'open', 3: 'open', 4: 'open', 5: 'open', 9: 'done', 8: 'open'}
    items = c.morning_todos(tasks, links, status, TODAY)
    assert [(i['task_id'], i['reason']) for i in items] == [(2, 'overdue'), (1, 'due_today'), (3, 'ready')]
    # task 4 is blocked and not due, task 5 is simply later: neither is listed
    blocked_due_today = c.morning_todos([T(4, '2026-03-18')], links, status, TODAY)
    assert blocked_due_today[0]['blocked_by'] == [8]
    assert 'waiting for #8' in c.morning_text('Asha', blocked_due_today, TODAY)


def test_morning_list_skips_closed_and_handles_bad_dates_and_empty():
    status = {1: 'done', 2: 'open'}
    assert c.morning_todos([T(1, '2026-03-10'), T(2, 'next week')], [], status, TODAY) == []
    assert 'Nothing is due' in c.morning_text('Asha', [], TODAY)


def test_project_health_delayed_at_risk_on_track():
    delayed = c.project_health([T(1, '2026-03-10'), T(2, '2026-03-05')], [], TODAY)
    assert delayed['status'] == 'delayed' and delayed['overdue'] == 2 and delayed['blocking']['task_id'] == 2
    risk = c.project_health([T(1, '2026-03-30'), T(2, '2026-03-20')], [L(1, 2)], TODAY)
    assert risk['status'] == 'at_risk' and risk['blocking']['task_id'] == 2 and '#1' in risk['blocking']['reason']
    ok = c.project_health([T(1, '2026-03-30'), T(2, '2026-04-20')], [L(1, 2)], TODAY)
    assert ok['status'] == 'on_track' and ok['blocking'] is None
    closed = c.project_health([T(1, '2026-03-10', 'done'), T(2, '2026-03-20')], [L(1, 2)], TODAY)
    assert closed['status'] == 'on_track'
    soft = c.project_health([T(1, '2026-03-30'), T(2, '2026-03-20')], [L(1, 2, 'soft')], TODAY)
    assert soft['status'] == 'on_track'                       # a soft link never makes a project at risk


def test_owner_text_names_the_blocker():
    h = c.project_health([T(1, '2026-03-10', title='Slab pour')], [], TODAY)
    text = c.owner_text('Villa W', h, TODAY)
    assert 'Delayed' in text and 'Slab pour' in text


def test_jobs_run_once_a_day_after_their_time_and_never_in_quiet_hours():
    at = lambda h, m=0: dt.datetime(2026, 3, 18, h, m)
    assert not c.job_due((8, 30), None, at(8, 29))
    assert c.job_due((8, 30), None, at(8, 30))
    assert not c.job_due((8, 30), TODAY, at(12))
    assert c.job_due((8, 30), TODAY - dt.timedelta(days=1), at(12))
    assert not c.job_due((20, 0), None, at(21, 30))           # quiet hours
    assert not c.job_due((8, 30), None, at(3))
