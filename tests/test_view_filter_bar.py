"""The filter bar and the view builder: a viewer can narrow a view and look at it another way without a ticket, and nothing is stored.
Everything still runs through the permission-aware report engine. Fictional data."""
import datetime as dt
import json

import pytest
from sqlalchemy import func, select

from studioos import universal_engine as u
from studioos import viewspec_filter_bar as bar
from studioos.db import Audit, SessionLocal, Task
from studioos.db import ApprovalTicket
from studioos.viewspec_models import ViewSpecRow, ViewSpecVersion
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_viewspec_app import save, task_list

KEY = 'mine.open_tasks'


def _day(offset):
    return (u._today() + dt.timedelta(days=offset)).isoformat()


def _make_tasks(admin):
    """Three open tasks in one project, due in the past, soon and later, for two people, and one finished task the view leaves out."""
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Filter', 'budget': '100000'}).json()
    for title, who, due in (('Pour slab', 'Asha', _day(-3)), ('Order tiles', 'Ravi', _day(2)), ('Paint walls', 'Asha', _day(20))):
        r = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': title, 'assignee': who, 'due_date': due})
        assert r.status_code == 200, r.text
    old = approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Old snagging', 'assignee': 'Asha', 'due_date': _day(-30)}).json()
    done = write(admin, 'patch', f"/api/tasks/{old['id']}/complete")
    assert done.status_code == 200, done.text
    saved = write(admin, 'post', f"/api/tickets/{done.json()['ticket_id']}/approve-and-save", {'confirmed': ['duplicate', 'amount'], 'note': 'fictional'})
    assert saved.status_code == 200, saved.text
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})        # this view leaves out finished tasks
    return p


@pytest.fixture
def tasks_off(admin):
    """The same data with the owner's switch left as it ships: off."""
    return _make_tasks(admin)


@pytest.fixture
def tasks(admin):
    """The same data with the filter bar and builder turned on."""
    p = _make_tasks(admin)
    assert write(admin, 'post', '/api/viewspecs/builder/switch', {'on': True}).json() == {'enabled': True}
    return p


def run(client, flt=None, look=None):
    params = {}
    if flt is not None:
        params['filter'] = json.dumps(flt)
    if look:
        params['as'] = look
    return client.get(f'/api/viewspecs/{KEY}/run', params=params)


def titles(response):
    assert response.status_code == 200, response.text
    shown = response.json()['shown']
    if shown['kind'] == 'board':
        return sorted(c['label'] for lane in shown['lanes'] for c in lane['cards'])
    if shown['kind'] == 'calendar':
        return sorted(x['label'] for day in shown['days'] for x in day['items']) if 'days' in shown else None
    return sorted(row['cells'][0] for row in shown['result']['rows'])


def cond(field, op, value=None):
    return {'field': field, 'op': op, **({} if value is None else {'value': value})}


# ------------------------------------------------------------------ the owner's switch

def test_the_filter_bar_is_off_until_the_owner_turns_it_on(admin, tasks_off):
    body = run(admin).json()                                                                    # the view runs exactly as it always did
    assert body['filter_bar'] is False and body['looks'] == [] and titles(run(admin)) == ['Order tiles', 'Paint walls', 'Pour slab']
    for call in (run(admin, cond('title', 'contains', 'Pour')), run(admin, look='board')):
        assert call.status_code == 422 and 'turned off' in call.json()['detail']
    assert admin.get('/api/viewspecs/builder').json() == {'enabled': False, 'types': [], 'operators': {}, 'dates': [], 'looks': [], 'limits': {}}


