"""v0.18 time and workload on the ticket path. Every change is a ticket item that a person approves; nothing here is
written by a route directly. The person making the change is the one who proposed it (a site engineer proposes their
own time, a manager proposes an approval); the owner approves the ticket.

validate(db, item) raises ValueError in plain English and writes nothing; apply(db, item, actor) re-validates, then writes.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from . import time_rules_core as core
from .access import can_access_project
from .db import ApprovalTicket, Config, Task, TicketRecordEvent, User, add_audit, now
from .time_models import CostRate, TaskEstimate, TimeEntry, TimeEntryLog, WorkHoliday, WorkLeave

TIME_TYPES = {'time_log', 'time_edit', 'time_submit', 'time_approve', 'time_reject', 'time_send_back', 'leave_record',
              'leave_cancel', 'holiday_add', 'holiday_remove', 'rate_set', 'task_estimate', 'time_setting'}

TIME_FIELDS = {
    'time_log': {'task_id', 'activity', 'work_date', 'minutes', 'note', 'source'},
    'time_edit': {'entry_id', 'minutes', 'note', 'work_date'},
    'time_submit': {'entry_id'}, 'time_approve': {'entry_id'},
    'time_reject': {'entry_id', 'reason'}, 'time_send_back': {'entry_id', 'reason'},
    'leave_record': {'user_id', 'start_date', 'end_date', 'kind', 'note'}, 'leave_cancel': {'leave_id'},
    'holiday_add': {'date', 'name'}, 'holiday_remove': {'holiday_id'},
    'rate_set': {'user_id', 'rate_paise_per_hour', 'effective_from'},
    'task_estimate': {'task_id', 'minutes'},
    'time_setting': {'key', 'value'},
}

SETTINGS = {   # key: (default, low, high)
    'time_daily_limit_minutes': (core.DEFAULT_DAILY_LIMIT_MINUTES, 60, 1440),
    'time_weekly_limit_minutes': (core.DEFAULT_WEEKLY_LIMIT_MINUTES, 60, 10080),
    'work_daily_capacity_minutes': (core.DEFAULT_DAILY_CAPACITY_MINUTES, 60, 1440),
}
RATE_ROLES = ('admin', 'manager', 'accounts')       # everyone else never sees a rate or a cost
MANAGE_ROLES = ('admin', 'manager')


STUDIO_UTC_OFFSET_MINUTES = 330   # India Standard Time. A proposed default; the owner confirms the studio's time zone.


def studio_now():
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=STUDIO_UTC_OFFSET_MINUTES)


def studio_today():
    return studio_now().date()


def setting(db, key):
    default = SETTINGS[key][0]
    row = db.get(Config, key)
    try:
        return int(row.value) if row else default
    except (TypeError, ValueError):
        return default


def week_off(db):
    row = db.get(Config, 'work_week_off')
    if not row:
        return set(core.DEFAULT_WEEKLY_OFF)
    try:
        days = {int(x) for x in row.value.split(',') if x.strip() != ''}
    except ValueError:
        return set(core.DEFAULT_WEEKLY_OFF)
    return days if all(0 <= d <= 6 for d in days) else set(core.DEFAULT_WEEKLY_OFF)


def holiday_dates(db):
    return set(db.scalars(select(WorkHoliday.holiday_date).where(WorkHoliday.retired_at.is_(None))))


def leave_dates(db, user_id):
    out = set()
    for row in db.scalars(select(WorkLeave).where(WorkLeave.user_id == user_id, WorkLeave.retired_at.is_(None))):
        try:
            a, b = core.parse_date(row.start_date), core.parse_date(row.end_date)
        except ValueError:
            continue
        out.update(d.isoformat() for d in core.date_range(a, b))
    return out


def rates_of(db, user_id):
    return [(r.effective_from, r.rate_paise_per_hour) for r in db.scalars(select(CostRate).where(CostRate.user_id == user_id))]


def _minutes(db, user_id, start, end, exclude_id=None):
    q = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
        TimeEntry.user_id == user_id, TimeEntry.work_date >= start, TimeEntry.work_date <= end,
        TimeEntry.status.in_(core.COUNTED_STATUSES))
    if exclude_id:
        q = q.where(TimeEntry.id != exclude_id)
    return int(db.scalar(q) or 0)


def _actor(db, item):
    ticket = db.get(ApprovalTicket, item.ticket_id) if item is not None and item.ticket_id else None
    user = db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None
    if not user:
        raise ValueError('The person making this change is not known')
    return user


def _need_roles(user, roles):
    if user.role not in roles:
        raise ValueError('Your role may not make this change')


def _int(d, key):
    if type(d.get(key)) is not int or d[key] <= 0:
        raise ValueError(f'{key} must be a record number')
    return d[key]


def _entry(db, d):
    e = db.get(TimeEntry, _int(d, 'entry_id'))
    if not e:
        raise ValueError('That time entry does not exist')
    return e


def _check_log(db, user, *, task_id, activity, work_date, minutes, exclude_id=None):
    if task_id is not None:
        t = db.get(Task, task_id) if type(task_id) is int else None
        if not t or t.deleted_at or not can_access_project(db, user, t.project_id):
            raise ValueError('That task does not exist')
    d = core.parse_date(work_date, 'Work date')
    monday, sunday = core.week_bounds(d)
    core.check_new_entry(
        work_date=work_date, minutes=minutes, today=studio_today(), has_task=task_id is not None, activity=activity,
        off_weekdays=week_off(db), holidays=holiday_dates(db), leave_days=leave_dates(db, user.id),
        minutes_that_day=_minutes(db, user.id, work_date, work_date, exclude_id),
        minutes_that_week=_minutes(db, user.id, monday.isoformat(), sunday.isoformat(), exclude_id),
        daily_limit=setting(db, 'time_daily_limit_minutes'), weekly_limit=setting(db, 'time_weekly_limit_minutes'))


def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in TIME_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - TIME_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    return globals()['_validate_' + kind](db, item, d)


def _validate_time_log(db, item, d):
    user = _actor(db, item)
    _need_roles(user, ('admin', 'manager', 'architect', 'site_engineer'))
    if d.get('source', 'manual') not in ('manual', 'timer'):
        raise ValueError('source must be manual or timer')
    activity = d.get('activity') or None
    _check_log(db, user, task_id=d.get('task_id'), activity=activity, work_date=d.get('work_date'), minutes=d.get('minutes'))
    if 'note' in d and (not isinstance(d['note'], str) or len(d['note']) > 1000):
        raise ValueError('A note is at most 1000 characters')


def _validate_time_edit(db, item, d):
    user, e = _actor(db, item), _entry(db, d)
    if e.user_id != user.id:
        raise ValueError('Only the person who logged the time can edit it')
    core.check_editable(e.status)
    _check_log(db, user, task_id=e.task_id, activity=e.activity or None, work_date=d.get('work_date', e.work_date),
               minutes=d.get('minutes', e.minutes), exclude_id=e.id)


def _review(db, item, d, action):
    user, e = _actor(db, item), _entry(db, d)
    return e, core.check_review(entry_status=e.status, entry_user_id=e.user_id, reviewer_id=user.id, reviewer_role=user.role,
                                action=action, reason=d.get('reason', ''))


def _validate_time_submit(db, item, d):
    _review(db, item, d, 'submit')


def _validate_time_approve(db, item, d):
    _review(db, item, d, 'approve')


def _validate_time_reject(db, item, d):
    _review(db, item, d, 'reject')


def _validate_time_send_back(db, item, d):
    _review(db, item, d, 'send_back')


def _validate_leave_record(db, item, d):
    user = _actor(db, item)
    who = _int(d, 'user_id')
    if who != user.id:
        _need_roles(user, MANAGE_ROLES)
    if not db.get(User, who):
        raise ValueError('That person does not exist')
    a, b = core.parse_date(d.get('start_date'), 'Start date'), core.parse_date(d.get('end_date'), 'End date')
    if b < a or (b - a).days > 365:
        raise ValueError('Leave must end on or after it starts, and last at most a year')
    if d.get('kind', 'leave') not in core.LEAVE_KINDS:
        raise ValueError('Leave kind must be leave, sick or other')
    booked = db.scalar(select(func.count()).select_from(TimeEntry).where(
        TimeEntry.user_id == who, TimeEntry.work_date >= d['start_date'], TimeEntry.work_date <= d['end_date'],
        TimeEntry.status.in_(core.COUNTED_STATUSES)))
    if booked:
        raise ValueError('Time is already logged on some of those days; send it back or reject it first')


def _validate_leave_cancel(db, item, d):
    user = _actor(db, item)
    row = db.get(WorkLeave, _int(d, 'leave_id'))
    if not row or row.retired_at:
        raise ValueError('That leave does not exist or was already cancelled')
    if row.user_id != user.id:
        _need_roles(user, MANAGE_ROLES)


def _validate_holiday_add(db, item, d):
    _need_roles(_actor(db, item), MANAGE_ROLES)
    core.parse_date(d.get('date'), 'Holiday date')
    if not isinstance(d.get('name'), str) or not 2 <= len(d['name'].strip()) <= 120:
        raise ValueError('A holiday needs a name')
    if d['date'] in holiday_dates(db):
        raise ValueError('That date is already a holiday')


def _validate_holiday_remove(db, item, d):
    _need_roles(_actor(db, item), MANAGE_ROLES)
    row = db.get(WorkHoliday, _int(d, 'holiday_id'))
    if not row or row.retired_at:
        raise ValueError('That holiday does not exist')


def _validate_rate_set(db, item, d):
    _need_roles(_actor(db, item), MANAGE_ROLES)
    if not db.get(User, _int(d, 'user_id')):
        raise ValueError('That person does not exist')
    core.validate_rate(d.get('rate_paise_per_hour'), d.get('effective_from'))
    if db.scalar(select(func.count()).select_from(CostRate).where(CostRate.user_id == d['user_id'],
                                                                  CostRate.effective_from == d['effective_from'])):
        raise ValueError('A rate with that effective date already exists; use a later date')


def _validate_task_estimate(db, item, d):
    _need_roles(_actor(db, item), ('admin', 'manager', 'architect'))
    t = db.get(Task, _int(d, 'task_id'))
    if not t or t.deleted_at:
        raise ValueError('That task does not exist')
    if type(d.get('minutes')) is not int or not 0 < d['minutes'] <= 100_000:
        raise ValueError('An estimate is a whole number of minutes above zero')


def _validate_time_setting(db, item, d):
    _need_roles(_actor(db, item), ('admin',))
    key, value = d.get('key'), d.get('value')
    if key in SETTINGS:
        _, low, high = SETTINGS[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be a whole number from {low} to {high}')
    elif key == 'work_week_off':
        if not isinstance(value, list) or any(type(x) is not int or not 0 <= x <= 6 for x in value) or len(set(value)) != len(value) or len(value) > 3:
            raise ValueError('work_week_off is up to three different weekday numbers, 0 (Monday) to 6 (Sunday)')
    else:
        raise ValueError('Unknown time setting')


# ------------------------------------------------------------------ apply

def apply(db, item, actor):
    validate(db, item)
    entity, entity_id, op = globals()['_apply_' + item.item_type](db, item, item.after_data, actor)
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type=entity, entity_id=entity_id, operation=op))
    add_audit(db, 'ticket_commit', entity, entity_id, f'Ticket #{item.ticket_id}, item #{item.id}: {item.item_type}', actor=actor)
    db.flush()
    return {'type': entity, 'id': entity_id, 'item_id': item.id}


def _log(db, item, entry, action, actor, reason=''):
    db.add(TimeEntryLog(entry_id=entry.id, action=action, actor=actor, reason=reason, ticket_id=item.ticket_id))


def _apply_time_log(db, item, d, actor):
    user = _actor(db, item)
    e = TimeEntry(user_id=user.id, task_id=d.get('task_id'), activity=(d.get('activity') or '').strip(), work_date=d['work_date'],
                  minutes=d['minutes'], note=d.get('note', ''), source=d.get('source', 'manual'))
    db.add(e)
    db.flush()
    _log(db, item, e, 'logged', actor)
    return 'time_entry', e.id, 'create'


def _apply_time_edit(db, item, d, actor):
    e = _entry(db, d)
    for k in ('minutes', 'note', 'work_date'):
        if k in d:
            setattr(e, k, d[k])
    e.status = 'draft'
    _log(db, item, e, 'edited', actor)
    return 'time_entry', e.id, 'update'


def _apply_time_submit(db, item, d, actor):
    e = _entry(db, d)
    e.status, e.submitted_at = 'submitted', now()
    _log(db, item, e, 'submitted', actor)
    return 'time_entry', e.id, 'update'


def _apply_time_approve(db, item, d, actor):
    e, user = _entry(db, d), _actor(db, item)
    e.status, e.decided_by, e.decided_at, e.decision_reason = 'approved', user.id, now(), ''
    e.rate_paise_per_hour = core.rate_in_force(rates_of(db, e.user_id), e.work_date)
    e.cost_paise = core.cost_paise(e.minutes, e.rate_paise_per_hour)
    _log(db, item, e, 'approved', actor)
    return 'time_entry', e.id, 'update'


def _apply_time_reject(db, item, d, actor):
    e, user = _entry(db, d), _actor(db, item)
    e.status, e.decided_by, e.decided_at, e.decision_reason = 'rejected', user.id, now(), d['reason'].strip()
    _log(db, item, e, 'rejected', actor, d['reason'].strip())
    return 'time_entry', e.id, 'update'


def _apply_time_send_back(db, item, d, actor):
    e, user = _entry(db, d), _actor(db, item)
    e.status, e.decided_by, e.decided_at, e.decision_reason = 'draft', user.id, now(), d['reason'].strip()
    e.rate_paise_per_hour = e.cost_paise = None
    _log(db, item, e, 'sent_back', actor, d['reason'].strip())
    return 'time_entry', e.id, 'update'


def _apply_leave_record(db, item, d, actor):
    row = WorkLeave(user_id=d['user_id'], start_date=d['start_date'], end_date=d['end_date'], kind=d.get('kind', 'leave'),
                    note=d.get('note', ''), created_by=actor)
    db.add(row)
    db.flush()
    return 'work_leave', row.id, 'create'


def _apply_leave_cancel(db, item, d, actor):
    row = db.get(WorkLeave, d['leave_id'])
    row.retired_at = now()
    return 'work_leave', row.id, 'update'


def _apply_holiday_add(db, item, d, actor):
    row = WorkHoliday(holiday_date=d['date'], name=d['name'].strip(), created_by=actor)
    db.add(row)
    db.flush()
    return 'work_holiday', row.id, 'create'


def _apply_holiday_remove(db, item, d, actor):
    row = db.get(WorkHoliday, d['holiday_id'])
    row.retired_at = now()
    return 'work_holiday', row.id, 'update'


def _apply_rate_set(db, item, d, actor):
    row = CostRate(user_id=d['user_id'], rate_paise_per_hour=d['rate_paise_per_hour'], effective_from=d['effective_from'], created_by=actor)
    db.add(row)
    db.flush()
    return 'cost_rate', row.id, 'create'


def _apply_task_estimate(db, item, d, actor):
    row = db.get(TaskEstimate, d['task_id'])
    if row:
        row.minutes, row.updated_by, row.updated_at = d['minutes'], actor, now()
    else:
        row = TaskEstimate(task_id=d['task_id'], minutes=d['minutes'], updated_by=actor)
        db.add(row)
    return 'task', d['task_id'], 'update'


def _apply_time_setting(db, item, d, actor):
    value = ','.join(str(x) for x in sorted(d['value'])) if d['key'] == 'work_week_off' else str(d['value'])
    row = db.get(Config, d['key'])
    if row:
        row.value = value
    else:
        db.add(Config(key=d['key'], value=value))
    return 'setting', 0, 'update'
