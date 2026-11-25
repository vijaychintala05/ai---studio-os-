"""Home, by role (App Flows map): what each person sees first. Widgets are built from what StudioOS already holds and each person only gets
the widgets their role allows (site engineers get no money widget, only the owner and accounts get Cash and bank). Read-only; a widget
is either a figure (kind 'metric') or a short list (kind 'list') whose rows can open a screen.
Owner: approvals, project health, urgent snags, money waiting for a second approval, cash and bank, today's meetings.
Manager: approvals, projects at risk, overdue tasks, site reports today. Architect: my tasks, tasks this week, snags on my projects.
Site engineer: Today, snags to fix, today's site report. Accounts: payments and costs to approve, vendor balances, cash and bank, unmatched payments."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import rhythm
from .access import visible_project_ids
from .books_routes import BOOKS_ROLES, bank_balance_rows, bill_rows, legacy_payable_rows, unmatched_payment_totals
from .db import (ApprovalTicket, ApprovalTicketItem, Cost, FlexibleRecord, Payment, Project, SiteReport, Task, User)
from .deps import get_db
from .security import current_user

router = APIRouter(prefix='/api/home', tags=['Home'])

SNAG_CLOSED = {'resolved', 'closed', 'verified', 'fixed'}
WIDGETS = {
    'admin': ('client_activity', 'approvals', 'project_health', 'snags_urgent', 'money_waiting', 'cash_bank', 'meetings_today'),
    'manager': ('client_activity', 'approvals', 'projects_at_risk', 'tasks_overdue', 'site_today'),
    'architect': ('client_activity', 'my_tasks', 'tasks_week', 'snags_mine'),
    'site_engineer': ('my_tasks', 'snags_mine', 'site_report_today'),
    'accounts': ('money_waiting', 'vendor_balances', 'cash_bank', 'unmatched_payments'),
    'viewer': ('project_health',),
}


def _today():
    from . import universal_engine as u
    return u._today()


def _names(user):
    return {n for n in (user.display_name, user.username) if n}


def metric(key, title, value, detail='', tone='', screen=''):
    return {'key': key, 'title': title, 'kind': 'metric', 'value': value, 'detail': detail, 'tone': tone, 'screen': screen}


def listing(key, title, rows, empty='Nothing.', screen=''):
    return {'key': key, 'title': title, 'kind': 'list', 'rows': rows[:6], 'more': max(0, len(rows) - 6), 'empty': empty, 'screen': screen}


def _approvals(db):
    ids = db.scalars(select(ApprovalTicketItem.ticket_id).where(ApprovalTicketItem.status == 'pending').distinct()).all()
    rows = db.scalars(select(ApprovalTicket).where(ApprovalTicket.id.in_(ids or [-1]), ApprovalTicket.status.notin_(['committed', 'reversed'])).order_by(ApprovalTicket.id)).all()
    return [{'label': f"Ticket #{t.id}: {(t.summary or 'waiting for a decision')[:70]}"} for t in rows]


def _cash(db):
    banks = bank_balance_rows(db).all()
    return sum(int(row.balance_paise) for row in banks), bool(banks)


def _snags(db, allowed, owner_names=None):
    out = []
    for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'work_issue', FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id.desc())):
        d = r.data or {}
        if str(d.get('issue_status', '')).casefold() in SNAG_CLOSED or (allowed is not None and r.project_id not in allowed):
            continue
        out.append((r, d))
    return out


def build(db, user, today):
    allowed = visible_project_ids(db, user)
    widgets = WIDGETS.get(user.role, WIDGETS['viewer'])
    names = _names(user)
    todos = rhythm.person_todos(db, user, today) if 'my_tasks' in widgets else []
    tomorrow_week = (today + dt.timedelta(days=7)).isoformat()
    health = rhythm.project_healths(db, today) if {'project_health','projects_at_risk'}.intersection(widgets) else []
    if allowed is not None:
        health = [h for h in health if h['project_id'] in allowed]
    out = {}
    out['approvals'] = lambda: (lambda rows: metric('approvals', 'Approvals waiting', len(rows), '; '.join(r['label'] for r in rows[:2]), 'warn' if rows else 'good', 'tickets'))(_approvals(db))
    out['project_health'] = lambda: listing('project_health', 'Projects', [{'label': f"{h['project']}: {h['status'].replace('_', ' ')}", 'tone': {'delayed': 'critical', 'at_risk': 'warn'}.get(h['status'], 'good')} for h in health], 'No projects yet.', 'projects')
    out['projects_at_risk'] = lambda: listing('projects_at_risk', 'Projects at risk', [{'label': f"{h['project']}: {h['status'].replace('_', ' ')}", 'tone': 'critical' if h['status'] == 'delayed' else 'warn'} for h in health if h['status'] != 'on_track'], 'Every project is on track.', 'projects')
    pnames, overdue = {}, []
    if 'tasks_overdue' in widgets:
        pnames = {p.id: p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)))}
        overdue = [t for t in db.scalars(select(Task).where(Task.deleted_at.is_(None), Task.status.notin_(['done', 'closed', 'cancelled']), Task.due_date != '', Task.due_date < today.isoformat()).order_by(Task.due_date))
                   if allowed is None or t.project_id in allowed]
    out['tasks_overdue'] = lambda: listing('tasks_overdue', 'Overdue tasks', [{'label': f"#{t.id} {t.title} ({pnames.get(t.project_id, '')}) due {t.due_date}" + (f", {t.assignee}" if t.assignee else ''), 'tone': 'critical'} for t in overdue], 'Nothing overdue.', 'tasks')
    out['my_tasks'] = lambda: listing('my_tasks', 'My tasks today', [{'label': f"#{i['task_id']} {i['title']}: {i['reason'].replace('_', ' ')}", 'tone': 'critical' if i['reason'] == 'overdue' else ''} for i in todos], 'Nothing is due today.', 'today')
    week_query = select(Task).where(Task.assignee.in_(names), Task.deleted_at.is_(None), Task.status.notin_(['done', 'closed', 'cancelled']), Task.due_date >= today.isoformat(), Task.due_date <= tomorrow_week).order_by(Task.due_date)
    if allowed is not None:
        week_query = week_query.where(Task.project_id.in_(allowed))
    week = db.scalars(week_query).all() if names and 'tasks_week' in widgets else []
    out['tasks_week'] = lambda: listing('tasks_week', 'My tasks this week', [{'label': f"{t.title} due {t.due_date}"} for t in week], 'Nothing due this week.', 'tasks')
    snags = _snags(db, allowed) if {'snags_urgent','snags_mine'}.intersection(widgets) else []
    urgent = [(r, d) for r, d in snags if str(d.get('severity', '')).casefold() in ('critical', 'high')]
    out['snags_urgent'] = lambda: metric('snags_urgent', 'Urgent snags', len(urgent), '; '.join(str(d.get('title', 'Snag')) for _, d in urgent[:2]), 'critical' if urgent else 'good', 'projects')
    mine = [(r, d) for r, d in snags if d.get('owner') == user.id]
    out['snags_mine'] = lambda: listing('snags_mine', 'Snags to fix', [{'label': str(d.get('title', 'Snag')), 'project_id': r.project_id, 'tone': 'critical' if str(d.get('severity', '')).casefold() in ('critical', 'high') else ''} for r, d in mine], 'No snags assigned to you.')
    reports = [r for r in db.scalars(select(SiteReport).where(SiteReport.deleted_at.is_(None))) if (allowed is None or r.project_id in allowed) and (r.report_date or (r.created_at.date().isoformat())) == today.isoformat()] if {'site_today','site_report_today'}.intersection(widgets) else []
    out['site_today'] = lambda: metric('site_today', 'Site reports today', len(reports), '', 'good' if reports else '', 'site')
    if 'site_report_today' in widgets:
        from .time_rules import STUDIO_UTC_OFFSET_MINUTES

        offset = dt.timezone(dt.timedelta(minutes=STUDIO_UTC_OFFSET_MINUTES))
        start = dt.datetime.combine(today, dt.time.min, offset).astimezone(dt.timezone.utc)
        pending = db.scalars(select(ApprovalTicketItem).join(ApprovalTicket).where(
            ApprovalTicket.submitter_id == user.id, ApprovalTicketItem.item_type == 'site_update',
            ApprovalTicketItem.status.in_(('pending','approved')),
            ApprovalTicketItem.created_at >= start, ApprovalTicketItem.created_at < start + dt.timedelta(days=1)))
        waiting = any(allowed is None or item.after_data.get('project') in allowed for item in pending)
        label = 'Sent' if reports else 'Waiting for approval' if waiting else 'Not sent yet'
        out['site_report_today'] = lambda: metric('site_report_today', "Today's site report", label, '', 'good' if reports else 'warn', 'site')
    meet = [d for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'meeting_note', FlexibleRecord.deleted_at.is_(None))) if (d := (r.data or {})).get('meeting_date') == today.isoformat()] if 'meetings_today' in widgets else []
    out['meetings_today'] = lambda: listing('meetings_today', "Today's meetings and visits", [{'label': f"{d.get('meeting_type') or 'Meeting'}: {str(d.get('decisions') or d.get('attendees') or '')[:60]}"} for d in meet], 'No meetings recorded for today.')
    money_rows = []
    if user.role in ('admin', 'accounts'):
        pend_costs = db.scalars(select(Cost).where(Cost.status == 'pending', Cost.deleted_at.is_(None))).all()
        pend_pay = db.scalars(select(Payment).where(Payment.status == 'pending', Payment.deleted_at.is_(None))).all()
        money_rows = [x for x in (pend_costs, pend_pay) if x]
        n = len(pend_costs) + len(pend_pay)
        out['money_waiting'] = lambda: metric('money_waiting', 'Money waiting for approval', n, 'costs and payments', 'warn' if n else 'good', 'budget')
    if user.role in BOOKS_ROLES:
        cash, has = _cash(db)
        out['cash_bank'] = lambda: metric('cash_bank', 'Cash and bank', cash, 'From the ledger' if has else 'No bank account registered', '', 'books')
        owed = {}
        for r in bill_rows(db, today) + legacy_payable_rows(db, today):
            if r['owed_paise'] > 0:
                owed[r['supplier_id']] = owed.get(r['supplier_id'], 0) + r['owed_paise']
        from .db import Party
        pn = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_(list(owed) or [-1])))}
        out['vendor_balances'] = lambda: listing('vendor_balances', 'Vendor balances', [{'label': pn.get(k, f'Supplier {k}'), 'amount_paise': v} for k, v in sorted(owed.items(), key=lambda x: -x[1])], 'Nothing owed to suppliers.', 'books')
        unmatched = unmatched_payment_totals(db)['count']
        out['unmatched_payments'] = lambda: metric('unmatched_payments', 'Payments not matched to the bank', unmatched, '', 'warn' if unmatched else 'good', 'books')
    if user.role in ('admin', 'manager', 'architect'):
        from .client_portal_staff import unread_rows
        fresh = unread_rows(db, user, limit=50)
        out['client_activity'] = lambda: listing('client_activity', f'New from clients ({len(fresh)})',
            [{'label': f"{pnames.get(a.project_id, '')}: {a.summary[:70]}", 'tone': 'warn', 'project_id': a.project_id,
              'tab': 'files' if a.kind == 'client_decision' else 'chat'} for a in fresh], 'Nothing new from clients.')
    return out


@router.get('')
def home(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .staff_reimbursements import amount_owed

    today = _today()
    makers = build(db, user, today)
    keys = [k for k in WIDGETS.get(user.role, WIDGETS['viewer']) if k in makers]
    result = {'role': user.role, 'date': today.isoformat(), 'widgets': [makers[k]() for k in keys]}
    owed = amount_owed(db, user.id)
    if owed:
        result['owed_to_you_paise'] = owed
    return result