def test_only_the_owner_can_turn_it_on_and_it_is_recorded(admin, tasks_off):
    site, _ = staff(admin, 'site.switch', 'site_engineer')
    manager, _ = staff(admin, 'mgr.switch', 'manager')
    try:
        for who in (site, manager):
            assert write(who, 'post', '/api/viewspecs/builder/switch', {'on': True}).status_code == 403
    finally:
        site.close()
        manager.close()
    assert admin.get('/api/viewspecs/builder').json()['enabled'] is False
    assert write(admin, 'post', '/api/viewspecs/builder/switch', {'on': True}).json() == {'enabled': True}
    cat = admin.get('/api/viewspecs/builder').json()
    assert cat['enabled'] is True and any(t['key'] == 'system.task' for t in cat['types'])
    assert run(admin).json()['looks'] == ['table', 'board', 'calendar']
    with SessionLocal() as db:
        notes = [a.description for a in db.scalars(select(Audit).where(Audit.entity_type == 'setting'))]
    assert 'Turned the filter bar and view builder on' in notes


def test_turning_it_off_hides_the_screens_and_keeps_everything_saved(admin, tasks):
    from tests.test_viewspec_app import task_list as make
    save(admin, admin, 'view_create', {'spec': make('mine.keep_me', 'Keep me'), 'scope': 'system'})
    with SessionLocal() as db:
        before = [db.scalar(select(func.count()).select_from(t)) for t in (ViewSpecRow, ViewSpecVersion, Task)]
    assert titles(run(admin, cond('title', 'contains', 'Pour'))) == ['Pour slab']
    assert write(admin, 'post', '/api/viewspecs/builder/switch', {'on': False}).json() == {'enabled': False}
    assert run(admin, cond('title', 'contains', 'Pour')).status_code == 422
    assert run(admin).json()['filter_bar'] is False and titles(run(admin)) == ['Order tiles', 'Paint walls', 'Pour slab']
    with SessionLocal() as db:
        assert [db.scalar(select(func.count()).select_from(t)) for t in (ViewSpecRow, ViewSpecVersion, Task)] == before      # nothing deleted
    assert admin.get('/api/viewspecs/mine.keep_me').json()['version'] == 1


# ------------------------------------------------------------------ filters

def test_a_view_runs_the_same_without_a_filter(admin, tasks):
    assert titles(run(admin)) == ['Order tiles', 'Paint walls', 'Pour slab']
    body = run(admin).json()
    assert body['filtered'] is False and body['record_type'] == 'system.task' and [f['name'] for f in body['fields']] == ['title', 'due_date', 'status']


def test_match_all_keeps_only_records_that_meet_every_condition(admin, tasks):
    flt = {'and': [cond('assignee', 'eq', 'Asha'), cond('due_date', 'after', 'today')]}
    assert titles(run(admin, flt)) == ['Paint walls']
    assert titles(run(admin, cond('title', 'contains', 'tiles'))) == ['Order tiles']          # one bare condition is allowed


def test_match_any_keeps_records_that_meet_at_least_one_condition_once(admin, tasks):
    flt = {'or': [cond('title', 'contains', 'Pour'), cond('title', 'contains', 'tiles'), cond('title', 'contains', 'Pour')]}
    assert titles(run(admin, flt)) == ['Order tiles', 'Pour slab']                              # a record that fits two branches shows once
    assert run(admin, flt).json()['shown']['result']['matched'] == 2


def test_dates_today_and_week_shortcuts_resolve(admin, tasks):
    assert titles(run(admin, cond('due_date', 'before', 'today'))) == ['Pour slab']
    assert titles(run(admin, {'and': [cond('due_date', 'after', 'today-8'), cond('due_date', 'before', 'today+8')]})) == ['Order tiles', 'Pour slab']
    assert titles(run(admin, cond('due_date', 'after', {'relative': 'today'}))) == ['Order tiles', 'Paint walls']
    week = {'and': [cond('due_date', 'after', 'week_start-1'), cond('due_date', 'before', 'week_start+7')]}          # "due this week"
    assert set(titles(run(admin, week))) <= {'Pour slab', 'Order tiles'}


def test_a_temporary_filter_can_only_narrow_the_view(admin, tasks):
    # the view itself leaves out finished tasks (status is not done); no filter, however written, brings them back
    assert titles(run(admin, cond('status', 'eq', 'done'))) == []
    assert titles(run(admin, {'or': [cond('status', 'eq', 'done'), cond('title', 'contains', 'Pour')]})) == ['Pour slab']
    assert titles(run(admin, cond('title', 'contains', 'snagging'))) == []             # the finished task stays out whatever is typed
    assert titles(run(admin, cond('status', 'neq', 'open'))) == []


