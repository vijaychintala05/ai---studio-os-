"""One project's home (App Flows map: Project page): the title block, health, and sections Tasks, Snags, Site, Money, Files and People.
Read-only. A person sees only projects they may access (a project they cannot see is a 404), and only the sections their role allows:
site engineers never see Money; Accounts sees Money only; the other roles see every section. Money is read from approved entries."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import rhythm_core as core
from .access import can_access_project
from .db import Document, FlexibleRecord, Project, ProjectMember, SiteReport, Task, User
from .deps import get_db
from .project_links import project_link_values
from .project_parties import active_contacts, contact_options
from .security import current_user
from .work_rules import active_links

router = APIRouter(prefix='/api/projects', tags=['Project page'])

SECTIONS = ('tasks', 'snags', 'site', 'money', 'files', 'people')
MONEY_ROLES = ('admin', 'manager', 'accounts')
LIMIT = 10
SNAG_CLOSED = {'resolved', 'closed', 'verified', 'fixed'}      # statuses of the Work pack issue record that need no more work


def sections_for(role):
    if role == 'accounts':
        return ['money']
    return [s for s in SECTIONS if s != 'money' or role in MONEY_ROLES]


def _today():
    from . import universal_engine as u
    return u._today()


@router.get('/{project_id}/page')
def project_page(project_id: int, as_role: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p or p.deleted_at or not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')          # not confirming that a project you cannot see exists
    role = user.role
    if as_role:                      # Preview as role (owner only): the same page as another role would see it; nothing is changed
        if user.role != 'admin' or as_role not in ('admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer'):
            raise HTTPException(403, 'Only the owner can preview as another role')
        role = as_role
    allowed = sections_for(role)
    today = _today()
    tasks = db.scalars(select(Task).where(Task.project_id == p.id, Task.deleted_at.is_(None)).order_by(Task.due_date, Task.id)).all()
    rows = [{'id': t.id, 'title': t.title, 'due': t.due_date, 'status': t.status} for t in tasks]
    health = core.project_health(rows, active_links(db, {r['id'] for r in rows}), today)
    open_tasks = [r for r in rows if r['status'] not in core.CLOSED]
    overdue = [r for r in open_tasks if core._date(r['due']) and core._date(r['due']) < today]
    links = project_link_values(db, [project_id], include_company=role in MONEY_ROLES)
    out = {'project': {'id': p.id, 'name': p.name, 'stage': p.stage, 'location': p.location, **links[project_id]},
           'health': {'status': health['status'], 'blocking': health.get('blocking')}, 'sections': allowed, 'data': {}, 'as_role': as_role}
    if 'tasks' in allowed:
        assignee = {t.id: t.assignee for t in tasks}
        out['data']['tasks'] = {'open': len(open_tasks), 'overdue': len(overdue), 'done': len(rows) - len(open_tasks),
                                'items': [{**r, 'assignee': assignee.get(r['id'], ''), 'overdue': r in overdue} for r in (overdue + [x for x in open_tasks if x not in overdue])[:LIMIT]]}
    if 'snags' in allowed:
        snags = [r for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'work_issue', FlexibleRecord.project_id == p.id,
                                                                    FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id.desc()))
                 if str((r.data or {}).get('issue_status', '')).casefold() not in SNAG_CLOSED]
        from .snag_photos import SnagPhoto
        shown = snags[:LIMIT]
        photos = {}
        for ph in db.scalars(select(SnagPhoto).where(SnagPhoto.record_id.in_([r.id for r in shown] or [-1])).order_by(SnagPhoto.id)):
            photos.setdefault(ph.record_id, []).append({'id': ph.id, 'slot': ph.slot, 'url': f'/api/snag-photos/{ph.id}/file'})
        out['data']['snags'] = {'open': len(snags), 'items': [{'id': r.id, 'title': (r.data or {}).get('title', 'Snag'), 'severity': (r.data or {}).get('severity', ''),
                                                              'due': (r.data or {}).get('due_date', ''), 'photos': photos.get(r.id, [])} for r in shown]}
    if 'site' in allowed:
        reports = db.scalars(select(SiteReport).where(SiteReport.project_id == p.id, SiteReport.deleted_at.is_(None)).order_by(SiteReport.id.desc()).limit(5)).all()
        out['data']['site'] = {'items': [{'id': r.id, 'note': r.note[:300], 'date': r.report_date or r.created_at.date().isoformat()} for r in reports]}
    if 'money' in allowed:
        from .operating_totals import project_expense
        actual, basis = project_expense(db, p.id)
        out['data']['money'] = {'budget_paise': p.budget_paise, 'cost_to_date_paise': actual,
                                'expense_basis': basis}
    if 'files' in allowed:
        docs = db.scalars(select(Document).where(Document.project_id == p.id).order_by(Document.id.desc()).limit(LIMIT)).all()
        out['data']['files'] = {'items': [{'id': d.id, 'name': d.name, 'type': d.doc_type} for d in docs]}
    if 'people' in allowed:
        members = db.scalars(select(User).join(ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == p.id)).all()
        by_name = {}
        for t in tasks:
            if t.status not in core.CLOSED and t.assignee:
                by_name[t.assignee] = by_name.get(t.assignee, 0) + 1
        out['data']['people'] = {'members': [{'name': u.display_name or u.username, 'role': u.role} for u in members],
                                 'open_tasks_by_person': [{'name': n, 'open': c} for n, c in sorted(by_name.items())],
                                 'contacts': [{'id': link.id, 'party_id': party.id, 'name': party.name, 'role': link.role}
                                              for link, party in active_contacts(db, [p.id])]}
        if not as_role and role in ('admin', 'manager'):
            out['data']['people']['contact_options'] = contact_options(db)
    return out
