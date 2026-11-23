"""Money formatting, amount parsing, payment and cost totals, and project lookups shared by the API routes.

Moved out of main.py without changing the code. main.py re-imports every name at the position where the
code used to be, because other modules import these names from studioos.main. Keeping them here lets the
router modules use them without importing main.py (which includes those routers).
"""
from __future__ import annotations
import re

from sqlalchemy import func, select

from .db import (ApprovalTicket, ApprovalTicketItem, Cost, FinancialAdjustment, Payment, PaymentReversal, Project)
from .providers import parse_money


def money(p): return round(int(p or 0) / 100, 2)


def parse_amount(value, *, allow_zero=False):
    """Strict INR amount validation for public APIs; reject ambiguous trailing text."""
    if isinstance(value,bool): raise ValueError('Amount must be a number')
    raw=str(value).strip()
    if allow_zero and re.fullmatch(r'(?:₹|Rs\.?|INR)?\s*0+(?:\.0{1,2})?', raw, re.I): return 0
    m=re.fullmatch(r'(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]*)(\.[0-9]{1,2})?\s*(?:(?:crores?|cr|lakhs?|lacs?|lakh|lac|k|thousand))?', raw, re.I)
    # commas only in Indian (1,25,000) or Western (125,000) grouping; anything else is a typo, not a number
    if not m or (',' in m.group(1) and not re.fullmatch(r'[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}|[0-9]{1,3}(?:,[0-9]{3})+', m.group(1))):
        raise ValueError('Enter a valid INR amount, e.g. 12500, 1,25,000 or ₹1.5 lakh')
    parsed=parse_money(raw)
    if parsed is None or parsed<0: raise ValueError('Amount must be a valid nonnegative number')
    return parsed


def adjustments(db):
    result={}
    for cost_id,total in db.execute(select(FinancialAdjustment.cost_id,func.sum(FinancialAdjustment.delta_paise)).group_by(FinancialAdjustment.cost_id)).all():
        result[cost_id]=int(total or 0)
    return result


def payment_sums(db, include_pending=False, exclude_ticket_item_id=None):
    stmt=(select(Payment.cost_id,func.coalesce(func.sum(Payment.amount_paise),0))
          .outerjoin(PaymentReversal,PaymentReversal.payment_id==Payment.id)
          .where(PaymentReversal.id.is_(None),Payment.deleted_at.is_(None)))
    if include_pending: stmt=stmt.where(Payment.status.in_(['approved','pending']))
    else: stmt=stmt.where(Payment.status=='approved')
    result=dict(db.execute(stmt.group_by(Payment.cost_id)).all())
    if include_pending:
        from .tickets import payment_request_key
        used={key for key, in db.execute(select(Payment.idempotency_key))if key}
        proposed=select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
            ApprovalTicketItem.item_type=='record_payment',ApprovalTicketItem.status.in_(['pending','approved']),
            ApprovalTicket.status.not_in(['committed','reversed']))
        if exclude_ticket_item_id is not None:proposed=proposed.where(ApprovalTicketItem.id!=exclude_ticket_item_id)
        for item in db.scalars(proposed):
            key=payment_request_key(item);d=item.after_data or {}
            if key in used:continue
            cid,amount=d.get('cost_id'),d.get('amount_paise')
            if type(cid)is int and type(amount)is int and amount>0:
                result[cid]=int(result.get(cid,0))+amount;used.add(key)
    return result


def cost_net(db,c):
    a=db.scalar(select(func.coalesce(func.sum(FinancialAdjustment.delta_paise),0)).where(FinancialAdjustment.cost_id==c.id)) or 0
    return c.amount_paise+int(a)


def start_finance_lock(db, cost_id=None):
    if db.bind.dialect.name=='sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    if cost_id is not None:
        return db.scalar(select(Cost).where(Cost.id==cost_id).with_for_update())


def project_dict(p):
    return {"id":p.id,"name":p.name,"client":p.client,"stage":p.stage,"budget":money(p.budget_paise),"budget_paise":p.budget_paise,"location":p.location,"client_phone":p.client_phone}


def project_data(db): return [project_dict(p) for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)).all()]


def resolve_project(db, name):
    if name is None: return None
    if isinstance(name, int) or (isinstance(name,str) and name.isdigit()):
        project = db.get(Project, int(name))
        return project if project and project.deleted_at is None else None
    matches = [p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all() if p.name.casefold() == str(name).strip().casefold()]
    return matches[0] if matches else None


def cost_totals(db, project_id=None):
    from .operating_totals import portfolio_totals

    _, total = portfolio_totals(db, project_id)
    return total
