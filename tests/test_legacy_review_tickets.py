"""Historical rows must be reviewed/corrected through tickets too.
The fixture represents imported old-version rows, never a public write path.
"""
import pytest
from sqlalchemy import select,func
from studioos.db import SessionLocal,Cost,Payment,FinancialAdjustment,PaymentReversal
from .conftest import write,approved_form


def legacy_rows(admin,cost_status='pending',payment_status='pending'):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Historical Review Site','budget':'100000'}).json()['id']
    user=admin.get('/api/auth/me').json()['user']['id']
    with SessionLocal()as db:
        c=Cost(project_id=project,kind='expense',title='Fictional old transport',amount_paise=100000,status=cost_status,created_by_id=user)
        db.add(c);db.flush()
        p=Payment(project_id=project,cost_id=c.id,amount_paise=20000,status=payment_status,created_by_id=user,idempotency_key='fictional-legacy-review-payment')
        db.add(p);db.commit();return c.id,p.id


@pytest.mark.parametrize('kind,decision',[('costs','approve'),('costs','reject'),('payments','approve'),('payments','reject')])
def test_old_review_button_only_drafts_until_ticket_commit(admin,kind,decision):
    cid,pid=legacy_rows(admin,'approved'if kind=='payments'else'pending')
    rid=cid if kind=='costs'else pid
    response=write(admin,'post',f'/api/{kind}/{rid}/{decision}',{'reason':'Fictional duplicate source rejected'}if decision=='reject'else{})
    assert response.status_code==200,response.text
    with SessionLocal()as db:assert db.get(Cost if kind=='costs'else Payment,rid).status=='pending'
    assert response.json().get('ticket_id'),response.text
    saved=write(admin,'post',f'/api/tickets/{response.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:assert db.get(Cost if kind=='costs'else Payment,rid).status==('approved'if decision=='approve'else'rejected')


def test_old_cost_correction_waits_for_ticket_and_preserves_original(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    response=write(admin,'post',f'/api/costs/{cid}/correct',{'new_amount':'1200','reason':'Fictional corrected source document'})
    assert response.status_code==200,response.text
    with SessionLocal()as db:
        assert db.scalar(select(func.count()).select_from(FinancialAdjustment))==0
        assert db.get(Cost,cid).amount_paise==100000
    saved=write(admin,'post',f'/api/tickets/{response.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        assert db.get(Cost,cid).amount_paise==100000
        assert db.scalar(select(FinancialAdjustment.delta_paise).where(FinancialAdjustment.cost_id==cid))==20000


def test_old_payment_reversal_waits_for_ticket_and_preserves_original(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    response=write(admin,'post',f'/api/payments/{pid}/reverse',{'reason':'Fictional wrong bank transfer reversed'})
    assert response.status_code==200,response.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(PaymentReversal))==0
    saved=write(admin,'post',f'/api/tickets/{response.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        assert db.get(Payment,pid).amount_paise==20000
        assert db.scalar(select(func.count()).select_from(PaymentReversal))==1


def test_old_purchase_recognition_waits_for_approved_ticket(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    with SessionLocal()as db:
        db.get(Cost,cid).kind='commitment';db.commit()
    response=write(admin,'patch',f'/api/costs/{cid}/recognize',{})
    assert response.status_code==200,response.text
    with SessionLocal()as db:assert db.get(Cost,cid).kind=='commitment'
    saved=write(admin,'post',f'/api/tickets/{response.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        assert db.get(Cost,cid).kind=='expense'
        assert db.scalar(select(func.count()).select_from(Cost))==1
        assert db.get(Cost,cid).amount_paise==100000


def test_two_old_correction_drafts_cannot_overwrite_each_others_result(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    first=write(admin,'post',f'/api/costs/{cid}/correct',{'new_amount':'1200','reason':'Fictional revised invoice one'}).json()
    second=write(admin,'post',f'/api/costs/{cid}/correct',{'new_amount':'1300','reason':'Fictional revised invoice two'}).json()
    assert write(admin,'post',f'/api/tickets/{first["ticket_id"]}/approve-and-save',{}).status_code==200
    stale=write(admin,'post',f'/api/tickets/{second["ticket_id"]}/approve-and-save',{})
    # approve-and-save reports failed revalidation as 422 before commit.
    assert stale.status_code==422 and 'Historical record changed'in stale.text,stale.text
    with SessionLocal()as db:
        assert db.scalar(select(func.sum(FinancialAdjustment.delta_paise)))==20000
        assert db.get(Cost,cid).amount_paise==100000


def test_correction_rechecks_new_payment_reservations_at_final_commit(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    draft=write(admin,'post',f'/api/costs/{cid}/correct',{'new_amount':'800','reason':'Fictional source amended before new payment'}).json()
    reservation=write(admin,'post','/api/payments',{'cost_id':cid,'amount':'700','idempotency_key':'fictional-reserved-after-correction'})
    assert reservation.status_code==200,reservation.text
    refused=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert refused.status_code in (409,422),refused.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinancialAdjustment))==0


def test_historical_source_identity_cannot_be_changed_in_review(admin):
    cid,pid=legacy_rows(admin,'approved','approved')
    draft=write(admin,'post',f'/api/payments/{pid}/reverse',{'reason':'Fictional payment correction'}).json()
    item=admin.get(f'/api/tickets/{draft["ticket_id"]}').json()['items'][0]
    changed={**item['after'],'record_id':pid+1}
    refused=write(admin,'patch',f'/api/tickets/items/{item["id"]}',{'after':changed})
    assert refused.status_code==422,refused.text


@pytest.mark.parametrize('operation',['cost_review','payment_review','adjustment','reversal'])
def test_api_money_orm_gate_requires_an_approved_ticket(admin,operation):
    cid,pid=legacy_rows(admin,'approved','approved')
    with SessionLocal()as db:
        db.info['write_source']='api:POST /fictional-accidental-old-write'
        if operation=='cost_review':db.get(Cost,cid).status='rejected'
        elif operation=='payment_review':db.get(Payment,pid).status='rejected'
        elif operation=='adjustment':db.add(FinancialAdjustment(cost_id=cid,delta_paise=100,reason='Fictional unreviewed change',created_by='admin'))
        else:db.add(PaymentReversal(payment_id=pid,reason='Fictional unreviewed reversal',created_by='admin'))
        with pytest.raises(PermissionError):db.flush()
        db.rollback()


@pytest.mark.parametrize('raw',[False,True])
def test_api_money_sql_gate_cannot_bypass_ticket_staging(admin,raw):
    from sqlalchemy import update
    cid,pid=legacy_rows(admin,'approved','approved')
    with SessionLocal()as db:
        db.info['write_source']='api:POST /fictional-accidental-sql-write'
        with pytest.raises(PermissionError):
            if raw:db.connection().exec_driver_sql("UPDATE costs SET status='rejected' WHERE id=%s"%cid)
            else:db.execute(update(Cost).where(Cost.id==cid).values(status='rejected'))
        db.rollback()


def test_source_creator_cannot_approve_another_persons_review_ticket(admin):
    from fastapi.testclient import TestClient
    from studioos.main import app
    cid,pid=legacy_rows(admin)
    manager=write(admin,'post','/api/users',{'username':'fictional.manager','display_name':'Fictional Manager','role':'manager','password':'FictionalManagerPassword2026'}).json()['id']
    with SessionLocal()as db:db.get(Cost,cid).created_by_id=manager;db.commit()
    policy=admin.get('/api/tickets/policy').json();policy['legacy_money_action']=['admin','manager']
    assert write(admin,'put','/api/tickets/policy',{'approvers':policy}).status_code==200
    proposal=write(admin,'post',f'/api/costs/{cid}/approve',{}).json()
    with TestClient(app)as reviewer:
        assert reviewer.post('/api/auth/login',json={'username':'fictional.manager','password':'FictionalManagerPassword2026'}).status_code==200
        result=write(reviewer,'post',f'/api/tickets/{proposal["ticket_id"]}/approve-and-save',{})
        assert result.status_code==403,result.text
    with SessionLocal()as db:assert db.get(Cost,cid).status=='pending'


@pytest.mark.parametrize('kind',['project','cost'])
def test_generic_undo_is_a_new_reviewed_compensating_ticket(admin,kind):
    project_draft=write(admin,'post','/api/projects',{'name':'Fictional Undo Gate Site','budget':'100000'}).json()
    saved=write(admin,'post',f'/api/tickets/{project_draft["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    project=saved.json()['committed_records'][0]['id'];original=project_draft['ticket_id']
    if kind=='cost':
        original=write(admin,'post','/api/costs',{'project_id':project,'kind':'expense','title':'Fictional mistaken cost','amount':'1000'}).json()['ticket_id']
        assert write(admin,'post',f'/api/tickets/{original}/approve-and-save',{}).status_code==200
    before=admin.get('/api/projects'if kind=='project'else'/api/costs').json()
    draft=write(admin,'post',f'/api/tickets/{original}/reverse',{'reason':'Fictional duplicate creation cancelled'})
    assert draft.status_code==200,draft.text
    assert admin.get('/api/projects'if kind=='project'else'/api/costs').json()==before
    assert draft.json()['ticket_id']!=original
    assert admin.get(f'/api/tickets/{original}').json()['status']=='committed'
    committed=write(admin,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{})
    assert committed.status_code==200,committed.text
    assert admin.get(f'/api/tickets/{original}').json()['status']=='reversed'
    assert admin.get('/api/projects'if kind=='project'else'/api/costs').json()==[]
