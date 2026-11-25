"""Client portal step 2: what a client may SEE, and the one place that decides it.

A client sees a file only if ALL of these hold (see `client_visible` and `deliverable_for_client`):
  - it is a `client_deliverable` record of THIS address's project (the project comes from the web address),
  - it is not deleted, its release is Final, and staff ticked "share with the client",
  - the file it points to belongs to the same project and is an approved uploaded document.
Anything else is a 404, exactly like a record that does not exist. Costs, budgets, payments, internal chat,
drafts and other projects are never reachable from here: this module only reads `client_deliverable`.
Staff create and change deliverables through approved tickets (the `client_portal` business pack).
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from .client_portal_models import ClientDecision, note_activity
from .client_portal_routes import PortalContext, portal_context
from .db import SessionLocal, FlexibleRecord, Document, UniversalRecordRevision, Project, add_audit, now
from .deps import get_db
from .security import permit

router = APIRouter()

DELIVERABLE_TYPE = 'client_deliverable'
MAX_LISTED = 500


def client_visible(rec: FlexibleRecord) -> bool:
    d = rec.data or {}
    return (rec.deleted_at is None and rec.record_type == DELIVERABLE_TYPE
            and d.get('shared_with_client') is True and d.get('release') == 'Final')


def _document_for(db, rec: FlexibleRecord):
    """The file behind a deliverable, only if it belongs to the same project as the deliverable."""
    file_id = (rec.data or {}).get('file')
    doc = db.get(Document, file_id) if type(file_id) is int else None
    return doc if doc is not None and doc.project_id == rec.project_id else None


def visible_deliverables(db, project_id: int) -> list[FlexibleRecord]:
    rows = db.scalars(select(FlexibleRecord).where(
        FlexibleRecord.record_type == DELIVERABLE_TYPE, FlexibleRecord.project_id == project_id,
        FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id.desc()).limit(5000)).all()
    # Filtered in Python so stored JSON is never turned into a query.
    return [r for r in rows if client_visible(r) and _document_for(db, r) is not None][:MAX_LISTED]


def deliverable_for_client(db, project_id: int, record_id: int) -> FlexibleRecord:
    rec = db.get(FlexibleRecord, record_id)
    if rec is None or rec.project_id != project_id or not client_visible(rec) or _document_for(db, rec) is None:
        raise HTTPException(404, 'Not found')
    return rec


def current_version(db, rec) -> int:
    """The version of the deliverable as staff last approved it. A decision belongs to ONE version."""
    return db.scalar(select(func.max(UniversalRecordRevision.version)).where(UniversalRecordRevision.record_id == rec.id)) or 1


def decision_state(db, rec) -> dict | None:
    """None when staff did not ask for approval. Otherwise pending, approved or changes_requested for the CURRENT version;
    a decision on an earlier version no longer counts (the client is asked again) and is flagged `earlier_version`."""
    if (rec.data or {}).get('needs_client_approval') is not True:
        return None
    rows = db.scalars(select(ClientDecision).where(ClientDecision.record_id == rec.id).order_by(ClientDecision.id.desc()).limit(50)).all()
    version = current_version(db, rec)
    latest = next((r for r in rows if r.record_version == version), None)
    out = {'state': latest.decision if latest else 'pending', 'earlier_version': bool(rows) and latest is None}
    if latest:
        out.update(by=latest.contact_name, at=latest.created_at.isoformat(), comment=latest.comment)
    return out


def _out(db, rec, doc):
    d = rec.data or {}
    return {'id': rec.id, 'title': d.get('title', ''), 'kind': d.get('kind', ''), 'note': d.get('note_for_client', ''),
            'file_name': doc.name, 'size_bytes': doc.size_bytes, 'added': rec.created_at.isoformat() if rec.created_at else '',
            'approval': decision_state(db, rec)}


@router.get('/portal-api/deliverables')
def list_deliverables(ctx: PortalContext = Depends(portal_context)):
    with SessionLocal() as db:
        return {'items': [_out(db, r, _document_for(db, r)) for r in visible_deliverables(db, ctx.project_id)]}


@router.get('/portal-api/deliverables/{record_id}/file')
def download_deliverable(record_id: int, ctx: PortalContext = Depends(portal_context)):
    from .intake_documents import approved_source
    with SessionLocal() as db:
        rec = deliverable_for_client(db, ctx.project_id, record_id)
        doc = _document_for(db, rec)
        try:
            path, filename, _ = approved_source(db, doc)
        except ValueError:
            raise HTTPException(404, 'Not found')
        add_audit(db, 'portal_file_opened', 'client_deliverable', rec.id,
                  f'{ctx.contact_name} opened "{(rec.data or {}).get("title", "")}"', actor=f'client:{ctx.contact_id}')
        db.commit()
    return FileResponse(path, media_type='application/octet-stream', filename=filename,
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox"})


# ---------------------------------------------------------------- client answers: approve, or ask for changes

PER_HOUR = 20


class DecisionIn(BaseModel):
    decision: Literal['approved', 'changes_requested']
    comment: str = Field(default='', max_length=2000)


@router.post('/portal-api/deliverables/{record_id}/decision')
def decide(record_id: int, v: DecisionIn, ctx: PortalContext = Depends(portal_context)):
    comment = v.comment.strip()
    if v.decision == 'changes_requested' and len(comment) < 3:
        raise HTTPException(422, 'Please say what you would like changed')
    with SessionLocal() as db:
        rec = deliverable_for_client(db, ctx.project_id, record_id)
        if (rec.data or {}).get('needs_client_approval') is not True:
            raise HTTPException(404, 'Not found')            # nothing was asked of the client here
        version = current_version(db, rec)
        last = db.scalar(select(ClientDecision).where(ClientDecision.record_id == rec.id, ClientDecision.contact_id == ctx.contact_id,
                         ClientDecision.record_version == version).order_by(ClientDecision.id.desc()).limit(1))
        if last and last.decision == v.decision and last.comment == comment:
            return {'ok': True, 'approval': decision_state(db, rec)}      # a double tap records nothing new
        since = now() - dt.timedelta(hours=1)
        if db.scalar(select(func.count(ClientDecision.id)).where(ClientDecision.contact_id == ctx.contact_id, ClientDecision.created_at >= since)) >= PER_HOUR:
            raise HTTPException(429, 'Too many answers in the last hour. Please try again later.')
        row = ClientDecision(project_id=ctx.project_id, record_id=rec.id, record_version=version, contact_id=ctx.contact_id,
                             contact_name=ctx.contact_name, decision=v.decision, comment=comment)
        db.add(row); db.flush()
        title = (rec.data or {}).get('title', '')
        verb = 'approved' if v.decision == 'approved' else 'asked for changes to'
        digest = hashlib.sha256(comment.encode()).hexdigest()[:16]
        add_audit(db, 'client_decision', 'client_deliverable', rec.id,
                  f'{ctx.contact_name} {verb} "{title}" (version {version}, answer #{row.id}, comment fingerprint {digest}): {comment[:200]}',
                  actor=f'client:{ctx.contact_id}')
        note_activity(db, ctx.project_id, 'client_decision', row.id,
                      f'{ctx.contact_name} {verb} "{title}"' + (f': {comment[:160]}' if comment else ''), ctx.contact_name)
        db.commit()
        return {'ok': True, 'approval': decision_state(db, rec)}


# ---------------------------------------------------------------- staff: what did the client say?

@router.get('/api/portal/{project_id}/decisions')
def staff_decisions(project_id: int, user=Depends(permit('admin', 'manager')), db=Depends(get_db)):
    p = db.get(Project, project_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(404, 'Project not found')
    rows = db.scalars(select(ClientDecision).where(ClientDecision.project_id == project_id).order_by(ClientDecision.id.desc()).limit(200)).all()
    titles = {r.id: (r.data or {}).get('title', '') for r in db.scalars(select(FlexibleRecord).where(
        FlexibleRecord.id.in_({x.record_id for x in rows}))).all()} if rows else {}
    return {'decisions': [{'id': r.id, 'deliverable_id': r.record_id, 'deliverable': titles.get(r.record_id, ''), 'version': r.record_version,
                           'by': r.contact_name, 'decision': r.decision, 'comment': r.comment, 'at': r.created_at.isoformat()} for r in rows]}
