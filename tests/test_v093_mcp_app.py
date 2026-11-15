"""v0.9.3 AI connector (MCP) end to end. Fictional data only.
Needs FastAPI and SQLAlchemy: python -m pytest -q tests/test_v093_mcp_app.py"""
import json
from fastapi.testclient import TestClient
from sqlalchemy import select
from .conftest import write
from .test_v090_app import chat, project
from studioos.main import app
from studioos.db import SessionLocal, Cost, ApprovalTicket, McpCall, ConnectorToken

PW = 'stage1-test-password-very-long'


def key(c, scope='read', password=PW, name='Claude test'):
    return write(c, 'post', '/api/connector-tokens', {'name': name, 'scope': scope, 'days': 30, 'password': password})


def rpc(client, token, method, params=None, ident=1, headers=None):
    body = {'jsonrpc': '2.0', 'method': method, 'id': ident, **({'params': params} if params is not None else {})}
    return client.post('/mcp', content=json.dumps(body), headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', **(headers or {})})


def call(client, token, tool, args=None):
    r = rpc(client, token, 'tools/call', {'name': tool, 'arguments': args or {}})
    assert r.status_code == 200, r.text
    return r.json()['result']


def on(monkeypatch):
    monkeypatch.setenv('STUDIOOS_MCP_ENABLED', 'true')


def test_endpoint_is_off_by_default(admin):
    t = key(admin).json()['token']
    assert rpc(admin, t, 'ping').status_code == 404


def test_key_needs_password_and_is_shown_once(admin, monkeypatch):
    assert key(admin, password='wrong-password').status_code == 403
    r = key(admin).json()
    assert r['token'].startswith('sos_') and r['state'] == 'active'
    listed = admin.get('/api/connector-tokens').json()['tokens']
    assert 'token' not in listed[0] and listed[0]['prefix'] == r['token'][:10]
    with SessionLocal() as db:
        assert db.scalars(select(ConnectorToken)).one().token_hash != r['token']


def test_full_mcp_conversation(admin, monkeypatch):
    on(monkeypatch)
    project(admin)
    t = key(admin).json()['token']
    init = rpc(admin, t, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}})
    assert init.status_code == 200 and init.json()['result']['protocolVersion'] == '2025-06-18'
    note = admin.post('/mcp', content=json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
                      headers={'Authorization': f'Bearer {t}'})
    assert note.status_code == 202
    names = [x['name'] for x in rpc(admin, t, 'tools/list').json()['result']['tools']]
    assert 'list_projects' in names and 'create_draft' not in names
    r = call(admin, t, 'list_projects')
    assert r['isError'] is False and r['structuredContent']['projects'][0]['name'] == 'Mehta Villa'
    assert 'client_phone' not in json.dumps(r)
    s = call(admin, t, 'get_project_status', {'project': 'mehta villa'})
    assert s['structuredContent']['project'] == 'Mehta Villa' and 'budget' in s['structuredContent']
    assert admin.get('/mcp').status_code == 405


def test_staff_key_sees_only_their_projects_and_no_budgets(admin, monkeypatch):
    on(monkeypatch)
    project(admin, 'Mehta Villa'); project(admin, 'Sharma Residence')
    write(admin, 'post', '/api/users', {'username': 'arch11', 'display_name': 'Architect', 'role': 'architect', 'password': 'fictional-architect-11'})
    pid = next(p['id'] for p in admin.get('/api/projects').json() if p['name'] == 'Mehta Villa')
    uid = next(u['id'] for u in admin.get('/api/users').json() if u['username'] == 'arch11')
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [uid]}).status_code == 200
    staff = TestClient(app)
    assert staff.post('/api/auth/login', json={'username': 'arch11', 'password': 'fictional-architect-11'}).status_code == 200
    t = key(staff, password='fictional-architect-11').json()['token']
    rows = call(staff, t, 'list_projects')['structuredContent']['projects']
    assert [r['name'] for r in rows] == ['Mehta Villa'] and 'approved_budget' not in rows[0]
    assert call(staff, t, 'get_project_status', {'project': 'Sharma Residence'})['isError'] is True
    assert call(staff, t, 'get_budget_summary')['isError'] is True


def test_draft_key_creates_only_a_draft(admin, monkeypatch):
    on(monkeypatch)
    project(admin)
    t = key(admin, scope='read_draft').json()['token']
    r = call(admin, t, 'create_draft', {'message': 'Log expense 3,200 for Anil Plumbing at Mehta Villa, paid by UPI.'})
    assert r['isError'] is False and r['structuredContent']['saved'] is False and r['structuredContent']['ticket']
    with SessionLocal() as db:
        assert db.scalars(select(Cost)).all() == []
        ticket = db.get(ApprovalTicket, r['structuredContent']['ticket'])
        assert ticket.status != 'committed' and ticket.session_id.startswith('mcp-')
    read_only = key(admin, name='read only').json()['token']
    assert rpc(admin, read_only, 'tools/call', {'name': 'create_draft', 'arguments': {'message': 'x'}}).json()['error']


def test_revoked_wrong_and_missing_keys_are_refused(admin, monkeypatch):
    on(monkeypatch)
    created = key(admin).json()
    assert rpc(admin, created['token'], 'ping').status_code == 200
    assert write(admin, 'post', f"/api/connector-tokens/{created['id']}/revoke").status_code == 200
    assert rpc(admin, created['token'], 'ping').status_code == 401
    assert rpc(admin, 'sos_' + 'x' * 43, 'ping').status_code == 401
    assert admin.post('/mcp', content='{}').status_code == 401


def test_limits_origin_address_and_public_host(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin).json()['token']
    assert rpc(admin, t, 'ping', headers={'Origin': 'https://evil.example'}).status_code == 403
    monkeypatch.setenv('STUDIOOS_MCP_ALLOWED_IPS', '203.0.113.0/24')
    assert rpc(admin, t, 'ping').status_code == 403            # the test client is not in that range
    monkeypatch.delenv('STUDIOOS_MCP_ALLOWED_IPS')
    monkeypatch.setenv('STUDIOOS_MCP_MAX_PER_MINUTE', '3')
    codes = [rpc(admin, t, 'ping').status_code for _ in range(5)]
    assert codes[-1] == 429
    monkeypatch.setenv('STUDIOOS_PUBLIC_HOST', 'testserver')
    assert admin.get('/').status_code == 404 and admin.get('/api/projects').status_code == 404
    with SessionLocal() as db:
        assert db.scalars(select(McpCall).where(McpCall.ok.is_(False))).all()


def test_admin_sees_connector_requests(admin, monkeypatch):
    on(monkeypatch)
    t = key(admin).json()['token']
    call(admin, t, 'list_open_tasks')
    rows = admin.get('/api/connector-calls').json()
    assert rows[0]['tool'] == 'list_open_tasks' and rows[0]['ok'] is True
