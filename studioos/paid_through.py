"""Paying accounts and their assignment to staff."""
from sqlalchemy import case, func, select

from .db import AccountingEntity, FinancePettyCashAccount, GLAccount, GLJournal, GLLine, RegisteredBank, User
from .security import FINANCE_READ


CASH_CODE = 'CASH'
CASH_NAME = 'Cash in Hand'


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


def list_accounts(db, entity_id, user):
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
