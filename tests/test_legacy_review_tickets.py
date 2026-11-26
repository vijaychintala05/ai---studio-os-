"""Retired tracker actions and approval guards on fictional data.
"""
import pytest
from studioos.db import SessionLocal,Cost,Payment,FinancialAdjustment,PaymentReversal
from .conftest import write


@pytest.mark.parametrize('kind,decision', [('costs', 'approve'), ('costs', 'reject'), ('payments', 'approve'), ('payments', 'reject')])
def test_old_review_buttons_refuse_to_open_a_ticket(admin, kind, decision):
    opening = admin.get('/api/tickets').json()
    response = write(admin, 'post', f'/api/{kind}/1/{decision}', {'reason': 'Fictional old review'})
    assert response.status_code == 410 and 'Books' in response.json()['detail']
    assert admin.get('/api/tickets').json() == opening


@pytest.mark.parametrize('model,values', [
    (Cost, {'project_id': 1, 'kind': 'expense', 'title': 'Fictional old cost', 'amount_paise': 100}),
    (Payment, {'project_id': 1, 'cost_id': 1, 'amount_paise': 100, 'idempotency_key': 'fictional-old-payment'}),
    (FinancialAdjustment, {'cost_id': 1, 'delta_paise': 100, 'reason': 'Fictional unreviewed change', 'created_by': 'admin'}),
    (PaymentReversal, {'payment_id': 1, 'reason': 'Fictional unreviewed reversal', 'created_by': 'admin'}),
])
def test_api_money_orm_gate_requires_an_approved_ticket(admin, model, values):
    with SessionLocal() as db:
        db.info['write_source'] = 'api:POST /fictional-accidental-old-write'
        db.add(model(**values))
        with pytest.raises(PermissionError, match='approved ticket item'):
            db.flush()
        db.rollback()


@pytest.mark.parametrize('raw', [False, True])
def test_api_money_sql_gate_cannot_bypass_ticket_staging(admin, raw):
    from sqlalchemy import update

    with SessionLocal() as db:
        db.info['write_source'] = 'api:POST /fictional-accidental-sql-write'
        with pytest.raises(PermissionError, match='approved ticket item'):
            if raw:
                db.connection().exec_driver_sql("UPDATE costs SET status='rejected' WHERE id=1")
            else:
                db.execute(update(Cost).where(Cost.id == 1).values(status='rejected'))
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
