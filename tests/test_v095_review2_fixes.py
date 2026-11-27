"""v0.9.5 fixes for the second independent v0.9.3 review (F03, F09, F13, F20, F21, F23).
Fictional data only. Needs FastAPI and SQLAlchemy; runs in the automatic pipeline."""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from .conftest import write, approved_form
from .test_money_form_tickets import _payment_form
from .test_v094_review_fixes import user, project, chat, FICTIONAL_USER_PASSWORD
from .test_v098_universal_accounting import propose, save
from studioos.db import SessionLocal, FinanceDirectBill, FinanceReversal, ConnectorToken, Task


def test_f03_bill_correction_cannot_leave_a_payment_without_its_bill(admin):
    body = _payment_form(admin)
    bill_id = body['data']['bill_id']
    reversal = propose(admin, 'finance_reverse_direct_bill', {'bill_id': bill_id, 'reason': 'Fictional corrected bill'})
    payment = write(admin, 'post', '/api/universal/proposals', body)
    assert payment.status_code == 200, payment.text
    save(admin, payment.json())
    result = write(admin, 'post', f"/api/tickets/{reversal['ticket_id']}/approve-and-save", {})
    assert result.status_code == 422 and 'Reverse every payment' in result.text
    with SessionLocal() as db:
        assert db.get(FinanceDirectBill, bill_id).amount_paise == 200000
        assert db.scalar(select(FinanceReversal.id)) is None


def test_f13_approval_is_rechecked_when_saving(admin):
    project(admin)
    m = user(admin, 'mgr31', 'manager')
    types = admin.get('/api/tickets/policy').json()
    pol = {t: (['admin'] if (t in ('suggest_schema', 'propose_data_type','reverse_saved_ticket') or t.startswith(('metadata_','finance_'))) else ['admin', 'manager']) for t in types}
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
