"""Scoped, named client/supplier fields must survive chat and explicit review."""
import pytest
from tests.conftest import write
from tests.test_v098_universal_accounting import propose,save
from tests.test_scoped_party_graph import scoped_contacts

@pytest.mark.parametrize('target,party_kind,field',[('system.client','create_client','client'),('system.supplier','create_vendor','supplier')])
def test_named_contact_field_becomes_an_exact_approved_reference(admin,target,party_kind,field):
    name='Fictional Contact 03'
    draft=write(admin,'post','/api/tickets/proposals',{'kind':party_kind,'data':{'name':name},'evidence':'Fictional source contact'})
    assert draft.status_code==200,draft.text
    party=save(admin,draft.json())['id']
    save(admin,propose(admin,'metadata_type',{'key':'fictional_sample_link','title':'Fictional sample link','fields':[
        {'name':'description','type':'text','required':True},{'name':field,'type':'reference','target':target,'required':True}]}))
    response=write(admin,'post','/api/chat',{'message':f'Fictional sample link; description: Fictional selection checked; {field}: {name}'})
    assert response.status_code==200,response.text
    item=next(i for i in response.json()['preview']['items']if i['item_type']=='metadata_record')
    assert item['after']['values'][field]==party,item
    assert not response.json()['ask'],response.json()['ask']
    assert admin.get('/api/graph/records/fictional_sample_link').json()['total']==0
    saved=save(admin,{'ticket_id':response.json()['ticket_id']})
    page=admin.get(f'/api/graph/record/{saved["id"]}').json()
    value=next(v for v in page['values']if v['name']==field)
    assert value['raw']==party and value['display']==name


def test_named_reference_does_not_resolve_an_invisible_supplier(admin,scoped_contacts):
    projects,vendors,site_id,site=scoped_contacts
    save(admin,propose(admin,'metadata_type',{'key':'fictional_scoped_link','title':'Fictional scoped link','fields':[
        {'name':'note','type':'text','required':True},{'name':'supplier','type':'reference','target':'system.supplier','required':True}]}))
    response=write(site,'post','/api/chat',{'message':'Fictional scoped link for Fictional Assigned Site; note: Fictional delivery query; supplier: Fictional Indigo Wiring'})
    assert response.status_code==200,response.text
    items=[i for i in response.json()['preview']['items']if i['item_type']=='metadata_record']
    assert len(items)==1,items
    assert items[0]['after']['values'].get('supplier')!=vendors[1]
    assert response.json()['ask'],response.json()
    assert admin.get('/api/graph/records/fictional_scoped_link').json()['total']==0
