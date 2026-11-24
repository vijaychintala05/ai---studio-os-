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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from .client_portal_routes import PortalContext, portal_context
from .db import SessionLocal, FlexibleRecord, Document, add_audit

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


def _out(rec, doc):
    d = rec.data or {}
    return {'id': rec.id, 'title': d.get('title', ''), 'kind': d.get('kind', ''), 'note': d.get('note_for_client', ''),
            'file_name': doc.name, 'size_bytes': doc.size_bytes, 'added': rec.created_at.isoformat() if rec.created_at else ''}


@router.get('/portal-api/deliverables')
def list_deliverables(ctx: PortalContext = Depends(portal_context)):
    with SessionLocal() as db:
        return {'items': [_out(r, _document_for(db, r)) for r in visible_deliverables(db, ctx.project_id)]}


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
