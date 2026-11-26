"""Read-only project expense and commitment totals in exact paise."""
from collections import defaultdict

from sqlalchemy import case, func, select

from .db import (
    AccountingPolicy, FinanceDirectBill, FinanceDirectBillLine, FinanceDirectBillPayment,
    FinancePurchaseOrder, FinanceReversal, FinanceSupplierBill,
    GLAccount, GLJournal, GLLine,
)

MIGRATED_EXPENSE_EVENT = 'LEGACY_EXPENSE_MIGRATED'
_NET_DEBIT = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)


def amounts(actual: int, commitments: int):
    known = actual + commitments
    return {'actual': round(actual / 100, 2), 'commitments': round(commitments / 100, 2),
            'known_costs': round(known / 100, 2), 'actual_paise': actual,
            'commitments_paise': commitments, 'known_costs_paise': known, 'basis': 'posted_books'}


def _posted_expenses(*columns):
    return (select(*columns).select_from(GLLine)
            .join(GLJournal, GLJournal.id == GLLine.journal_id)
            .join(GLAccount, GLAccount.id == GLLine.account_id)
            .where(GLJournal.status == 'posted', GLAccount.kind == 'expense'))


def company_expense_totals(db):
    """Net posted expense debits by company, including reversing credits."""
    query = _posted_expenses(GLJournal.entity_id, func.sum(_NET_DEBIT)).group_by(GLJournal.entity_id)
    return {entity_id: int(total) for entity_id, total in db.execute(query)}


def _posted_expense_totals(db, project_id):
    query = _posted_expenses(GLLine.project_id, func.sum(_NET_DEBIT)).group_by(GLLine.project_id)
    if project_id is not None:
        query = query.where(GLLine.project_id == project_id)
    return {pid: int(total) for pid, total in db.execute(query)}


def project_expense(db, project_id):
    return _posted_expense_totals(db, project_id).get(project_id, 0), 'posted_books'


def project_supplier_totals(db, project_id):
    """Return posted supplier outflow and AP, including bills wholly assigned to this project."""
    from .accounting_kernel import SUPPLIER_CASH_ADVANCE_EVENT, SUPPLIER_CASH_PAYMENT_EVENT
    from .expense_entry import EXPENSE_EVENT

    posted = (select(func.sum(GLLine.amount_paise)).select_from(GLLine)
              .join(GLJournal, GLJournal.id == GLLine.journal_id)
              .join(GLAccount, GLAccount.id == GLLine.account_id)
              .where(GLJournal.status == 'posted', GLLine.side == 'credit', GLAccount.kind.in_(('bank', 'cash')),
                     GLJournal.id.not_in(select(FinanceReversal.original_journal_id)), GLLine.project_id == project_id))
    paid = db.scalar(posted.where(
        GLJournal.source_event.in_((EXPENSE_EVENT, 'SUPPLIER_PAYMENT_POSTED', SUPPLIER_CASH_PAYMENT_EVENT,
                                   'SUPPLIER_ADVANCE_PAID', SUPPLIER_CASH_ADVANCE_EVENT))
        | ((GLJournal.source_event == 'TEXT_ENTRY_POSTED') & GLLine.supplier_id.is_not(None))
    )) or 0
    payable = db.scalar(select(func.sum(-_NET_DEBIT)).select_from(GLLine)
                        .join(GLJournal, GLJournal.id == GLLine.journal_id)
                        .join(AccountingPolicy, AccountingPolicy.payable_account_id == GLLine.account_id)
                        .where(GLJournal.status == 'posted', GLLine.project_id == project_id)) or 0

    lines = select(FinanceDirectBillLine.id).where(FinanceDirectBillLine.bill_id == FinanceDirectBill.id)
    direct = (select(FinanceDirectBill.id, FinanceDirectBill.amount_paise)
              .join(GLJournal, GLJournal.id == FinanceDirectBill.journal_id)
              .where(GLJournal.status == 'posted', GLJournal.id.not_in(select(FinanceReversal.original_journal_id)),
                     lines.where(FinanceDirectBillLine.project_id == project_id).exists(),
                     ~lines.where(FinanceDirectBillLine.project_id.is_distinct_from(project_id)).exists())
              .subquery())
    bill_total = db.scalar(select(func.sum(direct.c.amount_paise))) or 0
    paid_direct = db.scalar(select(func.sum(FinanceDirectBillPayment.amount_paise))
                           .join(direct, direct.c.id == FinanceDirectBillPayment.bill_id)
                           .join(GLJournal, GLJournal.id == FinanceDirectBillPayment.journal_id)
                           .where(GLJournal.status == 'posted', GLJournal.id.not_in(select(FinanceReversal.original_journal_id)))) or 0
    return int(paid + paid_direct), int(payable + bill_total - paid_direct)


def migration_totals(db, project_id=None):
    """Posted amounts for historical migration records, used by the archived preview."""
    reversed_row = select(FinanceReversal.id).where(FinanceReversal.original_journal_id == GLJournal.id).exists()
    migrated_amount = case((reversed_row, 0), else_=GLLine.amount_paise)
    query = _posted_expenses(GLLine.project_id, func.sum(migrated_amount)).where(
        GLJournal.source_event == MIGRATED_EXPENSE_EVENT, GLLine.side == 'debit',
    ).group_by(GLLine.project_id)
    if project_id is not None:
        query = query.where(GLLine.project_id == project_id)
    return {pid: int(total) for pid, total in db.execute(query)}


def _outstanding_orders(db, project_id):
    orders = select(FinancePurchaseOrder.id, FinancePurchaseOrder.project_id,
                    FinancePurchaseOrder.amount_paise).where(FinancePurchaseOrder.status == 'approved')
    if project_id is not None:
        orders = orders.where(FinancePurchaseOrder.project_id == project_id)
    selected = orders.subquery()
    billed = (select(FinanceSupplierBill.po_id, func.sum(FinanceSupplierBill.amount_paise).label('total'))
              .join(selected, selected.c.id == FinanceSupplierBill.po_id)
              .join(GLJournal, GLJournal.id == FinanceSupplierBill.journal_id)
              .where(GLJournal.status == 'posted',
                     GLJournal.id.not_in(select(FinanceReversal.original_journal_id)))
              .group_by(FinanceSupplierBill.po_id).subquery())
    totals = defaultdict(int)
    for pid, ordered, due in db.execute(
        select(selected.c.project_id, selected.c.amount_paise, billed.c.total)
        .outerjoin(billed, billed.c.po_id == selected.c.id)
    ):
        totals[pid] += max(0, ordered - int(due or 0))
    return totals


def portfolio_totals(db, project_id=None):
    """Net posted expenses and approved orders with an amount still to bill."""
    posted = _posted_expense_totals(db, project_id)
    orders = _outstanding_orders(db, project_id)
    projects = {pid: amounts(posted.get(pid, 0), orders.get(pid, 0)) for pid in posted.keys() | orders.keys()}
    return projects, amounts(sum(posted.values()), sum(orders.values()))
