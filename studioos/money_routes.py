"""Costs, payments and the approvals queue (historical money paths).

Moved out of main.py without changing the code; only `@app.` became `@costs_router.` or `@approvals_router.`. The two
routers are included in main.py where each group of routes used to be, so route order is unchanged. The request models
(CostIn, PaymentIn, CorrectionIn, ReversalIn) moved with them and are re-imported by main.py, which still uses
ReversalIn and _not_own_money elsewhere.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_runtime import financial_review
from .db import ApprovalTicket, ApprovalTicketItem, Cost, Payment, PaymentReversal, Project, User
from .deps import get_db
from .finance_helpers import adjustments, cost_net, money, parse_amount, payment_sums, start_finance_lock
from .security import APPROVERS, FINANCE_READ, FINANCE_WRITE, permit

costs_router = APIRouter()
approvals_router = APIRouter()


def _manual_draft(*args, **kwargs):
    """main.py owns _manual_draft and imports this module, so it is imported at call time to avoid a circular import."""
    from .main import _manual_draft as draft
    return draft(*args, **kwargs)


class CostIn(BaseModel):
    project_id: int
    kind: str
    title: str = Field(min_length=2,max_length=400)
    vendor: str = ""
    amount: str | float | int

class PaymentIn(BaseModel):
    cost_id: int
    amount: str | float | int
    idempotency_key: str = Field(min_length=12,max_length=100)

class CorrectionIn(BaseModel):
    reason: str=Field(min_length=10,max_length=500)
    new_amount: str | float | int

class ReversalIn(BaseModel):
    reason: str=Field(min_length=10,max_length=500)


@costs_router.get('/api/costs')
def get_costs(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    names={p.id:p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()}
    sums=payment_sums(db)
    pending=payment_sums(db,include_pending=True)
    a=adjustments(db)
    return [{"id":c.id,"project_id":c.project_id,"project":names.get(c.project_id,''),"kind":c.kind,"status":c.status,"title":c.title,"vendor":c.vendor,"payment_mode":c.payment_mode,"expense_date":c.expense_date,"gst_included":c.gst_included,"category":c.category,"amount":money(c.amount_paise+a.get(c.id,0)),"paid":money(sums.get(c.id,0)),"payment_pending":money(pending.get(c.id,0)-sums.get(c.id,0)),"outstanding":money(c.amount_paise+a.get(c.id,0)-sums.get(c.id,0))} for c in db.scalars(select(Cost).where(Cost.deleted_at.is_(None)).order_by(Cost.id.desc())).all()]

@costs_router.post('/api/costs')
def post_cost(v:CostIn,user:User=Depends(permit(*FINANCE_WRITE)),db:Session=Depends(get_db)):
    try:
        amount=parse_amount(v.amount)
        review=financial_review(db,v.project_id,amount,v.kind)
        if review['decision']=='blocked':raise ValueError('Financial validation failed')
        return _manual_draft(db,user,'record_cost',{'project':v.project_id,'kind':v.kind,'title':v.title,'vendor':v.vendor,'amount_paise':amount})
    except ValueError as e:raise HTTPException(400,str(e))

def _legacy_action_draft(db,user,kind,rid,action,reason,new_amount=None):
    from . import legacy_money
    try:
        obj=legacy_money.source(db,kind,rid)
        if action=='approve':_not_own_money(obj,user)
        return legacy_money.propose(db,user,kind,rid,action,reason,new_amount)
    except ValueError as ex:raise HTTPException(409,str(ex))

@costs_router.patch('/api/costs/{cost_id}/recognize')
def recognize_purchase(cost_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'recognize','Recognize the existing approved purchase commitment')

@costs_router.post('/api/payments')
def post_payment(v:PaymentIn,user:User=Depends(permit(*FINANCE_WRITE)),db:Session=Depends(get_db)):
    try:
        amount=parse_amount(v.amount);cost=start_finance_lock(db,v.cost_id)
        if not cost or cost.deleted_at:raise ValueError('Referenced cost does not exist')
        if cost.status!='approved':raise ValueError('Approve the cost or purchase before submitting a payment')
        existing=db.scalar(select(Payment).where(Payment.idempotency_key==v.idempotency_key))
        if existing:
            if existing.cost_id!=v.cost_id or existing.amount_paise!=amount:raise ValueError('Idempotency key already used for another payment')
            return {'id':existing.id,'amount':money(existing.amount_paise),'status':existing.status,'existing':True}
        pending=db.scalars(select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
            ApprovalTicketItem.item_type=='record_payment',ApprovalTicketItem.status.in_(['pending','approved']),
            ApprovalTicket.status.not_in(['committed','reversed']),
            ApprovalTicketItem.after_data['idempotency_key'].as_string()==v.idempotency_key)).first()
        if pending:
            d=pending.after_data
            if d.get('cost_id')!=v.cost_id or d.get('amount_paise')!=amount:raise ValueError('Idempotency key already used for another payment')
            return {'ticket_id':pending.ticket_id,'item_id':pending.id,'state':'pending','changed':False}
        return _manual_draft(db,user,'record_payment',{'cost_id':v.cost_id,'amount_paise':amount,'idempotency_key':v.idempotency_key})
    except ValueError as e:raise HTTPException(400,str(e))


@approvals_router.get('/api/approvals')
def pending_approvals(user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    costs=[{'id':c.id,'project_id':c.project_id,'title':c.title,'amount':money(cost_net(db,c)),'kind':c.kind} for c in db.scalars(select(Cost).where(Cost.status=='pending',Cost.deleted_at.is_(None))).all()]
    pays=[{'id':p.id,'cost_id':p.cost_id,'amount':money(p.amount_paise)} for p in db.scalars(select(Payment).where(Payment.status=='pending',Payment.deleted_at.is_(None))).all()]
    return {'costs':costs,'payments':pays}

def _not_own_money(record,user):
    """v0.9.4 (review C2): the two-person money rule applies on this screen too.
    Only the Admin (the owner) may approve an entry they made themselves."""
    if record.created_by_id is not None and record.created_by_id==user.id and user.role!='admin':
        raise HTTPException(403,'You entered this yourself; someone else must approve it')

@approvals_router.post('/api/costs/{cost_id}/approve')
def approve_cost(cost_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'approve','Approve the reviewed historical cost source')

@approvals_router.post('/api/costs/{cost_id}/reject')
def reject_cost(cost_id:int,body:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'reject',body.reason)

@approvals_router.post('/api/payments/{payment_id}/approve')
def approve_payment(payment_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'approve','Approve the reviewed historical payment source')

@approvals_router.post('/api/payments/{payment_id}/reject')
def reject_payment(payment_id:int,body:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'reject',body.reason)

@approvals_router.post('/api/costs/{cost_id}/correct')
def correct_cost(cost_id:int,v:CorrectionIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    try:amount=parse_amount(v.new_amount)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return _legacy_action_draft(db,user,'cost',cost_id,'correct',v.reason,amount)

@approvals_router.post('/api/payments/{payment_id}/reverse')
def reverse_payment(payment_id:int,v:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'reverse',v.reason)

@approvals_router.get('/api/payments')
def get_payments(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    reversals={r.payment_id for r in db.scalars(select(PaymentReversal)).all()}
    return [{'id':p.id,'cost_id':p.cost_id,'project_id':p.project_id,'amount':money(p.amount_paise),'status':'reversed' if p.id in reversals else p.status} for p in db.scalars(select(Payment).order_by(Payment.id.desc())).all()]
