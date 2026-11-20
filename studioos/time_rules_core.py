"""v0.18 time and workload rules, pure logic (no database, no web). Plain-English refusals as ValueError.

Rules from the owner's plan:
- time is logged to a task or to a named general activity, in whole minutes;
- submitted, then approved by someone other than the person; a rejection needs a reason;
- approved time is frozen: a change goes back through send-back with a reason;
- leave days, holidays and the weekly day off refuse entries; daily and weekly limits refuse entries;
- the cost rate in force on the work date is kept with the entry when it is approved;
- assigning a task shows the person's load and warns (it never blocks) before saving.
"""
from __future__ import annotations

import datetime as dt

ENTRY_STATUSES = ('draft', 'submitted', 'approved', 'rejected')
COUNTED_STATUSES = ('draft', 'submitted', 'approved')       # rejected time does not use up the limit
LEAVE_KINDS = ('leave', 'sick', 'other')
DEFAULT_DAILY_LIMIT_MINUTES = 600       # proposed defaults: the owner decides the real limits (HELD_FOR_OWNER.md)
DEFAULT_WEEKLY_LIMIT_MINUTES = 3600
DEFAULT_DAILY_CAPACITY_MINUTES = 480
DEFAULT_WEEKLY_OFF = (6,)               # Sunday (Python weekday 6)
MAX_ENTRY_MINUTES = 1440


def parse_date(value, what='Date'):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'{what} must be a date like 2026-03-31') from None


def hours_text(minutes):
    return f'{minutes // 60}h {minutes % 60:02d}m'


