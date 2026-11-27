"""The sectioned morning and evening summaries (the owner's headings). This module only reads: it gathers each section's lines for one
person from what StudioOS already holds, and rhythm_core turns them into text. Money sections are built only for roles that may see
money (owner, manager, accounts). Nothing here changes a task, approves anything or sends a message outside the app."""
from __future__ import annotations

import datetime as dt

from collections import defaultdict

from sqlalchemy import func, select

from . import rhythm_core as core
from .db import ApprovalTicket, ApprovalTicketItem, FlexibleRecord, GLJournal, GLLine, SiteReport, Task
from .security import APPROVERS, FINANCE_READ
from .time_rules import STUDIO_UTC_OFFSET_MINUTES

PURCHASE_AND_PAYMENT_LABELS = {
    'finance_po': 'purchase order', 'finance_bill': 'supplier bill', 'finance_direct_bill': 'supplier bill',
    'finance_inventory_bill': 'supplier bill', 'finance_expense': 'expense', 'finance_payment': 'supplier payment',
    'finance_direct_bill_payment': 'supplier payment', 'finance_advance': 'supplier advance',
    'finance_reimburse_staff': 'staff reimbursement',
}


def _rupees(paise):
    return 'Rs ' + format(round(int(paise or 0) / 100, 2), ',.2f').rstrip('0').rstrip('.')


def _names(user):
    return {n for n in (user.display_name, user.username) if n}


def _local_date(moment):
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return (moment + dt.timedelta(minutes=STUDIO_UTC_OFFSET_MINUTES)).date()


def _mentions(text, names):
    low = str(text or '').casefold()
    return any(n.casefold() in low for n in names)


def _meetings(db, user, today):
    """Meetings today, and follow-ups from the last 7 days, from the Work pack's meeting notes that name this person."""
    names = _names(user)
    meetings, follow = [], []
    for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'meeting_note', FlexibleRecord.deleted_at.is_(None))):
        d = r.data or {}
        when = str(d.get('meeting_date') or '')
        if not _mentions(d.get('attendees'), names):
            continue
        if when == today.isoformat():
            meetings.append(f"{d.get('meeting_type') or 'Meeting'} today" + (f": {d['decisions']}"[:80] if d.get('decisions') else ''))
        elif when and today - dt.timedelta(days=7) <= dt.date.fromisoformat(when) < today and d.get('next_steps'):
            follow.append(f"follow up from {when}: {str(d['next_steps'])[:80]}")
    return meetings + follow


def _pending_tickets(db):
    ids = db.scalars(select(ApprovalTicketItem.ticket_id).where(ApprovalTicketItem.status == 'pending').distinct()).all()
    rows = db.scalars(select(ApprovalTicket).where(ApprovalTicket.id.in_(ids), ApprovalTicket.status.notin_(['committed', 'reversed']))
                      .order_by(ApprovalTicket.id)).all() if ids else []
    return [f"ticket #{t.id}: {(t.summary or 'waiting for a decision')[:80]}" for t in rows]


def _pending_money(db):
    grouped = defaultdict(list)
    rows = db.execute(select(ApprovalTicketItem.item_type, ApprovalTicketItem.after_data).join(ApprovalTicket).where(
        ApprovalTicket.status.in_(('draft', 'in_review')), ApprovalTicketItem.status == 'pending',
        ApprovalTicketItem.item_type.in_(PURCHASE_AND_PAYMENT_LABELS),
    ))
    for kind, data in rows:
        grouped[PURCHASE_AND_PAYMENT_LABELS[kind]].append(data.get('amount_paise'))
    return [f'{len(amounts)} {label}{"s" if len(amounts) != 1 else ""} waiting for approval'
            + (f', {_rupees(sum(amounts))}' if all(type(amount) is int and amount > 0 for amount in amounts) else '')
            for label, amounts in sorted(grouped.items())]


