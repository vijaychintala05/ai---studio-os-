"""v0.9.4 fixes for the independent v0.9.3 review (C2, H1, H2, M3, M4, M10). Fictional data only.
Needs FastAPI and SQLAlchemy; runs in the automatic pipeline."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from .conftest import write, approved_form
from studioos.main import app
from studioos.db import SessionLocal, Cost, Payment, SiteReport, Project


def login(username, password):
    c = TestClient(app)
    assert c.post('/api/auth/login', json={'username': username, 'password': password}).status_code == 200
    return c


# Test-only fictional secret independent of the username; complies with v0.9.5 policy.
FICTIONAL_USER_PASSWORD = 'fictional-safe-test-secret-2026-long'

def user(admin, username, role):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.title(), 'role': role,
                                           'password': FICTIONAL_USER_PASSWORD})
    assert r.status_code == 200, r.text
    return login(username, FICTIONAL_USER_PASSWORD)


def project(admin, name='Review Villa', budget='500000'):
    assert approved_form(admin,'post','/api/projects', {'name': name, 'budget': budget}).status_code == 200
    return next(p['id'] for p in admin.get('/api/projects').json() if p['name'] == name)


def chat(c, msg, sid=''):
    r = write(c, 'post', '/api/chat', {'message': msg, 'session_id': sid})
    assert r.status_code == 200, r.text
    return r.json()


def test_c2_manager_cannot_approve_own_cost_on_the_approvals_screen(admin):
    pid=project(admin)
    policy=admin.get('/api/tickets/policy').json();policy['record_cost']=['admin','manager']
    assert write(admin,'put','/api/tickets/policy',{'approvers':policy}).status_code==200
    m=user(admin,'mgr21','manager')
    draft=write(m,'post','/api/costs',{'project_id':pid,'kind':'expense','title':'Plywood','vendor':'Fictional Ply','amount':'5000'})
    assert draft.status_code==200,draft.text
    ticket=draft.json()['ticket_id']
    assert write(m,'post',f'/api/tickets/{ticket}/approve-and-save',{}).status_code==403
    other=user(admin,'mgr22','manager')
    saved=write(other,'post',f'/api/tickets/{ticket}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        cost=db.get(Cost,saved.json()['committed_records'][0]['id'])
        assert cost.status=='approved'and cost.created_by_id!=cost.approved_by_id


def test_c2_payment_creator_cannot_approve_it(admin):
    pid=project(admin)
    c=approved_form(admin,'post','/api/costs',{'project_id':pid,'kind':'expense','title':'Tiles','vendor':'Fictional Tiles','amount':'8000'})
    assert c.status_code==200,c.text
    policy=admin.get('/api/tickets/policy').json();policy['record_payment']=['admin','manager','accounts']
    assert write(admin,'put','/api/tickets/policy',{'approvers':policy}).status_code==200
    acc=user(admin,'acc21','accounts')
    p=write(acc,'post','/api/payments',{'cost_id':c.json()['id'],'amount':'3000','idempotency_key':'fictional-pay-00021'})
    assert p.status_code==200,p.text
    ticket=p.json()['ticket_id']
    assert write(acc,'post',f'/api/tickets/{ticket}/approve-and-save',{}).status_code==403
    m=user(admin,'mgr23','manager')
    saved=write(m,'post',f'/api/tickets/{ticket}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        pay=db.get(Payment,saved.json()['committed_records'][0]['id'])
        assert pay.created_by_id is not None and pay.approved_by_id is not None and pay.created_by_id!=pay.approved_by_id


def test_h1_ticket_approval_is_the_only_money_approval(admin):
    project(admin)
    r = chat(admin, 'Log expense 3,200 for Anil Plumbing at Review Villa, paid by UPI.')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    assert admin.get('/api/approvals').json()['costs'] == []
    budgets = {b['name']: b for b in admin.get('/api/budgets').json()}
    assert budgets['Review Villa']['actual'] == 3200        # counts at once, not after a second tap


def test_h2_every_approved_field_is_saved(admin):
    project(admin)
    r = chat(admin, 'Log expense 3,200 for Anil Plumbing at Review Villa, paid by UPI.')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    with SessionLocal() as db:
        cost = db.scalars(select(Cost)).one()
        assert cost.payment_mode == 'upi'
    # A payment's method and date are kept.
    from studioos.tickets import ALLOWED_FIELDS
    assert {'payment_mode', 'date'} <= ALLOWED_FIELDS['record_payment']
    with SessionLocal() as db:
        cols = {c.name for c in Payment.__table__.columns} | {c.name for c in SiteReport.__table__.columns}
        assert {'payment_mode', 'paid_date', 'report_date'} <= cols


def test_h2_m3_correction_shows_net_before_and_applies_description(admin, monkeypatch):
    import studioos.main as main
    project(admin)
    r = chat(admin, 'Log expense 3,200 for Anil Plumbing at Review Villa, paid by UPI.')
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/approve-and-save", {}).status_code == 200
    with SessionLocal() as db:
        cost_id = db.scalars(select(Cost)).one().id
    for amount, title in ((300000, 'Plumbing labour'), (280000, 'Plumbing labour, final')):
        monkeypatch.setattr(main, 'extract', lambda *a, **k: {'intent': 'update_cost', 'data': {
            'id': cost_id, 'amount_paise': amount, 'title': title, 'vendor': 'Anil Plumbing'}})
        u = chat(admin, f'Correct expense {cost_id}')
        item = u['preview']['items'][0]
        if amount == 280000:
            assert item['before']['amount_paise'] == 300000          # after the earlier correction (M3)
        assert write(admin, 'post', f"/api/tickets/{u['ticket_id']}/approve-and-save", {}).status_code == 200
    with SessionLocal() as db:
        cost = db.get(Cost, cost_id)
        assert cost.title == 'Plumbing labour, final' and main.cost_net(db, cost) == 280000
    monkeypatch.setattr(main, 'extract', lambda *a, **k: {'intent': 'update_cost', 'data': {
        'id': cost_id, 'amount_paise': 280000, 'title': 'Plumbing labour, final', 'kind': 'commitment'}})
    u = chat(admin, f'Change expense {cost_id} to a purchase order')
    s = write(admin, 'post', f"/api/tickets/{u['ticket_id']}/approve-and-save", {})
    assert s.status_code == 422 and 'cannot change the type' in s.text


def test_m4_rename_onto_existing_project_is_refused_clearly(admin, monkeypatch):
    import studioos.main as main
    project(admin, 'Alpha Villa'); pid = project(admin, 'Beta Villa')
    monkeypatch.setattr(main, 'extract', lambda *a, **k: {'intent': 'update_project', 'data': {'id': pid, 'name': 'alpha villa'}})
    u = chat(admin, 'Rename Beta Villa to Alpha Villa')
    s = write(admin, 'post', f"/api/tickets/{u['ticket_id']}/approve-and-save", {})
    assert s.status_code == 422 and 'already has this name' in s.text
    with SessionLocal() as db:
        assert db.get(Project, pid).name == 'Beta Villa'
