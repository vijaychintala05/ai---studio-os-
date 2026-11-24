"""Staff side of the client portal (step 6): the project picker, the unread activity list, and the client-files screen's API.

Only admin, manager and architect (the roles that may talk to clients) use these, and only for projects they can access.
Changes to client files are DRAFT tickets (nothing changes until a person approves), exactly like the record edits.
"""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from .access import can_access_project, visible_project_ids
from .client_conversation import PROPOSERS
from .client_portal_content import DELIVERABLE_TYPE, client_visible, current_version, decision_state, _document_for
from .client_portal_models import ClientContact, PortalActivity, PortalActivityRead, ProjectPortal
from .client_portal_routes import portal_domain
from .db import Document, FlexibleRecord, Project
from .deps import get_db
from .security import permit

router = APIRouter()
KINDS = Literal['Drawing', 'Render', 'Material selection', 'Report', 'Other']
RELEASES = Literal['Draft', 'Final', 'Superseded']


def _project(db, user, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at is not None or not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')
    return p


def _last_seen(db, user):
    row = db.get(PortalActivityRead, user.id)
    return row.last_seen_id if row else 0


def _visible_activity(db, user):
    allowed = visible_project_ids(db, user)
    stmt = select(PortalActivity)
    if allowed is not None:
        stmt = stmt.where(PortalActivity.project_id.in_(allowed or [-1]))
    return stmt


# ------------------------------------------------------------------ project picker and unread activity

@router.get('/api/portal-projects')
def staff_projects(user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    allowed = visible_project_ids(db, user)
    seen = _last_seen(db, user)
    domain = portal_domain()
    portals = {p.project_id: p for p in db.scalars(select(ProjectPortal))}
    contacts = dict(db.execute(select(ClientContact.project_id, func.count()).where(ClientContact.active.is_(True)).group_by(ClientContact.project_id)).all())
    unread = dict(db.execute(select(PortalActivity.project_id, func.count()).where(PortalActivity.id > seen).group_by(PortalActivity.project_id)).all())
    rows = []
    for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)):
        if allowed is not None and p.id not in allowed:
            continue
        portal = portals.get(p.id)
        rows.append({'id': p.id, 'name': p.name, 'client': p.client,
                     'portal': {'slug': portal.slug, 'enabled': portal.enabled, 'address': f'{portal.slug}.{domain}' if domain else ''} if portal else None,
                     'contacts': contacts.get(p.id, 0), 'unread': unread.get(p.id, 0)})
    return {'domain_set': bool(domain), 'projects': rows}


@router.get('/api/portal-inbox')
def staff_inbox(limit: int = 50, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    if not 1 <= limit <= 200:
        raise HTTPException(422, 'Invalid page size')
    seen = _last_seen(db, user)
    names = {p.id: p.name for p in db.scalars(select(Project))}
    rows = db.scalars(_visible_activity(db, user).order_by(PortalActivity.id.desc()).limit(limit)).all()
    unread = db.scalar(_visible_activity(db, user).where(PortalActivity.id > seen).with_only_columns(func.count())) or 0
    return {'unread': unread, 'items': [{'id': r.id, 'project_id': r.project_id, 'project': names.get(r.project_id, ''), 'kind': r.kind,
                                         'summary': r.summary, 'actor': r.actor, 'at': r.created_at.isoformat(), 'unread': r.id > seen} for r in rows]}


@router.post('/api/portal-inbox/seen')
def staff_inbox_seen(user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    from .db import now
    top = db.scalar(_visible_activity(db, user).with_only_columns(func.max(PortalActivity.id))) or 0
    row = db.get(PortalActivityRead, user.id)
    if row is None:
        db.add(PortalActivityRead(user_id=user.id, last_seen_id=top))
    elif top > row.last_seen_id:
        row.last_seen_id, row.updated_at = top, now()
    db.commit()
    return {'ok': True, 'last_seen_id': top}


# ------------------------------------------------------------------ client files (deliverables)

class DeliverableIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    kind: KINDS
    file: int
    release: RELEASES = 'Draft'
    shared_with_client: bool = False
    needs_client_approval: bool = False
    note_for_client: str = Field(default='', max_length=4000)


class DeliverableEditIn(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    kind: KINDS | None = None
    file: int | None = None
    release: RELEASES | None = None
    shared_with_client: bool | None = None
    needs_client_approval: bool | None = None
    note_for_client: str | None = Field(default=None, max_length=4000)


@router.get('/api/portal/{project_id}/documents')
def staff_documents(project_id: int, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    """Files that can be shared with a client: approved uploads that belong to this project."""
    _project(db, user, project_id)
    rows = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.id.desc()).limit(500)).all()
    return {'documents': [{'id': d.id, 'name': d.name, 'size_bytes': d.size_bytes} for d in rows if re.fullmatch(r'intake/[0-9a-f]{64}', d.relative_path or '')]}


@router.get('/api/portal/{project_id}/deliverables')
def staff_deliverables(project_id: int, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _project(db, user, project_id)
    out = []
    for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == DELIVERABLE_TYPE, FlexibleRecord.project_id == project_id,
                                                     FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id.desc()).limit(500)):
        d, doc = r.data or {}, _document_for(db, r)
        out.append({'id': r.id, 'title': d.get('title', ''), 'kind': d.get('kind', ''), 'release': d.get('release', ''),
                    'shared_with_client': d.get('shared_with_client') is True, 'needs_client_approval': d.get('needs_client_approval') is True,
                    'note_for_client': d.get('note_for_client', ''), 'file': {'id': doc.id, 'name': doc.name} if doc else None,
                    'version': current_version(db, r), 'client_sees': bool(client_visible(r) and doc), 'approval': decision_state(db, r)})
    return {'deliverables': out}


def _draft(db, user, kind, data, evidence):
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, kind, data, evidence=evidence)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post('/api/portal/{project_id}/deliverables')
def staff_add_deliverable(project_id: int, v: DeliverableIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _project(db, user, project_id)
    values = v.model_dump()
    if not values['note_for_client'].strip():
        values.pop('note_for_client')
    return _draft(db, user, 'metadata_record', {'type_key': DELIVERABLE_TYPE, 'project_id': project_id, 'values': values},
                  'New client file drafted from the portal screen')


@router.post('/api/portal/{project_id}/deliverables/{record_id}/edit')
def staff_edit_deliverable(project_id: int, record_id: int, v: DeliverableEditIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _project(db, user, project_id)
    rec = db.get(FlexibleRecord, record_id)
    if rec is None or rec.record_type != DELIVERABLE_TYPE or rec.deleted_at or rec.project_id != project_id:
        raise HTTPException(404, 'Not found')
    changes = v.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, 'Nothing to change')
    values = {**(rec.data or {}), **changes}
    if not str(values.get('note_for_client', '')).strip():
        values.pop('note_for_client', None)
    return _draft(db, user, 'metadata_record_update', {'type_key': DELIVERABLE_TYPE, 'record_id': rec.id, 'project_id': project_id,
                                                      'expected_version': current_version(db, rec), 'values': values}, 'Client file edit from the portal screen')
