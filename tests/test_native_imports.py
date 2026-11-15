"""Native vendor/task CSV rows must use the same reviewed business records."""
from sqlalchemy import select
from .conftest import write, approved_form
from .test_v0140_intake_app import _up
from studioos.db import SessionLocal, Party, Task, IntakeImport


def test_vendor_csv_waits_for_approval_and_reimport_is_empty(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    data=b'name,phone,trade\nFictional Tiles Supplier,9000000001,tiles\nFictional Labour Contractor,9000000002,labour\n'
    it=_up(admin,'fictional-vendors.csv',data).json()
    preview=write(admin,'post',f'/api/intake/items/{it["id"]}/table',{'type_key':'system.supplier'})
    assert preview.status_code==200,preview.text
    assert preview.json()['to_import']==2 and not preview.json()['unreadable']
    proposal=write(admin,'post',f'/api/intake/items/{it["id"]}/import',{'type_key':'system.supplier'})
    assert proposal.status_code==200,proposal.text
    with SessionLocal() as db:assert db.scalars(select(Party)).all()==[]
    saved=write(admin,'post',f'/api/tickets/{proposal.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal() as db:
        assert {p.name for p in db.scalars(select(Party).where(Party.kind=='vendor'))}=={'Fictional Tiles Supplier','Fictional Labour Contractor'}
        assert len(db.scalars(select(IntakeImport)).one().record_ids)==2
    again=_up(admin,'same-vendors.csv',data).json()
    prev=write(admin,'post',f'/api/intake/items/{again["id"]}/table',{'type_key':'system.supplier'})
    assert prev.status_code==200,prev.text
    assert prev.json()['to_import']==0 and prev.json()['already_imported']==2


def test_task_csv_creates_native_project_tasks_only_after_review(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional CSV Site','budget':'1000'}).json()['id']
    it=_up(admin,'tasks.csv',b'title,due_date\nFictional floor layout,2026-11-20\nFictional site measurement,2026-11-21\n').json()
    req={'type_key':'system.task','project_id':project}
    p=write(admin,'post',f'/api/intake/items/{it["id"]}/import',req)
    assert p.status_code==200,p.text
    assert admin.get('/api/tasks').json()==[]
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal() as db:
        tasks=db.scalars(select(Task)).all()
        assert len(tasks)==2 and {t.project_id for t in tasks}=={project}
        assert {t.title for t in tasks}=={'Fictional floor layout','Fictional site measurement'}


def test_native_import_rechecks_source_instead_of_trusting_rehashed_rows(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    it=_up(admin,'vendors.csv',b'name,phone\nFictional Original Supplier,9000000020\n').json()
    p=write(admin,'post',f'/api/intake/items/{it["id"]}/import',{'type_key':'system.supplier'}).json()
    ticket=admin.get(f'/api/tickets/{p["ticket_id"]}').json()
    item=ticket['items'][0];after=item['after']
    after['rows'][0]['values']['name']='Fictional Forged Supplier'
    from studioos.native_imports import row_key
    after['rows'][0]['key']=row_key('system.supplier',after['rows'][0]['values'],None)
    patch=write(admin,'patch',f'/api/tickets/items/{item["id"]}',{'after':after})
    assert patch.status_code==422,patch.text
    with SessionLocal() as db:assert db.scalars(select(Party)).all()==[]


def test_native_import_rechecks_changed_file_at_final_save(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    it=_up(admin,'vendors.csv',b'name\nFictional Unchanged Supplier\n').json()
    p=write(admin,'post',f'/api/intake/items/{it["id"]}/import',{'type_key':'system.supplier'}).json()
    from studioos.db import IntakeItem
    from pathlib import Path
    with SessionLocal() as db:path=Path(db.get(IntakeItem,it['id']).stored_path)
    path.chmod(0o600);path.write_bytes(b'name\nFictional Altered Supplier\n')
    saved=write(admin,'post',f'/api/tickets/{p["ticket_id"]}/approve-and-save',{})
    assert saved.status_code in (409,422),saved.text
    assert 'source file changed' in saved.text.lower()
    with SessionLocal() as db:assert db.scalars(select(Party)).all()==[]


def test_native_import_does_not_give_staff_global_contact_writes(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    from .test_v0100_one_graph import add_user,client_for
    add_user(admin,'fictional.site','site_engineer');site=client_for('fictional.site')
    own=_up(site,'vendors.csv',b'name\nFictional Staff Vendor\n').json()
    assert write(site,'post',f'/api/intake/items/{own["id"]}/import',{'type_key':'system.supplier'}).status_code==422
    private=_up(admin,'private.csv',b'name\nFictional Private Vendor\n').json()
    from studioos.native_imports import row_key
    values={'name':'Fictional Private Vendor'}
    forged={'type_key':'system.supplier','intake_id':private['id'],'mapping':{'0':'name'},'rows':[{'values':values,'key':row_key('system.supplier',values,None)}]}
    assert write(site,'post','/api/universal/proposals',{'kind':'metadata_import','data':forged,'evidence':'Fictional access probe'}).status_code==404
    with SessionLocal() as db:assert db.scalars(select(Party)).all()==[]


def test_two_pending_imports_cannot_commit_the_same_vendor_rows(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    drafts=[]
    for name in ('first.csv','again.csv'):
        it=_up(admin,name,b'name\nFictional Once Only Supplier\n').json()
        p=write(admin,'post',f'/api/intake/items/{it["id"]}/import',{'type_key':'system.supplier'})
        assert p.status_code==200,p.text
        drafts.append(p.json()['ticket_id'])
    first=write(admin,'post',f'/api/tickets/{drafts[0]}/approve-and-save',{})
    assert first.status_code==200,first.text
    second=write(admin,'post',f'/api/tickets/{drafts[1]}/approve-and-save',{})
    assert second.status_code in (409,422),second.text
    with SessionLocal() as db:assert len(db.scalars(select(Party)).all())==1


def test_same_task_list_for_two_projects_keeps_both_relationships(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path))
    projects=[approved_form(admin,'post','/api/projects',{'name':f'Fictional CSV Site {i}','budget':'1000'}).json()['id']for i in range(2)]
    for project in projects:
        it=_up(admin,'checklist.csv',b'title\nFictional handover inspection\n').json()
        proposal=write(admin,'post',f'/api/intake/items/{it["id"]}/import',{'type_key':'system.task','project_id':project})
        assert proposal.status_code==200,proposal.text
        r=write(admin,'post',f'/api/tickets/{proposal.json()["ticket_id"]}/approve-and-save',{})
        assert r.status_code==200,r.text
    with SessionLocal() as db:
        tasks=db.scalars(select(Task)).all()
        assert len(tasks)==2 and {t.project_id for t in tasks}==set(projects)
