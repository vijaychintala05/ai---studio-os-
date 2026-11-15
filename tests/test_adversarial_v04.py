"""v0.4 adversarial acceptance checks. Run on disposable SQLite fixture only."""
import os,sqlite3
import pytest
from sqlalchemy import select,text,create_engine,inspect
from .conftest import write
from studioos.db import (SessionLocal,Project,Cost,Party,ApprovalTicket,ApprovalTicketItem,
                          TicketRecordLink,Audit)


def post_chat(c,msg,sid=''):
    r=write(c,'post','/api/chat',{'message':msg,'session_id':sid})
    assert r.status_code==200,r.text
    return r.json()


def test_ai_cannot_write_direct_with_orm_or_raw_sql(admin):
    with SessionLocal() as db:
        db.info.update(write_source='ai:malicious',ai_origin=True)
        db.add(Project(name='Unapproved cost project',budget_paise=1))
        with pytest.raises(PermissionError):db.flush()
        db.rollback()
    with SessionLocal() as db:
        db.info.update(write_source='ai:malicious',ai_origin=True)
        with pytest.raises(PermissionError):
            db.connection().exec_driver_sql("INSERT INTO projects (name,client,stage,budget_paise) VALUES ('Raw Attack','','Planning',1)")
        db.rollback()
    assert not admin.get('/api/projects').json()


def test_chat_confirmation_does_not_apply_proposal(admin):
    r=post_chat(admin,'Create project Confirmation Bypass with budget ₹10 lakh')
    second=post_chat(admin,'Confirm',r['session_id'])
    assert second['changed'] is False
    assert all(x['name']!='Confirmation Bypass' for x in admin.get('/api/projects').json())


def test_invalid_phone_stays_in_preview_and_cannot_be_approved(admin):
    r=post_chat(admin,'New client A Test Client, phone 98000.')
    i=admin.get('/api/tickets/'+str(r['ticket_id'])).json()['items'][0]
    assert any('invalid_phone' in f for f in i['flags'])
    assert i['field_evidence']['phone']['marker']=='invalid'
    denied=write(admin,'post',f'/api/tickets/items/{i["id"]}/approve')
    assert denied.status_code==422
    with SessionLocal() as db:assert db.scalars(select(Party)).all()==[]


def test_near_match_vendor_flagged_but_not_auto_written(admin):
    with SessionLocal() as db:
        db.add(Party(kind='vendor',name='Ravi Electricals'))
        db.commit()
    r=post_chat(admin,'New vendor: Ravi Electric, phone 9800000077, GSTIN pending.')
    t=admin.get('/api/tickets/'+str(r['ticket_id'])).json()
    assert len(t['items'])==1
    assert any('vendor' in x.casefold() and 'duplicate' in x.casefold() for x in t['items'][0]['flags'])
    with SessionLocal() as db:assert len(db.scalars(select(Party)).all())==1


def test_second_item_transaction_failure_rolls_back_all(monkeypatch,admin):
    import studioos.main as main
    r1=post_chat(admin,'Create project Transaction Alpha with budget ₹5 lakh')
    r2=post_chat(admin,'Create project Transaction Beta with budget ₹6 lakh',r1['session_id'])
    for r in (r1,r2):assert write(admin,'post',f'/api/tickets/items/{r["item_id"]}/approve').status_code==200
    real=main.apply_item
    count={'n':0}
    def fail(db,item,actor):
        count['n']+=1
        if count['n']==2:raise ValueError('Injected failure at second item')
        return real(db,item,actor)
    monkeypatch.setattr(main,'apply_item',fail)
    response=write(admin,'post',f'/api/tickets/{r1["ticket_id"]}/commit')
    assert response.status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(Project.id).where(Project.name=='Transaction Alpha')) is None
        assert db.scalar(select(Project.id).where(Project.name=='Transaction Beta')) is None
        assert db.get(ApprovalTicket,r1['ticket_id']).status!='committed'
        assert db.scalars(select(TicketRecordLink)).all()==[]


