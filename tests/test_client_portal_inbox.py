"""Staff are told when a client writes or answers: unread list, per-person read mark, project scope, Home widget."""
from sqlalchemy import select, text

from studioos.client_portal_models import PortalActivity
from studioos.db import SessionLocal
from tests.conftest import write
from tests.test_v0100_one_graph import add_user, client_for
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host, _sign_in  # noqa: F401
from tests.test_client_portal_content import pack, _doc  # noqa: F401
from tests.test_client_portal_decisions import _item, _decide
from tests.test_client_portal_chat import _say


def test_a_client_message_and_an_answer_each_make_a_notice(admin, portal_client, pack):
    pid, _ = _setup(admin)
    rid = _item(admin, pid, _doc(pid))
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Hello, is the layout ready?')
    _decide(portal_client, 'villa-one', rid, 'changes_requested', 'Please widen the door')
    inbox = admin.get('/api/portal-inbox').json()
    assert inbox['unread'] == 2
    kinds = [(i['kind'], i['project']) for i in inbox['items']]
    assert kinds == [('client_decision', 'Villa One'), ('client_message', 'Villa One')]
    assert 'Hello, is the layout ready?' in inbox['items'][1]['summary'] and 'asked for changes' in inbox['items'][0]['summary']
    # a double tap that records nothing new makes no new notice
    _decide(portal_client, 'villa-one', rid, 'changes_requested', 'Please widen the door')
    assert admin.get('/api/portal-inbox').json()['unread'] == 2


def test_seen_marks_only_my_reading(admin, portal_client):
    pid, _ = _setup(admin)
    add_user(admin, 'mgr.inbox', 'manager')
    mgr = client_for('mgr.inbox')
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'First question')
    assert write(admin, 'post', '/api/portal-inbox/seen').status_code == 200
    assert admin.get('/api/portal-inbox').json()['unread'] == 0
    assert mgr.get('/api/portal-inbox').json()['unread'] == 1       # the manager has not read it
    _say(portal_client, 'villa-one', 'Second question')
    assert admin.get('/api/portal-inbox').json()['unread'] == 1
    assert [i['unread'] for i in admin.get('/api/portal-inbox').json()['items']] == [True, False]


def test_staff_only_see_notices_for_projects_they_can_access(admin, portal_client):
    pid, _ = _setup(admin)
    add_user(admin, 'arch.inbox', 'architect')
    arch = client_for('arch.inbox')
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Private to the project team')
    assert arch.get('/api/portal-inbox').json() == {'unread': 0, 'items': []}
    assert arch.get('/api/portal-projects').json()['projects'] == []
    with SessionLocal() as db:
        from studioos.db import User
        aid = db.scalar(select(User.id).where(User.username == 'arch.inbox'))
    write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [aid]})
    assert arch.get('/api/portal-inbox').json()['unread'] == 1
    assert [p['unread'] for p in arch.get('/api/portal-projects').json()['projects']] == [1]


def test_only_client_facing_roles_and_signed_in_staff(admin, portal_client):
    _setup(admin)
    for role in ('site_engineer', 'accounts'):
        add_user(admin, f'{role}.inbox', role)
        c = client_for(f'{role}.inbox')
        assert c.get('/api/portal-inbox').status_code == 403 and c.get('/api/portal-projects').status_code == 403
        assert write(c, 'post', '/api/portal-inbox/seen').status_code == 403
    assert portal_client.get('/api/portal-inbox').status_code == 401


def test_notices_are_permanent(admin, portal_client):
    import pytest
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Keep this')
    with SessionLocal() as db:
        n = db.scalar(select(PortalActivity)); n.summary = 'changed'
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()
    with SessionLocal() as db:
        db.delete(db.scalar(select(PortalActivity)))
        with pytest.raises(PermissionError):
            db.flush()
        db.rollback()


def test_project_list_shows_portal_status_and_unread(admin, portal_client):
    pid, _ = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Hi')
    p = admin.get('/api/portal-projects').json()
    row = next(x for x in p['projects'] if x['id'] == pid)
    assert p['domain_set'] is True and row['portal'] == {'slug': 'villa-one', 'enabled': True, 'address': 'villa-one.portal.example.test'}
    assert row['contacts'] == 1 and row['unread'] == 1


def test_home_widget_counts_new_client_activity(admin, portal_client):
    _setup(admin)
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Anything new?')
    w = next(w for w in admin.get('/api/home').json()['widgets'] if w['key'] == 'client_activity')
    assert w['value'] == 1 and w['screen'] == 'portal' and 'Anything new?' in w['detail']
    write(admin, 'post', '/api/portal-inbox/seen')
    assert next(w for w in admin.get('/api/home').json()['widgets'] if w['key'] == 'client_activity')['value'] == 0
