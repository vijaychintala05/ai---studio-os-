"""Supplier balances carried into Books by approved historical migrations."""
from hashlib import sha256

from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from .db import (AccountingEntity, ApprovalTicketItem, Cost, FinanceBankReconciliation, FinanceReversal,
                 GLAccount, GLJournal, GLLine, Party, add_audit)
from .operating_totals import MIGRATED_EXPENSE_EVENT

PAY = 'finance_pay_legacy_balance'
REVERSE_PAYMENT = 'finance_reverse_legacy_balance_payment'
PAYMENT_EVENT = 'LEGACY_EXPENSE_BALANCE_PAID'
PAYMENT_FIELDS = {
    PAY: {'opening_journal_id', 'paid_through_id', 'amount_paise', 'payment_date', 'payment_reference'},
    REVERSE_PAYMENT: {'journal_id', 'reason'},
}


def _unreversed(journal):
    return ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == journal.id).exists()


def open_legacy_payables(db, *, entity_id=None, supplier_id=None, allowed_projects=None, opening_journal_id=None):
    payment = aliased(GLJournal)
    debit = aliased(GLLine)
    paid = (select(func.coalesce(func.sum(debit.amount_paise), 0))
            .join(payment, payment.id == debit.journal_id)
            .where(payment.source_event == PAYMENT_EVENT, payment.status == 'posted',
                   payment.source_id == GLJournal.id, payment.entity_id == GLJournal.entity_id,
                   debit.account_id == GLLine.account_id, debit.side == 'debit', _unreversed(payment))
            .correlate(GLJournal, GLLine).scalar_subquery())
    outstanding = GLLine.amount_paise - paid
    query = (select(GLJournal.id, GLJournal.entity_id, GLJournal.posted_at, Cost.id, Cost.title,
                    GLLine.project_id, GLLine.supplier_id, GLLine.account_id, outstanding)
             .join(GLLine, GLLine.journal_id == GLJournal.id)
             .join(GLAccount, GLAccount.id == GLLine.account_id)
             .join(Cost, Cost.id == GLJournal.source_id)
             .where(GLJournal.source_event == MIGRATED_EXPENSE_EVENT, GLJournal.status == 'posted',
                    GLAccount.kind == 'payable', GLLine.side == 'credit', _unreversed(GLJournal))
             .order_by(GLJournal.id))
    if entity_id is not None:
        query = query.where(GLJournal.entity_id == entity_id)
    if supplier_id is not None:
        query = query.where(GLLine.supplier_id == supplier_id)
    if allowed_projects is not None:
        query = query.where(GLLine.project_id.in_(allowed_projects))
    if opening_journal_id is not None:
        query = query.where(GLJournal.id == opening_journal_id)
    return [{'journal_id': journal, 'entity_id': entity, 'posted_date': posted.date().isoformat(),
             'cost_id': cost, 'title': title, 'project_id': project, 'supplier_id': supplier,
             'account_id': account, 'outstanding_paise': int(amount)}
            for journal, entity, posted, cost, title, project, supplier, account, amount in db.execute(query)
            if amount != 0]


def has_payments(db, opening_journal_ids):
    return bool(db.scalar(select(GLJournal.id).where(
        GLJournal.source_event == PAYMENT_EVENT, GLJournal.status == 'posted',
        GLJournal.source_id.in_(opening_journal_ids), _unreversed(GLJournal),
    ).limit(1)))


def posted_legacy_payments(db, *, entity_id=None, supplier_id=None, allowed_projects=None,
                           cash_date=None, limit=20):
    opening = aliased(GLJournal)
    matched = select(FinanceBankReconciliation.id).where(FinanceBankReconciliation.journal_id == GLJournal.id).exists()
    item = ApprovalTicketItem
    query = (select(GLJournal.id, GLJournal.event_key, opening.id, Cost.title, GLLine.amount_paise,
                    GLLine.account_id, GLAccount.kind, item.after_data, matched)
             .join(opening, opening.id == GLJournal.source_id)
             .join(Cost, Cost.id == opening.source_id)
             .join(GLLine, GLLine.journal_id == GLJournal.id)
             .join(GLAccount, GLAccount.id == GLLine.account_id)
             .join(item, and_(item.ticket_id == GLJournal.ticket_id, item.item_type == PAY, item.status == 'approved',
                              item.after_data['opening_journal_id'].as_integer() == opening.id,
                              item.after_data['paid_through_id'].as_integer() == GLLine.account_id))
             .where(GLJournal.source_event == PAYMENT_EVENT, GLJournal.status == 'posted',
                    GLLine.side == 'credit', _unreversed(GLJournal))
             .order_by(GLJournal.id.desc()).limit(limit))
    if entity_id is not None:
        query = query.where(GLJournal.entity_id == entity_id)
    if supplier_id is not None:
        query = query.where(GLLine.supplier_id == supplier_id)
    if allowed_projects is not None:
        query = query.where(GLLine.project_id.in_(allowed_projects))
    if cash_date is not None:
        query = query.where(GLAccount.kind == 'cash', item.after_data['payment_date'].as_string() == cash_date)
    return [{'journal_id': journal, 'opening_journal_id': original, 'title': title, 'amount_paise': amount,
             'kind': kind, 'matched': is_matched, 'reference': data['payment_reference'], 'payment_date': data['payment_date']}
            for journal, key, original, title, amount, account, kind, data, is_matched in db.execute(query)
            if key == _event_key(account, data['payment_reference'].strip())]