def morning_sections(db, user, today, todos):
    urgent = core.urgent(todos, today)
    urgent_ids = {(i['reason'], i.get('task_id'), i.get('snag_id')) for i in urgent}
    rest = [i for i in todos if (i['reason'], i.get('task_id'), i.get('snag_id')) not in urgent_ids]
    s = {
        'Urgent & Critical Issues': [core.item_line(i) for i in urgent],
        "Today's Priorities": [core.item_line(i) for i in rest if i['reason'] in ('due_today', 'ready', 'snag')],
        'Overdue Tasks': [core.item_line(i) for i in rest if i['reason'] == 'overdue'],
        'Meetings & Follow-ups': _meetings(db, user, today),
        'Pending Approvals': _pending_tickets(db)[:20] if user.role in APPROVERS else [],
        'Payments & Purchases': _pending_money(db) if user.role in FINANCE_READ else [],
        'Project Plans & Dependencies': [core.item_line(i) for i in todos if i.get('blocked_by')],
    }
    return s


def _tasks_completed_today(db, user, today):
    names = _names(user)
    out = []
    rows = db.execute(select(ApprovalTicketItem, ApprovalTicket).join(ApprovalTicket, ApprovalTicket.id == ApprovalTicketItem.ticket_id)
                      .where(ApprovalTicketItem.item_type == 'update_task', ApprovalTicket.status.in_(['committed']))).all()
    for item, ticket in rows:
        d = item.after_data or {}
        if d.get('status') != 'done' or _local_date(ticket.committed_at) != today:
            continue
        task = db.get(Task, d.get('id')) if type(d.get('id')) is int else None
        if task and task.assignee in names:
            out.append(f'#{task.id} {task.title}')
    return out


def _decisions_today(db, user, today):
    rows = db.scalars(select(ApprovalTicket).where(ApprovalTicket.status == 'committed').order_by(ApprovalTicket.id)).all()
    out = []
    for t in rows:
        if _local_date(t.committed_at) != today:
            continue
        if user.role in APPROVERS or t.submitter_id == user.id:
            out.append(f"ticket #{t.id} saved: {(t.summary or 'no summary')[:80]}")
    return out


def _money_today(db, today):
    studio_zone = dt.timezone(dt.timedelta(minutes=STUDIO_UTC_OFFSET_MINUTES))
    start = dt.datetime.combine(today, dt.time.min, studio_zone).astimezone(dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    rows = db.execute(select(GLJournal.id, GLJournal.source_event, func.sum(GLLine.amount_paise))
                      .join(GLLine).where(GLJournal.status == 'posted', GLLine.side == 'debit',
                                         GLJournal.posted_at >= start, GLJournal.posted_at < end)
                      .group_by(GLJournal.id, GLJournal.source_event).order_by(GLJournal.id))
    return [f'{event.replace("_", " ").capitalize()} #{journal_id}: {_rupees(amount)}'
            for journal_id, event, amount in rows]


def _progress(db, user, today, healths):
    names = _names(user)
    mine = {t.project_id for t in db.scalars(select(Task).where(Task.assignee.in_(names), Task.deleted_at.is_(None)))}
    reports = {}
    for r in db.scalars(select(SiteReport).where(SiteReport.deleted_at.is_(None))):
        if (r.report_date or (_local_date(r.created_at) or today).isoformat()) == today.isoformat():
            reports[r.project_id] = reports.get(r.project_id, 0) + 1
    out = []
    for h in healths:
        if user.role in APPROVERS or h['project_id'] in mine:
            extra = f", {reports[h['project_id']]} site report(s) today" if reports.get(h['project_id']) else ''
            out.append(f"{h['project']}: {h['status'].replace('_', ' ')}{extra}")
    return out


def evening_sections(db, user, today, todos, healths):
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    names = _names(user)
    tomorrow_tasks = db.scalars(select(Task).where(Task.assignee.in_(names), Task.deleted_at.is_(None), Task.due_date == tomorrow,
                                                   Task.status.notin_(core.CLOSED))).all()
    tomorrow_lines = [f"#{t.id} {t.title}" for t in tomorrow_tasks]
    tomorrow_lines += [core.item_line(i) for i in todos if i['reason'] == 'snag' and i.get('due') == tomorrow]
    return {
        'Critical Unresolved Issues': [core.item_line(i) for i in core.urgent(todos, today)],
        'Tasks Completed': _tasks_completed_today(db, user, today),
        'Pending & Overdue Tasks': [core.item_line(i) for i in todos if i['reason'] in ('overdue', 'due_today')],
        'Project & Site Progress': _progress(db, user, today, healths),
        'Decisions & Approvals': _decisions_today(db, user, today),
        'Financial Transactions': _money_today(db, today) if user.role in FINANCE_READ else [],
        "Tomorrow's Priorities": tomorrow_lines,
    }
