"""Approved expense defaults shared by Books and the site expense form."""
from sqlalchemy import func, select

from .db import AccountingEntity, FinanceExpenseCategory, GLAccount, add_audit

CATEGORY_TYPE = 'finance_expense_category'
CATEGORY_FIELDS = {'entity_id', 'name', 'expense_account_id'}


def _current(db, entity_id, key):
    return db.scalar(select(FinanceExpenseCategory).where(
        FinanceExpenseCategory.entity_id == entity_id, FinanceExpenseCategory.category_key == key,
    ).order_by(FinanceExpenseCategory.id.desc()).limit(1))


def _active_expense(account, entity_id):
    return account and account.entity_id == entity_id and account.kind == 'expense' and account.active and account.posting_allowed


def validate(db, data):
    if set(data) != CATEGORY_FIELDS or type(data.get('entity_id')) is not int or type(data.get('expense_account_id')) is not int:
        raise ValueError('Choose the company and expense account for this category.')
    raw = data['name']
    if not isinstance(raw, str) or not raw.isprintable() or not 2 <= len(' '.join(raw.split())) <= 120 or len(raw) > 120:
        raise ValueError('Give the expense category a name between 2 and 120 characters.')
    name = ' '.join(raw.split())
    account = db.get(GLAccount, data['expense_account_id'])
    if not _active_expense(account, data['entity_id']):
        raise ValueError('Choose an active expense account for this company.')
    previous = _current(db, data['entity_id'], name.casefold())
    if previous is not None and previous.expense_account_id == account.id:
        raise ValueError('That category already uses this expense account.')
    return name, account


def preview(db, data):
    name, account = validate(db, data)
    return {'event': CATEGORY_TYPE, 'journal_lines': [], 'gl_effect_paise': 0, 'requires_ticket_approval': True,
            'category': name, 'expense_account': account.name}


def apply(db, item, actor):
    data = item.after_data
    validate(db, data)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == data['entity_id']).with_for_update())
    name, account = validate(db, data)
    row = FinanceExpenseCategory(entity_id=account.entity_id, name=name, category_key=name.casefold(),
                                 expense_account_id=account.id, ticket_id=item.ticket_id)
    db.add(row)
    db.flush()
    add_audit(db, CATEGORY_TYPE, 'finance_expense_category', row.id,
              f'Approved default expense account from ticket #{item.ticket_id}.', actor=actor)
    return {'type': 'finance_expense_category', 'id': row.id, 'item_id': item.id}


def categories(db, entity_id, *, site=False):
    model = FinanceExpenseCategory
    latest = select(func.max(model.id)).where(model.entity_id == entity_id).group_by(model.category_key)
    rows = db.scalars(select(model).join(GLAccount, GLAccount.id == model.expense_account_id).where(
        model.id.in_(latest), GLAccount.entity_id == entity_id, GLAccount.kind == 'expense',
        GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True),
    ).order_by(model.name, model.id))
    return [{'id': row.id, 'name': row.name, **({} if site else {'expense_account_id': row.expense_account_id})}
            for row in rows]


def resolve(db, entity_id, category_id):
    row = db.get(FinanceExpenseCategory, category_id) if type(category_id) is int else None
    if row is None or row.entity_id != entity_id:
        raise ValueError('Choose an approved expense category for this company.')
    current = _current(db, entity_id, row.category_key)
    if current is None or current.id != row.id:
        raise ValueError('This expense category changed. Open the form again and choose the updated category.')
    if not _active_expense(db.get(GLAccount, row.expense_account_id), entity_id):
        raise ValueError('Ask accounts to update this expense category.')
    return row
