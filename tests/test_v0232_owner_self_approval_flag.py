"""Owner decision 5: the owner may still approve their own money entry, but it is flagged in the audit log.
Fictional data only."""
from sqlalchemy import select
from studioos.db import SessionLocal, Audit
from studioos.two_person import is_own_entry, is_owner_self_approval
from .conftest import write, approved_form


def audit_texts():
    with SessionLocal() as db:
        return [a.description for a in db.scalars(select(Audit)).all()]


def test_the_helper_only_fires_for_the_owner_on_their_own_entry():
    assert is_owner_self_approval('admin', 5, 5) is True
    assert is_owner_self_approval('admin', 5, 6) is False
    assert is_owner_self_approval('manager', 5, 5) is False       # a manager is blocked, not flagged
    assert is_owner_self_approval('admin', 5, None) is False
    assert is_own_entry('admin', 5, 5) is False                    # the owner's exception itself is unchanged


def test_owner_approving_their_own_cost_is_allowed_and_flagged(admin):
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Own Approval Site', 'budget': '1000000'}).json()['id']
    r = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional tiles', 'vendor': 'Fictional Tiles Co', 'amount': '1200'})
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
    assert any('owner approved their own money entry' in t.lower() for t in audit_texts())


def test_owner_approving_someone_elses_entry_is_not_flagged(admin):
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Approval Site', 'budget': '1000000'}).json()['id']
    write(admin, 'post', '/api/users', {'username': 'own_acc', 'display_name': 'Fictional Accounts', 'role': 'accounts', 'password': 'fictional-accounts-own-1'})
    from fastapi.testclient import TestClient
    from studioos.main import app
    acc = TestClient(app)
    assert acc.post('/api/auth/login', json={'username': 'own_acc', 'password': 'fictional-accounts-own-1'}).status_code == 200
    r = write(acc, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional paint', 'vendor': 'Fictional Paint Co', 'amount': '900'})
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
    assert not any('owner approved their own money entry' in t.lower() for t in audit_texts())
