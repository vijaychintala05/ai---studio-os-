"""v0.19 daily rhythm on the scheduler: the morning to-do list for each person and the owner's project summary.

Both are facts built from dates and dependencies (see rhythm_core.py). They are kept in each person's in-app summaries
(SummaryDelivery) and are sent nowhere else: no WhatsApp or e-mail channel is switched on here. Nothing in this module
changes a task, lifts a block or approves anything.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from . import rhythm_core as core
from .db import FlexibleRecord, JobRun, Project, SessionLocal, SummaryDelivery, Task, User, now
from .work_rules import active_links

JOBS = {'rhythm_morning': (core.MORNING_HOUR, core.MORNING_MINUTE), 'rhythm_owner': (core.OWNER_HOUR, core.OWNER_MINUTE)}


def _status_map(db, ids):
    return {t.id: ('deleted' if t.deleted_at else t.status) for t in db.scalars(select(Task).where(Task.id.in_(list(ids))))}


def person_todos(db, user, today):
    names = {n for n in (user.display_name, user.username) if n}
    rows = db.execute(select(Task, Project.name).join(Project, Project.id == Task.project_id)
                      .where(Task.assignee.in_(names), Task.deleted_at.is_(None), Task.status.notin_(core.CLOSED),
                             Project.deleted_at.is_(None))).all()
    tasks = [{'id': t.id, 'title': t.title, 'due': t.due_date, 'project': p} for t, p in rows]
    ids = {t['id'] for t in tasks}
    links = active_links(db, ids)
    status_of = _status_map(db, ids | {l['predecessor_id'] for l in links})
    todos = core.morning_todos(tasks, links, status_of, today)
    snags = db.execute(select(FlexibleRecord, Project.name).outerjoin(Project, Project.id == FlexibleRecord.project_id)
                       .where(FlexibleRecord.record_type == core.SNAG_TYPE, FlexibleRecord.deleted_at.is_(None))).all()
    return todos + core.snag_items([{'id': r.id, 'data': r.data, 'project': p or ''} for r, p in snags], user.id, today)


def project_healths(db, today):
    out = []
    for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.id)):
        rows = db.scalars(select(Task).where(Task.project_id == p.id, Task.deleted_at.is_(None))).all()
        tasks = [{'id': t.id, 'title': t.title, 'due': t.due_date, 'status': t.status} for t in rows]
        links = active_links(db, {t['id'] for t in tasks})
        out.append({'project_id': p.id, 'project': p.name, **core.project_health(tasks, links, today)})
    return out


def _deliver(db, key, user_id, period, text):
    if db.scalar(select(SummaryDelivery.id).where(SummaryDelivery.summary_key == key, SummaryDelivery.user_id == user_id,
                                                  SummaryDelivery.period == period)):
        return 0
    db.add(SummaryDelivery(summary_key=key, user_id=user_id, period=period, text=text, channels={'in_app': 'kept'}))
    return 1


def run_morning(db, today):
    made = 0
    for u in db.scalars(select(User).where(User.active.is_(True), User.role != 'viewer')):
        items = person_todos(db, u, today)
        if items:
            made += _deliver(db, 'rhythm_morning', u.id, today.isoformat(), core.morning_text(u.display_name or u.username, items, today))
    return made


def run_owner(db, today):
    made = 0
    admins = db.scalars(select(User).where(User.active.is_(True), User.role == 'admin')).all()
    for h in project_healths(db, today):
        text = core.owner_text(h['project'], h, today)
        for a in admins:
            made += _deliver(db, f"rhythm_owner_p{h['project_id']}", a.id, today.isoformat(), text)
    return made


def _run(db, job, today):
    return f'{(run_morning if job == "rhythm_morning" else run_owner)(db, today)} message(s) kept'


def run_job(job, today):
    if job not in JOBS:
        raise ValueError('Unknown job')
    with SessionLocal() as db:
        db.info['write_source'] = f'job:{job}'
        run = JobRun(job=job)
        db.add(run)
        db.commit()
        try:
            detail, outcome = _run(db, job, today), 'ok'
            db.commit()
        except Exception as ex:          # recorded; the next run tries again
            db.rollback()
            detail, outcome = str(ex)[:400], 'failed'
        run = db.get(JobRun, run.id)
        run.finished_at, run.outcome, run.detail = now(), outcome, detail
        db.commit()
        return {'job': job, 'outcome': outcome, 'detail': detail}


def due_jobs(local_now, runs):
    """runs: {job: naive local datetime of the last finished run}."""
    return [j for j, t in JOBS.items() if core.job_due(t, runs[j].date() if runs.get(j) else None, local_now)]
