import os
from sqlalchemy import select
from studioos.db import SessionLocal,Project,FinanceExpense,FinanceReversal,User,engine
from .books_fixtures import draft_project_expense
from .conftest import write, approved_form
from .test_money_form_tickets import _payment_form
from .test_v098_universal_accounting import finance_setup, propose, save

def test_authentication_and_csrf(client):
    assert client.get('/api/export').status_code==401
    assert client.post('/api/projects',json={'name':'Villa A'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':'not-valid'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']}).status_code==200
    assert client.post('/api/projects',json={'name':'Villa A'}).status_code==403
    assert approved_form(client,'post','/api/projects',{'name':'Villa A','budget':'450000'}).status_code==200
    assert write(client,'post','/api/auth/logout').status_code==200
    assert client.get('/api/projects').status_code==401

def test_permissions_and_private_finances(admin):
    p=approved_form(admin,'post','/api/projects',{'name':'Villa C','budget':'250000'}).json()
    r=write(admin,'post','/api/users',{'username':'site01','display_name':'Site Engineer','password':'a-long-special-password-123','role':'site_engineer'})
    assert r.status_code==200
    # v0.6.3: site engineers see only projects they are assigned to.
    assert write(admin,'put',f"/api/projects/{p['id']}/members",{'user_ids':[r.json()['id']]}).status_code==200
    write(admin,'post','/api/auth/logout')
    assert admin.post('/api/auth/login',json={'username':'site01','password':'a-long-special-password-123'}).status_code==200
    assert admin.get('/api/budgets').status_code==403
    assert admin.get('/api/costs').status_code==403
    assert admin.get('/api/export').status_code==403
    assert admin.get('/api/approvals').status_code==403
    assert 'budget' not in admin.get('/api/projects').json()[0]
    assert admin.get('/api/summary').json()['total_budget']==0
    assert '250000' not in admin.post('/api/chat',json={'message':'Show all projects'},headers={'X-CSRF-Token':admin.cookies.get('studioos_csrf')}).text
    assert write(admin,'post','/api/costs',{'project_id':p['id'],'kind':'expense','title':'Supplies','amount':'120'}).status_code==403
    assert approved_form(admin,'post','/api/site-reports',{'project_id':p['id'],'note':'Foundation work started'}).status_code==200

def test_invalid_project_budget_and_zero_budget_alert(admin):
    finance_setup(admin)
    bad=approved_form(admin,'post','/api/projects',{'name':'Villa A','budget':'not a price'})
    assert bad.status_code==400
    p=approved_form(admin,'post','/api/projects',{'name':'Villa A','budget':'0'}).json()
    cost = draft_project_expense(admin, p['id'], 100000, note='Fictional site survey')
    assert cost.status_code == 200, cost.text
    assert admin.get('/api/budgets').json()[0]['over_budget'] is False
    with SessionLocal() as db:
        assert db.scalar(select(FinanceExpense.id)) is None
    save(admin, cost.json())
    b=admin.get('/api/budgets').json()[0]
    assert b['known_costs']==1000 and b['remaining']==-1000 and b['over_budget'] is True

def test_payment_confirmation_idempotency_and_reversal(admin):
    payload = _payment_form(admin)
    path = '/api/finance-ledger/proposals'
    company = admin.get('/api/finance-ledger/entities').json()[0]['id']

    def payable():
        return admin.get(f'/api/finance-ledger/payables/{company}').json()['direct_bills'][0]['outstanding_paise']

    absent = write(admin, 'post', path, {**payload, 'data': {**payload['data'], 'bill_id': 999999}})
    assert absent.status_code == 422
    payment = write(admin, 'post', path, payload)
    assert payment.status_code == 200, payment.text
    assert write(admin, 'post', path, payload).json()['ticket_id'] == payment.json()['ticket_id']
    assert payable() == 200000
    posted = save(admin, payment.json())
    assert payable() == 150000
    overpaid = write(admin, 'post', path, {**payload, 'data': {
        **payload['data'], 'amount_paise': 160000, 'idempotency_key': 'fictional-overpaid-test',
    }})
    assert overpaid.status_code == 422 and 'more than what is still owed' in overpaid.text
    reversal = {'kind': 'finance_reverse_direct_bill_payment', 'evidence': 'Fictional reversal',
                'data': {'payment_id': posted['id'], 'reason': 'Entered against the wrong invoice'}}
    draft = write(admin, 'post', path, reversal)
    assert draft.status_code == 200, draft.text
    assert payable() == 150000
    save(admin, draft.json())
    assert payable() == 200000
    assert write(admin, 'post', path, reversal).status_code == 422
    assert admin.get('/api/budgets').json()[0]['known_costs'] == 2000

