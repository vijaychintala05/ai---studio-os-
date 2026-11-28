"""v0.12.0 "Show it in any form" (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the
build sandbox).

A question is answered in words with its first rows and saves nothing; answers are limited by access;
a report saved with a display and visible_to is listed and run only for those roles; a figure report
runs and exports; dashboards and layouts are Admin tickets stored as append-only versions; home shows
your role's dashboard; filters pushed to the database give the same answer; approving a report makes
its expression indexes. Fictional data, disposable database."""
from sqlalchemy import select, func, text

from .conftest import write, approved_form
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import install, add_user, client_for
from studioos.db import SessionLocal, engine, UniversalViewDefinition
from studioos import views_core as V


def _issue(admin, pid, owner, sev='High', status='Open'):
    return save(admin, propose(admin, 'metadata_record', {'type_key': 'work_issue', 'project_id': pid, 'values': {
        'title': f'Fictional {sev} issue', 'owner': owner, 'severity': sev, 'issue_status': status}}))['id']


def test_question_answered_in_words_and_limited_by_access(admin):
    install(admin, 'work')
    pa = project(admin)
    pb = approved_form(admin,'post','/api/projects', {'name': 'Fictional Project B', 'budget': '500000'}).json()['id']
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    write(admin, 'put', f'/api/projects/{pa}/members', {'user_ids': [asha]})
    for pid in (pa, pa, pb):
        _issue(admin, pid, asha)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(UniversalViewDefinition))
    r = write(admin, 'post', '/api/views/ask', {'question': 'How many open issues?'}).json()
    assert r['status'] == 'ok' and r['result']['figures'][0]['value'] == '3' and 'Only records you are allowed to see' in r['words']
    mine = write(client_for('asha.rao'), 'post', '/api/views/ask', {'question': 'How many open issues?'}).json()
    assert mine['result']['figures'][0]['value'] == '2'
    assert write(admin, 'post', '/api/views/ask', {'question': 'How are we doing?'}).json()['status'] == 'unsure'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalViewDefinition)) == before
    assert write(admin, 'post', '/api/views/classify', {'message': 'Open issues by owner'}).json()['kind'] == 'question'


def test_printable_report_draft_preserves_open_status_and_named_project(admin):
    install(admin, 'work')
    target = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Kapoor Villa'}).json()['id']
    other = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Villa'}).json()['id']
    owner = add_user(admin, 'fictional.report.owner', 'architect')
    matching_issue = _issue(admin, target, owner, 'High', 'Open')
    _issue(admin, target, owner, 'Low', 'Closed')
    _issue(admin, other, owner, 'Low', 'Open')
    question = 'Produce a printable list of open snags for Fictional Kapoor Villa to hand to the contractor.'
    assert write(admin, 'post', '/api/views/classify', {'message': question}).json()['kind'] == 'question'
    answer = write(admin, 'post', '/api/views/ask', {'question': question}).json()
    assert answer['status'] == 'ok', answer
    definition = answer['report']
    assert {'path': 'issue_status', 'op': 'eq', 'value': 'Open'} in definition['filters']
    assert {'path': 'project.name', 'op': 'eq', 'value': 'Fictional Kapoor Villa'} in definition['filters']
    assert [row['record_id'] for row in answer['result']['rows']] == [matching_issue]
    printed = write(admin, 'post', '/api/views/show', {'definition': definition, 'display': {'kind': 'print'}}).json()
    assert [row['record_id'] for row in printed['result']['rows']] == [matching_issue]
    report = {**definition, 'key': 'fictional_open_snags', 'display': {'kind': 'print'}}
    draft = propose(admin, 'metadata_report', report)
    assert draft['ticket_id']
    item = admin.get(f'/api/tickets/{draft["ticket_id"]}').json()['items'][0]
    assert item['after']['filters'] == definition['filters']


