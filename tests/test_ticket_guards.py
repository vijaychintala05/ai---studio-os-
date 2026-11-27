"""Stage 2 security regression tests: every AI business mutation needs ticket approval."""
import pytest
from sqlalchemy import select, text
from .conftest import write, approved_form
from studioos.db import (SessionLocal, Project, Task, Cost, ApprovalTicket,
                         ApprovalTicketItem, TicketRecordLink, WriteJournal)


def proposal(client, message, sid=''):
    r=write(client,'post','/api/chat',{'message':message,'session_id':sid})
    assert r.status_code==200,r.text
    return r.json()


def test_chat_never_writes_projects_even_on_confirm(admin):
    first=proposal(admin,'Create project Villa Ticket with budget ₹12 lakh')
    assert first['ticket_id'] and first['item_id']
    with SessionLocal() as db:
        assert db.scalars(select(Project)).all()==[]
    ignored=proposal(admin,'Confirm',first['session_id'])
    assert ignored.get('changed') is False
    with SessionLocal() as db:
        assert db.scalars(select(Project)).all()==[]
    ticket=admin.get('/api/tickets/'+str(first['ticket_id'])).json()
    assert ticket['items'][0]['before'] is None
    assert ticket['items'][0]['after']['name']=='Villa Ticket'
    assert ticket['conversation'][0]['text'].startswith('Create project')
    assert ticket['items'][0]['source_message_id']==ticket['conversation'][0]['id']


def test_backend_orm_gate_rejects_ai_origin_and_direct_sql(admin):
    with SessionLocal() as db:
        db.info.update(write_source='chat',ai_origin=True)
        db.add(Project(name='Unauthorized',budget_paise=500000))
        with pytest.raises(PermissionError):db.commit()
        db.rollback()
    with SessionLocal() as db:
        db.info.update(write_source='ai:tool',ai_origin=True)
        with pytest.raises(PermissionError):
            db.execute(text("INSERT INTO projects (name,client,stage,budget_paise) VALUES ('Sneaky','','Planning',0)"))
        db.rollback()
    assert admin.get('/api/projects').json()==[]


def test_approved_ticket_creates_linked_record_and_manual_forms_still_work(admin):
    proposed=proposal(admin,'Create project Ticket Villa with budget ₹20 lakh')
    item,ticket=proposed['item_id'],proposed['ticket_id']
    assert write(admin,'post',f'/api/tickets/items/{item}/approve').status_code==200
    assert admin.get('/api/projects').json()==[]
    result=write(admin,'post',f'/api/tickets/{ticket}/commit')
    assert result.status_code==200,result.text
    assert len(result.json()['committed_records'])==1
    with SessionLocal() as db:
        link=db.scalar(select(TicketRecordLink))
        assert link.item_id==item and link.ticket_id==ticket
        journal=db.scalar(select(WriteJournal).where(WriteJournal.entity_type=='project',WriteJournal.source=='ai:ticket-commit'))
        assert journal and journal.original_chat_message_id
    # Existing manual API remains available and audit-logged.
    manual=approved_form(admin,'post','/api/projects',{'name':'Manual Project','budget':'25000'})
    assert manual.status_code==200,manual.text
    assert len(admin.get('/api/projects').json())==2


def test_rejected_items_never_written_and_edit_requires_reapproval(admin):
    first=proposal(admin,'Create project Rejected Villa with budget ₹10 lakh')
    second=proposal(admin,'Create project Kept Villa with budget ₹12 lakh',first['session_id'])
    assert first['ticket_id']==second['ticket_id']
    rejected=write(admin,'post',f"/api/tickets/items/{first['item_id']}/reject",{'note':'Not required'})
    assert rejected.status_code==200
    edit=write(admin,'patch',f"/api/tickets/items/{second['item_id']}",{'after':{'name':'Edited Villa','amount_paise':130000000}})
    assert edit.status_code==200,edit.text
    edited = edit.json()['items'][1]
    assert edited['status']=='pending'
    assert write(admin,'post',f"/api/tickets/{first['ticket_id']}/commit").status_code==409
    assert write(admin,'post',f"/api/tickets/items/{second['item_id']}/approve",
                 {'review_fingerprint': edited['review_fingerprint']}).status_code==200
    assert write(admin,'post',f"/api/tickets/{first['ticket_id']}/commit").status_code==200
    names={p['name'] for p in admin.get('/api/projects').json()}
    assert names=={'Edited Villa'}
    with SessionLocal() as db:
        assert db.scalar(select(TicketRecordLink).where(TicketRecordLink.item_id==first['item_id'])) is None


