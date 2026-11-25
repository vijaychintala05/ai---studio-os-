"""Read-only project expense and commitment totals in exact paise."""
from collections import defaultdict

from sqlalchemy import case, func, select

from .db import (
    Cost, FinancePurchaseOrder, FinanceReversal, FinanceSupplierBill, FinancialAdjustment,
    GLAccount, GLJournal, GLLine,
)

MIGRATED_EXPENSE_EVENT = 'LEGACY_EXPENSE_MIGRATED'
_NET_EXPENSE = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)


def amounts(actual: int, commitments: int, basis: str):
    known = actual + commitments
    return {'actual': round(actual / 100, 2), 'commitments': round(commitments / 100, 2),
            'known_costs': round(known / 100, 2), 'actual_paise': actual,
            'commitments_paise': commitments, 'known_costs_paise': known, 'basis': basis}


def _posted_expenses(*columns):
    return (select(*columns).select_from(GLLine)
            .join(GLJournal, GLJournal.id == GLLine.journal_id)
            .join(GLAccount, GLAccount.id == GLLine.account_id)
            .where(GLJournal.status == 'posted', GLAccount.kind == 'expense'))


def company_expense_totals(db):
    """Net posted expense debits by company, including reversing credits."""
    query = _posted_expenses(GLJournal.entity_id, func.sum(_NET_EXPENSE)).group_by(GLJournal.entity_id)
    return {entity_id: int(total) for entity_id, total in db.execute(query)}


def _posted_expense_totals(db, project_id):
    reversed_row = select(FinanceReversal.id).where(FinanceReversal.original_journal_id == GLJournal.id).exists()
    # Preserve zero for projects with a reversed migration, so legacy totals reappear.
    migrated_amount = case((
        (GLJournal.source_event == MIGRATED_EXPENSE_EVENT) & (GLLine.side == 'debit'),
        case((reversed_row, 0), else_=GLLine.amount_paise),
    ))
    query = _posted_expenses(GLLine.project_id, func.sum(_NET_EXPENSE), func.sum(migrated_amount)).group_by(GLLine.project_id)
    if project_id is not None:
        query = query.where(GLLine.project_id == project_id)
    posted, migrated = {}, {}
    for pid, net_total, migrated_total in db.execute(query):
        posted[pid] = int(net_total)
        if migrated_total is not None:
            migrated[pid] = int(migrated_total)
    return posted, migrated


def _legacy_totals(db, project_id):
    costs = select(Cost.id, Cost.project_id, Cost.kind, Cost.amount_paise).where(
        Cost.status == 'approved', Cost.deleted_at.is_(None), Cost.kind.in_(('expense', 'commitment')),
    )
    if project_id is not None:
        costs = costs.where(Cost.project_id == project_id)
    selected = costs.subquery()
    adjustments = (select(FinancialAdjustment.cost_id, func.sum(FinancialAdjustment.delta_paise).label('delta'))
                   .join(selected, selected.c.id == FinancialAdjustment.cost_id)
                   .group_by(FinancialAdjustment.cost_id).subquery())
    query = (select(selected.c.project_id, selected.c.kind,
                    func.sum(selected.c.amount_paise + func.coalesce(adjustments.c.delta, 0)))
             .outerjoin(adjustments, adjustments.c.cost_id == selected.c.id)
             .group_by(selected.c.project_id, selected.c.kind))
    totals = defaultdict(lambda: [0, 0])
    for pid, kind, total in db.execute(query):
        totals[pid][0 if kind == 'expense' else 1] = int(total)
    return totals


def project_expense(db, project_id):
    posted, migrated = _posted_expense_totals(db, project_id)
    if project_id in posted and project_id not in migrated:
        return posted[project_id], 'posted_books'
    legacy = _legacy_totals(db, project_id)[project_id][0]
    return _project_expense_value(project_id, posted, legacy, migrated)


def migration_totals(db, project_id=None):
    """Amounts copied to Books, including zero once a project's batch is reversed."""
    return _posted_expense_totals(db, project_id)[1]


def _project_expense_value(project_id, posted, legacy, migrated):
    if project_id in migrated:
        remaining = legacy - migrated[project_id]
        books = posted.get(project_id, 0)
        basis = 'mixed' if remaining and books else 'earlier_tracker' if remaining else 'posted_books'
        return books + remaining, basis
    if project_id in posted:
        return posted[project_id], 'posted_books'
    return legacy, 'earlier_tracker'


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
    """Choose the expense source for each project, including projects still on the tracker."""
    legacy = _legacy_totals(db, project_id)
    posted, migrated = _posted_expense_totals(db, project_id)
    orders = _outstanding_orders(db, project_id)
    projects = {}
    for pid in legacy.keys() | posted.keys() | orders.keys():
        previous_expenses, previous_orders = legacy.get(pid, (0, 0))
        from_books = pid in posted
        actual, basis = _project_expense_value(pid, posted, previous_expenses, migrated)
        commitments = orders.get(pid, 0) if from_books or pid in orders else previous_orders
        if pid in migrated and pid not in orders:
            commitments = previous_orders
        result = amounts(actual, commitments, basis)
        if from_books or pid in orders:
            result['legacy_tracker'] = amounts(previous_expenses, previous_orders, 'earlier_tracker')
        projects[pid] = result

    has_books = bool(posted or orders)
    has_tracker = any(row['actual_paise'] for row in projects.values() if row['basis'] in ('earlier_tracker', 'mixed'))
    basis = ('mixed' if has_tracker else 'posted_books') if has_books else 'earlier_tracker'
    total = amounts(sum(row['actual_paise'] for row in projects.values()),
                    sum(row['commitments_paise'] for row in projects.values()), basis)
    if has_books:
        total['legacy_tracker'] = amounts(sum(row[0] for row in legacy.values()),
                                          sum(row[1] for row in legacy.values()), 'earlier_tracker')
    return projects, total
