"""v0.12.0 "Show it in any form", database-free part (standard library only).

Question or entry; question -> report (offline patterns, AI through the gateway with strict checks,
never SQL); the answer in words; single figures; display forms (table, bar, line, tiles, board,
calendar, timeline, print) checked and shaped; dashboards per role; per-type layouts; expression
index statements (run on real SQLite: the planner uses them); filters pushed to the database only
narrow. Fictional data only."""
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'views_questions'))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import world, packs, STAFF, TODAY  # noqa: E402
import run_questions  # noqa: E402

G, GW, V = load('graph_core', 'ai_gateway', 'views_core')
CAT, RES, RECS = world()
ALIASES = {k: t.get('aliases', []) for k, t in packs()[0].items()}
PEOPLE = [{'id': k, 'name': v} for k, v in STAFF.items()]
TYPE_WORDS = [w for k, t in packs()[0].items() for w in [t['title']] + t.get('aliases', [])]


def ask(q, gateway=None):
    return V.question_to_report(q, CAT, TODAY, gateway, aliases=ALIASES, people=PEOPLE)


# ------------------------------------------------------------------ question or entry

@pytest.mark.parametrize('msg,kind', [
    ('How many open issues?', 'question'), ('Open issues by owner', 'question'), ('kitne open issues hain?', 'question'),
    ('Total hours this week', 'question'), ('owner wise open issues', 'question'), ('Show overdue milestones', 'question'),
    ('Timesheet: Ravi 6 hours on drawings yesterday', 'entry'), ('Ravi 6 hours drawings yesterday', 'entry'),
    ('Add issue: lift not working', 'entry'), ('Mark Asha absent today', 'entry'),
    ('issues', 'unsure'), ('Ravi Fictional Tower', 'unsure'), ('Show me how to log 6 hours?', 'unsure'),
])
def test_question_or_entry(msg, kind):
    assert V.classify(msg, TYPE_WORDS)['kind'] == kind


# ------------------------------------------------------------------ question -> report

def test_fifty_questions_offline_no_wrong_answer(tmp_path):
    r = run_questions.main(['--out', str(tmp_path / 'q.json')])
    assert r['questions'] == 50 and r['totals']['wrong'] == 0
    h = run_questions.main(['--set', str(ROOT / 'tests' / 'views_questions' / 'questions_holdout.json'), '--out', str(tmp_path / 'h.json')])
    assert h['totals']['wrong'] == 0


def test_answer_is_a_report_definition_in_words_never_sql():
    out = ask('Open issues by owner this week')
    assert out['status'] == 'ok' and out['source'] == 'offline'
    d = out['report']
    assert d['base'] == 'work_issue' and d['group_by'] == ['owner'] and {'path': 'issue_status', 'op': 'eq', 'value': 'Open'} in d['filters']
    assert 'select' not in json.dumps(d).lower()
    words = out['words']
    assert words.startswith('Shows the number of work issue records') and 'status is Open' in words and 'for each owner' in words
    assert 'Only records you are allowed to see' in words


def test_describe_dates_and_numbers_in_plain_words():
    d = {'key': 'xx', 'title': 'x', 'base': 'timesheet_entry', 'group_by': ['employee'], 'measures': [{'agg': 'sum', 'path': 'hours'}],
         'filters': [{'path': 'work_date', 'op': 'gte', 'value': 'today-7'}, {'path': 'hours', 'op': 'gt', 'value': '4'}]}
    w = V.describe(d, CAT)
    assert 'the total hours' in w.lower() and '7 days before today' in w and 'is more than 4' in w


def _gw(reply):
    s = {'enabled': True, 'provider': 'claude', 'model': 'fictional', 'monthly_cap_usd': '1', 'input_usd_per_1m': '1', 'output_usd_per_1m': '1'}
    return GW.Gateway(s, GW.FakeTransport(reply, 10, 10), GW.MemoryLog(), {'STUDIOOS_ALLOW_LIVE_AI': 'true'})


def test_ai_report_is_used_only_when_it_passes_check_report():
    good = _gw(json.dumps({'base': 'work_issue', 'group_by': ['severity'], 'measures': [{'agg': 'count'}]}))
    out = ask('break issues down by how bad they are', good)
    assert out['source'] == 'ai' and out['report']['group_by'] == ['severity']
    for bad in ('SELECT * FROM users', json.dumps({'sql': 'DROP TABLE x'}), json.dumps({'base': 'gl_lines', 'columns': ['amount']}),
                json.dumps({'base': 'work_issue', 'group_by': ['password']}), json.dumps({'base': 'work_issue', 'filters': [{'path': 'owner.password', 'op': 'eq', 'value': 'x'}], 'columns': ['title']})):
        gw = _gw(bad)
        out = ask('Open issues by owner', gw)
        assert out['source'] == 'offline' and out['report']['group_by'] == ['owner']
        assert gw.log.rows[-1]['outcome'] == 'invalid'