def test_empty_and_filled_in_need_no_value(admin, tasks):
    assert titles(run(admin, cond('assignee', 'not_empty'))) == ['Order tiles', 'Paint walls', 'Pour slab']
    assert titles(run(admin, cond('assignee', 'empty'))) == []


@pytest.mark.parametrize('flt,words', [
    ('not json', 'could not be read'),
    ('[1, 2]', 'could not be read'),
    (json.dumps({'and': []}), 'between 1 and'),
    (json.dumps({'and': [cond('title', 'contains', str(i)) for i in range(bar.MAX_CONDITIONS + 1)]}), 'between 1 and'),
    (json.dumps({'and': [{'or': [cond('title', 'eq', 'x')]}]}), 'Groups inside a group'),
    (json.dumps(cond('assignee', 'eq', {'me': True})), 'cannot be used in a filter bar yet'),
    (json.dumps(cond('due_date', 'between', ['2026-01-01', '2026-02-01'])), 'cannot be used'),
    (json.dumps(cond('due_date', 'contains', 'x')), 'cannot be used'),
    (json.dumps(cond('no_such_field', 'eq', 'x')), 'not a field'),
    (json.dumps({'field': 'title', 'path': ['project', 'name'], 'op': 'eq', 'value': 'x'}), 'either field or path'),
    (json.dumps(cond('due_date', 'before', 'next tuesday')), 'Date must be'),
])
def test_bad_filters_are_refused_in_plain_words(admin, tasks, flt, words):
    r = admin.get(f'/api/viewspecs/{KEY}/run', params={'filter': flt})
    assert r.status_code == 422 and words in r.json()['detail'], r.text


def test_an_oversized_filter_is_refused(admin, tasks):
    r = admin.get(f'/api/viewspecs/{KEY}/run', params={'filter': json.dumps(cond('title', 'eq', 'x' * 3000))})
    assert r.status_code == 422


def test_match_any_is_refused_on_totals(admin, tasks):
    chart = task_list('mine.by_status', 'Tasks by status')
    chart['primitive'] = 'chart'
    chart['group'] = {'columns': {'field': 'status'}}
    chart['aggregate'] = [{'fn': 'count', 'as': 'n'}]
    save(admin, admin, 'view_create', {'spec': chart, 'scope': 'system'})
    flt = {'or': [cond('title', 'contains', 'Pour'), cond('title', 'contains', 'tiles')]}
    r = admin.get('/api/viewspecs/mine.by_status/run', params={'filter': json.dumps(flt)})
    assert r.status_code == 422 and 'not on totals' in r.json()['detail']
    ok = admin.get('/api/viewspecs/mine.by_status/run', params={'filter': json.dumps({'and': [cond('title', 'contains', 'Pour')]})})
    assert ok.status_code == 200 and ok.json()['shown']['points'][0]['text'] == '1'            # "Match all" narrows totals too


# ------------------------------------------------------------------ nothing is stored

def _counts():
    with SessionLocal() as db:
        return [db.scalar(select(func.count()).select_from(t)) for t in (ViewSpecRow, ViewSpecVersion, ApprovalTicket, Audit, Task)]


def test_a_temporary_filter_and_a_look_write_nothing(admin, tasks):
    before = _counts()
    run(admin, {'or': [cond('title', 'contains', 'Pour'), cond('assignee', 'eq', 'Ravi')]})
    run(admin, cond('due_date', 'before', 'today'), look='board')
    run(admin, look='calendar')
    assert _counts() == before
    got = admin.get(f'/api/viewspecs/{KEY}').json()
    assert got['version'] == 1 and got['spec']['primitive'] == 'table'                          # the saved view is exactly as it was


# ------------------------------------------------------------------ looks

