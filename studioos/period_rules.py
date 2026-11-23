"""Ticket-based document period locks, legal holds, and party registration type."""
from __future__ import annotations

from sqlalchemy import select

from . import period_core as core
from .db import AccountingEntity, ApprovalTicket, Party, Project, TicketRecordEvent, User, add_audit, now
from .period_models import LegalHold, PartyTaxProfile, PeriodAreaLock

PERIOD_TYPES = {'period_area_lock', 'period_area_reopen', 'legal_hold_place', 'legal_hold_release', 'party_tax_profile'}
PERIOD_FIELDS = {
    'period_area_lock': {'entity_id', 'year_month', 'area', 'reason'},
    'period_area_reopen': {'lock_id', 'reason'},
    'legal_hold_place': {'project_id', 'reason'},
    'legal_hold_release': {'hold_id', 'reason'},
    'party_tax_profile': {'party_id', 'registration_type', 'effective_from'},
}
ROLES = {'period_area_lock': ('admin', 'accounts'), 'period_area_reopen': ('admin',), 'legal_hold_place': ('admin',),
         'legal_hold_release': ('admin',), 'party_tax_profile': ('admin', 'accounts')}


def active_locks(db, entity_id):
    """Read once per session and entity: a statement import checks hundreds of lines. apply() clears the cache."""
    cache = db.info.setdefault('_period_locks', {})
    if entity_id not in cache:
        cache[entity_id] = [(r.area, r.year_month) for r in db.scalars(select(PeriodAreaLock).where(
            PeriodAreaLock.entity_id == entity_id, PeriodAreaLock.reopened_at.is_(None)))]
    return cache[entity_id]


def check_document_date(db, entity_id, area, document_date):
    core.check_document_date(active_locks(db, entity_id), area, document_date)


def held_project_ids(db):
    return set(db.scalars(select(LegalHold.project_id).where(LegalHold.released_at.is_(None))))


def check_project_may_change(db, project_id):
    """A legal hold freezes deletion of a project's work."""
    if project_id in held_project_ids(db):
        raise ValueError('This project is under a legal hold and its records cannot be deleted')


def _actor(db, item):
    t = db.get(ApprovalTicket, item.ticket_id) if item.ticket_id else None
    u = db.get(User, t.submitter_id) if t and t.submitter_id else None
    if not u:
        raise ValueError('The person making this change is not known')
    return u


def _reason(d, what='A reason'):
    if not isinstance(d.get('reason'), str) or len(d['reason'].strip()) < 5:
        raise ValueError(f'{what} of at least 5 characters is required')


def _int(d, key):
    if type(d.get(key)) is not int or d[key] <= 0:
        raise ValueError(f'{key} must be a record number')
    return d[key]


def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in PERIOD_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - PERIOD_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    if _actor(db, item).role not in ROLES[kind]:
        raise ValueError('Your role may not make this change')
    return globals()['_v_' + kind](db, d)


def _v_period_area_lock(db, d):
    from .chart_of_accounts import local_today

    if not db.get(AccountingEntity, _int(d, 'entity_id')):
        raise ValueError('Legal entity required')
    core.check_lock_request(d.get('year_month'), d.get('area'), local_today().strftime('%Y-%m'))
    _reason(d, 'An explanation')
    if (d['area'], d['year_month']) in active_locks(db, d['entity_id']):
        raise ValueError('That month is already locked for that area')


def _v_period_area_reopen(db, d):
    row = db.get(PeriodAreaLock, _int(d, 'lock_id'))
    if not row or row.reopened_at:
        raise ValueError('That lock does not exist or was already reopened')
    _reason(d)


def _v_legal_hold_place(db, d):
    p = db.get(Project, _int(d, 'project_id'))
    if not p or p.deleted_at:
        raise ValueError('That project does not exist')
    _reason(d)
    if d['project_id'] in held_project_ids(db):
        raise ValueError('That project already has a legal hold')


def _v_legal_hold_release(db, d):
    row = db.get(LegalHold, _int(d, 'hold_id'))
    if not row or row.released_at:
        raise ValueError('That hold does not exist or was already released')
    _reason(d)


def _v_party_tax_profile(db, d):
    p = db.get(Party, _int(d, 'party_id'))
    if not p or p.deleted_at:
        raise ValueError('That party does not exist')
    if d.get('registration_type') not in core.REGISTRATION_TYPES:
        raise ValueError('Registration type must be regular, composition, unregistered or empty')
    import datetime as dt
    try:
        dt.date.fromisoformat(d.get('effective_from'))
    except (TypeError, ValueError):
        raise ValueError('Effective-from must be a date like 2026-04-01') from None


def apply(db, item, actor):
    d, kind = item.after_data, item.item_type
    db.info.pop('_period_locks', None)
    validate(db, item)
    if kind in ('period_area_lock', 'period_area_reopen'):
        lock = db.get(PeriodAreaLock, d['lock_id']) if kind == 'period_area_reopen' else None
        entity_id = lock.entity_id if lock else d['entity_id']
        # Keep the same entity-first lock order as posting a bill or bank payment.
        db.get(AccountingEntity, entity_id, with_for_update=True)
        if lock:
            db.refresh(lock)
        db.info.pop('_period_locks', None)
        validate(db, item)
    if kind == 'period_area_lock':
        row = PeriodAreaLock(entity_id=d['entity_id'], year_month=d['year_month'], area=d['area'], reason=d['reason'].strip(), locked_by=actor)
        db.add(row)
        entity, op = 'period_area_lock', 'create'
    elif kind == 'period_area_reopen':
        row = db.get(PeriodAreaLock, d['lock_id'])
        row.reopened_at, row.reopened_by, row.reopen_reason = now(), actor, d['reason'].strip()
        entity, op = 'period_area_lock', 'update'
    elif kind == 'legal_hold_place':
        row = LegalHold(project_id=d['project_id'], reason=d['reason'].strip(), placed_by=actor)
        db.add(row)
        entity, op = 'legal_hold', 'create'
    elif kind == 'legal_hold_release':
        row = db.get(LegalHold, d['hold_id'])
        row.released_at, row.released_by, row.release_reason = now(), actor, d['reason'].strip()
        entity, op = 'legal_hold', 'update'
    else:
        row = PartyTaxProfile(party_id=d['party_id'], registration_type=d['registration_type'], effective_from=d['effective_from'], created_by=actor)
        db.add(row)
        entity, op = 'party_tax_profile', 'create'
    db.flush()
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type=entity, entity_id=row.id, operation=op))
    add_audit(db, 'ticket_commit', entity, row.id, f'Ticket #{item.ticket_id}, item #{item.id}: {kind}', actor=actor)
    db.flush()
    db.info.pop('_period_locks', None)
    return {'type': entity, 'id': row.id, 'item_id': item.id}


def check_bank_line_date(db, d):
    """A bank statement line cannot be added to a month locked for bank. Skipped when the date or bank is not valid:
    the finance rules refuse those on their own."""
    from .db import RegisteredBank
    import datetime as dt
    bank = db.get(RegisteredBank, d.get('bank_id')) if type(d.get('bank_id')) is int else None
    date = d.get('booking_date')
    if not bank or not isinstance(date, str):
        return
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return
    check_document_date(db, bank.entity_id, 'bank', date)