def test_saved_report_display_visibility_and_figure_export(admin):
    install(admin, 'work')
    pa = project(admin)
    owner = add_user(admin, 'ravi.kumar', 'architect')
    _issue(admin, pa, owner)
    save(admin, propose(admin, 'metadata_report', {'key': 'issues_by_owner_mgr', 'title': 'Issues by owner (managers)', 'base': 'work_issue',
                                                   'group_by': ['owner'], 'display': {'kind': 'bar'}, 'visible_to': ['manager']}))
    save(admin, propose(admin, 'metadata_report', {'key': 'open_issue_count', 'title': 'Open issues', 'base': 'work_issue', 'figure': True,
                                                   'measures': [{'agg': 'count'}], 'filters': [{'path': 'issue_status', 'op': 'eq', 'value': 'Open'}]}))
    arch = client_for('ravi.kumar')
    assert 'issues_by_owner_mgr' not in [r['key'] for r in arch.get('/api/graph/reports').json()]
    assert arch.get('/api/graph/reports/issues_by_owner_mgr/run').status_code == 404
    add_user(admin, 'meera.iyer', 'manager')
    assert client_for('meera.iyer').get('/api/graph/reports/issues_by_owner_mgr/run').status_code == 200
    fig = admin.get('/api/graph/reports/open_issue_count/run').json()
    assert fig['mode'] == 'figure' and fig['figures'][0]['value'] == '1'
    assert admin.get('/api/graph/reports/open_issue_count/export.csv').text.splitlines()[1] == '1'
    bad = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_report', 'data': {'key': 'bad_line', 'title': 'Bad',
                'base': 'work_issue', 'group_by': ['owner'], 'display': {'kind': 'line'}}, 'evidence': 'fictional test evidence'})
    assert bad.status_code == 422


def test_dashboards_and_layouts_are_admin_tickets_with_versions(admin):
    install(admin, 'work')
    install(admin, 'people')
    save(admin, propose(admin, 'metadata_report', {'key': 'issues_by_severity', 'title': 'Issues by severity', 'base': 'work_issue', 'group_by': ['severity']}))
    d = {'key': 'site_home', 'title': 'Site team', 'roles': ['site_engineer'], 'tiles': [{'report': 'issues_by_severity', 'display': {'kind': 'tiles'}}]}
    save(admin, propose(admin, 'metadata_dashboard', d))
    save(admin, propose(admin, 'metadata_dashboard', {**d, 'title': 'Site team (v2)'}))
    add_user(admin, 'asha.rao', 'site_engineer')
    home = client_for('asha.rao').get('/api/views/home').json()
    assert home['dashboard']['title'] == 'Site team (v2)' and home['dashboard']['version'] == 2 and home['tiles'][0]['view']['kind'] == 'tiles'
    sugg = admin.post('/api/views/layout/work_issue/suggest', headers={'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')}).json()
    save(admin, propose(admin, 'metadata_layout', sugg['layout']))
    assert admin.get('/api/views/layout/work_issue').json()['layout']['sections']
    add_user(admin, 'meera.iyer', 'manager')
    mgr = client_for('meera.iyer')
    p = write(mgr, 'post', '/api/universal/proposals', {'kind': 'metadata_dashboard', 'data': {**d, 'key': 'mgr_home'}, 'evidence': 'fictional test evidence'})
    if p.status_code == 200:
        assert write(mgr, 'post', f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save', {}).status_code == 403
    with SessionLocal() as db:
        row = db.scalar(select(UniversalViewDefinition))
        try:
            db.execute(text('DELETE FROM universal_view_definitions WHERE id = :i'), {'i': row.id}); db.flush()
            assert False, 'append-only'
        except Exception:
            db.rollback()


def test_pushed_filters_same_answer_and_indexes_made(admin):
    install(admin, 'work')
    pa = project(admin)
    owner = add_user(admin, 'ravi.kumar', 'architect')
    for sev, st in (('High', 'Open'), ('Low', 'Open'), ('High', 'Closed')):
        _issue(admin, pa, owner, sev, st)
    defn = {'key': 'open_high', 'title': 'Open high', 'base': 'work_issue', 'columns': ['title'],
            'filters': [{'path': 'issue_status', 'op': 'eq', 'value': 'Open'}, {'path': 'severity', 'op': 'in', 'value': ['High']}]}
    r = write(admin, 'post', '/api/graph/reports/preview', {'definition': defn}).json()
    assert len(r['rows']) == 1
    save(admin, propose(admin, 'metadata_report', defn))
    q = ("SELECT indexname FROM pg_indexes WHERE tablename = 'flexible_records'" if engine.dialect.name == 'postgresql'
         else "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'flexible_records'")
    with engine.connect() as c:
        names = {r[0] for r in c.execute(text(q))}
    assert V.index_name('work_issue', 'issue_status') in names and V.index_name('work_issue', 'severity') in names