def test_a_view_can_be_shown_as_a_board_or_a_calendar(admin, tasks):
    board = run(admin, look='board').json()
    assert board['look'] == 'board' and board['shown']['kind'] == 'board'
    assert [lane['name'] for lane in board['shown']['lanes']] == ['open'] and board['shown']['lanes'][0]['count'] == 3
    cal = run(admin, look='calendar').json()
    assert cal['look'] == 'calendar' and cal['shown']['kind'] == 'calendar'
    assert run(admin).json()['looks'] == ['table', 'board', 'calendar']
    assert titles(run(admin, cond('assignee', 'eq', 'Ravi'), look='board')) == ['Order tiles']      # a filter and a look together


def test_a_look_the_fields_cannot_show_is_refused_with_the_reason(admin, tasks):
    plain = task_list('mine.titles_only', 'Titles only')
    plain['source']['items'][0]['fields'] = [{'field': 'title'}, {'field': 'assignee'}]
    plain['source']['items'][0].pop('sort')
    save(admin, admin, 'view_create', {'spec': plain, 'scope': 'system'})
    r = admin.get('/api/viewspecs/mine.titles_only/run', params={'as': 'calendar'})
    assert r.status_code == 422 and "no date field" in r.json()['detail']
    r = admin.get('/api/viewspecs/mine.titles_only/run', params={'as': 'board'})
    assert r.status_code == 422 and "no status-like field" in r.json()['detail']
    assert admin.get('/api/viewspecs/mine.titles_only/run').json()['looks'] == ['table']
    assert run(admin, look='gallery').status_code == 422


def test_totals_and_charts_have_no_other_look(admin, tasks):
    chart = task_list('mine.by_status', 'Tasks by status')
    chart['primitive'] = 'chart'
    chart['group'] = {'columns': {'field': 'status'}}
    chart['aggregate'] = [{'fn': 'count', 'as': 'n'}]
    save(admin, admin, 'view_create', {'spec': chart, 'scope': 'system'})
    body = admin.get('/api/viewspecs/mine.by_status/run').json()
    assert body['looks'] == []
    r = admin.get('/api/viewspecs/mine.by_status/run', params={'as': 'table'})
    assert r.status_code == 422 and 'another way' in r.json()['detail']


# ------------------------------------------------------------------ what the builder offers

def test_the_builder_lists_fields_and_only_runnable_operators(admin, tasks):
    cat = admin.get('/api/viewspecs/builder').json()
    keys = [t['key'] for t in cat['types']]
    assert 'system.task' in keys and 'system.project' in keys and 'system.user' not in keys          # staff accounts are not offered
    task = next(t for t in cat['types'] if t['key'] == 'system.task')
    assert {f['name']: f['kind'] for f in task['fields']}['due_date'] == 'date'
    assert set(cat['operators']['date']) == {'eq', 'neq', 'before', 'after', 'empty', 'not_empty'}
    for kind, ops in cat['operators'].items():
        assert set(ops) <= set(bar.RUNNABLE_OPS), kind
    assert cat['operators']['relation'] == ['empty', 'not_empty'] and 'between' not in cat['operators']['number']
    assert cat['looks'] == ['table', 'board', 'calendar']


def test_everything_the_builder_offers_can_be_run(admin, tasks):
    """Each operator the builder offers for each kind of field is accepted by the check and mapped by the runner."""
    from studioos import viewspec_core as core
    for kind, ops in bar.RUNNABLE_BY_KIND.items():
        for op in ops:
            assert op in core.OPS_BY_KIND[kind]
            assert op in core._OP_TO_REPORT


