"""v0.20 controls, pure logic: lock areas by document date, retention, legal holds. No tax logic: the accountant has not
confirmed any tax rule, so this release only holds controls and empty fields. Plain-English refusals as ValueError.
"""
from __future__ import annotations

import datetime as dt
import re

AREAS = ('sales', 'purchases', 'bank')       # from the CA plan: separate locks, plus the existing one final close
REGISTRATION_TYPES = ('', 'regular', 'composition', 'unregistered')
DEFAULT_RETENTION_YEARS = 10                 # the CA plan's default, extendable by legal hold
_YM = re.compile(r'^20[0-9]{2}-(0[1-9]|1[0-2])$')


def check_lock_request(year_month, area, current_year_month):
    if area not in AREAS:
        raise ValueError('Lock area must be sales, purchases or bank')
    if not isinstance(year_month, str) or not _YM.match(year_month):
        raise ValueError('Month must look like 2026-03')
    if year_month > current_year_month:
        raise ValueError('A future month cannot be locked')


def is_locked(active_locks, area, document_date):
    """active_locks: iterable of (area, year_month). A document is locked when its own month is locked for its area."""
    try:
        month = dt.date.fromisoformat(document_date).strftime('%Y-%m')
    except (TypeError, ValueError):
        raise ValueError('The document date must be a date like 2026-03-31') from None
    return (area, month) in set(active_locks)


def check_document_date(active_locks, area, document_date):
    if is_locked(active_locks, area, document_date):
        raise ValueError(f'The {area} books for {document_date[:7]} are locked; ask the owner to reopen that month')


def retention_until(document_date, years=DEFAULT_RETENTION_YEARS):
    d = dt.date.fromisoformat(document_date)
    try:
        return d.replace(year=d.year + years)
    except ValueError:                      # 29 February
        return d.replace(year=d.year + years, day=28)


def check_may_delete(*, held, document_date, today, years=DEFAULT_RETENTION_YEARS):
    """A legal hold blocks deletion outright; otherwise a dated record is kept until its retention ends."""
    if held:
        raise ValueError('This record is under a legal hold and cannot be deleted')
    if document_date and today < retention_until(document_date, years):
        raise ValueError(f'This record must be kept until {retention_until(document_date, years).isoformat()}')
