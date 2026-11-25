"""Book an approved staff claim and settle it through an approved paying account."""
from sqlalchemy import case, func, select

from .access import can_access_project
from .db import (
    AccountingEntity, FinanceExpense, FinanceReversal, FinanceStaffAccount, FinanceStaffReimbursement,
    GLAccount, GLJournal, GLLine, User, add_audit,
)
from .paid_through import expense_source
from .security import FINANCE_WRITE

CLAIM_EVENT = 'STAFF_EXPENSE_CLAIMED'
PAYMENT_EVENT = 'STAFF_REIMBURSEMENT_POSTED'
PAYMENT_FIELDS = {'claim_id', 'paid_through_id', 'amount_paise', 'payment_date', 'request_key'}


def claim_account(db, entity_id, staff, ticket_id):
    from .chart_of_accounts import _code_for

    existing = db.scalar(select(FinanceStaffAccount).where(
        FinanceStaffAccount.entity_id == entity_id, FinanceStaffAccount.user_id == staff.id,
    ))
    if existing is not None:
        return db.get(GLAccount, existing.account_id)
    name = f'Owed to {staff.display_name or staff.username}'
    account = GLAccount(entity_id=entity_id, name=name, code=_code_for(db, entity_id, f'STAFF_OWED_{staff.id}'),
                        kind='liability')
    db.add(account)
    db.flush()
    db.add(FinanceStaffAccount(account_id=account.id, entity_id=entity_id, user_id=staff.id, ticket_id=ticket_id))
    db.flush()
    return account


def active_payment(claim_id):
    return select(FinanceStaffReimbursement.id).where(
        FinanceStaffReimbursement.claim_id == claim_id,
        ~select(FinanceReversal.id).where(
            FinanceReversal.original_journal_id == FinanceStaffReimbursement.journal_id,
        ).exists(),
    )


def open_claims(db, *, entity_id=None, user_id=None):
    query = (select(FinanceExpense, User.display_name, User.username)
             .join(FinanceStaffAccount, FinanceStaffAccount.account_id == FinanceExpense.paid_through_id)
             .join(User, User.id == FinanceStaffAccount.user_id)
             .where(FinanceStaffAccount.entity_id == FinanceExpense.entity_id,
                    FinanceStaffAccount.user_id == FinanceExpense.submitted_by_id,
                    ~select(FinanceReversal.id).where(
                        FinanceReversal.original_journal_id == FinanceExpense.journal_id,
                    ).exists(), ~active_payment(FinanceExpense.id).exists())
             .order_by(FinanceExpense.date, FinanceExpense.id))
    if entity_id is not None:
        query = query.where(FinanceExpense.entity_id == entity_id)
    if user_id is not None:
        query = query.where(FinanceStaffAccount.user_id == user_id)
    return [
        {'id': claim.id, 'date': claim.date, 'amount_paise': claim.amount_paise,
         'note': claim.note, **({'staff': display or username} if user_id is None else {})}
        for claim, display, username in db.execute(query)
    ]


def amount_owed(db, user_id):
    net = case((GLLine.side == 'credit', GLLine.amount_paise), else_=-GLLine.amount_paise)
    value = db.scalar(select(func.sum(net)).join(FinanceStaffAccount, FinanceStaffAccount.account_id == GLLine.account_id)
                      .join(GLJournal, GLJournal.id == GLLine.journal_id)
                      .where(FinanceStaffAccount.user_id == user_id, GLJournal.status == 'posted',
                             GLJournal.entity_id == FinanceStaffAccount.entity_id))
    return int(value or 0)