def test_money_fields_are_not_offered_or_filterable_without_money_access(admin):
    write(admin, 'post', '/api/viewspecs/builder/switch', {'on': True})
    from tests.test_v098_universal_accounting import propose
    from tests.test_v098_universal_accounting import save as save_ticket
    save_ticket(admin, propose(admin, 'metadata_type', {'key': 'equipment', 'title': 'Equipment', 'description': 'Owned equipment',
        'fields': [{'name': 'serial_number', 'type': 'text', 'required': True}, {'name': 'purchase_cost', 'type': 'money', 'required': True}]}))
    admin_fields = {f['name'] for t in admin.get('/api/viewspecs/builder').json()['types'] if t['key'] == 'equipment' for f in t['fields']}
    assert admin_fields == {'serial_number', 'purchase_cost'}
    site, _ = staff(admin, 'site.filter', 'site_engineer')
    try:
        offered = {f['name'] for t in site.get('/api/viewspecs/builder').json()['types'] if t['key'] == 'equipment' for f in t['fields']}
        assert offered == {'serial_number'}
        view = task_list('mine.equipment', 'Equipment')
        view['source']['items'][0] = {'record_type': 'equipment', 'fields': [{'field': 'serial_number'}]}
        save(admin, admin, 'view_create', {'spec': view, 'scope': 'system'})
        r = site.get('/api/viewspecs/mine.equipment/run', params={'filter': json.dumps(cond('purchase_cost', 'gt', 100))})
        assert r.status_code == 422                                                              # a filter on a hidden field reveals nothing
        assert site.get('/api/viewspecs/mine.equipment/run').status_code == 200
    finally:
        site.close()


# ------------------------------------------------------------------ access

def test_a_filter_never_shows_records_the_person_may_not_see(admin, tasks):
    site, _ = staff(admin, 'site.reader', 'site_engineer')                 # not on the project
    try:
        for flt in (None, cond('assignee', 'eq', 'Asha'), {'or': [cond('title', 'contains', 'Pour'), cond('title', 'contains', 'tiles')]}):
            assert titles(run(site, flt)) == []
        assert run(site, look='board').json()['shown']['lanes'] == []
    finally:
        site.close()


def test_the_run_route_is_still_a_plain_read(admin, tasks):
    from tests.conftest import write
    assert write(admin, 'post', f'/api/viewspecs/{KEY}/run', {}).status_code == 405                # nothing here can write


# ------------------------------------------------------------------ "Match any" over more records than one screen shows

def _bulk(admin, project_id, n_asha, n_slab, n_both):
    """n_asha tasks for Asha, n_slab 'Zebra' tasks for Ravi, n_both for Asha that are also 'Zebra'. (A word the fixture tasks never use, so the
    database and the report engine agree on case.)"""
    rows = [Task(project_id=project_id, title=f'Plain {i}', assignee='Asha', status='open') for i in range(n_asha)]
    rows += [Task(project_id=project_id, title=f'Zebra {i}', assignee='Ravi', status='open') for i in range(n_slab)]
    rows += [Task(project_id=project_id, title=f'Zebra both {i}', assignee='Asha', status='open') for i in range(n_both)]
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def test_match_any_union_is_exact_and_flags_a_cut_off_branch(admin, tasks):
    _bulk(admin, tasks['id'], 260, 240, 30)
    with SessionLocal() as db:
        asha = db.scalar(select(func.count()).select_from(Task).where(Task.assignee == 'Asha', Task.status == 'open'))
        slab = db.scalar(select(func.count()).select_from(Task).where(Task.title.contains('Zebra'), Task.status == 'open'))
        both = db.scalar(select(func.count()).select_from(Task).where(Task.assignee == 'Asha', Task.title.contains('Zebra'), Task.status == 'open'))
    flt = {'or': [cond('assignee', 'eq', 'Asha'), cond('title', 'contains', 'Zebra')]}
    res = run(admin, flt).json()['shown']['result']
    assert res['matched'] == asha + slab - both and res['incomplete'] is False             # every record found by either condition, counted once
    assert len(res['rows']) == 200                                                          # the screen still shows the first 200
    ids = [row['record_id'] for row in res['rows']]
    assert len(ids) == len(set(ids))
    _bulk(admin, tasks['id'], 300, 0, 0)                                                    # now one branch alone is over the engine's 500-row cap
    res = run(admin, flt).json()['shown']['result']
    assert res['incomplete'] is True and res['matched'] >= 500                              # a lower bound, and it says so