def test_unclear_questions_are_asked_back():
    for q in ('How are we doing?', 'Issues by colour', 'How many?', 'Total cost by supplier'):
        assert ask(q)['status'] == 'unsure'


def test_single_figure_and_its_display():
    out = ask('Total hours this week')
    assert out['report']['figure'] is True
    res = V.run(RES, CAT, out['report'], TODAY)
    assert res['mode'] == 'figure' and res['figures'][0]['label'].startswith('Sum of')
    tiles = V.shape({'kind': 'tiles'}, res)
    assert tiles['tiles'][0]['value'] == res['figures'][0]['value']


# ------------------------------------------------------------------ display forms

def _grouped(q='Total hours by person this week'):
    d = ask(q)['report']
    return d, V.run(RES, CAT, d, TODAY)


def test_bar_and_line_charts_get_exact_numbers():
    d, res = _grouped()
    V.check_display({'kind': 'bar'}, d, CAT)
    bar = V.shape({'kind': 'bar'}, res)
    assert len(bar['points']) == len(res['rows'])
    assert all(p['value'] == r['numbers'][0] for p, r in zip(bar['points'], res['rows']))
    with pytest.raises(G.GraphError):
        V.check_display({'kind': 'line'}, d, CAT)                     # first group is a person, not a date
    by_day = {'key': 'xx', 'title': 'Hours by day', 'base': 'timesheet_entry', 'group_by': ['work_date'],
              'measures': [{'agg': 'sum', 'path': 'hours'}], 'filters': [{'path': 'work_date', 'op': 'gte', 'value': 'today-6'}]}
    V.check_display({'kind': 'line'}, by_day, CAT)
    line = V.shape({'kind': 'line'}, V.run(RES, CAT, by_day, TODAY))
    assert [p['label'] for p in line['points']] == sorted(p['label'] for p in line['points'])


def test_board_calendar_and_timeline_need_the_right_columns():
    lst = {'key': 'xx', 'title': 'Issues', 'base': 'work_issue', 'columns': ['title', 'issue_status', 'due_date', 'owner']}
    V.check_display({'kind': 'board', 'column': 1}, lst, CAT)
    res = V.run(RES, CAT, lst, TODAY)
    board = V.shape({'kind': 'board', 'column': 1}, res, lst, CAT)
    assert [l['name'] for l in board['lanes']] == [o for o in ['Open', 'In progress', 'Resolved', 'Closed'] if any(l['name'] == o for l in board['lanes'])]
    assert sum(l['count'] for l in board['lanes']) == len(res['rows'])
    V.check_display({'kind': 'calendar', 'date_column': 2}, lst, CAT)
    cal = V.shape({'kind': 'calendar', 'date_column': 2}, res, lst, CAT, TODAY)
    assert sum(d['count'] for d in cal['days']) == sum(1 for r in res['rows'] if r['cells'][2] != '(none)')
    for bad in ({'kind': 'calendar', 'date_column': 0}, {'kind': 'board', 'column': 9}, {'kind': 'timeline', 'start_column': 2},
                {'kind': 'pie'}, {'kind': 'table', 'script': 'x'}):
        with pytest.raises(G.GraphError):
            V.check_display(bad, lst, CAT)
    leave = {'key': 'yy', 'title': 'Leave', 'base': 'leave_request', 'columns': ['employee', 'from_date', 'to_date', 'leave_type']}
    V.check_display({'kind': 'timeline', 'start_column': 1, 'end_column': 2}, leave, CAT)
    tl = V.shape({'kind': 'timeline', 'start_column': 1, 'end_column': 2}, V.run(RES, CAT, leave, TODAY))
    assert tl['bars'] and tl['start'] <= tl['bars'][0]['start'] and all(b['start'] <= b['end'] for b in tl['bars'])
    with pytest.raises(G.GraphError):
        V.check_display({'kind': 'board', 'column': 0}, ask('Open issues by owner')['report'], CAT)   # grouped, not a list


# ------------------------------------------------------------------ dashboards and layouts

