import json
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect

from studioos import ai_wiring
from studioos.db import ApprovalTicketItem, Document, RecordType, SessionLocal, User
from studioos.migrations import apply_migrations
from .conftest import approved_form, write
from .test_v0100_one_graph import add_user, client_for
from .test_v0110_ai_app import _turn_on
from .test_v017_work_rules_app import propose as work_propose, save as work_save
from .test_v093_mcp_app import call, key, on
from .test_v098_universal_accounting import propose, save


@pytest.fixture
def scope(admin):
    projects = [
        approved_form(admin, 'post', '/api/projects', {'name': f'Fictional Review Site {suffix}'}).json()['id']
        for suffix in ('A', 'B')
    ]
    member = add_user(admin, 'fictional.review.site', 'site_engineer')
    assigned = write(admin, 'put', f'/api/projects/{projects[0]}/members', {'user_ids': [member]})
    assert assigned.status_code == 200, assigned.text
    with client_for('fictional.review.site') as site:
        yield site, *projects


def test_task_transition_checks_project_scope(admin, scope):
    site, project_a, project_b = scope
    tasks = [
        approved_form(admin, 'post', '/api/tasks', {'project_id': pid, 'title': f'Fictional check {suffix}'}).json()['id']
        for pid, suffix in ((project_a, 'A'), (project_b, 'B'))
    ]
    work_save(admin, 'work_workflow_publish', {
        'key': 'fictional_checks', 'name': 'Fictional checks', 'applies_to': {'target': 'task'},
        'definition': {
            'statuses': [{'key': 'open', 'label': 'Open', 'class': 'open', 'start': True},
                         {'key': 'checked', 'label': 'Checked', 'class': 'closed'}],
            'transitions': [{'name': 'check', 'from': 'open', 'to': 'checked', 'roles': ['site_engineer']}],
        },
    })

    def transition(task_id):
        return work_propose(site, 'work_transition', {
            'workflow_key': 'fictional_checks', 'target': 'task', 'target_id': task_id, 'transition': 'check',
        })

    assert transition(tasks[0]).status_code == 200
    denied, missing = transition(tasks[1]), transition(999999)
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


TYPE = 'fictional_site_pay'
AMOUNT = 621739
REPORT = {'key': 'fictional_site_pay_report', 'title': 'Fictional site pay',
          'base': TYPE, 'columns': ['work_note', 'wage_amount']}


@pytest.fixture
def pay(admin, scope):
    site, project_a, project_b = scope
    save(admin, propose(admin, 'metadata_type', {
        'key': TYPE, 'title': 'Fictional site pay', 'label_field': 'wage_amount',
        'fields': [{'name': 'wage_amount', 'type': 'integer'}, {'name': 'work_note', 'type': 'text'}],
    }))
    rows = [
        save(admin, propose(admin, 'metadata_record', {'type_key': TYPE, 'project_id': pid,
             'values': {'work_note': f'Fictional work {suffix}', 'wage_amount': amount}}))['id']
        for pid, suffix, amount in ((project_a, 'A', AMOUNT), (project_b, 'B', 440123))
    ]
    save(admin, propose(admin, 'metadata_report', REPORT))
    return site, rows[0]


@pytest.mark.parametrize('path', [
    '/api/universal/records/{type}',
    '/api/universal/records/{type}/{id}',
    '/api/universal/dashboard/{type}',
    '/api/graph/records/{type}',
    '/api/graph/record/{id}',
    '/api/graph/targets/{type}',
])
def test_record_reads_hide_finance_fields(admin, pay, path):
    site, record = pay
    url = path.format(type=TYPE, id=record)
    restricted, finance = site.get(url), admin.get(url)
    assert restricted.status_code == finance.status_code == 200
    assert str(AMOUNT) in finance.text
    assert str(AMOUNT) not in restricted.text
    assert '440123' not in restricted.text
    assert 'Fictional work A' in restricted.text
    assert 'Fictional work B' not in restricted.text


def test_finance_field_cannot_filter_universal_list(pay):
    site, _ = pay
    result = site.get(f'/api/universal/records/{TYPE}',
                      params={'filter_field': 'wage_amount', 'filter_value': AMOUNT})
    assert result.status_code == 422 and 'finance only' in result.text.lower()


