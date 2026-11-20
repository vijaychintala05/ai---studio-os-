"""Running stored views: a spec becomes a report for the existing permission-aware engine and its display; unsupported specs say so;
the API returns data shaped for the browser and only counts what the person may see. Fictional data."""
import copy
from pathlib import Path

import pytest

from studioos import viewspec_core as v
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff
from tests.test_viewspec_app import save, task_list


def test_a_table_spec_becomes_a_report():
    spec = task_list()
    report, display = v.spec_to_report(spec)
    assert report['base'] == 'system.task' and report['columns'] == ['title', 'due_date', 'status']
    assert report['filters'] == [{'path': 'status', 'op': 'ne', 'value': 'done'}] and display == {'kind': 'table'}
    assert report['key'] == 'spec_mine_open_tasks'


def test_board_calendar_timeline_and_chart_set_their_columns():
    s = task_list()
    s['primitive'] = 'board'
    s['group'] = {'columns': {'field': 'status'}}
    r, d = v.spec_to_report(s)
    assert d == {'kind': 'board', 'column': r['columns'].index('status')}
    s = task_list()
    s['primitive'] = 'calendar'
    s['layout'] = {'date_field': 'due_date'}
    r, d = v.spec_to_report(s)
    assert d == {'kind': 'calendar', 'date_column': 1}
    s = task_list()
    s['primitive'] = 'chart'
    s['group'] = {'columns': {'field': 'status'}}
    s['aggregate'] = [{'fn': 'count', 'as': 'n'}]
    r, d = v.spec_to_report(s)
    assert r['group_by'] == ['status'] and r['measures'] == [{'agg': 'count', 'label': 'n'}] and d == {'kind': 'bar'}
    s['group'] = {}
    r, d = v.spec_to_report(s)
    assert r['figure'] is True and 'group_by' not in r


def test_params_relative_dates_and_optional_context():
    s = task_list()
    s['source']['items'][0]['filter'] = {'and': [{'field': 'project', 'op': 'eq', 'value': {'param': 'project_id'}},
                                                  {'field': 'due_date', 'op': 'before', 'value': {'relative': 'today'}}]}
    r, _ = v.spec_to_report(s, {'project_id': 7})
    assert r['filters'] == [{'path': 'project', 'op': 'eq', 'value': 7}, {'path': 'due_date', 'op': 'lt', 'value': 'today'}]
    r, _ = v.spec_to_report(s)                                           # context not given: that condition is left out
    assert r['filters'] == [{'path': 'due_date', 'op': 'lt', 'value': 'today'}]


@pytest.mark.parametrize('change,text', [
    (lambda s: s.update(primitive='gallery'), 'gallery'),
    (lambda s: s['source']['items'].append(copy.deepcopy(s['source']['items'][0])), 'several record types'),
    (lambda s: s['source']['items'][0].update(filter={'or': [{'field': 'status', 'op': 'eq', 'value': 'x'}]}), 'or-filters'),
    (lambda s: s['source']['items'][0].update(filter={'and': [{'field': 'assignee', 'op': 'eq', 'value': {'me': True}}]}), 'signed-in person'),
    (lambda s: s['source']['items'][0].update(filter={'and': [{'field': 'due_date', 'op': 'within_last', 'value': 7}]}), 'operator'),
])
def test_unsupported_specs_say_why(change, text):
    s = task_list()
    change(s)
    with pytest.raises(v.Unsupported, match=text):
        v.spec_to_report(s)


def test_the_run_endpoint_counts_only_what_the_person_may_see(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Run', 'budget': '100000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'X', 'due_date': '2026-12-01'})
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Order tiles', 'assignee': 'Y', 'due_date': '2026-12-02'})
    save(admin, admin, 'view_create', {'spec': task_list(), 'scope': 'system'})
    r = admin.get('/api/viewspecs/mine.open_tasks/run')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['name'] == 'Open tasks' and body['primitive'] == 'table' and body['shown']['kind'] == 'table'
    cells = [c for row in body['shown']['result']['rows'] for c in row['cells']]
    assert 'Pour slab' in cells and 'Order tiles' in cells
    site, _ = staff(admin, 'site.run', 'site_engineer')           # not on the project: the engine shows them none of it
    try:
        shown = site.get('/api/viewspecs/mine.open_tasks/run').json()['shown']
        assert [c for row in shown['result']['rows'] for c in row['cells']] == []
    finally:
        site.close()


def test_a_chart_view_runs_and_an_unsupported_one_is_422(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Chart', 'budget': '100000'}).json()
    for t in ('A', 'B'):
        approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': f'Task {t}', 'assignee': 'X', 'due_date': '2026-12-01'})
    chart = task_list('mine.by_status', 'Tasks by status')
    chart['primitive'] = 'chart'
    chart['group'] = {'columns': {'field': 'status'}}
    chart['aggregate'] = [{'fn': 'count', 'as': 'n'}]
    save(admin, admin, 'view_create', {'spec': chart, 'scope': 'system'})
    body = admin.get('/api/viewspecs/mine.by_status/run').json()
    assert body['shown']['kind'] == 'bar' and body['shown']['points'] and body['shown']['points'][0]['text'] == '2'
    gallery = task_list('mine.gallery', 'Gallery')
    gallery['primitive'] = 'gallery'
    gallery['source']['items'][0]['fields'] = [{'field': 'title'}]
    assert write(admin, 'post', '/api/viewspecs/validate', {'spec': gallery}).json()['valid'] is False      # no image field on tasks
    assert admin.get('/api/viewspecs/no.such/run').status_code == 404


def test_a_feed_is_a_dated_list_the_date_first_and_it_runs(admin):
    spec = task_list('mine.feed', 'Task feed')
    spec['primitive'] = 'feed'
    spec['layout'] = {'date_field': 'due_date'}
    report, display = v.spec_to_report(spec)
    assert report['columns'][0] == 'due_date' and report['sort'] == 'first_column' and display == {'kind': 'table'}
    no_date = task_list('mine.feed2')
    no_date['primitive'] = 'feed'
    assert write(admin, 'post', '/api/viewspecs/validate', {'spec': no_date}).json()['valid'] is False                 # a feed names its date field
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Feed', 'budget': '1000'}).json()
    for title, due in (('Second', '2026-12-02'), ('First', '2026-12-01')):
        approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': title, 'assignee': 'X', 'due_date': due})
    save(admin, admin, 'view_create', {'spec': spec, 'scope': 'system'})
    body = admin.get('/api/viewspecs/mine.feed/run').json()
    rows = body['shown']['result']['rows']
    assert body['primitive'] == 'feed' and [r['cells'][0] for r in rows] == ['2026-12-01', '2026-12-02']           # oldest first from the engine
    js = (Path(__file__).resolve().parent.parent / 'studioos' / 'static' / 'newwork.js').read_text(encoding='utf-8')
    assert 'function nwFeed' in js and '.reverse()' in js and "r.primitive === 'feed'" in js                       # the screen shows newest first
