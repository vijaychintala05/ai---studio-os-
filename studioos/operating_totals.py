"""Read-only project budget totals from the selected books, in exact paise.
Earlier tracker rows remain available separately; never add two purchase paths.
"""
from sqlalchemy import case,func,select
from collections import defaultdict
from .db import GLAccount,GLJournal,GLLine,FinancePurchaseOrder,FinanceSupplierBill,FinanceReversal,Cost,FinancialAdjustment


def amounts(actual:int,commitments:int,basis:str):
    actual=int(actual);commitments=int(commitments);known=actual+commitments
    return {'actual':round(actual/100,2),'commitments':round(commitments/100,2),'known_costs':round(known/100,2),
        'actual_paise':actual,'commitments_paise':commitments,'known_costs_paise':known,'basis':basis}


def books_totals(db,project_id=None,legacy=None):
    net=case((GLLine.side=='debit',GLLine.amount_paise),else_=-GLLine.amount_paise)
    statement=select(func.coalesce(func.sum(net),0)).join(GLJournal,GLJournal.id==GLLine.journal_id).join(GLAccount,GLAccount.id==GLLine.account_id).where(GLJournal.status=='posted',GLAccount.kind=='expense')
    if project_id is not None:statement=statement.where(GLLine.project_id==project_id)
    actual=int(db.scalar(statement)or 0)
    orders=select(FinancePurchaseOrder).where(FinancePurchaseOrder.status=='approved')
    if project_id is not None:orders=orders.where(FinancePurchaseOrder.project_id==project_id)
    orders=db.scalars(orders).all();commitments=0
    if orders:
        reversed_journals=select(FinanceReversal.original_journal_id)
        billed=dict(db.execute(select(FinanceSupplierBill.po_id,func.sum(FinanceSupplierBill.amount_paise))
            .join(GLJournal,GLJournal.id==FinanceSupplierBill.journal_id)
            .where(FinanceSupplierBill.po_id.in_([o.id for o in orders]),GLJournal.status=='posted',GLJournal.id.not_in(reversed_journals))
            .group_by(FinanceSupplierBill.po_id)).all())
        commitments=sum(max(0,o.amount_paise-int(billed.get(o.id,0)))for o in orders)
    result=amounts(actual,commitments,'posted_books')
    if legacy is not None:result['legacy_tracker']=legacy
    return result


def portfolio_totals(db):
    """One complete financial read for all project budgets and the firm total.

    Keep unassigned expenses in the firm total, clamp each order's remaining
    commitment separately, and retain (never add) the earlier tracker values.
    This is a fresh request read, with no cross-request or approval cache.
    """
    from .purchase_path import books_active
    legacy=defaultdict(lambda:[0,0]);legacy_total=[0,0]
    adjustments=dict(db.execute(select(FinancialAdjustment.cost_id,func.sum(FinancialAdjustment.delta_paise))
                               .group_by(FinancialAdjustment.cost_id)).all())
    for row in db.scalars(select(Cost).where(Cost.deleted_at.is_(None))):
        if row.status!='approved'or row.kind not in ('expense','commitment'):continue
        value=row.amount_paise+int(adjustments.get(row.id,0)or 0);slot=0 if row.kind=='expense'else 1
        legacy[row.project_id][slot]+=value;legacy_total[slot]+=value
    earlier={pid:amounts(*values,'earlier_tracker')for pid,values in legacy.items()}
    earlier_total=amounts(*legacy_total,'earlier_tracker')
    if not books_active(db):return earlier,earlier_total
    actual=defaultdict(int);commitments=defaultdict(int)
    net=case((GLLine.side=='debit',GLLine.amount_paise),else_=-GLLine.amount_paise)
    grouped=db.execute(select(GLLine.project_id,func.coalesce(func.sum(net),0))
        .join(GLJournal,GLJournal.id==GLLine.journal_id).join(GLAccount,GLAccount.id==GLLine.account_id)
        .where(GLJournal.status=='posted',GLAccount.kind=='expense').group_by(GLLine.project_id))
    for pid,value in grouped:actual[pid]=int(value)
    orders=db.scalars(select(FinancePurchaseOrder).where(FinancePurchaseOrder.status=='approved')).all()
    if orders:
        billed=dict(db.execute(select(FinanceSupplierBill.po_id,func.sum(FinanceSupplierBill.amount_paise))
            .join(GLJournal,GLJournal.id==FinanceSupplierBill.journal_id)
            .where(FinanceSupplierBill.po_id.in_([o.id for o in orders]),GLJournal.status=='posted',
                   GLJournal.id.not_in(select(FinanceReversal.original_journal_id)))
            .group_by(FinanceSupplierBill.po_id)).all())
        for order in orders:commitments[order.project_id]+=max(0,order.amount_paise-int(billed.get(order.id,0)))
    out={}
    for pid in actual.keys()|commitments.keys()|earlier.keys():
        out[pid]=amounts(actual[pid],commitments[pid],'posted_books')
        out[pid]['legacy_tracker']=earlier.get(pid,amounts(0,0,'earlier_tracker'))
    total=amounts(sum(actual.values()),sum(commitments.values()),'posted_books');total['legacy_tracker']=earlier_total
    return out,total
