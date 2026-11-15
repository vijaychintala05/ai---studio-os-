"""Contacts used by another project stay out of staff graph pickers/references."""
import pytest
from sqlalchemy import select
from .conftest import write,approved_form
from .test_v098_universal_accounting import propose,save
from .test_v0914_chart_of_accounts import approve
from .test_v0100_one_graph import add_user,client_for
from studioos.db import SessionLocal,User
from studioos.graph_query import Resolver


@pytest.fixture
def scoped_contacts(admin):
    projects=[approved_form(admin,'post','/api/projects',{'name':name,'client':client,'budget':'100000'}).json()['id']for name,client in [
        ('Fictional Assigned Site','Fictional Cedar Client'),('Fictional Other Site','Fictional Indigo Client')]]
    vendors=[]
    for name in ('Fictional Cedar Tiles','Fictional Indigo Wiring'):
        p=write(admin,'post','/api/tickets/proposals',{'kind':'create_vendor','data':{'name':name},'evidence':'Fictional reviewed contact'})
        assert p.status_code==200,p.text
        vendors.append(save(admin,p.json())['id'])
    entity=save(admin,propose(admin,'finance_setup',{'entity_name':'Fictional Scope Checks Firm','expense_code':'5000','ap_code':'2100','bank_code':'1000','bank_name':'Fictional Scope Bank','bank_masked':'****0000'}))['id']
    save(admin,propose(admin,'finance_install_chart',{'entity_id':entity,'standard':'india_interiors'}))
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    chart={a['code']:a for a in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']}
    for i,name in enumerate(('Fictional Cedar Tiles','Fictional Indigo Wiring')):
        gl=save(admin,propose(admin,'finance_open_account',{'entity_id':entity,'name':name,'parent_id':chart['SUNDRY_CREDITORS']['id']}))['id']
        p=propose(admin,'finance_text_entry',{'entity_id':entity,'recipe':'purchase','project_id':projects[i],
            'idempotency_key':f'fictional:scoped:purchase:{i}',
            'slots':{'amount':250000,'item':'tiles','from_party':name,'date':'2026-11-10','gst_mode':'none','settlement':'credit','reference':f'FX-SCOPE-{i}'},
            'accounts':{'item':chart['TILES_STONE']['id'],'party':gl}})
        r=approve(admin,p,confirmed=('duplicate',));assert r.status_code==200,r.text
    site_id=add_user(admin,'fictional.scoped.site','site_engineer')
    assert write(admin,'put',f'/api/projects/{projects[0]}/members',{'user_ids':[site_id]}).status_code==200
    site=client_for('fictional.scoped.site')
    return projects,vendors,site_id,site


def test_staff_contact_pickers_include_own_text_purchases_only(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    assert {r['id']for r in site.get('/api/graph/targets/system.supplier').json()}=={vendors[0]}
    clients=site.get('/api/graph/targets/system.client').json()
    assert {r['label']for r in clients}=={'Fictional Cedar Client'}
    assert len(admin.get('/api/graph/targets/system.supplier').json())==2


def test_resolver_does_not_follow_an_unrelated_supplier(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    with SessionLocal()as db:
        r=Resolver(db,db.get(User,site_id))
        assert r.system_node('system.supplier',vendors[0]) is not None
        assert r.system_node('system.supplier',vendors[1]) is None


def test_staff_cannot_propose_a_reference_to_an_unrelated_supplier(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    save(admin,propose(admin,'metadata_type',{'key':'vendor_followup','title':'Vendor follow-up','fields':[
        {'name':'note','type':'text','required':True},{'name':'supplier','type':'reference','target':'system.supplier','required':True}]}))
    data={'kind':'metadata_record','data':{'type_key':'vendor_followup','project_id':projects[0],'values':{'note':'Fictional delivery check','supplier':vendors[1]}},'evidence':'Fictional forbidden reference probe'}
    blocked=write(site,'post','/api/universal/proposals',data)
    assert blocked.status_code in (404,422),blocked.text
    data['data']['values']['supplier']=vendors[0]
    allowed=write(site,'post','/api/universal/proposals',data)
    assert allowed.status_code==200,allowed.text


def test_pending_contact_reference_does_not_grant_access_but_approved_one_does(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    save(admin,propose(admin,'metadata_type',{'key':'vendor_instruction','title':'Vendor instruction','fields':[
        {'name':'note','type':'text','required':True},{'name':'supplier','type':'reference','target':'system.supplier','required':True}]}))
    p=propose(admin,'metadata_record',{'type_key':'vendor_instruction','project_id':projects[0],'values':{'note':'Fictional approved delivery instruction','supplier':vendors[1]}})
    assert {r['id']for r in site.get('/api/graph/targets/system.supplier').json()}=={vendors[0]}
    save(admin,p)
    assert {r['id']for r in site.get('/api/graph/targets/system.supplier').json()}==set(vendors)


def test_draft_edit_cannot_bypass_supplier_scope(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    save(admin,propose(admin,'metadata_type',{'key':'vendor_update','title':'Vendor update','fields':[
        {'name':'note','type':'text','required':True},{'name':'supplier','type':'reference','target':'system.supplier','required':True}]}))
    d={'type_key':'vendor_update','project_id':projects[0],'values':{'note':'Fictional delivery check','supplier':vendors[0]}}
    p=propose(site,'metadata_record',d)
    d['values']['supplier']=vendors[1]
    blocked=write(site,'patch',f'/api/tickets/items/{p["item_id"]}',{'after':d})
    assert blocked.status_code==422,blocked.text


def test_prompt_contacts_use_same_approved_scope_as_pickers(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    from studioos.main import _visible_parties
    with SessionLocal()as db:
        user=db.get(User,site_id)
        names={p['name']for p in _visible_parties(db,{projects[0]},user)}
        assert names=={'Fictional Cedar Client','Fictional Cedar Tiles'}
