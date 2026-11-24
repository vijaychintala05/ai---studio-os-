"""Approved, reversible copying of reviewed tracker expenses into Books."""
from sqlalchemy import select

from .db import AccountingEntity, ApprovalTicket, GLAccount, GLJournal, Party, User, add_audit
from .legacy_expense_preview import preview_batch
from .operating_totals import MIGRATED_EXPENSE_EVENT
from .paid_through import list_accounts

MIGRATE = 'finance_migrate_expenses'
REVERSE = 'finance_reverse_expense_migration'
MIGRATION_TYPES = {MIGRATE, REVERSE}
MIGRATION_FIELDS = {
    MIGRATE: {'entity_id', 'entries', 'review_fingerprint', 'signoff_reference'},
    REVERSE: {'batch_ticket_id', 'reason'},
}


def requester(db, item):
    ticket = db.get(ApprovalTicket, item.ticket_id)
    return db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None


def validate(db, kind, data, actor):
    from .accounting_kernel import (
        _calendar_date, _check_dated_posting, _is_reversed, _reconciled, require_three_links, required_text,
    )
    from .universal_routes import LegacyExpensePreview

    if actor is None or not actor.active or actor.role not in ('admin', 'accounts'):
        raise ValueError('Only the owner and accounts can prepare expense migration.')
    if set(data) != MIGRATION_FIELDS[kind]:
        raise ValueError('Use the reviewed migration details.')
    if kind == REVERSE:
        required_text(data['reason'], 'Reason for reversing the batch', 400)
        if type(data['batch_ticket_id']) is not int:
            raise ValueError('Choose an approved migration batch.')
        journals = db.scalars(select(GLJournal).where(
            GLJournal.ticket_id == data['batch_ticket_id'],
            GLJournal.source_event == MIGRATED_EXPENSE_EVENT, GLJournal.status == 'posted',
        ).order_by(GLJournal.id)).all()
        if len({j.entity_id for j in journals}) != 1 or any(
            _is_reversed(db, j.id) or _reconciled(db, j.id) for j in journals
        ):
            raise ValueError('Choose an approved migration batch that has not been reversed or matched.')
        return journals

    entity_id = data['entity_id']
    if type(entity_id) is not int or db.get(AccountingEntity, entity_id) is None:
        raise ValueError('Choose an existing company.')
    required_text(data['signoff_reference'], 'Accountant sign-off reference', 400)
    try:
        mappings = LegacyExpensePreview.model_validate({'entries': data['entries']}).entries
    except ValueError as exc:
        raise ValueError('Choose between one and 50 reviewed historical expenses.') from exc
    if len({entry.cost_id for entry in mappings}) != len(mappings):
        raise ValueError('Include each historical cost only once.')
    sources = {row['id']: row for row in list_accounts(db, entity_id, actor)}
    result = preview_batch(db, entity_id, mappings, sources)
    batch = result['batch']
    if data['review_fingerprint'] != batch['review_fingerprint']:
        raise ValueError('The migration preview changed. Preview it again before sending it for approval.')
    if not batch['ready_for_review']:
        raise ValueError('Resolve all issues in the migration preview first.')
    for entry in result['entries']:
        debit, credit = (db.get(GLAccount, line['account_id']) for line in entry['journal_lines'])
        party = db.get(Party, entry['vendor_id'])
        require_three_links('finance_expense', entity_id=entity_id, party=party, source=credit, account=debit)
        day = _calendar_date(entry['date'], 'Expense date')
        _check_dated_posting(db, entity_id, 'purchases', day, 'Expense date')
        if credit.kind == 'bank':
            _check_dated_posting(db, entity_id, 'bank', day, 'Expense date')
    return result


def preview(db, kind, data, actor):
    checked = validate(db, kind, data, actor)
    if kind == MIGRATE:
        return {**checked, 'requires_ticket_approval': True, 'event': MIGRATED_EXPENSE_EVENT}
    return {'event': kind, 'original_journal_ids': [j.id for j in checked], 'requires_ticket_approval': True}


def apply(db, item, approved_by):
    from .accounting_kernel import _post, _reverse_posted

    kind, data = item.item_type, item.after_data
    actor = requester(db, item)
    checked = validate(db, kind, data, actor)
    entity_id = data['entity_id'] if kind == MIGRATE else checked[0].entity_id
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    checked = validate(db, kind, data, actor)
    journal_ids = []
    if kind == MIGRATE:
        for entry in checked['entries']:
            debit, credit = entry['journal_lines']
            journal = _post(
                db, entity_id=entity_id, event_kind=MIGRATED_EXPENSE_EVENT,
                event_key=f'legacy-expense:{item.id}:{entry["cost_id"]}', source_id=entry['cost_id'],
                debit_account=debit['account_id'], credit_account=credit['account_id'],
                amount=entry['amount_paise'], project_id=entry['project_id'], supplier_id=entry['vendor_id'],
                ticket_id=item.ticket_id, policy_version=1,
            )
            journal_ids.append(journal.id)
    else:
        for journal in checked:
            journal_ids.append(_reverse_posted(db, journal.id, data['reason'], item.ticket_id).id)
    add_audit(db, kind, 'expense_migration_batch', item.ticket_id,
              f'Approved ticket recorded {len(journal_ids)} matching journal entries.', actor=approved_by)
    return {'type': 'expense_migration_batch', 'id': item.ticket_id, 'item_id': item.id, 'journal_ids': journal_ids}
