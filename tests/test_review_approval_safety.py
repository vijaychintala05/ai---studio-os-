from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from studioos import runtime_clock
from studioos.db import Audit, SessionLocal
from .conftest import approved_undo, write
from .test_v025_approval_limits import draft_cost, set_limits, team  # noqa: F401


def draft(client, path, data):
    response = write(client, 'post', path, data)
    assert response.status_code == 200, response.text
    return response.json()


def save(client, ticket_id):
    response = write(client, 'post', f'/api/tickets/{ticket_id}/approve-and-save')
    assert response.status_code == 200, response.text
    return response.json()['committed_records'][0]['id']


def item(client, ticket_id):
    return client.get(f'/api/tickets/{ticket_id}').json()['items'][0]


def test_reversed_cost_stays_undone(admin, team):
    project_id, _, accounts = team
    ticket_id = draft_cost(accounts, project_id, 123)
    save(admin, ticket_id)
    assert approved_undo(admin, ticket_id, 'Fictional purchase cancelled').status_code == 200
    response = write(admin, 'post', f'/api/tickets/{ticket_id}/commit')
    assert (response.status_code, len(admin.get('/api/costs').json())) == (409, 0)


@pytest.mark.parametrize(('path', 'data'), [
    ('/api/costs', {'title': 'Fictional tiles', 'kind': 'expense', 'amount': '25'}),
    ('/api/tasks', {'title': 'Fictional site visit'}),
    ('/api/site-reports', {'note': 'Fictional paint check'}),
    ('/api/site-expenses', {'title': 'Fictional brushes', 'amount': '25'}),
])
def test_deleted_project_refuses_new_work(admin, path, data):
    ticket = draft(admin, '/api/projects', {'name': 'Fictional Juniper House'})
    project_id = save(admin, ticket['ticket_id'])
    assert approved_undo(admin, ticket['ticket_id'], 'Fictional project cancelled').status_code == 200
    response = write(admin, 'post', path, {**data, 'project_id': project_id})
    assert response.status_code in (400, 404), response.text
    assert response.json()['detail'] == 'Project not found'


@pytest.mark.parametrize('one_step', [False, True])
def test_manager_cannot_approve_money_they_edited(admin, team, one_step):
    project_id, manager, accounts = team
    assert set_limits(admin).status_code == 200
    ticket_id = draft_cost(accounts, project_id, 123)
    entry = item(admin, ticket_id)
    url = f"/api/tickets/items/{entry['id']}"
    edit = write(manager, 'patch', url, {'after': {**entry['after'], 'amount_paise': 13500}})
    assert edit.status_code == 200, edit.text
    approval_url = f'/api/tickets/{ticket_id}/approve-and-save' if one_step else url + '/approve'
    refused = write(manager, 'post', approval_url)
    assert refused.status_code == 403, refused.text

    owner_ticket = draft_cost(admin, project_id, 191)
    save(admin, owner_ticket)
    with SessionLocal() as db:
        assert db.scalar(select(Audit.id).where(
            Audit.action == 'owner_self_approval', Audit.entity_id == owner_ticket,
        )) is not None


@pytest.mark.parametrize('one_step', [False, True])
def test_approval_refuses_values_changed_since_review(admin, team, one_step):
    project_id, manager, accounts = team
    assert set_limits(admin).status_code == 200
    ticket_id = draft_cost(accounts, project_id, 123)
    reviewed = item(manager, ticket_id)
    url = f"/api/tickets/items/{reviewed['id']}"
    edit = write(accounts, 'patch', url, {'after': {**reviewed['after'], 'amount_paise': 13500}})
    assert edit.status_code == 200, edit.text

    # Two signed-in clients and separate request sessions. Submit what the manager read.
    fingerprint = reviewed.get('review_fingerprint', 'old-preview')
    approval_url = f'/api/tickets/{ticket_id}/approve-and-save' if one_step else url + '/approve'
    payload = {'review_fingerprints': {str(reviewed['id']): fingerprint}} if one_step else {'review_fingerprint': fingerprint}
    refused = write(manager, 'post', approval_url, payload)
    assert refused.status_code == 409, refused.text
    assert 'review again' in refused.json()['detail'].lower()
    unreviewed = write(manager, 'post', approval_url)
    assert unreviewed.status_code == 409, unreviewed.text
    assert 'review again' in unreviewed.json()['detail'].lower()
    assert item(manager, ticket_id)['status'] == 'pending'
    current = item(manager, ticket_id)['review_fingerprint']
    payload = {'review_fingerprints': {str(reviewed['id']): current}} if one_step else {'review_fingerprint': current}
    accepted = write(manager, 'post', approval_url, payload)
    assert accepted.status_code == 200, accepted.text


@pytest.mark.parametrize('save_first', [False, True])
def test_monthly_limit_uses_approval_month(admin, team, monkeypatch, save_first):
    project_id, manager, accounts = team
    assert set_limits(admin, 50000, 60000).status_code == 200
    # 23:59 on January 31 in India. Two minutes later in India it is February 1,
    # even though the UTC calendar still says January 31.
    monkeypatch.setattr(runtime_clock, 'utc_now', lambda: datetime(2026, 1, 31, 18, 29, tzinfo=timezone.utc))
    first, second = (draft_cost(accounts, project_id, amount) for amount in (400, 325))
    january = draft_cost(accounts, project_id, 350)
    january_item = item(admin, january)['id']
    assert write(manager, 'post', f'/api/tickets/items/{january_item}/approve').status_code == 200
    monkeypatch.setattr(runtime_clock, 'utc_now', lambda: datetime(2026, 1, 31, 18, 31, tzinfo=timezone.utc))
    # Saving a January approval in February must not use up February's limit.
    assert write(manager, 'post', f'/api/tickets/{january}/commit').status_code == 200
    item_ids = [item(admin, ticket_id)['id'] for ticket_id in (first, second)]
    approved = write(manager, 'post', f'/api/tickets/items/{item_ids[0]}/approve')
    assert approved.status_code == 200, approved.text
    assert manager.get('/api/my-approval-rights').json()['approved_this_month_rupees'] == 400
    if save_first:
        saved = write(manager, 'post', f'/api/tickets/{first}/commit')
        assert saved.status_code == 200, saved.text
        assert manager.get('/api/my-approval-rights').json()['approved_this_month_rupees'] == 400
    refused = write(manager, 'post', f'/api/tickets/items/{item_ids[1]}/approve')
    assert refused.status_code == 403 and 'monthly' in refused.text, refused.text


def test_approval_columns_match_after_upgrade():
    from sqlalchemy import create_engine, inspect
    from studioos.migrations import apply_migrations

    old = create_engine('sqlite://')
    fresh = create_engine('sqlite://')
    with old.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE approval_ticket_items (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('INSERT INTO approval_ticket_items (id) VALUES (7)')
    apply_migrations(old)
    apply_migrations(fresh)
    names = {'last_edited_by', 'decided_at'}
    def approval_columns(engine):
        return {col['name']: (str(col['type']), col['nullable']) for col in
                inspect(engine).get_columns('approval_ticket_items') if col['name'] in names}

    assert approval_columns(old).keys() == names
    assert approval_columns(old) == approval_columns(fresh)
    with old.connect() as conn:
        assert conn.exec_driver_sql('SELECT id, last_edited_by, decided_at FROM approval_ticket_items').one() == (7, None, None)