@pytest.mark.parametrize('surface', ['run', 'preview', 'export', 'connector'])
def test_reports_protect_finance_fields(admin, pay, monkeypatch, surface):
    site, _ = pay
    if surface == 'connector':
        on(monkeypatch)

        def run(client, password):
            token_response = key(client, password=password)
            assert token_response.status_code == 200, token_response.text
            return call(client, token_response.json()['token'], 'run_report', {'report': REPORT['key']})

        assert str(AMOUNT) in json.dumps(run(admin, 'stage1-test-password-very-long'))
        result = run(site, 'Fixture-Strong-Moss7!Keystone')
        assert result['isError'] and 'finance only' in json.dumps(result).lower()
        return

    def run(client):
        if surface == 'preview':
            return write(client, 'post', '/api/graph/reports/preview', {'definition': REPORT})
        suffix = 'export.csv' if surface == 'export' else 'run'
        return client.get(f"/api/graph/reports/{REPORT['key']}/{suffix}")

    owner, result = run(admin), run(site)
    assert owner.status_code == 200 and str(AMOUNT) in owner.text
    assert result.status_code == 422 and 'finance only' in result.text.lower()
    if surface == 'preview':
        count = {'key': 'fictional_work_count', 'title': 'Fictional work count', 'base': TYPE,
                 'figure': True, 'measures': [{'agg': 'count'}]}
        visible = write(site, 'post', '/api/graph/reports/preview', {'definition': count})
        assert visible.status_code == 200 and visible.json()['matched'] == 1, visible.text


def test_document_targets_hide_unassigned_files(admin, scope):
    site, project_a, project_b = scope
    with SessionLocal() as db:
        db.add_all(Document(name=name, relative_path=f'fictional/{name}', project_id=pid)
                   for name, pid in [('assigned.pdf', project_a), ('other.pdf', project_b), ('unassigned.pdf', None)])
        db.commit()
    url = '/api/graph/targets/system.document'
    assert {row['label'] for row in admin.get(url).json()} == {'assigned.pdf', 'other.pdf', 'unassigned.pdf'}
    assert {row['label'] for row in site.get(url).json()} == {'assigned.pdf'}


def test_reader_examples_are_project_scoped(admin, scope, monkeypatch):
    site, project_a, project_b = scope
    save(admin, propose(admin, 'metadata_type', {'key': 'fictional_check_note', 'title': 'Fictional check note',
         'fields': [{'name': 'material', 'type': 'text'}]}))
    for pid, source_pid, text in (
        (project_a, project_a, 'copper-check-example'),
        (project_b, project_b, 'granite-private-example'),
        (project_a, project_b, 'granite-moved-project-example'),
    ):
        draft = propose(admin, 'metadata_record', {'type_key': 'fictional_check_note', 'project_id': pid,
                        'values': {'material': 'Sample'}})
        with SessionLocal() as db:
            rt = db.get(RecordType, 'fictional_check_note')
            item = db.get(ApprovalTicketItem, draft['item_id'])
            user = db.get(User, admin.get('/api/auth/me').json()['user']['id'])
            ai_wiring.record_corrections(db, user, item, rt, {'material': 'Sample'}, {'material': 'Checked'},
                                         {'values.material': {'marker': 'sourced', 'source_words': text,
                                                              'source_project_id': source_pid}})
            db.commit()

    settings = write(admin, 'put', '/api/ai/settings', {
        'provider': 'claude', 'model': 'fictional-model', 'enabled': True, 'monthly_cap_usd': '2',
        'input_usd_per_1m': '3', 'output_usd_per_1m': '15',
    })
    assert settings.status_code == 200, settings.text
    fake = _turn_on(monkeypatch, lambda system, message: '{}')
    site_id = site.get('/api/auth/me').json()['user']['id']
    with SessionLocal() as db:
        ai_wiring.read_message(db, db.get(User, site_id), db.get(RecordType, 'fictional_check_note'),
                               'Fictional check note: Sample', date(2026, 11, 21),
                               [{'id': project_a, 'name': 'Fictional Review Site A'}], [])
    prompt = json.dumps(fake.calls)
    assert 'copper-check-example' in prompt
    assert 'granite-private-example' not in prompt
    assert 'granite-moved-project-example' not in prompt


def test_correction_scope_column_matches_after_upgrade():
    old = create_engine('sqlite://')
    fresh = create_engine('sqlite://')
    with old.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE ai_corrections (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('INSERT INTO ai_corrections(id) VALUES (7)')
    apply_migrations(old)
    apply_migrations(fresh)

    def scope_column(engine):
        return [(str(col['type']), col['nullable']) for col in inspect(engine).get_columns('ai_corrections')
                if col['name'] == 'project_id']

    assert scope_column(old) == scope_column(fresh) == [('INTEGER', True)]
    with old.connect() as conn:
        assert conn.exec_driver_sql('SELECT id, project_id FROM ai_corrections').one() == (7, None)
