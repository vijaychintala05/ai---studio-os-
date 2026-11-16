"""Explicit references disambiguate similar tasks without widening project access."""
import json
from tests.conftest import write,approved_form
from tests.test_v0100_one_graph import add_user,client_for


def fixture(admin):
    p=approved_form(admin,'post','/api/projects',{'name':'Fictional Reference Site','budget':'10000'}).json()['id']
    ids=[approved_form(admin,'post','/api/tasks',{'project_id':p,'title':'Layout drawing '+key}).json()['id']for key in ('T001','T002')]
    return p,ids


def send(client,message):
    r=write(client,'post','/api/chat',{'message':message});assert r.status_code==200,r.text;return r.json()


def test_explicit_task_id_with_project_drafts_only_the_referenced_task(admin):
    p,ids=fixture(admin);r=send(admin,f'Task #{ids[1]} at Fictional Reference Site is 100% done')
    item=next(i for i in r.get('preview',{}).get('items',[])if i['item_type']=='update_task')
    assert item['after']['id']==ids[1]and item['after']['progress']==100
    assert all(t['status']=='open'for t in admin.get('/api/tasks').json())
    assert write(admin,'post',f'/api/tickets/{r["ticket_id"]}/approve-and-save',{}).status_code==200
    assert {t['id']:t['status']for t in admin.get('/api/tasks').json()}=={ids[0]:'open',ids[1]:'done'}


def test_bare_explicit_task_id_resolves_its_visible_project(admin):
    p,ids=fixture(admin);r=send(admin,f'Task #{ids[0]} is complete')
    item=next(i for i in r.get('preview',{}).get('items',[])if i['item_type']=='update_task')
    assert item['after']['id']==ids[0]and item['after']['project']=='Fictional Reference Site'


def test_ambiguous_title_choice_is_actionable_even_when_only_suffixes_differ(admin):
    p,ids=fixture(admin);r=send(admin,'Layout drawing at Fictional Reference Site is 100% done')
    ask=next(q for q in r['ask']if q['id']=='task')
    chosen=send(admin,ask['choices'][1]['value'])
    assert chosen['preview']['items'][0]['after']['id']==ids[1]


def test_hidden_reference_never_exposes_or_updates_the_other_project(admin):
    p,ids=fixture(admin);own=approved_form(admin,'post','/api/projects',{'name':'Fictional Own Site','budget':'1000'}).json()['id']
    uid=add_user(admin,'fictional.reference.site','site_engineer');write(admin,'put',f'/api/projects/{own}/members',{'user_ids':[uid]})
    site=client_for('fictional.reference.site')
    try:
        r=send(site,f'Task #{ids[0]} is 100% done')
        assert not any(i['item_type']=='update_task'for i in r.get('preview',{}).get('items',[]))
        assert 'Layout drawing'not in json.dumps(r)
    finally:site.close()
