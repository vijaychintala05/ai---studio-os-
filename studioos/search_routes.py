"""Search (App Flows overlay): find a project, task, snag, site report, file or contact by name. Narrowed to one project when asked
(project_id), and always limited to what the person may see: projects they are on, files and records of those projects, and contacts only
for roles that may see contacts and only the ones their projects relate to. A project you cannot see is never confirmed (404)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .access import can_access_project, visible_project_ids
from .db import Document, FlexibleRecord, Party, Project, SiteReport, Task, User
from .deps import get_db
from .security import current_user

router = APIRouter(prefix='/api/search', tags=['Search'])

PER_GROUP = 8
PARTY_ROLES = ('admin', 'manager', 'accounts')


def _like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


@router.get('')
def search(q: str = Query(min_length=2, max_length=80), project_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, 'Type at least 2 characters')
    if project_id is not None and not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')
    allowed = visible_project_ids(db, user)
    pat = _like(q)
    names = {p.id: p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)))}

    def in_scope(stmt, col):
        if project_id is not None:
            return stmt.where(col == project_id)
        return stmt if allowed is None else stmt.where(col.in_(allowed or {-1}))

    groups = {}
    if project_id is None:
        stmt = select(Project).where(Project.deleted_at.is_(None), or_(Project.name.ilike(pat, escape='\\'), Project.client.ilike(pat, escape='\\')))
        if allowed is not None:
            stmt = stmt.where(Project.id.in_(allowed or {-1}))
        groups['projects'] = [{'type': 'project', 'id': p.id, 'title': p.name, 'detail': p.client or p.stage, 'project_id': p.id}
                              for p in db.scalars(stmt.order_by(Project.name).limit(PER_GROUP))]
    stmt = in_scope(select(Task).where(Task.deleted_at.is_(None), or_(Task.title.ilike(pat, escape='\\'), Task.assignee.ilike(pat, escape='\\'))), Task.project_id)
    groups['tasks'] = [{'type': 'task', 'id': t.id, 'title': t.title, 'detail': f"{names.get(t.project_id, '')} · {t.status}", 'project_id': t.project_id}
                       for t in db.scalars(stmt.order_by(Task.id.desc()).limit(PER_GROUP))]
    stmt = in_scope(select(FlexibleRecord).where(FlexibleRecord.record_type == 'work_issue', FlexibleRecord.deleted_at.is_(None)), FlexibleRecord.project_id)
    snags = [r for r in db.scalars(stmt.order_by(FlexibleRecord.id.desc()).limit(200)) if q.casefold() in str((r.data or {}).get('title', '')).casefold()]
    groups['snags'] = [{'type': 'snag', 'id': r.id, 'title': (r.data or {}).get('title', 'Snag'), 'detail': names.get(r.project_id, ''), 'project_id': r.project_id}
                       for r in snags[:PER_GROUP]]
    stmt = in_scope(select(SiteReport).where(SiteReport.deleted_at.is_(None), SiteReport.note.ilike(pat, escape='\\')), SiteReport.project_id)
    groups['site'] = [{'type': 'site_report', 'id': r.id, 'title': r.note[:80], 'detail': names.get(r.project_id, ''), 'project_id': r.project_id}
                      for r in db.scalars(stmt.order_by(SiteReport.id.desc()).limit(PER_GROUP))]
    stmt = in_scope(select(Document).where(or_(Document.name.ilike(pat, escape='\\'), Document.relative_path.ilike(pat, escape='\\'))), Document.project_id)
    groups['files'] = [{'type': 'document', 'id': d.id, 'title': d.name, 'detail': names.get(d.project_id, ''), 'project_id': d.project_id}
                       for d in db.scalars(stmt.order_by(Document.id.desc()).limit(PER_GROUP))]
    if project_id is None and user.role in PARTY_ROLES:
        from .party_access import visible_party_ids
        permitted = visible_party_ids(db, user, allowed)
        stmt = select(Party).where(Party.deleted_at.is_(None), Party.name.ilike(pat, escape='\\'))
        if permitted is not None:
            stmt = stmt.where(Party.id.in_(permitted or [-1]))
        groups['contacts'] = [{'type': 'party', 'id': x.id, 'title': x.name, 'detail': x.kind, 'project_id': None} for x in db.scalars(stmt.order_by(Party.name).limit(PER_GROUP))]
    groups = {k: v for k, v in groups.items() if v}
    return {'query': q, 'project_id': project_id, 'groups': groups, 'total': sum(len(v) for v in groups.values())}
