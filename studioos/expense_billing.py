"""v64: billable expenses, the way Zoho Books does them.

An expense can be marked billable to a client (with an optional mark-up). It then waits as "unbilled" until it is put on
that client's invoice, when it becomes "invoiced". It cannot be put on two live invoices. If the invoice is reversed,
the expense is unbilled again. Nothing here posts to the ledger: the invoice does that, as for any invoice."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import FinanceExpense, FinanceExpenseBilling, GLAccount, GLJournal, FinanceReversal, Party, Project, SalesInvoice

MAX_MARKUP_BPS = 10_000


def billed_amount(amount_paise: int, markup_bps: int | None) -> int:
    """The cost plus the mark-up, to the nearest paisa (a 10% mark-up on 1,000.00 is 1,100.00)."""
    return int(amount_paise) + (int(amount_paise) * int(markup_bps or 0) + 5_000) // 10_000


def cost_before_tax(e: FinanceExpense) -> int:
    """What the client is billed for: the cost without the input GST the company claims back."""
    return int(e.amount_paise) - int(e.tax_paise or 0)


def _reversed(journal_id):
    return select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal_id).exists()


def _live_billing(expense_id: int):
    """An invoice link whose invoice has not been reversed."""
    return (select(FinanceExpenseBilling.id)
            .join(SalesInvoice, SalesInvoice.id == FinanceExpenseBilling.invoice_id)
            .where(FinanceExpenseBilling.expense_id == expense_id,
                   ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == SalesInvoice.journal_id).exists()))


def status_of(db: Session, expense: FinanceExpense) -> str:
    """'' (not billable), 'unbilled' or 'invoiced'."""
    if not expense.billable:
        return ''
    return 'invoiced' if db.scalar(_live_billing(expense.id).limit(1)) is not None else 'unbilled'


def unbilled(db: Session, entity_id: int, client_id: int) -> list[dict]:
    rows = db.scalars(select(FinanceExpense).where(
        FinanceExpense.entity_id == entity_id, FinanceExpense.customer_id == client_id, FinanceExpense.billable.is_(True),
        ~_reversed(FinanceExpense.journal_id)).order_by(FinanceExpense.date, FinanceExpense.id)).all()
    out = []
    for e in rows:
        if status_of(db, e) != 'unbilled':
            continue
        account = db.get(GLAccount, e.expense_account_id)
        project = db.get(Project, e.project_id) if e.project_id else None
        vendor = db.get(Party, e.vendor_id) if e.vendor_id else None
        what = (e.note or '').strip() or (account.name if account else 'Expense')
        out.append({'id': e.id, 'date': e.date, 'description': what, 'expense_account': account.name if account else '',
                    'vendor': vendor.name if vendor else (e.no_vendor_name or ''), 'project_id': e.project_id,
                    'project': project.name if project else '', 'reference_number': e.reference_number or '',
                    'amount_paise': cost_before_tax(e), 'markup_bps': e.markup_bps or 0,
                    'billable_paise': billed_amount(cost_before_tax(e), e.markup_bps)})
    return out


def check_for_invoice(db: Session, entity_id: int, client_id: int, expense_ids) -> list[FinanceExpense]:
    """The expenses an invoice may bill: this client's, billable, posted, and not already on a live invoice."""
    if expense_ids in (None, [], ()):
        return []
    if not isinstance(expense_ids, list) or len(expense_ids) > 100 or any(type(i) is not int for i in expense_ids) \
            or len(set(expense_ids)) != len(expense_ids):
        raise ValueError('Choose the billable expenses to put on this invoice.')
    found = []
    for i in expense_ids:
        e = db.get(FinanceExpense, i)
        if e is None or e.entity_id != entity_id or e.customer_id != client_id or not e.billable:
            raise ValueError('A billable expense chosen for this invoice is not billable to this client.')
        if db.scalar(select(_reversed(e.journal_id))):
            raise ValueError('A chosen expense has been reversed and cannot be billed.')
        if status_of(db, e) != 'unbilled':
            raise ValueError('A chosen expense is already on an invoice.')
        found.append(e)
    return found


def link(db: Session, invoice_id: int, expenses: list[FinanceExpense]) -> None:
    for e in expenses:
        db.add(FinanceExpenseBilling(expense_id=e.id, invoice_id=invoice_id, billed_paise=billed_amount(cost_before_tax(e), e.markup_bps)))