def test_cost_corrections_are_immutable(admin):
    finance_setup(admin)
    pid=approved_form(admin,'post','/api/projects',{'name':'Villa D','budget':'30000'}).json()['id']
    expense = save(admin, draft_project_expense(admin, pid, 1000000, note='Fictional earthwork').json())
    correction = propose(admin, 'finance_correct_expense', {'expense_id': expense['id'], 'before_amount_paise': 1000000,
                         'amount_paise': 750000, 'reason': 'Corrected vendor invoice after audit'})
    assert admin.get('/api/budgets').json()[0]['actual']==10000
    replacement = save(admin, correction)
    assert admin.get('/api/budgets').json()[0]['actual']==7500
    with SessionLocal() as db:
        original = db.get(FinanceExpense, expense['id'])
        assert original.amount_paise == 1000000
        assert db.get(FinanceExpense, replacement['id']).amount_paise == 750000
        assert db.scalars(select(FinanceReversal.original_journal_id)).one() == original.journal_id

def test_chat_ticket_proposal_and_owner_isolation(admin):
    csrf=admin.cookies.get('studioos_csrf')
    def chat(message,sid=''):
        return admin.post('/api/chat',json={'message':message,'session_id':sid},headers={'X-CSRF-Token':csrf})
    a=chat('Create project Villa A with budget ₹20 lakh').json()
    assert a['ticket_id'] and not a['changed']
    assert admin.get('/api/projects').json()==[]
    result=chat('confirm',a['session_id']).json()
    assert result['changed'] is False and admin.get('/api/projects').json()==[]
    tid=a['ticket_id'];item=a['item_id']
    assert write(admin,'post',f'/api/tickets/items/{item}/approve').status_code==200
    assert write(admin,'post',f'/api/tickets/{tid}/commit').status_code==200
    assert admin.get('/api/projects').json()[0]['budget']==2000000
    # user isolation
    write(admin,'post','/api/users',{'username':'architect01','display_name':'Architect','role':'architect','password':'architecture-password-123'})
    write(admin,'post','/api/auth/logout')
    assert admin.post('/api/auth/login',json={'username':'architect01','password':'architecture-password-123'}).status_code==200
    response=write(admin,'post','/api/chat',{'message':'show tasks','session_id':a['session_id']})
    assert response.status_code==403

def test_provider_adapters_do_not_migrate_records(admin,monkeypatch):
    approved_form(admin,'post','/api/projects',{'name':'Villa A','budget':'90000'})
    assert write(admin,'post','/api/settings/provider',{'provider':'claude'}).status_code==409
    monkeypatch.setenv('ANTHROPIC_API_KEY','not-live-key')
    assert write(admin,'post','/api/settings/provider',{'provider':'claude'}).status_code==200
    assert admin.get('/api/projects').json()[0]['budget']==90000
    assert write(admin,'post','/api/settings/provider',{'provider':'demo'}).status_code==200

def test_export_is_admin_only_and_contains_adjustments(admin):
    approved_form(admin,'post','/api/projects',{'name':'Office A','budget':'100000'})
    data=admin.get('/api/export')
    assert data.status_code==200
    assert data.json()['format']=='studioos-export-v2'
    assert data.json()['projects'][0]['name']=='Office A'
    assert 'financial_adjustments' in data.json()
    assert 'STUDIOOS_ADMIN_PASSWORD' not in data.text

def test_nas_metadata_read_only(admin,monkeypatch,tmp_path):
    (tmp_path/'Villa A').mkdir();(tmp_path/'Villa A'/'REV_01.pdf').write_bytes(b'%PDF fake')
    (tmp_path/'secret.key').write_text('not indexed')
    monkeypatch.setenv('STUDIOOS_NAS_ROOT',str(tmp_path))
    r=write(admin,'post','/api/documents/index-nas')
    assert r.status_code==200
    assert r.json()['added']==1
    assert admin.get('/api/documents').json()[0]['relative_path']=='Villa A/REV_01.pdf'
