"""v0.18 time, calendar, rates, timer and workload APIs. Reads follow the plan: a site engineer sees only their own time
and never a rate or a cost. Every change is a draft ticket for a person to approve; the workload check only warns."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import time_rules_core as core
from .access import can_access_project
from .db import Task, User
from .deps import get_db
from .security import current_user, permit
from .time_models import CostRate, TaskEstimate, TimeEntry, TimerRun, WorkHoliday, WorkLeave
from .time_rules import (MANAGE_ROLES, RATE_ROLES, SETTINGS, STUDIO_UTC_OFFSET_MINUTES, TIME_TYPES, holiday_dates, leave_dates,
                         setting, studio_now, studio_today, week_off)
from .work_models import TaskStructure
from .work_rules_core import CLOSED_TASK_STATUSES

router = APIRouter(prefix='/api/time', tags=['Time and workload'])


class Proposal(BaseModel):
    kind: str
    data: dict


def _entry_out(e, show_money):
    out = {'id': e.id, 'user_id': e.user_id, 'task_id': e.task_id, 'activity': e.activity, 'work_date': e.work_date,
           'minutes': e.minutes, 'note': e.note, 'source': e.source, 'status': e.status, 'decision_reason': e.decision_reason}
    if show_money:
        out['rate_paise_per_hour'], out['cost_paise'] = e.rate_paise_per_hour, e.cost_paise
    return out


@router.get('/entries')
def entries(status: str | None = None, user_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(TimeEntry).order_by(TimeEntry.work_date.desc(), TimeEntry.id.desc()).limit(500)
    if user.role not in MANAGE_ROLES:
        q = q.where(TimeEntry.user_id == user.id)
    elif user_id:
        q = q.where(TimeEntry.user_id == user_id)
    if status:
        q = q.where(TimeEntry.status == status)
    return [_entry_out(e, user.role in RATE_ROLES) for e in db.scalars(q)]


@router.get('/settings')
def settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {**{k: setting(db, k) for k in SETTINGS}, 'work_week_off': sorted(week_off(db)), 'today': studio_today().isoformat()}


@router.get('/calendar')
def calendar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(WorkLeave).where(WorkLeave.retired_at.is_(None)).order_by(WorkLeave.start_date)
    if user.role not in MANAGE_ROLES:
        q = q.where(WorkLeave.user_id == user.id)
    holidays = db.scalars(select(WorkHoliday).where(WorkHoliday.retired_at.is_(None)).order_by(WorkHoliday.holiday_date))
    return {'holidays': [{'id': h.id, 'date': h.holiday_date, 'name': h.name} for h in holidays],
            'leave': [{'id': l.id, 'user_id': l.user_id, 'start_date': l.start_date, 'end_date': l.end_date, 'kind': l.kind}
                      for l in db.scalars(q)]}


@router.get('/rates')
def rates(user: User = Depends(permit(*RATE_ROLES)), db: Session = Depends(get_db)):
    return [{'id': r.id, 'user_id': r.user_id, 'rate_paise_per_hour': r.rate_paise_per_hour, 'effective_from': r.effective_from}
            for r in db.scalars(select(CostRate).order_by(CostRate.user_id, CostRate.effective_from))]


@router.get('/workload')
def workload(assignee: str, due_date: str, start_date: str = '', estimate_minutes: int = 0, task_id: int = 0,
             user: User = Depends(permit('admin', 'manager', 'architect')), db: Session = Depends(get_db)):
    """Shown before an assignment is saved. It warns about load and leave; it never blocks."""
    person = db.scalar(select(User).where((User.display_name == assignee) | (User.username == assignee)))
    rows = db.execute(select(Task, TaskEstimate.minutes, TaskStructure.start_date)
                      .outerjoin(TaskEstimate, TaskEstimate.task_id == Task.id)
                      .outerjoin(TaskStructure, TaskStructure.task_id == Task.id)
                      .where(Task.assignee == assignee, Task.deleted_at.is_(None),
                             Task.status.notin_(CLOSED_TASK_STATUSES))).all()
    tasks = [{'id': t.id, 'minutes': m or 0, 'start': s or '', 'due': t.due_date} for t, m, s in rows]
    try:
        result = core.workload_check(
            tasks=tasks, new_task={'id': task_id or None, 'minutes': estimate_minutes, 'start': start_date, 'due': due_date},
            capacity=setting(db, 'work_daily_capacity_minutes'), off_weekdays=week_off(db), holidays=holiday_dates(db),
            leave_days=leave_dates(db, person.id) if person else set(), today=studio_today())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**result, 'person_known': bool(person)}


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit('admin', 'manager', 'architect', 'site_engineer', 'accounts')),
            db: Session = Depends(get_db)):
    """Draft a ticket for one time or calendar change. A person approves it before anything is written."""
    if v.kind not in TIME_TYPES:
        raise HTTPException(400, 'Unknown kind of time change')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))


class TimerStart(BaseModel):
    task_id: int | None = None
    activity: str = ''


def _running(db, user):
    return db.scalar(select(TimerRun).where(TimerRun.user_id == user.id, TimerRun.stopped_at.is_(None), TimerRun.discarded.is_(False)))


def _naive_utc(value):
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None) if value.tzinfo else value


@router.get('/timer')
def timer(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _running(db, user)
    if not t:
        return {'running': False}
    return {'running': True, 'task_id': t.task_id, 'activity': t.activity, 'started_at': t.started_at.isoformat()}


@router.post('/timer/start')
def timer_start(v: TimerStart, user: User = Depends(permit('admin', 'manager', 'architect', 'site_engineer')),
                db: Session = Depends(get_db)):
    if _running(db, user):
        raise HTTPException(400, 'A timer is already running; stop or discard it first')
    if bool(v.task_id) == bool(v.activity.strip()):
        raise HTTPException(400, 'Start the timer on one task or one named general activity')
    if v.task_id:
        t = db.get(Task, v.task_id)
        if not t or t.deleted_at or not can_access_project(db, user, t.project_id):
            raise HTTPException(404, 'Task not found')
    db.add(TimerRun(user_id=user.id, task_id=v.task_id, activity=v.activity.strip()))
    db.commit()
    return {'running': True}


@router.post('/timer/discard')
def timer_discard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _running(db, user)
    if not t:
        raise HTTPException(400, 'No timer is running')
    t.discarded = True
    db.commit()
    return {'running': False}


@router.post('/timer/stop')
def timer_stop(user: User = Depends(permit('admin', 'manager', 'architect', 'site_engineer')), db: Session = Depends(get_db)):
    """Stopping drafts a time entry ticket from the elapsed time. Nothing is recorded until it is approved."""
    t = _running(db, user)
    if not t:
        raise HTTPException(400, 'No timer is running')
    started_utc = _naive_utc(t.started_at)
    minutes = max(1, round((dt.datetime.utcnow() - started_utc).total_seconds() / 60))
    work_date = (started_utc + dt.timedelta(minutes=STUDIO_UTC_OFFSET_MINUTES)).date().isoformat()
    data = {'work_date': work_date, 'minutes': minutes, 'source': 'timer'}
    data.update({'task_id': t.task_id} if t.task_id else {'activity': t.activity})
    from .main import _manual_draft
    try:
        draft = _manual_draft(db, user, 'time_log', data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    t = _running(db, user)
    t.stopped_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {**draft, 'minutes': minutes}
