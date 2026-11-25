"""Read-route inventory and role sweep with strictly fictional project records."""
import json
import re
from contextlib import ExitStack
from pathlib import Path

import pytest
from sqlalchemy import select

from studioos import ai_wiring
from studioos.db import Document, Project, RecordType, SessionLocal, User
from .api_surface import current_surface
from .conftest import approved_form, write
from .test_v018_time_app import staff
from .test_v098_universal_accounting import finance_setup, propose, save


INVENTORY = Path(__file__).parent / 'fixtures' / 'access_read_routes.txt'
PROJECTS = (
    ('Cedar Workshop G5', '123456.78', 'Fictional Cedar Household'),
    ('Marigold Archive G5', '876543.21', 'Fictional Marigold Family'),
)
AMOUNTS = ('123456.78', '12345678', '876543.21', '87654321', '543219.87', '54321987')
COST = 'G5 concealed service charge'
MISSING = 987654321
TYPE = 'fictional_g5_note'
READ_QUERY = {
    '/api/search': {'q': 'G5'},
    '/api/books/reports/budget-vs-actual': {'year_month': '2026-11'},
    '/api/universal/documents/due': {'project_id': '{project_id}'},
    '/api/site-expenses/options': {'project_id': '{project_id}'},
}
# Missing records are intentional for resources not created by this fixture. Happy
# paths for those resource types remain covered by their dedicated feature tests.
ABSENT_PARAMETERS = dict.fromkeys((
    'account_id', 'action_id', 'bank_id', 'bill_id', 'chart_index', 'inbox_id',
    'invoice_id', 'issue_id', 'item_id', 'obj_id', 'photo_id', 'po_id', 'ticket_id',
    'version',
), MISSING)


def read_paths():
    return [line for line in INVENTORY.read_text(encoding='utf-8').splitlines() if line.startswith('/')]


def test_every_read_endpoint_is_in_the_sweep():
    paths = read_paths()
    assert len(paths) == len(set(paths))
    expected = {r['path'] for r in current_surface()['routes'] if 'GET' in r['methods']}
    assert set(paths) == expected
    assert set(READ_QUERY) <= expected


@pytest.fixture
def sweep(admin, monkeypatch):
    monkeypatch.delenv('STUDIOOS_NAS_ROOT', raising=False)
    project_ids = []
    for name, budget, client in PROJECTS:
        row = approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': budget, 'client': client})
        assert row.status_code == 200, row.text
        project_ids.append(row.json()['id'])
    visible, hidden = project_ids
    cost = approved_form(admin, 'post', '/api/costs', {'project_id': visible, 'kind': 'expense',
                         'title': COST, 'amount': '543219.87'})
    assert cost.status_code == 200, cost.text
    company = finance_setup(admin)
    save(admin, propose(admin, 'metadata_type', {
        'key': TYPE, 'title': 'Fictional field note',
        'fields': [{'name': 'note', 'type': 'text'}],
    }))
    with SessionLocal() as db:
        documents = [Document(project_id=pid, name=name+'.pdf', relative_path='fictional/'+name+'.pdf',
                              doc_type='pdf', size_bytes=42)
                     for pid, (name, _, _) in zip(project_ids, PROJECTS)]
        db.add_all(documents)
        db.commit()
        document_ids = [doc.id for doc in documents]
        client_ids = [db.get(Project, ident).client_id for ident in project_ids]
    with ExitStack() as stack:
        people = {}
        for role in ('site_engineer', 'architect', 'manager', 'accounts'):
            browser, uid = staff(admin, f'fictional.g5.{role}', role)
            stack.callback(browser.close)
            people[role] = (browser, uid)
            if role in ('site_engineer', 'architect'):
                result = write(admin, 'put', f'/api/projects/{visible}/members', {'user_ids': [
                    identity for _, identity in people.values()
                ]})
                assert result.status_code == 200, result.text
        yield people, project_ids, company, document_ids, client_ids


def _arguments(project_id, company, document_id, client_id):
    return {**ABSENT_PARAMETERS, 'project_id': project_id, 'entity_id': company,
            'document_id': document_id, 'client_id': client_id, 'party_id': client_id,
            'record_id': MISSING, 'key': 'fictional-not-present', 'type_key': TYPE,
            'target': 'system.document', 'kind': 'task', 'name': 'fictional-not-present',
            'pack': 'fictional-not-present', 'session_id': 'fictional-no-session',
            'sha256': '0' * 64}