def test_failed_pre_migration_backup_blocks_ddl(tmp_path,monkeypatch):
    import studioos.migrations as migration
    src=tmp_path/'old.db'
    with sqlite3.connect(src) as con:
        con.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200))')
        con.execute("INSERT INTO projects VALUES (1,'keep')")
    engine=create_engine('sqlite:///'+str(src))
    def explode(*args,**kwargs):raise IOError('Backup storage unavailable')
    monkeypatch.setattr(migration,'before_schema_migration',explode)
    with pytest.raises(IOError,match='Backup storage unavailable'):
        migration.apply_migrations(engine)
    with sqlite3.connect(src) as con:
        assert con.execute('SELECT name FROM projects WHERE id=1').fetchone()==('keep',)
        assert 'approval_tickets' not in {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_reviewing_item_still_does_not_touch_financial_queue(admin):
    p=write(admin,'post','/api/projects',{'name':'Ledger Test','budget':'100000'})
    assert p.status_code==200
    r=post_chat(admin,'Log expense 3,200 for Anil Plumbing at Ledger Test, paid by UPI.')
    with SessionLocal() as db:assert db.scalars(select(Cost)).all()==[]
    a=write(admin,'post',f'/api/tickets/items/{r["item_id"]}/approve')
    assert a.status_code==200,a.text
    with SessionLocal() as db:assert db.scalars(select(Cost)).all()==[]
    c=write(admin,'post',f'/api/tickets/{r["ticket_id"]}/commit')
    assert c.status_code==200,c.text
    # v0.9.4 (review H1): the ticket approval IS the money approval; nothing waits twice.
    assert admin.get('/api/approvals').json()['costs']==[]
    costs=admin.get('/api/costs').json()
    assert len(costs)==1 and costs[0]['amount']==3200 and costs[0]['status']=='approved'


def test_soft_reverse_does_not_hard_delete(admin):
    r=post_chat(admin,'Create project Reversible Residence with budget ₹5 lakh')
    assert write(admin,'post',f'/api/tickets/items/{r["item_id"]}/approve').status_code==200
    assert write(admin,'post',f'/api/tickets/{r["ticket_id"]}/commit').status_code==200
    reverse=write(admin,'post',f'/api/tickets/{r["ticket_id"]}/reverse',{'reason':'Customer cancelled the demonstration'})
    assert reverse.status_code==200,reverse.text
    with SessionLocal() as db:
        p=db.scalar(select(Project).where(Project.name=='Reversible Residence'))
        assert p is not None and p.deleted_at is not None
        assert db.get(ApprovalTicket,r['ticket_id']).status=='reversed'
        assert db.scalar(select(Audit.id).where(Audit.action=='reverse_ticket')) is not None
    assert all(x['name']!='Reversible Residence' for x in admin.get('/api/projects').json())


def test_duplicate_expense_requires_explicit_review_note(admin):
    assert write(admin,'post','/api/projects',{'name':'Duplicate Residence','budget':'300000'}).status_code==200
    posted=write(admin,'post','/api/costs',{'project_id':1,'kind':'expense','title':'wiring material','vendor':'Ravi Electricals','amount':'12500'})
    assert posted.status_code==200,posted.text
    proposed=post_chat(admin,'Paid 12,500 cash to Ravi Electricals for wiring material at Duplicate Residence today.')
    item=admin.get('/api/tickets/'+str(proposed['ticket_id'])).json()['items'][0]
    assert any('possible_duplicate' in f for f in item['flags'])
    denied=write(admin,'post',f'/api/tickets/items/{item["id"]}/approve',{'note':'Looks okay'})
    assert denied.status_code==409
    with SessionLocal() as db:assert len(db.scalars(select(Cost)).all())==1


def test_unusual_amount_requires_confirmation_note(admin):
    proposed=post_chat(admin,'Paid 4,50,000 to Anil Plumbing for the bathroom taps.')
    item=admin.get('/api/tickets/'+str(proposed['ticket_id'])).json()['items'][0]
    assert any('unusually_high_amount' in f for f in item['flags'])
    assert write(admin,'post',f'/api/tickets/items/{item["id"]}/approve').status_code==409
    assert write(admin,'post',f'/api/tickets/items/{item["id"]}/approve',{'note':'amount confirmed against signed PO'}).status_code==200
    with SessionLocal() as db:assert db.scalars(select(Cost)).all()==[]


def test_ambiguous_sharma_name_is_not_autosaved(admin):
    p1=write(admin,'post','/api/projects',{'name':'Sharma Residence','budget':'100000'})
    p2=write(admin,'post','/api/projects',{'name':'Sharma Showroom','budget':'100000'})
    assert p1.status_code==p2.status_code==200
    proposed=post_chat(admin,'Ask Anil to finish bathroom plumbing rough-in at Sharma by next Friday.')
    item=admin.get('/api/tickets/'+str(proposed['ticket_id'])).json()['items'][0]
    assert item['after']['project'] is None
    assert write(admin,'post',f'/api/tickets/items/{item["id"]}/approve').status_code==422
    with SessionLocal() as db:assert db.scalars(select(__import__('studioos.db',fromlist=['Task']).Task)).all()==[]


def test_soft_reversed_expense_is_hidden_from_financial_queue(admin):
    project=write(admin,'post','/api/projects',{'name':'Reverse Cost Test','budget':'90000'})
    assert project.status_code==200
    proposed=post_chat(admin,'Log expense 3,200 for Anil Plumbing at Reverse Cost Test, paid by UPI.')
    assert write(admin,'post',f'/api/tickets/items/{proposed["item_id"]}/approve').status_code==200
    assert write(admin,'post',f'/api/tickets/{proposed["ticket_id"]}/commit').status_code==200
    assert len(admin.get('/api/costs').json())==1      # v0.9.4: approved in the ticket, not queued
    reversed_=write(admin,'post',f'/api/tickets/{proposed["ticket_id"]}/reverse',{'reason':'Duplicate expense entry cancelled'})
    assert reversed_.status_code==200,reversed_.text
    assert admin.get('/api/approvals').json()['costs']==[] and admin.get('/api/costs').json()==[]
    with SessionLocal() as db:
        costs=db.scalars(select(Cost)).all()
        assert len(costs)==1 and costs[0].deleted_at is not None


def test_approved_update_ticket_cannot_be_silently_soft_reversed(admin):
    # Changes to historical records require a separate compensating correction ticket.
    r=post_chat(admin,'New client XYZ Testing, phone 9800000087.')
    assert write(admin,'post',f'/api/tickets/items/{r["item_id"]}/approve').status_code==200
    assert write(admin,'post',f'/api/tickets/{r["ticket_id"]}/commit').status_code==200
    with SessionLocal() as db:
        party=db.scalar(select(Party).where(Party.name=='XYZ Testing'))
        assert party is not None
        party_id=party.id
    # A manually constructed AI suggestion is a ticket, not a direct write.
    from studioos.db import ChatSession,ChatMessage
    from studioos.tickets import add_proposal
    with SessionLocal() as db:
        adminuser=db.scalar(select(__import__('studioos.db',fromlist=['User']).User).where(__import__('studioos.db',fromlist=['User']).User.username=='admin'))
        session=ChatSession(id='update-existing-party',user_id=adminuser.id,pending=None)
        db.add(session);db.flush()
        source=ChatMessage(session_id=session.id,user_id=adminuser.id,speaker='user',content='Correct XYZ Testing phone number to 9800000088')
        db.add(source);db.flush()
        ticket,item=add_proposal(db,session,'update_client',{'id':party_id,'name':'XYZ Testing','phone':'9800000088'},source.id)
        tid=ticket.id;iid=item.id;db.commit()
    assert write(admin,'post',f'/api/tickets/items/{iid}/approve').status_code==200
    assert write(admin,'post',f'/api/tickets/{tid}/commit').status_code==200
    blocked=write(admin,'post',f'/api/tickets/{tid}/reverse',{'reason':'Undo the historical update'})
    assert blocked.status_code==409
    with SessionLocal() as db:
        assert db.get(Party,party_id).phone=='9800000088'
        assert db.get(ApprovalTicket,tid).status=='committed'
