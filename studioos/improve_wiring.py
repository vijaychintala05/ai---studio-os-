"""v0.15.0 self-improvement connected to the database (thin; the logic is in improve_core).

Jobs (run by the server-side scheduler, or by an Admin on the Self-check screen):
  daily_rules       the v0.10.0 daily rules, now also proposing tickets when a rule says so
  email_poll        the v0.14.0 mailbox, when it is set up
  summaries_daily / summaries_weekly   summaries per person, built with that person's access
  suggestions       at most 5 suggestions a week, with evidence
Nothing a job does writes business data: notices, summaries and suggestions are records about the
system, and every change is a ticket a person approves.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import threading
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import graph_query as gq
from . import improve_core as IM
from . import universal_engine as u
from .db import (ApprovalTicket, AskedQuestion, ChatMessage, ChatSession, Config, FlexibleRecord, ImproveSuggestion, IntakeItem,
                 JobRun, Project, RecordType, SessionLocal, SummaryDelivery, UniversalRecordRevision, UniversalReport,
                 UniversalViewDefinition, UniversalWorkflow, UniversalWorkflowNotice, User, add_audit, now)

LOCK_KEY = 'scheduler_lock'


# ------------------------------------------------------------------ proposals made by the system

def _system_user(db: Session):
    """Proposals made by jobs are submitted in the name of the first active Admin (they still need
    an approval; the ticket says which rule or suggestion made them)."""
    return db.scalar(select(User).where(User.role == 'admin', User.active.is_(True)).order_by(User.id).limit(1))


def propose(db: Session, kind: str, data: dict, evidence: str, user=None):
    from .tickets import add_proposal, validate_item
    user = user or _system_user(db)
    if user is None:
        raise ValueError('No active Admin to submit the proposal')
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, pending=None)
    db.add(session)
    db.flush()
    msg = ChatMessage(session_id=session.id, user_id=user.id, speaker='user', content=evidence[:2000])
    db.add(msg)
    db.flush()
    ticket, item = add_proposal(db, session, kind, data, msg.id, provider='rules')
    validate_item(db, item)
    item.flags = list(dict.fromkeys(list(item.flags or []) + ['Proposed by StudioOS itself: check it like any other draft']))
    return ticket


# ------------------------------------------------------------------ rules that propose

def validate_rule_action(db: Session, d: dict):
    """Called from universal_engine.validate_workflow for actions other than 'notify'."""
    rt = db.get(RecordType, d['type_key'])
    if d.get('event') != 'daily':
        raise ValueError('Rules that propose run in the daily check only')
    types = {k: {'title': t.title, 'fields': t.design['runtime_fields']} for k, t in gq.universal_types(db).items()}
    try:
        return IM.check_rule_action(d['action'], {f['name']: f for f in rt.design['runtime_fields']}, types)
    except IM.G.GraphError as ex:
        raise ValueError(str(ex)) from None


def rule_proposal(db: Session, workflow, rec, version: int, today: dt.date):
    action = (workflow.definition or {}).get('action')
    if not isinstance(action, dict):
        return None
    project = db.get(Project, rec.project_id) if rec.project_id else None
    p = IM.rule_proposal(action, {'id': rec.id, 'type': rec.record_type, 'data': dict(rec.data or {}), 'version': version,
                                  'project_id': rec.project_id, 'project_name': project.name if project else ''}, today)
    if p is None or (p['kind'] == 'create_task' and not p['data']['project']):
        return None
    try:
        return propose(db, p['kind'], p['data'], f'Rule "{workflow.key}" matched record #{rec.id} on {today.isoformat()}')
    except ValueError as ex:
        # v0.15.1: a rule that cannot make its proposal says why (the daily check still goes on).
        import logging
        logging.getLogger('studioos').warning('rule %s could not propose for record #%s: %s', workflow.key, rec.id, ex)
        return None


# ------------------------------------------------------------------ suggestions

def _types_and_records(db: Session):
    types = {k: {'title': t.title, 'fields': t.design['runtime_fields'], 'label_field': t.design.get('label_field')}
             for k, t in gq.universal_types(db).items()}
    recs = [{'id': r.id, 'type': r.record_type, 'data': r.data or {}} for r in db.scalars(
        select(FlexibleRecord).where(FlexibleRecord.record_type.in_(list(types) or ['-']), FlexibleRecord.deleted_at.is_(None))
        .order_by(FlexibleRecord.id.desc()).limit(20000))]
    return types, recs


def _without_blocked_hides(db: Session, cands: list[dict]) -> list[dict]:
    """Do not suggest hiding a field that a report, view or rule still uses: approving that change would be refused."""
    if not any(c['kind'] == 'hide_empty_field' for c in cands):
        return cands
    from . import restructure_core as RC
    from . import restructure_wiring as RW
    world = RW.build_world(db)
    keep = []
    for c in cands:
        if c['kind'] == 'hide_empty_field':
            try:
                if RC.plan(c['proposal']['data'], world, u._today())['blockers']:
                    continue
            except (RC.ChangeError, ValueError):
                continue
        keep.append(c)
    return keep


def make_suggestions(db: Session, today: dt.date) -> list[ImproveSuggestion]:
    from . import ai_wiring
    from .ai_learning import alias_suggestions
    types, recs = _types_and_records(db)
    since = dt.datetime.combine(today - dt.timedelta(days=28), dt.time(), tzinfo=dt.timezone.utc)
    questions = [{'text': q.text, 'report': q.report} for q in db.scalars(select(AskedQuestion).where(AskedQuestion.created_at >= since))]
    saved = [r.title for r in db.scalars(select(UniversalReport))]
    cands = (IM.note_field_suggestions(types, recs) + IM.empty_field_suggestions(types, recs) +
             IM.question_suggestions(questions, saved) +
             IM.alias_suggestions(alias_suggestions(ai_wiring.correction_rows(db, None, 2000), existing=ai_wiring.approved_aliases(db), options=ai_wiring.option_map(db))))
    cands = _without_blocked_hides(db, cands)
    known = {s.fingerprint: s.status for s in db.scalars(select(ImproveSuggestion))}
    week = today - dt.timedelta(days=today.weekday())
    this_week = db.scalar(select(func.count()).select_from(ImproveSuggestion).where(ImproveSuggestion.week == week.isoformat())) or 0
    picked = IM.weekly_suggestions(cands, dismissed=frozenset(f for f, s in known.items() if s == 'dismissed'),
                                   already=frozenset(known), limit=max(0, IM.MAX_PER_WEEK - this_week))
    rows = []
    for c in picked:
        row = ImproveSuggestion(fingerprint=c['fingerprint'], kind=c['kind'], title=c['title'][:300], evidence=c['evidence'],
                                proposal=c['proposal'], week=week.isoformat())
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def accept_suggestion(db: Session, user, sid: int):
    s = db.get(ImproveSuggestion, sid)
    if not s or s.status != 'open':
        raise ValueError('Suggestion not open')
    ticket = propose(db, s.proposal['kind'], s.proposal['data'], f'Suggestion: {s.title}', user)
    s.status, s.ticket_id, s.decided_by = 'proposed', ticket.id, user.username
    add_audit(db, 'suggestion_accepted', 'improve_suggestion', s.id, f'Suggestion proposed as ticket #{ticket.id}', actor=user.username)
    return ticket


def dismiss_suggestion(db: Session, user, sid: int):
    s = db.get(ImproveSuggestion, sid)
    if not s or s.status != 'open':
        raise ValueError('Suggestion not open')
    s.status, s.decided_by = 'dismissed', user.username
    add_audit(db, 'suggestion_dismissed', 'improve_suggestion', s.id, 'Suggestion dismissed (it will not come back)', actor=user.username)


def log_question(db: Session, user, text: str, report: dict | None):
    db.add(AskedQuestion(user_id=getattr(user, 'id', None), text=str(text)[:300], report=report))


# ------------------------------------------------------------------ summaries

def validate_summary(db: Session, d: dict):
    try:
        return IM.check_summary(d, {r.key for r in db.scalars(select(UniversalReport))})
    except IM.G.GraphError as ex:
        raise ValueError(str(ex)) from None


def apply_summary(db: Session, item, actor):
    d = validate_summary(db, item.after_data or {})
    version = int(db.scalar(select(func.coalesce(func.max(UniversalViewDefinition.version), 0))
                            .where(UniversalViewDefinition.kind == 'summary', UniversalViewDefinition.key == d['key'])) or 0) + 1
    row = UniversalViewDefinition(kind='summary', key=d['key'], version=version, definition=dict(d), ticket_id=item.ticket_id)
    db.add(row)
    db.flush()
    add_audit(db, 'universal_summary', 'universal_view_definition', row.id, f'Ticket #{item.ticket_id} saved summary {d["key"]}', actor=actor)
    return {'type': 'universal_summary', 'id': row.id, 'item_id': item.id}


def send_summaries(db: Session, every: str, today: dt.date, senders=None) -> int:
    from .views_wiring import latest
    senders = senders or {'email': IM.SmtpSender(), 'whatsapp': IM.NoSender()}
    period = today.isoformat() if every == 'day' else (today - dt.timedelta(days=today.weekday())).isoformat()
    users = [{'id': x.id, 'role': x.role, 'active': x.active, 'name': x.display_name or x.username, 'username': x.username}
             for x in db.scalars(select(User))]
    contacts = _contacts(db)
    made = 0
    for d in latest(db, 'summary').values():
        if d.get('every') != every:
            continue
        for person in IM.recipients(d, users):
            if db.scalar(select(SummaryDelivery.id).where(SummaryDelivery.summary_key == d['key'], SummaryDelivery.user_id == person['id'],
                                                          SummaryDelivery.period == period)):
                continue
            me = db.get(User, person['id'])
            results = []
            for key in d['reports']:
                rep = db.get(UniversalReport, key)
                try:
                    results.append(gq.run_report(db, me, gq.report_definition(db, rep)) if rep else {'title': key, 'error': 'missing'})
                except ValueError as ex:
                    results.append({'title': rep.title if rep else key, 'error': str(ex)})
            text = IM.summary_text(d['title'], person['name'], results, today)
            channels = {'in_app': 'kept'}
            for ch in d['channels']:
                if ch == 'in_app':
                    continue
                to = contacts.get(person['id'], {}).get(ch)
                sender = senders.get(ch)
                if not to or sender is None or not sender.configured():
                    channels[ch] = 'not set up'
                    continue
                try:
                    sender.send(to, d['title'], text)
                    channels[ch] = 'sent'
                except Exception:
                    channels[ch] = 'failed'
            db.add(SummaryDelivery(summary_key=d['key'], user_id=person['id'], period=period, text=text, channels=channels))
            made += 1
    db.flush()
    return made


def _contacts(db: Session) -> dict:
    """Staff e-mail / phone for summaries: the employee profile's work phone and addresses the Admin
    added for the inbox (v0.14.0)."""
    from .intake_wiring import known_senders
    from .intake_core import email_key, phone_key
    out = {}
    for k in known_senders(db):
        if k.get('kind') != 'staff':
            continue
        c = out.setdefault(k['id'], {})
        if email_key(k['address']):
            c.setdefault('email', email_key(k['address']))
        if phone_key(k['address']):
            c.setdefault('whatsapp', phone_key(k['address']))
    return out


def my_summaries(db: Session, user, limit: int = 20) -> list[dict]:
    return [{'id': s.id, 'summary': s.summary_key, 'period': s.period, 'text': s.text, 'channels': s.channels,
             'at': s.created_at.isoformat() if s.created_at else None}
            for s in db.scalars(select(SummaryDelivery).where(SummaryDelivery.user_id == user.id)
                                .order_by(SummaryDelivery.id.desc()).limit(limit))]


# ------------------------------------------------------------------ weekly review draft

def review_draft(db: Session, user, employee_id: int, week_start: dt.date):
    """Manager or Admin: a weekly_review draft (ticket) with the checked facts of the week."""
    if user.role not in ('admin', 'manager'):
        raise ValueError('Only a manager or the Admin prepares reviews')
    if not db.get(RecordType, 'weekly_review'):
        raise ValueError('Install the People pack first')
    emp = db.get(User, employee_id)
    if not emp or not emp.active:
        raise ValueError('Staff member not found')
    get = lambda t: [{'data': r.data or {}} for r in db.scalars(select(FlexibleRecord).where(
        FlexibleRecord.record_type == t, FlexibleRecord.deleted_at.is_(None)).limit(20000))]
    facts = IM.review_facts(employee_id, week_start, get('attendance_entry'), get('timesheet_entry'), get('work_issue'),
                            get('sop_run'), u._today())
    values = IM.review_draft_values(employee_id, user.id, week_start, facts)
    ticket = propose(db, 'metadata_record', {'type_key': 'weekly_review', 'project_id': None, 'values': values},
                     f'Weekly review draft for {emp.display_name or emp.username}, week of {week_start.isoformat()} (facts only)', user)
    return ticket, facts


# ------------------------------------------------------------------ jobs and the scheduler

def _run_job(db: Session, job: str, today: dt.date) -> str:
    if job == 'daily_rules':
        return f'{gq.maybe_run_daily_rules(db)} notice(s)'
    if job == 'email_poll':
        from .intake_core import ImapMailbox
        from .intake_wiring import email_poll
        box = ImapMailbox()
        if not box.configured():
            return 'mailbox not set up'
        return f'{len(email_poll(db, box))} item(s)'
    if job in ('summaries_daily', 'summaries_weekly'):
        return f'{send_summaries(db, "day" if job == "summaries_daily" else "week", today)} summary(ies)'
    if job == 'suggestions':
        return f'{len(make_suggestions(db, today))} suggestion(s)'
    raise ValueError('Unknown job')


def run_job(job: str, today: dt.date | None = None) -> dict:
    today = today or u._today()
    with SessionLocal() as db:
        db.info['write_source'] = f'job:{job}'
        run = JobRun(job=job)
        db.add(run)
        db.commit()
        try:
            detail, outcome = _run_job(db, job, today), 'ok'
            db.commit()
        except Exception as ex:          # recorded; the next run tries again
            db.rollback()
            detail, outcome = str(ex)[:400], 'failed'
        run = db.get(JobRun, run.id)
        run.finished_at, run.outcome, run.detail = now(), outcome, detail
        db.commit()
        return {'job': job, 'outcome': outcome, 'detail': detail}


def last_runs(db: Session) -> dict:
    out = {}
    for job, at in db.execute(select(JobRun.job, func.max(JobRun.finished_at)).where(JobRun.outcome == 'ok').group_by(JobRun.job)):
        if at is not None:
            out[job] = at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)
    return out


def _take_lock(db: Session, holder: str, ttl: int = 600) -> bool:
    """One scheduler at a time across processes (a row in the settings table with an expiry)."""
    from sqlalchemy import update

    row = db.get(Config, LOCK_KEY)
    t = now().timestamp()
    if row is not None:
        try:
            who, until = row.value.split('|')
            if who != holder and float(until) > t:
                return False
        except ValueError:
            pass
        value = f'{holder}|{t + ttl}'
        claimed = db.execute(update(Config).where(Config.key == LOCK_KEY, Config.value == row.value)
                             .values(value_text=value, _legacy_value=value)
                             .execution_options(synchronize_session=False)).rowcount
        if claimed != 1:
            db.rollback()
            return False
    else:
        db.add(Config(key=LOCK_KEY, value=f'{holder}|{t + ttl}'))
    try:
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


def tick(holder: str, local_now: dt.datetime | None = None) -> list[dict]:
    """One scheduler pass: run every due job (local time from STUDIOOS_TZ_OFFSET_MINUTES, default IST)."""
    offset = int(os.getenv('STUDIOOS_TZ_OFFSET_MINUTES', '330'))
    local_now = local_now or (now() + dt.timedelta(minutes=offset)).replace(tzinfo=None)
    with SessionLocal() as db:
        if not _take_lock(db, holder):
            return []
        runs = {k: (v + dt.timedelta(minutes=offset)).replace(tzinfo=None) for k, v in last_runs(db).items()}
    done = [run_job(job, local_now.date()) for job in IM.due_jobs(local_now, runs, int(os.getenv('STUDIOOS_JOBS_HOUR', '7')))]
    from . import rhythm   # v0.19: the morning list (8:30) and the owner's project summary, never in quiet hours
    return done + [rhythm.run_job(job, local_now.date()) for job in rhythm.due_jobs(local_now, runs)]


_THREAD = None
_STOP_SCHEDULER = None


def start_scheduler():
    """A daemon thread, every 5 minutes. Off when STUDIOOS_SCHEDULER=off (tests set it off)."""
    global _THREAD, _STOP_SCHEDULER
    if os.getenv('STUDIOOS_SCHEDULER', 'on').casefold() == 'off' or (_THREAD and _THREAD.is_alive()):
        return None
    interval=300
    if os.getenv('STUDIOOS_ENV')=='test' and os.getenv('STUDIOOS_SIMULATION_CLOCK'):
        interval=max(1,min(300,int(os.getenv('STUDIOOS_SIMULATION_POLL_SECONDS','1'))))
    holder = f'{os.getpid()}-{uuid.uuid4().hex[:6]}'
    stopped = threading.Event()

    def loop():
        if stopped.wait(min(30,interval)):
            return
        while not stopped.is_set():
            try:
                tick(holder)
            except Exception as ex:   # never let the thread die
                print('StudioOS scheduler:', str(ex)[:200])
            stopped.wait(interval)
    _STOP_SCHEDULER = stopped
    _THREAD = threading.Thread(target=loop, name='studioos-scheduler', daemon=True)
    _THREAD.start()
    return _THREAD


def stop_scheduler():
    if _STOP_SCHEDULER is not None:
        _STOP_SCHEDULER.set()
        _THREAD.join(timeout=2)


# ------------------------------------------------------------------ self-check

def health(db: Session) -> dict:
    from . import ai_wiring
    from .data_safety import health as safety, read_status
    from .intake_core import ImapMailbox, TesseractOcr
    from .migrations import LATEST_VERSION
    from .db import SchemaMigration
    t = now()
    waiting = db.scalars(select(ApprovalTicket).where(ApprovalTicket.status.not_in(('committed', 'reversed')))).all()
    old = [x for x in waiting if x.created_at and (t - (x.created_at if x.created_at.tzinfo else x.created_at.replace(tzinfo=dt.timezone.utc))).days >= 3]
    try:
        free = shutil.disk_usage(os.getenv('FILES_PATH') or '.').free // (1024 * 1024)
    except OSError:
        free = None
    try:
        b = safety(read_status())
        worst = next((c for c in b.get('checks', []) if c['level'] != 'ok'), None)
        backup = {'overall': b.get('overall'), 'summary': (worst or {}).get('title') or 'Backups and restore tests are up to date'}
    except Exception:
        backup = {}
    week_ago = t - dt.timedelta(days=7)
    facts = {'schema_version': db.scalar(select(func.max(SchemaMigration.version))), 'latest_version': LATEST_VERSION,
             'backup': backup, 'job_runs': last_runs(db), 'email_configured': ImapMailbox().configured(),
             'job_failures': db.scalar(select(func.count()).select_from(JobRun).where(JobRun.outcome == 'failed', JobRun.started_at >= week_ago)) or 0,
             'tickets_waiting': len(waiting), 'tickets_waiting_over_3_days': len(old),
             'quarantined': db.scalar(select(func.count()).select_from(IntakeItem).where(IntakeItem.status == 'quarantined')) or 0,
             'ai': ai_wiring.gateway(db).status(), 'disk_free_mb': free, 'ocr': TesseractOcr().available(),
             'open_suggestions': db.scalar(select(func.count()).select_from(ImproveSuggestion).where(ImproveSuggestion.status == 'open')) or 0}
    checks = IM.health(facts, t)
    fails = [{'job': r.job, 'at': r.started_at.isoformat() if r.started_at else None, 'detail': r.detail}
             for r in db.scalars(select(JobRun).where(JobRun.outcome == 'failed').order_by(JobRun.id.desc()).limit(10))]
    return {'checks': checks, 'failures': fails, 'overall': 'fail' if any(c['level'] == 'fail' for c in checks) else
            ('warn' if any(c['level'] == 'warn' for c in checks) else 'ok')}