def test_dashboards_per_role():
    reports = {'open_issues_by_owner': {}, 'hours_this_week': {}}
    d = V.check_dashboard({'key': 'site_home', 'title': 'Site team', 'roles': ['site_engineer', 'architect'],
                           'tiles': [{'report': 'open_issues_by_owner', 'display': {'kind': 'bar'}}, {'report': 'hours_this_week'}]}, reports)
    m = V.check_dashboard({'key': 'mgr_home', 'title': 'Managers', 'roles': ['manager'], 'tiles': [{'report': 'hours_this_week'}]}, reports)
    assert V.dashboard_for('site_engineer', [d, m])['key'] == 'site_home'
    assert V.dashboard_for('manager', [d, m])['key'] == 'mgr_home'
    assert V.dashboard_for('viewer', [d, m]) is None
    assert V.dashboard_for('admin', [d, m])['key'] == 'mgr_home'
    for bad in ({'key': 'xx', 'title': 'X1', 'roles': [], 'tiles': [{'report': 'hours_this_week'}]},
                {'key': 'xx', 'title': 'X1', 'roles': ['boss'], 'tiles': [{'report': 'hours_this_week'}]},
                {'key': 'xx', 'title': 'X1', 'roles': ['manager'], 'tiles': [{'report': 'nope'}]},
                {'key': 'xx', 'title': 'X1', 'roles': ['manager'], 'tiles': [{'report': 'hours_this_week'}] * 13}):
        with pytest.raises(G.GraphError):
            V.check_dashboard(bad, reports)


def test_layouts_are_checked_and_suggested_offline():
    fields = next(t for t in packs()[0].values() if t['key'] == 'work_issue')['fields']
    lay = V.suggest_layout('work_issue', fields)
    names = [f for s in lay['sections'] for f in s['fields']]
    assert sorted(names) == sorted(f['name'] for f in fields) and len(names) == len(set(names))
    assert V.apply_layout(lay, fields) == lay['sections']
    part = {'type_key': 'work_issue', 'sections': [{'title': 'Who', 'fields': ['owner']}]}
    V.check_layout(part, fields)
    assert V.apply_layout(part, fields)[-1]['title'] == 'Other'
    for bad in ({'type_key': 'work_issue', 'sections': [{'title': 'A', 'fields': ['owner']}, {'title': 'B', 'fields': ['owner']}]},
                {'type_key': 'work_issue', 'sections': [{'title': 'A', 'fields': ['nope']}]},
                {'type_key': 'work_issue', 'sections': [{'title': 'A', 'fields': ['owner'], 'html': '<b>'}]}):
        with pytest.raises(G.GraphError):
            V.check_layout(bad, fields)


# ------------------------------------------------------------------ speed

def test_index_statements_are_safe_and_used_by_sqlite():
    d = ask('Open issues by owner')['report']
    pairs = V.indexed_fields(CAT, d)
    assert ('work_issue', 'issue_status') in pairs and ('work_issue', 'owner') in pairs
    with pytest.raises(G.GraphError):
        V.index_statement('sqlite', "work_issue'; DROP TABLE x; --", 'owner')
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE flexible_records (id INTEGER PRIMARY KEY, record_type TEXT, data JSON, deleted_at TEXT)')
    con.executemany('INSERT INTO flexible_records (record_type, data) VALUES (?, ?)',
                    [('work_issue', json.dumps({'issue_status': 'Open' if i % 5 else 'Closed'})) for i in range(3000)])
    for t, f in pairs:
        con.execute(V.index_statement('sqlite', t, f))
        con.execute(V.index_statement('sqlite', t, f))          # twice: nothing changes
    plan = con.execute("EXPLAIN QUERY PLAN SELECT id FROM flexible_records WHERE record_type = 'work_issue' AND deleted_at IS NULL "
                       "AND json_extract(data, '$.issue_status') = 'Open'").fetchall()
    assert any(V.index_name('work_issue', 'issue_status') in str(row) for row in plan)
    pg = V.index_statement('postgresql', 'work_issue', 'issue_status')
    assert "((data ->> 'issue_status'))" in pg and "record_type = 'work_issue'" in pg


def test_pushed_filters_only_narrow():
    d = {'key': 'xx', 'title': 'x', 'base': 'work_issue', 'columns': ['title'],
         'filters': [{'path': 'issue_status', 'op': 'eq', 'value': 'Open'}, {'path': 'due_date', 'op': 'gte', 'value': 'today-7'},
                     {'path': 'owner', 'op': 'eq', 'value': 'Asha Rao'}, {'path': 'title', 'op': 'contains', 'value': 'x'}]}
    pushed = V.pushable_filters(CAT, d, TODAY)
    assert pushed == [('issue_status', 'eq', 'Open'), ('due_date', 'gte', '2026-11-07')]
