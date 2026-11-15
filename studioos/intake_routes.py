"""v0.14.0 intake APIs: upload, the inbox, drafts and imports (tickets), the WhatsApp webhook and the
e-mail poll. The webhook has no sign-in: it is accepted only with a valid signature made with
STUDIOOS_WHATSAPP_APP_SECRET (unset: every call is refused)."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import intake_core as I
from . import intake_wiring as W
from .db import IntakeItem, SessionLocal, User, add_audit
from .security import current_user, permit

router = APIRouter(prefix='/api/intake', tags=['Inbox: files, imports, WhatsApp, e-mail'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    base64: str = Field(min_length=4, max_length=12_000_000)
    note: str = Field(default='', max_length=500)


class DraftIn(BaseModel):
    type_key: str = Field(min_length=2, max_length=60)


class TableIn(BaseModel):
    type_key: str | None = None
    mapping: dict | None = None
    project_id: int | None = None
    new_type: dict | None = None


class SenderIn(BaseModel):
    address: str = Field(min_length=5, max_length=120)
    user_id: int


def _item(db, user, item_id) -> IntakeItem:
    it = db.get(IntakeItem, item_id)
    if not it or not W.visible(db, user, it):
        raise HTTPException(404, 'Not found')
    return it


@router.post('/upload')
def upload(v: UploadIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot send files')
    try:
        it = W.upload(db, user, v.filename, v.base64, v.note)
    except (I.IntakeError, ValueError) as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return W.item_view(db, it, full=True)


@router.get('/items')
def items(status: str = '', user: User = Depends(current_user), db: Session = Depends(_db)):
    q = select(IntakeItem).order_by(IntakeItem.id.desc()).limit(100)
    if status:
        q = q.where(IntakeItem.status == status)
    if user.role not in ('admin', 'manager'):
        q = q.where(IntakeItem.uploaded_by == user.id)
    return {'items': [W.item_view(db, x) for x in db.scalars(q)]}


@router.get('/items/{item_id}')
def item(item_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    return W.item_view(db, _item(db, user, item_id), full=True)


@router.get('/items/{item_id}/file')
def item_file(item_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    it = _item(db, user, item_id)
    if not it.stored_path or it.scan == 'infected' or not os.path.isfile(it.stored_path):
        raise HTTPException(404, 'No file')
    # always a download, never shown or run in the page
    return FileResponse(it.stored_path, media_type='application/octet-stream', filename=it.filename,
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox"})


@router.post('/items/{item_id}/draft')
def draft(item_id: int, v: DraftIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot draft')
    it = _item(db, user, item_id)
    try:
        ti = W.make_draft(db, user, it, v.type_key)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    return {'ticket_id': ti.ticket_id, 'item_id': ti.id, 'low_confidence': [k for k, m in (ti.field_evidence or {}).items() if m.get('low_confidence')]}


@router.post('/items/{item_id}/table')
def table(item_id: int, v: TableIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    it = _item(db, user, item_id)
    if it.status not in ('table', 'drafted', 'imported'):
        raise HTTPException(422, 'This item is not a table')
    try:
        out = W.table_preview(db, user, it, v.type_key, v.mapping, v.project_id)
    except (I.IntakeError, ValueError) as ex:
        raise HTTPException(422, str(ex))
    out.pop('_rows', None)
    return out


@router.post('/items/{item_id}/import')
def do_import(item_id: int, v: TableIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot import')
    it = _item(db, user, item_id)
    try:
        ticket = W.propose_import(db, user, it, v.type_key or '', v.mapping or {}, v.project_id, v.new_type)
    except (I.IntakeError, ValueError) as ex:
        db.rollback()
        raise HTTPException(422, str(ex))
    return {'ticket_id': ticket.id}


@router.post('/items/{item_id}/release')
def release(item_id: int, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    """Admin: a quarantined message is genuine; it goes to the inbox (nothing is saved)."""
    it = _item(db, user, item_id)
    if it.status != 'quarantined':
        raise HTTPException(409, 'Only quarantined items')
    it.status = 'new' if it.text.strip() else 'needs_reading'
    add_audit(db, 'intake_released', 'intake_item', it.id, 'Released from quarantine', actor=user.username)
    db.commit()
    return W.item_view(db, it)


@router.post('/items/{item_id}/reject')
def reject(item_id: int, user: User = Depends(permit('admin', 'manager')), db: Session = Depends(_db)):
    it = _item(db, user, item_id)
    it.status = 'rejected'
    add_audit(db, 'intake_rejected', 'intake_item', it.id, 'Rejected', actor=user.username)
    db.commit()
    return W.item_view(db, it)


@router.post('/senders')
def senders(v: SenderIn, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        W.add_sender(db, v.address, v.user_id, user.username)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return {'saved': True}


@router.get('/whatsapp')
def whatsapp_verify(request: Request):
    """The provider's one-time check of the webhook address (needs STUDIOOS_WHATSAPP_VERIFY_TOKEN)."""
    token = os.getenv('STUDIOOS_WHATSAPP_VERIFY_TOKEN', '')
    q = request.query_params
    if token and q.get('hub.mode') == 'subscribe' and q.get('hub.verify_token') == token:
        return PlainTextResponse(q.get('hub.challenge', '')[:100])
    raise HTTPException(403, 'Refused')


@router.post('/whatsapp')
async def whatsapp(request: Request):
    body = await request.body()
    if len(body) > 1_000_000 or not I.verify_signature(os.getenv('STUDIOOS_WHATSAPP_APP_SECRET', ''), body,
                                                        request.headers.get('X-Hub-Signature-256')):
        raise HTTPException(403, 'Refused')
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, 'Not JSON')
    with SessionLocal() as db:
        db.info['write_source'] = 'webhook:whatsapp'
        made = W.whatsapp(db, payload)
        db.commit()
    return {'received': len(made)}


@router.post('/email/poll')
def email_poll(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    box = I.ImapMailbox()
    if not box.configured():
        raise HTTPException(422, 'The mailbox is not set up (STUDIOOS_IMAP_HOST, _USER, _PASSWORD on the server)')
    try:
        made = W.email_poll(db, box)
    except Exception:
        raise HTTPException(502, 'The mailbox could not be read')
    db.commit()
    return {'received': len(made)}
