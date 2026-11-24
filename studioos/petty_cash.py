"""A staff member's own petty cash and approved transfers into it."""
from sqlalchemy import case, func, select

from .access import visible_project_ids
from .db import AccountingEntity, ApprovalTicket, FinanceExpense, FinancePettyCashAccount, FinanceReversal, GLAccount, GLJournal, GLLine, User, add_audit
from .paid_through import CASH_CODE

TOPUP = 'finance_petty_cash_topup'
TOPUP_FIELDS = {'account_id', 'amount_paise', 'request_key'}
REVERSE_TOPUP = 'finance_reverse_petty_cash_topup'
REVERSE_FIELDS = {'journal_id', 'reason'}
TOPUP_EVENT = 'PETTY_CASH_TOPPED_UP'


def _balances(db, ids):
    signed = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)
    return dict(db.execute(select(GLLine.account_id, func.sum(signed)).join(GLJournal).where(
        GLJournal.status == 'posted', GLLine.account_id.in_(ids),
    ).group_by(GLLine.account_id)).all())


def my_accounts(db, user):
    accounts = db.execute(select(GLAccount, AccountingEntity.name).join(
        AccountingEntity, AccountingEntity.id == GLAccount.entity_id,
    ).join(FinancePettyCashAccount, FinancePettyCashAccount.account_id == GLAccount.id).where(
        FinancePettyCashAccount.user_id == user.id,
        FinancePettyCashAccount.entity_id == GLAccount.entity_id,
        GLAccount.kind == 'cash', GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True),
    ).order_by(AccountingEntity.name, GLAccount.id)).all()
    if not accounts:
        return []
    ids = [account.id for account, _ in accounts]
    balances = _balances(db, ids)
    expense = FinanceExpense
    query = select(expense.paid_through_id, func.count()).where(
        expense.paid_through_id.in_(ids), expense.submitted_by_id == user.id, expense.receipt_id.is_(None),
        ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == expense.journal_id).exists(),
    ).group_by(expense.paid_through_id)
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        query = query.where(expense.project_id.in_(allowed))
    missing = dict(db.execute(query).all())
    return [{'id': account.id, 'name': account.name, 'company_name': company,
             'balance_paise': int(balances.get(account.id, 0)), 'missing_receipt_count': missing.get(account.id, 0)}
            for account, company in accounts]


def requester(db, item):
    ticket = db.get(ApprovalTicket, item.ticket_id)
    return db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None


def validate(db, data, actor):
    from .accounting_kernel import _check_dated_posting, positive_minor, require_three_links
    from .chart_of_accounts import local_today

    if set(data) != TOPUP_FIELDS or actor is None or not actor.active or actor.role == 'viewer':
        raise ValueError('Choose your petty cash account and enter a top-up amount.')
    ident = data['account_id']
    account = db.get(GLAccount, ident) if type(ident) is int else None
    assignment = db.get(FinancePettyCashAccount, ident) if account else None
    if assignment is None or assignment.user_id != actor.id or assignment.entity_id != account.entity_id:
        raise ValueError('Choose your own petty cash account.')
    source = db.scalar(select(GLAccount).where(GLAccount.entity_id == account.entity_id, GLAccount.code == CASH_CODE))
    require_three_links(TOPUP, entity_id=account.entity_id, party=actor, source=source, account=account)
    if source.id == account.id:
        raise ValueError('Choose a petty cash account separate from Cash in Hand.')
    positive_minor(data['amount_paise'])
    key = data['request_key']
    if not isinstance(key, str) or not 12 <= len(key) <= 100 or key != key.strip():
        raise ValueError('Open a new top-up request and try again.')
    _check_dated_posting(db, account.entity_id, 'bank', local_today(), 'Transfer date')
    return source, account


def preview(db, data, actor):
    source, account = validate(db, data, actor)
    amount = data['amount_paise']
    warnings = []
    if _balances(db, [source.id]).get(source.id, 0) < amount:
        warnings.append('This transfer would take Cash in Hand below zero.')
    return {'event': TOPUP_EVENT, 'requires_ticket_approval': True,
            'journal_lines': [{'side': 'debit', 'account_name': account.name, 'amount_paise': amount},
                              {'side': 'credit', 'account_name': source.name, 'amount_paise': amount}],
            'warnings': warnings, 'note': 'Approve after the cash has been handed to the staff member.'}


def apply(db, item, approved_by):
    from .accounting_kernel import _post
    data = item.after_data
    actor = requester(db, item)
    _, account = validate(db, data, actor)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == account.entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    source, account = validate(db, data, actor)
    journal = _post(db, entity_id=account.entity_id, event_kind=TOPUP_EVENT,
                    event_key=f'petty-cash-topup:{item.id}', source_id=item.id, ticket_id=item.ticket_id,
                    debit_account=account.id, credit_account=source.id, amount=data['amount_paise'],
                    project_id=None, supplier_id=None, policy_version=1)
    add_audit(db, TOPUP, 'gl_journal', journal.id, f'Approved cash transfer from ticket #{item.ticket_id}.', actor=approved_by)
    return {'type': 'petty_cash_topup', 'id': journal.id, 'item_id': item.id, 'journal_id': journal.id}


def validate_reverse(db, data):
    from .accounting_kernel import _check_dated_posting, _is_reversed, required_text
    from .chart_of_accounts import local_today

    if set(data) != REVERSE_FIELDS or type(data.get('journal_id')) is not int:
        raise ValueError('Choose a posted petty cash top-up and give a reason.')
    journal = db.get(GLJournal, data['journal_id'])
    if journal is None or journal.source_event != TOPUP_EVENT or journal.status != 'posted' or _is_reversed(db, journal.id):
        raise ValueError('Choose a petty cash top-up that has not already been reversed.')
    required_text(data['reason'], 'Reason for reversing the top-up', 400)
    _check_dated_posting(db, journal.entity_id, 'bank', local_today(), 'Transfer date')
    return journal


def preview_reverse(db, data):
    journal = validate_reverse(db, data)
    lines = db.scalars(select(GLLine).where(GLLine.journal_id == journal.id).order_by(GLLine.id)).all()
    return {'event': 'JOURNAL_REVERSAL', 'requires_ticket_approval': True,
            'note': 'Review the cash return before approving.',
            'journal_lines': [{'side': 'credit' if line.side == 'debit' else 'debit',
                               'account_name': db.get(GLAccount, line.account_id).name,
                               'amount_paise': line.amount_paise} for line in lines]}


def apply_reverse(db, item, approved_by):
    from .accounting_kernel import _reverse_posted

    original = validate_reverse(db, item.after_data)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == original.entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    validate_reverse(db, item.after_data)
    journal = _reverse_posted(db, original.id, item.after_data['reason'], item.ticket_id)
    add_audit(db, REVERSE_TOPUP, 'gl_journal', journal.id,
              f'Approved reversal of petty cash journal #{original.id}.', actor=approved_by)
    return {'type': 'reversing_journal', 'id': journal.id, 'item_id': item.id, 'journal_id': journal.id}
