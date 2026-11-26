"""Historical tracker rows remain readable and cannot be changed by the old controls.
The fixture represents imported old-version rows, never a public write path.
"""
import pytest
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


@pytest.mark.parametrize('kind,decision', [('costs', 'approve'), ('costs', 'reject'), ('payments', 'approve'), ('payments', 'reject')])
def test_old_review_buttons_refuse_to_touch_historical_rows(admin, kind, decision):
    cost_id, payment_id = legacy_rows(admin)
    model, record_id = (Cost, cost_id) if kind == 'costs' else (Payment, payment_id)
    opening = admin.get('/api/tickets').json()
    response = write(admin, 'post', f'/api/{kind}/{record_id}/{decision}', {'reason': 'Fictional old review'})
    assert response.status_code == 410 and 'Books' in response.json()['detail']
    assert admin.get('/api/tickets').json() == opening
    with SessionLocal() as db:
        assert db.get(model, record_id).status == 'pending'


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


def test_generic_undo_is_a_new_reviewed_compensating_ticket(admin):
    project_draft=write(admin,'post','/api/projects',{'name':'Fictional Undo Gate Site','budget':'100000'}).json()
    saved=write(admin,'post',f'/api/tickets/{project_draft["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    original=project_draft['ticket_id']
    before=admin.get('/api/projects').json()
    draft=write(admin,'post',f'/api/tickets/{original}/reverse',{'reason':'Fictional duplicate creation cancelled'})
    assert draft.status_code==200,draft.text
    assert admin.get('/api/projects').json()==before
    assert draft.json()['ticket_id']!=original
    assert admin.get(f'/api/tickets/{original}').json()['status']=='committed'
    committed=write(admin,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{})
    assert committed.status_code==200,committed.text
    assert admin.get(f'/api/tickets/{original}').json()['status']=='reversed'
    assert admin.get('/api/projects').json()==[]
