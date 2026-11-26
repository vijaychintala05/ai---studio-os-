"""Staff are told when a client writes or answers: per-project unread list, per-person read mark, project scope, Home widget."""
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
    inbox = admin.get(f'/api/portal/{pid}/inbox').json()
    assert inbox['unread'] == 2
    assert [i['kind'] for i in inbox['items']] == ['client_decision', 'client_message']
    assert 'Hello, is the layout ready?' in inbox['items'][1]['summary'] and 'asked for changes' in inbox['items'][0]['summary']
    _decide(portal_client, 'villa-one', rid, 'changes_requested', 'Please widen the door')     # a double tap records nothing new
    assert admin.get(f'/api/portal/{pid}/inbox').json()['unread'] == 2


def test_read_marks_are_per_person_and_per_project(admin, portal_client):
    p1, _ = _setup(admin)
    p2, _ = _setup(admin, name='Villa Two', slug='villa-two', phone='9123456780', email='ravi@example.test')
    add_user(admin, 'mgr.inbox', 'manager')
    mgr = client_for('mgr.inbox')
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'First question')
    _sign_in(portal_client, 'villa-two', '9123456780')
    h = {**_host('villa-two'), 'X-CSRF-Token': portal_client.cookies.get('studioos_portal_csrf', '')}
    portal_client.post('/portal-api/chat', json={'body': 'Question for project two'}, headers=h)
    assert write(admin, 'post', f'/api/portal/{p1}/inbox/seen').status_code == 200
    assert admin.get(f'/api/portal/{p1}/inbox').json()['unread'] == 0
    assert admin.get(f'/api/portal/{p2}/inbox').json()['unread'] == 1          # reading one project does not clear the other
    assert mgr.get(f'/api/portal/{p1}/inbox').json()['unread'] == 1            # the manager has not read it
    assert [i['unread'] for i in admin.get(f'/api/portal/{p1}/inbox').json()['items']] == [False]


def test_staff_only_see_notices_for_projects_they_can_access(admin, portal_client):
    pid, _ = _setup(admin)
    add_user(admin, 'arch.inbox', 'architect')
    arch = client_for('arch.inbox')
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Private to the project team')
    assert arch.get(f'/api/portal/{pid}/inbox').status_code == 404 and arch.get(f'/api/portal/{pid}/status').status_code == 404
    assert write(arch, 'post', f'/api/portal/{pid}/inbox/seen').status_code == 404
    with SessionLocal() as db:
        from studioos.db import User
        aid = db.scalar(select(User.id).where(User.username == 'arch.inbox'))
    write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [aid]})
    assert arch.get(f'/api/portal/{pid}/inbox').json()['unread'] == 1


def test_only_client_facing_roles_and_signed_in_staff(admin, portal_client):
    pid, _ = _setup(admin)
    for role in ('site_engineer', 'accounts'):
        add_user(admin, f'{role}.inbox', role)
        c = client_for(f'{role}.inbox')
        assert c.get(f'/api/portal/{pid}/inbox').status_code == 403 and c.get(f'/api/portal/{pid}/status').status_code == 403
        assert write(c, 'post', f'/api/portal/{pid}/inbox/seen').status_code == 403
    assert portal_client.get(f'/api/portal/{pid}/inbox').status_code == 401


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


def test_status_shows_the_address_and_hides_personal_details(admin, portal_client):
    pid, _ = _setup(admin)
    add_user(admin, 'arch.status', 'architect')
    s = admin.get(f'/api/portal/{pid}/status').json()
    assert s['domain_set'] is True and s['contacts'] == 1
    assert s['portal'] == {'slug': 'villa-one', 'enabled': True, 'address': 'villa-one.portal.example.test'}
    assert '9876543210' not in str(s) and 'asha@' not in str(s)                 # counts only; the people list stays admin-only
    arch = client_for('arch.status')
    assert arch.get(f'/api/portal/{pid}').status_code == 403                    # full setup (phones, emails) is admin-only


def test_home_lists_new_client_activity_and_each_row_opens_its_project(admin, portal_client):
    pid, _ = _setup(admin)
    _sign_in(portal_client, 'villa-one')
    _say(portal_client, 'villa-one', 'Anything new?')
    w = next(w for w in admin.get('/api/home').json()['widgets'] if w['key'] == 'client_activity')
    assert w['kind'] == 'list' and w['title'] == 'New from clients (1)'
    assert w['rows'][0]['project_id'] == pid and w['rows'][0]['tab'] == 'chat' and 'Villa One: Asha Fictional: Anything new?' in w['rows'][0]['label']
    write(admin, 'post', f'/api/portal/{pid}/inbox/seen')
    w = next(w for w in admin.get('/api/home').json()['widgets'] if w['key'] == 'client_activity')
    assert w['rows'] == [] and w['title'] == 'New from clients (0)'


def test_there_is_no_cross_project_menu_entry_any_more():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / 'studioos' / 'static' / 'index.html').read_text()
    assert 'data-view="portal"' not in html            # the Client portal lives inside each project's page
    static = Path(__file__).resolve().parents[1] / 'studioos' / 'static'
    js = (static / 'projectpage.js').read_text()
    # The project page shows the portal panel inside its "Files & Portal" tab (PR 120); the panel itself is built in portal_admin.js
    assert 'paProjectPanel' in js and "label: 'Files & Portal'" in js and 'bodyPanel = (d.sections.includes(\'files\')' in js and '+ portalPanel;' in js
    assert 'id="pp-portal"' in (static / 'portal_admin.js').read_text()