def _event_key(account_id, reference):
    return f'legacy-balance-payment:{account_id}:{sha256(reference.encode()).hexdigest()}'


def reference_used(db, account_id, reference):
    return bool(db.scalar(select(GLJournal.id).where(GLJournal.event_key == _event_key(account_id, reference))))


def validate(db, kind, data, actor):
    from .accounting_kernel import (_bank_reference_used, _calendar_date, _cash_reference_used,
                                    _check_dated_posting, _reconciled, _supplier_payment_source,
                                    positive_minor, require_three_links, required_text)
    from .access import visible_project_ids
    from .security import FINANCE_WRITE

    if actor is None or not actor.active or actor.role not in FINANCE_WRITE:
        raise ValueError('Only the money team can pay or reverse a historical balance.')
    if set(data) != PAYMENT_FIELDS[kind]:
        raise ValueError('Use the reviewed historical payment details.')
    if kind == REVERSE_PAYMENT:
        required_text(data['reason'], 'Reason for reversing the payment', 400)
        journal_id = data['journal_id']
        journal = db.scalar(select(GLJournal).where(
            GLJournal.id == journal_id, GLJournal.source_event == PAYMENT_EVENT,
            GLJournal.status == 'posted', _unreversed(GLJournal),
        )) if type(journal_id) is int else None
        if journal is None or _reconciled(db, journal.id):
            raise ValueError('Choose a posted historical payment that has not been reversed or matched.')
        return journal

    amount = positive_minor(data['amount_paise'])
    reference = required_text(data['payment_reference'], 'Payment reference')
    day = _calendar_date(data['payment_date'], 'Payment date')
    ident = data['opening_journal_id']
    rows = open_legacy_payables(db, opening_journal_id=ident, allowed_projects=visible_project_ids(db, actor)) if type(ident) is int else []
    if len(rows) != 1:
        raise ValueError('Choose a historical expense balance that is still open.')
    balance = rows[0]
    entity = balance['entity_id']
    source, bank = _supplier_payment_source(db, entity, data, actor)
    party = db.get(Party, balance['supplier_id'])
    if party is None or party.deleted_at:
        raise ValueError('Choose a balance linked to an active vendor.')
    require_three_links('finance_payment', entity_id=entity, party=party, source=source,
                        account=db.get(GLAccount, balance['account_id']))
    _check_dated_posting(db, entity, 'bank' if bank else 'purchases', day, 'Payment date')
    if reference_used(db, source.id, reference) or (
        _bank_reference_used(db, bank.id, reference, None) if bank else _cash_reference_used(db, source.id, reference)
    ):
        raise ValueError('This payment reference was already used for that account.')
    if amount > balance['outstanding_paise']:
        raise ValueError('This is more than what is still owed.')
    return balance, source, bank, reference


def preview(db, kind, data, actor):
    from .paid_through import cash_warnings

    checked = validate(db, kind, data, actor)
    if kind == REVERSE_PAYMENT:
        return {'event': kind, 'original_journal_id': checked.id, 'requires_ticket_approval': True}
    balance, source, bank, _ = checked
    amount = data['amount_paise']
    warnings = [] if bank else cash_warnings(db, source, balance['supplier_id'], data['payment_date'], amount)
    return {'event': PAYMENT_EVENT, 'balance': balance, 'paid_through': source.name,
            'remaining_paise': balance['outstanding_paise'] - amount, 'warnings': warnings,
            'requires_ticket_approval': True}


def apply(db, item, actor, approved_by):
    from .accounting_kernel import _post_lines, _reverse_posted

    kind, data = item.item_type, item.after_data
    checked = validate(db, kind, data, actor)
    entity = checked.entity_id if kind == REVERSE_PAYMENT else checked[0]['entity_id']
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == entity).with_for_update())
    db.info.pop('_period_locks', None)
    checked = validate(db, kind, data, actor)
    if kind == REVERSE_PAYMENT:
        journal = _reverse_posted(db, checked.id, data['reason'], item.ticket_id)
    else:
        balance, source, _, reference = checked
        project = balance['project_id']
        amount = data['amount_paise']
        journal = _post_lines(db, entity_id=entity, event_kind=PAYMENT_EVENT,
                              event_key=_event_key(source.id, reference), source_id=balance['journal_id'],
                              lines=[(balance['account_id'], 'debit', amount, project),
                                     (source.id, 'credit', amount, project)],
                              supplier_id=balance['supplier_id'], ticket_id=item.ticket_id, policy_version=1)
    add_audit(db, kind, 'gl_journal', journal.id, f'Approved historical balance payment action on ticket #{item.ticket_id}.',
              actor=approved_by)
    return {'type': 'legacy_balance_payment', 'id': journal.id, 'journal_id': journal.id, 'item_id': item.id}