def validate_payment(db, data, actor):
    from .accounting_kernel import _calendar_date, _check_dated_posting, _check_open, _is_reversed, require_three_links
    from .chart_of_accounts import local_today

    if actor is None or actor.role not in FINANCE_WRITE or not actor.active:
        raise ValueError('Only accounts or a manager can propose a staff payment.')
    if set(data) != PAYMENT_FIELDS or type(data['claim_id']) is not int:
        raise ValueError('Choose a staff claim, paying account, amount and payment date.')
    claim = db.get(FinanceExpense, data['claim_id'])
    owed = db.get(FinanceStaffAccount, claim.paid_through_id) if claim else None
    if (owed is None or owed.entity_id != claim.entity_id or owed.user_id != claim.submitted_by_id
            or _is_reversed(db, claim.journal_id) or not can_access_project(db, actor, claim.project_id)):
        raise ValueError('Choose an approved staff claim.')
    if db.scalar(active_payment(claim.id)) is not None:
        raise ValueError('This claim has already been reimbursed.')
    liability = db.get(GLAccount, owed.account_id)
    source = expense_source(db, data['paid_through_id'], actor)
    require_three_links('finance_reimburse_staff', entity_id=claim.entity_id, party=db.get(User, owed.user_id),
                        source=source, account=liability)
    if type(data['amount_paise']) is not int or data['amount_paise'] != claim.amount_paise:
        raise ValueError('Enter the full amount owed on this claim.')
    day = _calendar_date(data['payment_date'], 'Payment date')
    if data['payment_date'] < claim.date:
        raise ValueError('The reimbursement date must be on or after the expense date.')
    if day > local_today():
        raise ValueError('Payment date cannot be in the future.')
    if source.kind == 'bank':
        _check_dated_posting(db, claim.entity_id, 'bank', day, 'Payment date')
    else:
        _check_open(db, claim.entity_id, day.isoformat())
    _check_open(db, claim.entity_id)
    key = data['request_key']
    if not isinstance(key, str) or not 12 <= len(key) <= 100 or key != key.strip():
        raise ValueError('This payment needs a request reference.')
    if db.scalar(select(FinanceStaffReimbursement.id).where(
        FinanceStaffReimbursement.submitted_by_id == actor.id, FinanceStaffReimbursement.request_key == key,
    )) is not None:
        raise ValueError('This payment request has already been posted.')
    return claim, source


def pay(db, item, approver):
    from .accounting_kernel import _post
    from .expense_entry import submitter

    data = item.after_data
    actor = submitter(db, item)
    claim, _ = validate_payment(db, data, actor)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == claim.entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    claim, source = validate_payment(db, data, actor)
    journal = _post(db, entity_id=claim.entity_id, event_kind=PAYMENT_EVENT, event_key=f'staff-payment:{item.id}',
                    source_id=item.id, debit_account=claim.paid_through_id, credit_account=source.id,
                    amount=claim.amount_paise, project_id=claim.project_id, supplier_id=None,
                    ticket_id=item.ticket_id, policy_version=1)
    db.add(FinanceStaffReimbursement(id=item.id, claim_id=claim.id, journal_id=journal.id,
                                    paid_through_id=source.id, submitted_by_id=actor.id,
                                    payment_date=data['payment_date'], request_key=data['request_key']))
    db.flush()
    add_audit(db, 'finance_staff_reimbursement', 'finance_staff_reimbursement', item.id,
              f'Approved ticket #{item.ticket_id} reimbursed expense #{claim.id}.', actor=approver)
    return {'type': 'staff_reimbursement', 'id': item.id, 'item_id': item.id, 'journal_id': journal.id}


def payment_to_reverse(db, data):
    from .accounting_kernel import _check_dated_posting, _is_reversed, _reconciled, required_text
    from .chart_of_accounts import local_today

    if set(data) != {'payment_id', 'reason'} or type(data['payment_id']) is not int:
        raise ValueError('Choose a posted staff payment and enter a reason.')
    required_text(data['reason'], 'Reversal reason', 400)
    payment = db.get(FinanceStaffReimbursement, data['payment_id'])
    if payment is None or _is_reversed(db, payment.journal_id):
        raise ValueError('Choose an unreversed staff payment.')
    if _reconciled(db, payment.journal_id):
        raise ValueError('Ask accounts to review the bank match before reversing the payment.')
    claim = db.get(FinanceExpense, payment.claim_id)
    source = db.get(GLAccount, payment.paid_through_id)
    today = local_today()
    if source.kind == 'bank':
        _check_dated_posting(db, claim.entity_id, 'bank', today, 'Reversal date')
    return payment, claim


def reverse_payment(db, item, actor):
    from .accounting_kernel import _reverse_posted

    _, claim = payment_to_reverse(db, item.after_data)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == claim.entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    payment, _ = payment_to_reverse(db, item.after_data)
    journal = _reverse_posted(db, payment.journal_id, item.after_data['reason'].strip(), item.ticket_id)
    add_audit(db, 'finance_staff_payment_reversed', 'finance_staff_reimbursement', payment.id,
              f'Approved ticket #{item.ticket_id} reversed reimbursement #{payment.id}.', actor=actor)
    return {'type': 'reversing_journal', 'id': journal.id, 'item_id': item.id, 'journal_id': journal.id}
