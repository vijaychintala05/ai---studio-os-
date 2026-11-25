"""Paying accounts and their assignment to staff."""
from sqlalchemy import case, func, or_, select

from .db import (
    AccountingEntity, FinanceExpense, FinancePettyCashAccount, FinanceReversal,
    FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierCashAdvance, FinanceSupplierCashPayment,
    GLAccount, GLJournal, GLLine, RegisteredBank, User,
)
from .security import FINANCE_READ


CASH_CODE = 'CASH'
CASH_NAME = 'Cash in Hand'
CASH_REVIEW_LIMIT = 1_000_000


def cash_warnings(db, account, vendor_id, day, amount, *, project_id=None):
    signed = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)
    balance = db.scalar(select(func.sum(signed)).join(GLJournal).where(
        GLJournal.entity_id == account.entity_id, GLJournal.status == 'posted', GLLine.account_id == account.id,
    )) or 0
    warnings = ['This payment would take the cash account below zero.'] if balance < amount else []
    total = amount
    if type(vendor_id) is int and isinstance(day, str):
        from .legacy_payables import posted_legacy_payments

        def unreversed(model):
            return ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == model.journal_id).exists()

        payment, advance, expense = FinanceSupplierCashPayment, FinanceSupplierCashAdvance, FinanceExpense
        bill = FinanceSupplierBill
        bill_cash = select(func.sum(payment.amount_paise)).join(bill).where(
            bill.entity_id == account.entity_id, bill.supplier_id == vendor_id,
            payment.payment_date == day, payment.journal_id.is_not(None), unreversed(payment),
        )
        advance_cash = select(func.sum(advance.amount_paise)).where(
            advance.entity_id == account.entity_id, advance.supplier_id == vendor_id,
            advance.payment_date == day, advance.journal_id.is_not(None), unreversed(advance),
        )
        expense_cash = select(func.sum(expense.amount_paise)).join(GLAccount, GLAccount.id == expense.paid_through_id).where(
            expense.entity_id == account.entity_id, expense.vendor_id == vendor_id,
            expense.date == day, GLAccount.kind == 'cash', unreversed(expense),
        )
        allowed_projects = None
        if project_id is not None:
            bill_cash = bill_cash.join(FinancePurchaseOrder).where(FinancePurchaseOrder.project_id == project_id)
            advance_cash = advance_cash.where(advance.project_id == project_id)
            expense_cash = expense_cash.where(expense.project_id == project_id)
            allowed_projects = {project_id}
        total += sum(db.scalar(query) or 0 for query in (bill_cash, advance_cash, expense_cash))
        total += sum(row['amount_paise'] for row in posted_legacy_payments(
            db, entity_id=account.entity_id, supplier_id=vendor_id, allowed_projects=allowed_projects,
            cash_date=day, limit=None,
        ))
    if total > CASH_REVIEW_LIMIT:
        warnings.append('Cash paid exceeds ₹10,000 for this payment or vendor today. Ask accounts to check it.')
    return warnings

def expense_source(db, account_id, actor):
    account = db.get(GLAccount, account_id) if type(account_id) is int else None
    if account is None or not account.active or not account.posting_allowed:
        raise ValueError('Choose an active account under Paid through.')
    assignment = db.get(FinancePettyCashAccount, account.id)
    if assignment is not None and account.kind == 'cash' and assignment.entity_id == account.entity_id:
        if assignment.user_id != actor.id:
            raise ValueError('Choose your own petty cash account.')
        return account
    if actor.role in FINANCE_READ:
        if account.kind == 'cash' and account.code == CASH_CODE:
            return account
        if account.kind == 'bank' and db.scalar(select(RegisteredBank.id).where(
            RegisteredBank.gl_account_id == account.id, RegisteredBank.entity_id == account.entity_id,
        )) is not None:
            return account
    raise ValueError('Choose an account you can pay through.')


def petty_cash_custodian(db, data):
    if set(data) != {'entity_id', 'user_id'} or any(type(value) is not int for value in data.values()):
        raise ValueError('Choose a company and a staff member for this petty cash account.')
    if db.get(AccountingEntity, data['entity_id']) is None:
        raise ValueError('Choose an existing company.')
    user = db.get(User, data['user_id'])
    if user is None or not user.active or user.role == 'viewer':
        raise ValueError('Choose an active staff member.')
    if db.scalar(select(FinancePettyCashAccount.account_id).where(
        FinancePettyCashAccount.entity_id == data['entity_id'],
        FinancePettyCashAccount.user_id == user.id,
    )) is not None:
        raise ValueError('This staff member already has a petty cash account for this company.')
    return user


def list_accounts(db, entity_id, user, *, for_expense=False):
    query = (
        select(GLAccount, RegisteredBank, FinancePettyCashAccount)
        .outerjoin(RegisteredBank, (RegisteredBank.gl_account_id == GLAccount.id)
                   & (RegisteredBank.entity_id == GLAccount.entity_id))
        .outerjoin(FinancePettyCashAccount, (FinancePettyCashAccount.account_id == GLAccount.id)
                   & (FinancePettyCashAccount.entity_id == GLAccount.entity_id))
        .where(GLAccount.entity_id == entity_id, GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True))
        .order_by(GLAccount.name, GLAccount.id)
    )
    cash = (GLAccount.kind == 'cash') & (GLAccount.code == CASH_CODE)
    petty_cash = (GLAccount.kind == 'cash') & FinancePettyCashAccount.account_id.is_not(None)
    if user.role in FINANCE_READ:
        query = query.where(cash | petty_cash | ((GLAccount.kind == 'bank') & RegisteredBank.id.is_not(None)))
        if for_expense:
            query = query.where(or_(FinancePettyCashAccount.user_id.is_(None), FinancePettyCashAccount.user_id == user.id))
    else:
        query = query.where(petty_cash, FinancePettyCashAccount.user_id == user.id)
    sources = db.execute(query).all()
    if not sources:
        return []
    net = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)
    balances = dict(db.execute(
        select(GLLine.account_id, func.sum(net)).join(GLJournal, GLJournal.id == GLLine.journal_id)
        .where(GLJournal.status == 'posted', GLJournal.entity_id == entity_id,
               GLLine.account_id.in_([account.id for account, _, _ in sources]))
        .group_by(GLLine.account_id)
    ).all())
    return [{
        'id': account.id, 'name': account.name,
        'kind': 'petty_cash' if petty else account.kind,
        'bank_id': bank.id if bank else None,
        'balance_paise': int(balances.get(account.id, 0)),
    } for account, bank, petty in sources]