def date_range(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


# ---------------------------------------------------------------- logging time

def check_new_entry(*, work_date, minutes, today, has_task, activity, off_weekdays, holidays, leave_days,
                    minutes_that_day, minutes_that_week, daily_limit, weekly_limit):
    """Raises ValueError for the first rule an entry breaks. holidays/leave_days: sets of ISO dates."""
    if type(minutes) is not int or not 1 <= minutes <= MAX_ENTRY_MINUTES:
        raise ValueError('Time must be a whole number of minutes, from 1 to 1440')
    if bool(has_task) == bool(activity):
        raise ValueError('Log time to one task or to one named general activity, not both and not neither')
    if activity is not None and not (2 <= len(str(activity).strip()) <= 80):
        raise ValueError('A general activity needs a name of 2 to 80 characters')
    d = parse_date(work_date, 'Work date')
    if d > today:
        raise ValueError('Time cannot be logged for a future date')
    if work_date in leave_days:
        raise ValueError('Time cannot be logged on a day you are on leave')
    if work_date in holidays:
        raise ValueError('Time cannot be logged on a holiday')
    if d.weekday() in off_weekdays:
        raise ValueError('Time cannot be logged on the weekly day off')
    if minutes_that_day + minutes > daily_limit:
        raise ValueError(f'That would make {hours_text(minutes_that_day + minutes)} on one day; the daily limit is {hours_text(daily_limit)}')
    if minutes_that_week + minutes > weekly_limit:
        raise ValueError(f'That would make {hours_text(minutes_that_week + minutes)} in one week; the weekly limit is {hours_text(weekly_limit)}')


def week_bounds(d):
    monday = d - dt.timedelta(days=d.weekday())
    return monday, monday + dt.timedelta(days=6)


# ---------------------------------------------------------------- review

def check_review(*, entry_status, entry_user_id, reviewer_id, reviewer_role, action, reason=''):
    """action: submit | approve | reject | send_back. Returns the new status."""
    if action == 'submit':
        if entry_status != 'draft':
            raise ValueError('Only a draft can be submitted')
        if reviewer_id != entry_user_id:
            raise ValueError('Only the person who logged the time can submit it')
        return 'submitted'
    if action in ('approve', 'reject'):
        if entry_status != 'submitted':
            raise ValueError('Only submitted time can be approved or rejected')
        if reviewer_role not in ('admin', 'manager'):
            raise ValueError('Only an owner or a manager can review time')
        if reviewer_id == entry_user_id:
            raise ValueError('Time cannot be approved or rejected by the person who logged it')
        if action == 'reject' and len(str(reason).strip()) < 5:
            raise ValueError('A rejection needs a reason of at least 5 characters')
        return 'approved' if action == 'approve' else 'rejected'
    if action == 'send_back':
        if entry_status != 'approved':
            raise ValueError('Only approved time can be sent back')
        if reviewer_role not in ('admin', 'manager'):
            raise ValueError('Only an owner or a manager can send approved time back')
        if reviewer_id == entry_user_id:
            raise ValueError('Approved time cannot be sent back by the person who logged it')
        if len(str(reason).strip()) < 5:
            raise ValueError('Sending time back needs a reason of at least 5 characters')
        return 'draft'
    raise ValueError('Unknown review action')


def check_editable(entry_status):
    if entry_status not in ('draft', 'rejected'):
        raise ValueError('Submitted or approved time cannot be edited; approved time goes back through send-back first')


# ---------------------------------------------------------------- rates

def rate_in_force(rates, work_date):
    """rates: list of (effective_from, paise_per_hour). The latest one on or before work_date, else None."""
    best = None
    for eff, paise in rates:
        if eff <= work_date and (best is None or eff > best[0]):
            best = (eff, paise)
    return best[1] if best else None


def cost_paise(minutes, rate_paise_per_hour):
    """Whole paise, rounded half up. Money is never a float."""
    if rate_paise_per_hour is None:
        return None
    return (minutes * rate_paise_per_hour + 30) // 60


def validate_rate(paise, effective_from):
    if type(paise) is not int or not 0 < paise <= 10_000_000:
        raise ValueError('A rate is whole paise per hour, above zero')
    parse_date(effective_from, 'Effective-from date')


# ---------------------------------------------------------------- workload

def working_days(start, end, off_weekdays, holidays):
    return [d for d in date_range(start, end) if d.weekday() not in off_weekdays and d.isoformat() not in holidays]


def spread_minutes(minutes, days):
    """Spread a task's estimate evenly over its working days (the remainder goes to the earliest days)."""
    if not days or minutes <= 0:
        return {}
    base, extra = divmod(minutes, len(days))
    return {d: base + (1 if i < extra else 0) for i, d in enumerate(days)}


def workload_check(*, tasks, new_task, capacity, off_weekdays, holidays, leave_days, today):
    """tasks: the person's open tasks [{'id','minutes','start','due'}] (start/due ISO or ''). new_task: same shape.
    Returns {'warnings': [...], 'peak_minutes': n, 'overloaded_days': [...]}. Never raises for a heavy load: it warns."""
    warnings = []
    due = new_task.get('due')
    if not due:
        return {'warnings': ['The task has no due date, so the load cannot be checked'], 'peak_minutes': 0, 'overloaded_days': []}
    end = parse_date(due, 'Due date')
    start = parse_date(new_task.get('start') or today.isoformat(), 'Start date')
    if end < start:
        return {'warnings': ['The due date is before the start'], 'peak_minutes': 0, 'overloaded_days': []}
    window = list(date_range(start, end))
    for d in window:
        if d.isoformat() in leave_days:
            warnings.append(f'On leave on {d.isoformat()}')
    days = [d for d in working_days(start, end, off_weekdays, holidays) if d.isoformat() not in leave_days]
    if not days:
        warnings.append('There is no working day between the start and the due date')
        return {'warnings': warnings, 'peak_minutes': 0, 'overloaded_days': []}
    load = {}
    for t in tasks:
        if t.get('id') == new_task.get('id') or not t.get('minutes') or not t.get('due'):
            continue
        t_end = parse_date(t['due'], 'Due date')
        t_start = parse_date(t.get('start') or min(today, t_end).isoformat(), 'Start date')
        if t_end < t_start:
            continue
        t_days = [d for d in working_days(t_start, t_end, off_weekdays, holidays) if d.isoformat() not in leave_days]
        for d, m in spread_minutes(t['minutes'], t_days).items():
            load[d] = load.get(d, 0) + m
    for d, m in spread_minutes(new_task.get('minutes') or 0, days).items():
        load[d] = load.get(d, 0) + m
    over = sorted(d for d in days if load.get(d, 0) > capacity)
    peak = max((load.get(d, 0) for d in days), default=0)
    if over:
        warnings.append(f'Overloaded on {len(over)} day(s), peak {hours_text(peak)} against {hours_text(capacity)} a day')
    if not new_task.get('minutes'):
        warnings.append('The task has no time estimate, so its own load is not counted')
    return {'warnings': warnings, 'peak_minutes': peak, 'overloaded_days': [d.isoformat() for d in over]}
