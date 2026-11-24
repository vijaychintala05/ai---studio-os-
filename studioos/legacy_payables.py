"""Supplier balances carried into Books by approved historical migrations."""
from sqlalchemy import select

from .db import Cost, FinanceReversal, GLAccount, GLJournal, GLLine
from .operating_totals import MIGRATED_EXPENSE_EVENT


def open_legacy_payables(db, *, entity_id=None, supplier_id=None, allowed_projects=None):
    reversed_journal = select(FinanceReversal.id).where(FinanceReversal.original_journal_id == GLJournal.id).exists()
    query = (select(GLJournal.id, GLJournal.entity_id, GLJournal.posted_at, Cost.id, Cost.title,
                    GLLine.project_id, GLLine.supplier_id, GLLine.amount_paise)
             .join(GLLine, GLLine.journal_id == GLJournal.id)
             .join(GLAccount, GLAccount.id == GLLine.account_id)
             .join(Cost, Cost.id == GLJournal.source_id)
             .where(GLJournal.source_event == MIGRATED_EXPENSE_EVENT, GLJournal.status == 'posted',
                    GLAccount.kind == 'payable', GLLine.side == 'credit', ~reversed_journal)
             .order_by(GLJournal.id))
    if entity_id is not None:
        query = query.where(GLJournal.entity_id == entity_id)
    if supplier_id is not None:
        query = query.where(GLLine.supplier_id == supplier_id)
    if allowed_projects is not None:
        query = query.where(GLLine.project_id.in_(allowed_projects))
    return [{'journal_id': journal, 'entity_id': entity, 'posted_date': posted.date().isoformat(),
             'cost_id': cost, 'title': title, 'project_id': project, 'supplier_id': supplier,
             'outstanding_paise': amount}
            for journal, entity, posted, cost, title, project, supplier, amount in db.execute(query)]
