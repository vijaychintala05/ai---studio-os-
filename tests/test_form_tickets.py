"""Human forms must draft before business records exist."""
from .conftest import write


def test_project_form_is_not_an_implicit_approval(admin):
    before=admin.get('/api/projects').json()
    p=write(admin,'post','/api/projects',{'name':'Fictional pending form site','budget':'1000'})
    assert p.status_code==200,p.text
    assert admin.get('/api/projects').json()==before
    assert p.json()['ticket_id']
    r=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert r.status_code==200,r.text
    assert len(admin.get('/api/projects').json())==len(before)+1


def test_task_and_site_forms_wait_for_review(admin):
    c=write(admin,'post','/api/chat',{'message':'Create project Fictional Review Site'}).json()
    r=write(admin,'post',f'/api/tickets/{c["ticket_id"]}/approve-and-save',{})
    assert r.status_code==200,r.text
    pid=admin.get('/api/projects').json()[0]['id']
    for path,data,listing in [('/api/tasks',{'project_id':pid,'title':'Fictional task to review'},'/api/tasks'),('/api/site-reports',{'project_id':pid,'note':'Fictional inspection note'},'/api/site-reports')]:
        before=admin.get(listing).json();p=write(admin,'post',path,data)
        assert p.status_code==200,p.text
        assert admin.get(listing).json()==before
        assert write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{}).status_code==200
        assert len(admin.get(listing).json())==len(before)+1
