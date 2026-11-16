"""Read-only project budget totals from the selected books, in exact paise.
Earlier tracker rows remain available separately; never add two purchase paths.
"""
from sqlalchemy import case,func,select
from .db import GLAccount,GLJournal,GLLine,FinancePurchaseOrder,FinanceSupplierBill,FinanceReversal


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
