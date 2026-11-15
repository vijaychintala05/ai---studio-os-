"""v0.6.2 regression tests: one or more tests for each code-review finding.

Fictional data only, on the disposable SQLite test database from conftest.py.
"""
import os
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, create_engine, inspect, text, update
from .conftest import write, approved_form
from studioos.main import app
from studioos.db import (SessionLocal, ApprovalTicket, ApprovalTicketItem, ChatSession, Cost,
                         LoginSession, User, now)

ADMIN_PW = os.environ['STUDIOOS_ADMIN_PASSWORD']


def post_chat(c, msg, sid=''):
    r = write(c, 'post', '/api/chat', {'message': msg, 'session_id': sid})
    assert r.status_code == 200, r.text
    return r.json()


def login(c, username, password):
    return c.post('/api/auth/login', json={'username': username, 'password': password})


def add_user(admin, username, role, password):
    r = write(admin, 'post', '/api/users', {'username': username, 'display_name': username.title(),
                                           'role': role, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()['id']


def committed_expense(admin, project, amount_text='3,200'):
    """Chat an expense, approve and commit its ticket. Returns (ticket_id, cost_id).
    v0.9.4: approving the ticket approves the cost; there is no second step."""
    r = post_chat(admin, f'Log expense {amount_text} for Anil Plumbing at {project}, paid by UPI.')
    assert write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve").status_code == 200
    c = write(admin, 'post', f"/api/tickets/{r['ticket_id']}/commit")
    assert c.status_code == 200, c.text
    cost_id = next(x['id'] for x in c.json()['committed_records'] if x['type'] == 'cost')
    with SessionLocal() as db:
        assert db.get(Cost, cost_id).status == 'approved'
    return r['ticket_id'], cost_id


# Finding 1: reversed costs must not count in per-project budgets ----------------

def test_reversed_cost_no_longer_counts_in_project_budget(admin):
    assert approved_form(admin,'post','/api/projects', {'name': 'Budget Reverse Villa', 'budget': '90000'}).status_code == 200
    ticket_id, _ = committed_expense(admin, 'Budget Reverse Villa')
    row = next(b for b in admin.get('/api/budgets').json() if b['name'] == 'Budget Reverse Villa')
    assert row['actual'] == 3200
    r = write(admin, 'post', f'/api/tickets/{ticket_id}/reverse', {'reason': 'Entered against the wrong project'})
    assert r.status_code == 200, r.text
    row = next(b for b in admin.get('/api/budgets').json() if b['name'] == 'Budget Reverse Villa')
    assert row['actual'] == 0 and row['known_costs'] == 0 and row['over_budget'] is False
    # Per-project and firm-wide totals now agree.
    assert admin.get('/api/summary').json()['costs']['actual'] == 0


# Finding 2: OpenAI request has no tool_choice; output limit comes from settings --

def test_output_token_limit_comes_from_settings(monkeypatch):
    from studioos import providers
    monkeypatch.setenv('STUDIOOS_MAX_OUTPUT_TOKENS', '900')
    assert providers.max_output_tokens() == 900
    monkeypatch.setenv('STUDIOOS_MAX_OUTPUT_TOKENS', 'lots')
    with pytest.raises(RuntimeError):
        providers.max_output_tokens()
    monkeypatch.setenv('STUDIOOS_MAX_OUTPUT_TOKENS', '0')
    with pytest.raises(RuntimeError):
        providers.max_output_tokens()


@pytest.mark.parametrize('provider,key_env,model_env,field', [
    ('openai', 'OPENAI_API_KEY', 'OPENAI_MODEL', 'max_completion_tokens'),
    ('claude', 'ANTHROPIC_API_KEY', 'ANTHROPIC_MODEL', 'max_tokens'),
    ('gemini', 'GEMINI_API_KEY', 'GEMINI_MODEL', 'maxOutputTokens'),
])
def test_every_adapter_uses_configured_limit_and_sends_no_tools(monkeypatch, provider, key_env, model_env, field):
    from studioos import providers
    monkeypatch.setenv('STUDIOOS_MAX_OUTPUT_TOKENS', '700')
    monkeypatch.setenv(key_env, 'fake-unit-test-key')
    monkeypatch.setenv(model_env, 'fake-model')
    seen = {}
    def fake_request(provider_name, model, prompt, message, url, headers, body, read_output, read_usage):
        seen['body'] = body
        return {'intent': 'unknown', 'data': {}}
    monkeypatch.setattr(providers, '_one_live_request', fake_request)
    providers.extract('Create project Fixture', [], provider)
    body = seen['body']
    limit = body.get(field) if field != 'maxOutputTokens' else body['generationConfig'][field]
    assert limit == 700
    assert 'tools' not in body and 'tool_choice' not in body


# Finding 3: rejected payments do not block cost reversal -----------------------

def test_rejected_payment_does_not_block_cost_reversal(admin):
    assert approved_form(admin,'post','/api/projects', {'name': 'Payment Reverse Villa', 'budget': '90000'}).status_code == 200
    ticket_id, cost_id = committed_expense(admin, 'Payment Reverse Villa')
    pay = write(admin, 'post', '/api/payments', {'cost_id': cost_id, 'amount': '1000', 'idempotency_key': 'fixture-payment-0001'})
    assert pay.status_code == 200, pay.text
    # A PENDING payment still blocks reversal.
    blocked = write(admin, 'post', f'/api/tickets/{ticket_id}/reverse', {'reason': 'Trying to reverse with a pending payment'})
    assert blocked.status_code == 409
    rejected = write(admin, 'post', f"/api/payments/{pay.json()['id']}/reject", {'reason': 'Wrong cost reference used'})
    assert rejected.status_code == 200
    # A REJECTED payment no longer blocks it.
    ok = write(admin, 'post', f'/api/tickets/{ticket_id}/reverse', {'reason': 'Expense entered in error, payment rejected'})
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        assert db.get(Cost, cost_id).deleted_at is not None


# Finding 4: chats that propose nothing create no ticket ------------------------

def test_plain_question_creates_no_ticket(admin):
    r = post_chat(admin, 'show tasks')
    assert not r.get('ticket_id')
    with SessionLocal() as db:
        assert db.scalars(select(ApprovalTicket)).all() == []
    assert admin.get('/api/tickets').json() == []


def test_old_empty_draft_tickets_are_hidden_from_inbox(admin):
    with SessionLocal() as db:
        me = db.scalar(select(User).where(User.username == 'admin'))
        db.add(ChatSession(id='legacy-empty-draft', user_id=me.id, pending=None)); db.flush()
        db.add(ApprovalTicket(session_id='legacy-empty-draft', submitter_id=me.id, summary='hello', status='draft'))
        db.commit()
    assert admin.get('/api/tickets').json() == []
    r = post_chat(admin, 'Create project Visible Ticket Villa with budget ₹5 lakh')
    listed = admin.get('/api/tickets').json()
    assert [t['id'] for t in listed] == [r['ticket_id']]


# Finding 5: user management and idle timeout ----------------------------------

def test_admin_can_deactivate_and_reactivate_employee(admin):
    uid = add_user(admin, 'siteuser1', 'site_engineer', 'fictional-site-password-1')
    staff = TestClient(app)
    assert login(staff, 'siteuser1', 'fictional-site-password-1').status_code == 200
    assert staff.get('/api/auth/me').status_code == 200
    off = write(admin, 'patch', f'/api/users/{uid}/active', {'active': False, 'reason': 'Left the company'})
    assert off.status_code == 200, off.text
    assert off.json()['sessions_ended'] == 1
    assert staff.get('/api/auth/me').status_code == 401
    assert login(staff, 'siteuser1', 'fictional-site-password-1').status_code == 401
    on = write(admin, 'patch', f'/api/users/{uid}/active', {'active': True, 'reason': 'Rejoined the team'})
    assert on.status_code == 200
    assert login(staff, 'siteuser1', 'fictional-site-password-1').status_code == 200


def test_admin_cannot_deactivate_self_or_owner(admin):
    with SessionLocal() as db:
        me = db.scalar(select(User).where(User.username == 'admin')).id
    r = write(admin, 'patch', f'/api/users/{me}/active', {'active': False, 'reason': 'Should not be allowed'})
    assert r.status_code == 409
    r = write(admin, 'post', f'/api/users/{me}/reset-password', {'new_password': 'another-long-password-1'})
    assert r.status_code == 409


def test_admin_password_reset_signs_employee_out(admin):
    uid = add_user(admin, 'architect9', 'architect', 'first-fictional-password')
    staff = TestClient(app)
    assert login(staff, 'architect9', 'first-fictional-password').status_code == 200
    weak = write(admin, 'post', f'/api/users/{uid}/reset-password', {'new_password': 'architect9-is-my-name'})
    assert weak.status_code == 400  # contains the username
    r = write(admin, 'post', f'/api/users/{uid}/reset-password', {'new_password': 'second-fictional-password'})
    assert r.status_code == 200 and r.json()['sessions_ended'] == 1
    assert staff.get('/api/auth/me').status_code == 401
    assert login(staff, 'architect9', 'first-fictional-password').status_code == 401
    assert login(staff, 'architect9', 'second-fictional-password').status_code == 200


def test_user_changes_own_password_and_other_sessions_end(admin):
    add_user(admin, 'manager7', 'manager', 'manager-old-password-x')
    phone = TestClient(app)
    laptop = TestClient(app)
    assert login(phone, 'manager7', 'manager-old-password-x').status_code == 200
    assert login(laptop, 'manager7', 'manager-old-password-x').status_code == 200
    wrong = write(phone, 'post', '/api/auth/change-password',
                  {'current_password': 'not-the-password', 'new_password': 'manager-new-password-y'})
    assert wrong.status_code == 403
    ok = write(phone, 'post', '/api/auth/change-password',
               {'current_password': 'manager-old-password-x', 'new_password': 'manager-new-password-y'})
    assert ok.status_code == 200, ok.text
    assert ok.json()['other_sessions_ended'] == 1
    assert phone.get('/api/auth/me').status_code == 200      # current session kept
    assert laptop.get('/api/auth/me').status_code == 401     # other session ended
    assert login(laptop, 'manager7', 'manager-new-password-y').status_code == 200


def test_idle_session_is_signed_out(admin):
    assert admin.get('/api/auth/me').status_code == 200
    with SessionLocal() as db:
        db.execute(update(LoginSession).values(last_seen_at=now() - timedelta(minutes=31)))
        db.commit()
    r = admin.get('/api/auth/me')
    assert r.status_code == 401 and 'inactivity' in r.json()['detail']
    with SessionLocal() as db:
        assert db.scalars(select(LoginSession)).all() == []


def test_active_session_stays_signed_in(admin):
    with SessionLocal() as db:
        db.execute(update(LoginSession).values(last_seen_at=now() - timedelta(minutes=10)))
        db.commit()
    assert admin.get('/api/auth/me').status_code == 200
    with SessionLocal() as db:
        seen = db.scalars(select(LoginSession)).one().last_seen_at.replace(tzinfo=None)
    assert now().replace(tzinfo=None) - seen < timedelta(minutes=1)  # activity recorded


def test_new_users_need_a_strong_password(admin):
    r = write(admin, 'post', '/api/users', {'username': 'shortpw', 'display_name': 'Short',
                                           'role': 'viewer', 'password': 'shortpw-1234567'})
    assert r.status_code == 400  # contains the username


# Finding 6: second person for money items -------------------------------------

def test_manager_can_still_reject_own_expense(admin):
    assert approved_form(admin,'post','/api/projects', {'name': 'Reject Own Villa', 'budget': '90000'}).status_code == 200
    types = admin.get('/api/tickets/policy').json()
    policy = {t: (['admin'] if (t in ('suggest_schema', 'propose_data_type') or t.startswith(('metadata_','finance_'))) else ['admin', 'manager']) for t in types}
    assert write(admin, 'put', '/api/tickets/policy', {'approvers': policy}).status_code == 200
    add_user(admin, 'manager6', 'manager', 'manager-six-password-z')
    mgr = TestClient(app)
    assert login(mgr, 'manager6', 'manager-six-password-z').status_code == 200
    r = post_chat(mgr, 'Log expense 1,900 for Anil Plumbing at Reject Own Villa, paid by UPI.')
    assert write(mgr, 'post', f"/api/tickets/items/{r['item_id']}/reject", {'note': 'Entered twice'}).status_code == 200


def test_manager_cannot_approve_own_expense_but_admin_can(admin):
    assert approved_form(admin,'post','/api/projects', {'name': 'Second Person Villa', 'budget': '90000'}).status_code == 200
    # Admin lets managers approve every non-schema item type.
    types = admin.get('/api/tickets/policy').json()
    policy = {t: (['admin'] if (t in ('suggest_schema', 'propose_data_type') or t.startswith(('metadata_','finance_'))) else ['admin', 'manager']) for t in types}
    assert write(admin, 'put', '/api/tickets/policy', {'approvers': policy}).status_code == 200
    add_user(admin, 'manager8', 'manager', 'manager-eight-password')
    mgr = TestClient(app)
    assert login(mgr, 'manager8', 'manager-eight-password').status_code == 200
    r = post_chat(mgr, 'Log expense 2,100 for Anil Plumbing at Second Person Villa, paid by UPI.')
    own = write(mgr, 'post', f"/api/tickets/items/{r['item_id']}/approve")
    assert own.status_code == 403 and 'someone else' in own.json()['detail']
    # A different person (here the Admin) can approve and commit it.
    assert write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve").status_code == 200
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/commit").status_code == 200


def test_commit_rechecks_second_person_rule(admin):
    """Even if an approval was recorded some other way, commit refuses a self-approved money item."""
    assert approved_form(admin,'post','/api/projects', {'name': 'Commit Check Villa', 'budget': '90000'}).status_code == 200
    types = admin.get('/api/tickets/policy').json()
    policy = {t: (['admin'] if (t in ('suggest_schema', 'propose_data_type') or t.startswith(('metadata_','finance_'))) else ['admin', 'manager']) for t in types}
    assert write(admin, 'put', '/api/tickets/policy', {'approvers': policy}).status_code == 200
    add_user(admin, 'manager9', 'manager', 'manager-nine-password')
    mgr = TestClient(app)
    assert login(mgr, 'manager9', 'manager-nine-password').status_code == 200
    r = post_chat(mgr, 'Log expense 2,300 for Anil Plumbing at Commit Check Villa, paid by UPI.')
    with SessionLocal() as db:
        item = db.get(ApprovalTicketItem, r['item_id'])
        item.status = 'approved'
        item.decided_by = db.scalar(select(User).where(User.username == 'manager9')).id
        db.commit()
    c = write(mgr, 'post', f"/api/tickets/{r['ticket_id']}/commit")
    assert c.status_code == 403
    with SessionLocal() as db:
        assert db.scalars(select(Cost)).all() == []


# Findings 7 and 8: login timing, version, dead code ----------------------------

def test_unknown_username_still_runs_a_password_hash(client, monkeypatch):
    import studioos.main as main
    calls = []
    monkeypatch.setattr(main, 'dummy_password_check', lambda pw: calls.append(pw))
    r = client.post('/api/auth/login', json={'username': 'nobody-here', 'password': 'whatever-password'})
    assert r.status_code == 401 and calls == ['whatever-password']
    calls.clear()
    assert login(client, 'admin', ADMIN_PW).status_code == 200
    assert calls == []


def test_health_reports_current_version(client):
    from studioos.main import APP_VERSION
    assert client.get('/health').json()['version'] == APP_VERSION  # 0.6.3 since v0.6.3


def test_old_direct_write_path_is_gone():
    import studioos.main as main
    assert not hasattr(main, 'execute_action')
    assert not hasattr(main, 'proposal_text')


def test_fresh_database_reaches_v9_with_session_tracking(tmp_path):
    from studioos.migrations import apply_migrations, LATEST_VERSION
    e = create_engine('sqlite:///' + str(tmp_path / 'fresh.db'))
    apply_migrations(e)
    assert LATEST_VERSION >= 9  # v0.6.3 moved the latest to 10; v9 must still be included
    assert 'last_seen_at' in {c['name'] for c in inspect(e).get_columns('login_sessions')}
    with e.connect() as conn:
        assert conn.execute(text('SELECT MAX(version) FROM schema_migrations')).scalar() == LATEST_VERSION
        assert conn.execute(text('SELECT COUNT(*) FROM schema_migrations WHERE version=9')).scalar() == 1
