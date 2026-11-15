"""v0.9.5 fixes for the second independent v0.9.3 review (F03, F09, F13, F20, F21, F23).
Fictional data only. Needs FastAPI and SQLAlchemy; runs in the automatic pipeline."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from .conftest import write, approved_form
from .test_v094_review_fixes import user, project, chat, FICTIONAL_USER_PASSWORD
from studioos.db import SessionLocal, Cost, ConnectorToken, Task


def test_f03_ticket_correction_cannot_go_below_paid(admin, monkeypatch):
    import studioos.main as main
    pid = project(admin)
    c = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional joinery', 'vendor': 'Fictional Wood', 'amount': '10000'})
    assert write(admin, 'post', f"/api/costs/{c.json()['id']}/approve").status_code == 200
    p = write(admin, 'post', '/api/payments', {'cost_id': c.json()['id'], 'amount': '8000', 'idempotency_key': 'fictional-pay-review-f03'})
    assert write(admin, 'post', f"/api/payments/{p.json()['id']}/approve").status_code == 200
    monkeypatch.setattr(main, 'extract', lambda *a, **k: {'intent': 'update_cost', 'data': {'id': c.json()['id'], 'amount_paise': 100000}})
    u = chat(admin, 'Correct the joinery cost to 1,000')
    s = write(admin, 'post', f"/api/tickets/{u['ticket_id']}/approve-and-save", {})
    assert s.status_code == 422 and 'below what is already paid' in s.text
    with SessionLocal() as db:
        assert main.cost_net(db, db.get(Cost, c.json()['id'])) == 1000000


def test_f13_approval_is_rechecked_when_saving(admin):
    project(admin)
    m = user(admin, 'mgr31', 'manager')
    types = admin.get('/api/tickets/policy').json()
    pol = {t: (['admin'] if (t in ('suggest_schema', 'propose_data_type') or t.startswith(('metadata_','finance_'))) else ['admin', 'manager']) for t in types}
    assert write(admin, 'put', '/api/tickets/policy', {'approvers': pol}).status_code == 200
    r = chat(admin, 'Add task: Fictional site measurement at Review Villa')
    assert write(m, 'post', f"/api/tickets/items/{r['item_id']}/approve", {}).status_code == 200
    uid = next(u['id'] for u in admin.get('/api/users').json() if u['username'] == 'mgr31')
    assert write(admin, 'patch', f'/api/users/{uid}/active', {'active': False, 'reason': 'Left the firm (fictional)'}).status_code == 200
    s = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/commit")
    assert s.status_code == 403 and 'no longer active' in s.text
    with SessionLocal() as db:
        assert db.scalars(select(Task)).all() == []


def test_f20_site_engineer_progress_drafts_a_task_update(admin):
    pid = project(admin)
    assert approved_form(admin,'post','/api/tasks', {'project_id': pid, 'title': 'Bathroom tiling'}).status_code == 200
    se = user(admin, 'site31', 'site_engineer')
    uid = next(u['id'] for u in admin.get('/api/users').json() if u['username'] == 'site31')
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [uid]}).status_code == 200
    r = chat(se, 'Tiling at Review Villa is 40% done')
    assert r['preview']['items'][0]['item_type'] == 'update_task' and r['preview']['items'][0]['after']['progress'] == 40


def test_f23_password_reset_revokes_connector_keys(admin):
    m = user(admin, 'mgr32', 'manager')
    assert write(m, 'post', '/api/connector-tokens', {'name': 'phone', 'scope': 'read', 'days': 30,
                                                      'password': FICTIONAL_USER_PASSWORD}).status_code == 200
    uid = next(u['id'] for u in admin.get('/api/users').json() if u['username'] == 'mgr32')
    assert write(admin, 'post', f'/api/users/{uid}/reset-password', {'new_password': 'fictional-new-password-32'}).status_code == 200
    with SessionLocal() as db:
        assert all(t.revoked_at is not None for t in db.scalars(select(ConnectorToken).where(ConnectorToken.user_id == uid)).all())


def test_f21_oversized_connector_request_is_refused_before_reading(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_MCP_ENABLED', 'true')
    t = write(admin, 'post', '/api/connector-tokens', {'name': 'big', 'scope': 'read', 'days': 30,
                                                       'password': 'stage1-test-password-very-long'}).json()['token']
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': {'pad': 'x' * 70000}})
    r = admin.post('/mcp', content=body, headers={'Authorization': f'Bearer {t}', 'Content-Type': 'application/json'})
    assert r.status_code == 413