def test_failed_second_item_rolls_back_first(monkeypatch,admin):
    import studioos.main as main
    a=proposal(admin,'Create project First Approved with budget ₹5 lakh')
    b=proposal(admin,'Create project Second Approved with budget ₹7 lakh',a['session_id'])
    for p in (a,b):
        r=write(admin,'post',f"/api/tickets/items/{p['item_id']}/approve")
        assert r.status_code==200,r.text
    original=main.apply_item
    count={'n':0}
    def failure(db,item,user):
        count['n']+=1
        if count['n']==2:raise ValueError('Simulated second-item failure')
        return original(db,item,user)
    monkeypatch.setattr(main,'apply_item',failure)
    commit=write(admin,'post',f"/api/tickets/{a['ticket_id']}/commit")
    assert commit.status_code==409,commit.text
    with SessionLocal() as db:
        assert db.scalars(select(Project)).all()==[]
        assert db.scalars(select(TicketRecordLink)).all()==[]
        assert db.get(ApprovalTicket,a['ticket_id']).status!='committed'


def test_only_admin_can_approve_schema_even_if_manager_can_propose(admin):
    r=proposal(admin,'Please add a field for supplier GSTIN')
    assert r['item_id']
    # Both the stored policy and HTTP decision enforce admin-only schema approval.
    pol=admin.get('/api/tickets/policy').json()
    assert pol['suggest_schema']==['admin']
    bad={k:['admin','manager'] for k in pol}
    assert write(admin,'put','/api/tickets/policy',{'approvers':bad}).status_code==400
    write(admin,'post','/api/users',{'username':'projectmanager','display_name':'Project Manager','role':'manager','password':'manager-password-strong'})
    write(admin,'post','/api/auth/logout')
    assert admin.post('/api/auth/login',json={'username':'projectmanager','password':'manager-password-strong'}).status_code==200
    assert write(admin,'post',f"/api/tickets/items/{r['item_id']}/approve").status_code==403
    assert write(admin,'post',f"/api/tickets/{r['ticket_id']}/commit").status_code==409


def test_ticket_approval_is_separate_from_financial_queue(admin):
    from studioos.db import FinanceExpense
    from .books_fixtures import draft_project_expense
    from .test_v098_universal_accounting import finance_setup

    finance_setup(admin)
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Cost Project', 'budget': '100000'}).json()
    draft = draft_project_expense(admin, project['id'], 950000, note='Fictional cement')
    assert draft.status_code == 200, draft.text
    r = draft.json()
    assert admin.get('/api/approvals').json()['costs']==[]
    with SessionLocal() as db:
        assert db.scalar(select(FinanceExpense.id)) is None
    assert write(admin,'post',f"/api/tickets/items/{r['item_id']}/approve").status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(FinanceExpense.id)) is None
    assert write(admin,'post',f"/api/tickets/{r['ticket_id']}/commit").status_code==200
    with SessionLocal() as db:
        assert db.scalars(select(FinanceExpense.amount_paise)).one() == 950000
    assert admin.get('/api/approvals').json()['costs']==[]


def test_raw_connection_sql_cannot_bypass_ai_origin(admin):
    with SessionLocal() as db:
        db.info.update(write_source='ai:untrusted-tool',ai_origin=True)
        with pytest.raises(PermissionError):
            db.connection().exec_driver_sql("INSERT INTO projects (name,client,stage,budget_paise) VALUES ('Raw Bypass','','Planning',1)")
        db.rollback()
    assert admin.get('/api/projects').json()==[]


def test_policy_allows_manager_only_when_admin_configures_type(admin):
    pol=admin.get('/api/tickets/policy').json()
    pol['create_task']=['admin','manager']
    assert write(admin,'put','/api/tickets/policy',{'approvers':pol}).status_code==200
    assert set(admin.get('/api/tickets/policy').json()['create_task'])=={'admin','manager'}
    assert admin.get('/api/tickets/policy').json()['suggest_schema']==['admin']


def test_second_admin_account_is_blocked(admin):
    r=write(admin,'post','/api/users',{'username':'otherowner','display_name':'Other Owner','role':'admin','password':'owner-password-strong'})
    assert r.status_code==403