def _check_payload(body, *, scoped):
    if scoped:
        assert PROJECTS[1][0].casefold() not in body.casefold(), 'unassigned project name'
        assert PROJECTS[1][2].casefold() not in body.casefold(), 'unassigned client name'
        assert COST.casefold() not in body.casefold(), 'protected cost title'
        plain = body.replace(',', '')
        assert not any(amount in plain for amount in AMOUNTS), 'protected amount'


def test_access_sweep(sweep):
    people, projects, company, documents, clients = sweep
    assigned = _arguments(projects[0], company, documents[0], clients[0])
    hidden = _arguments(projects[1], company, documents[1], clients[1])
    failures = []
    for role, (browser, _) in people.items():
        scoped = role in ('site_engineer', 'architect')
        for path in read_paths():
            query = READ_QUERY.get(path, {})
            cases = [assigned, hidden] if scoped and (
                {'project_id', 'client_id', 'document_id', 'party_id'} & set(re.findall(r'\{([^{}]+)\}', path)) or
                '{project_id}' in query.values()
            ) else [assigned]
            for args in cases:
                url = path.format(**args)
                params = {key: str(value).format(**args) for key, value in query.items()}
                if path.startswith('/api/books/reports/'):
                    params['entity_id'] = company
                try:
                    response = browser.get(url, params=params)
                    assert response.status_code in (200, 204, 302, 303, 400, 401, 403, 404, 405, 409, 410, 422, 429, 501), response.status_code
                    if path.startswith('/api/books/reports/'):
                        assert response.status_code == (200 if role == 'accounts' else 403), response.text
                    _check_payload(response.text, scoped=scoped)
                except Exception as exc:
                    failures.append(f'{role} GET {url}: {type(exc).__name__}: {exc}')
        assert {row['id'] for row in browser.get('/api/projects').json()} == (
            {projects[0]} if scoped else set(projects)
        )
        if scoped:
            assert browser.get(f'/api/projects/{projects[1]}/page').status_code == 404
            assert browser.get('/api/books/home').status_code == 403
    assert not failures, '\n'.join(failures)


def test_ai_contexts_stay_inside_current_project_and_money_scope(sweep, monkeypatch):
    from studioos import main

    captures = {}
    def capture(message, projects, provider, **kwargs):
        captures[message] = {'projects': projects, **kwargs}
        return {'intent': 'unknown', 'data': {}}

    monkeypatch.setattr(main, 'extract', capture)
    people, projects, *_ = sweep
    for role, (browser, user_id) in people.items():
        scoped = role in ('site_engineer', 'architect')
        message = f'What do you have for me today? {role}'
        result = write(browser, 'post', '/api/chat', {'message': message})
        assert result.status_code == 200, result.text
        context = captures[message]
        assert {row['id'] for row in context['projects']} == (
            {projects[0]} if scoped else set(projects)
        )
        _check_payload(json.dumps(context), scoped=scoped)
        with SessionLocal() as db:
            records = [{'id': row.id, 'name': row.name} for row in db.scalars(select(Project))]
            context = ai_wiring.reader_context(db, db.get(User, user_id), db.get(RecordType, TYPE), records, [])
        assert {row['id'] for row in context['projects']} == (
            {projects[0]} if scoped else set(projects)
        )
        _check_payload(json.dumps(context), scoped=scoped)


def test_ask_does_not_reuse_unscoped_history_after_a_staff_assignment_changes(admin, sweep, monkeypatch):
    from studioos import main

    captured = []
    def capture(message, projects, provider, **kwargs):
        captured.append({'projects': projects, **kwargs})
        return {'intent': 'unknown', 'data': {}}

    monkeypatch.setattr(main, 'extract', capture)
    people, projects, *_ = sweep
    site, _ = people['site_engineer']
    first = write(site, 'post', '/api/chat', {'message': f'What is next for {PROJECTS[0][0]}?'})
    assert first.status_code == 200, first.text
    assert len(captured) == 1 and len(captured[0]['projects']) == 1

    result = write(admin, 'put', f'/api/projects/{projects[0]}/members', {
        'user_ids': [people['architect'][1]],
    })
    assert result.status_code == 200, result.text
    second = write(site, 'post', '/api/chat', {'session_id': first.json()['session_id'], 'message': 'What is next now?'})
    assert second.status_code == 200, second.text
    assert len(captured) == 2
    assert captured[1]['projects'] == []
    assert PROJECTS[0][0] not in json.dumps(captured[1])
