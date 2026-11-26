"""v63: receipt and bill images on expenses, purchase orders and payments (Zoho Books: "Attach files").

The file goes through the same intake storage as every other upload: checked by its real bytes (not its name), size
limited, virus-scanned, kept read-only under its fingerprint. These files do NOT appear in "Files to sort".
An image is only linked to a record when that record's change request is approved; until then it is just uploaded."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import intake_core as I
from . import intake_wiring as W
from .db import Cost, IntakeItem, Payment, RecordAttachment, SessionLocal, User, add_audit
from .security import current_user

router = APIRouter(prefix='/api/expense-images', tags=['Receipt and bill images'])
IMAGE_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}
MAX_FILES = 5
STATUS = 'attached'


class ImageIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    base64: str = Field(min_length=4, max_length=12_000_000)


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


def view(item: IntakeItem) -> dict:
    return {'id': item.id, 'filename': item.filename, 'media_type': item.media_type, 'size_bytes': item.size_bytes,
            'is_image': item.media_type.startswith('image/')}


def validate_ids(db: Session, ids, submitter_id, role) -> list[int]:
    """Every id must be a clean receipt file this person uploaded (the owner and managers may use any)."""
    if ids in (None, [], ()):
        return []
    if not isinstance(ids, list) or len(ids) > MAX_FILES or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        raise ValueError(f'Attach up to {MAX_FILES} receipt images or PDFs.')
    for i in ids:
        item = db.get(IntakeItem, i)
        if not item or item.status != STATUS or item.media_type not in IMAGE_TYPES or item.scan in ('infected', 'scan_error'):
            raise ValueError('One of the attached files is missing or not accepted. Upload it again.')
        if role not in ('admin', 'manager') and item.uploaded_by != submitter_id:
            raise ValueError('You can only attach files you uploaded yourself.')
    return list(ids)


def duplicates(db: Session, ids) -> list[str]:
    """The same file (same fingerprint) already attached to another record."""
    out = []
    for i in ids or []:
        item = db.get(IntakeItem, i)
        if not item:
            continue
        for found in db.scalars(select(RecordAttachment).join(IntakeItem, IntakeItem.id == RecordAttachment.intake_item_id)
                                .where(IntakeItem.sha256 == item.sha256)).all():
            out.append(f'possible_duplicate: this receipt file ({item.filename}) is already attached to {found.kind} #{found.record_id}')
    return list(dict.fromkeys(out))


def link(db: Session, kind: str, record_id: int, ids) -> None:
    for i in ids or []:
        db.add(RecordAttachment(kind=kind, record_id=record_id, intake_item_id=i))


def for_record(db: Session, kind: str, record_id: int) -> list[dict]:
    rows = db.scalars(select(IntakeItem).join(RecordAttachment, RecordAttachment.intake_item_id == IntakeItem.id)
                      .where(RecordAttachment.kind == kind, RecordAttachment.record_id == record_id)
                      .order_by(RecordAttachment.id)).all()
    return [view(r) for r in rows]


def can_see(db: Session, user: User, item: IntakeItem) -> bool:
    if user.role in ('admin', 'manager') or item.uploaded_by == user.id:
        return True
    from .access import can_access_project
    from .security import FINANCE_READ
    for found in db.scalars(select(RecordAttachment).where(RecordAttachment.intake_item_id == item.id)).all():
        if found.kind in ('bill', 'expense'):          # a bill or an expense in the books: the money team, or the project's people
            if user.role in FINANCE_READ:
                return True
            if found.kind == 'expense':
                from .db import FinanceExpense
                exp = db.get(FinanceExpense, found.record_id)
                if exp and exp.project_id and can_access_project(db, user, exp.project_id):
                    return True
            continue
        rec = db.get(Cost if found.kind == 'cost' else Payment, found.record_id)
        if rec and can_access_project(db, user, rec.project_id):
            return True
    return False


@router.post('')
def upload(v: ImageIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot attach files')
    try:
        data = base64.b64decode(v.base64, validate=True)
    except Exception:
        raise HTTPException(422, 'The file did not arrive whole')
    try:
        if I.check_file(data, v.filename)['media_type'] not in IMAGE_TYPES:
            raise I.IntakeError('Attach a photo (JPG or PNG) or a PDF')
        item = W.receive_file(db, data, v.filename, 'upload', sender=user.username,
                              sender_match={'kind': 'staff', 'id': user.id}, uploaded_by=user.id, note='receipt image')
    except (I.IntakeError, ValueError) as ex:
        raise HTTPException(422, str(ex))
    if item.scan in ('infected', 'scan_error'):
        raise HTTPException(422, 'This file did not pass the safety scan')
    item.status = STATUS          # kept out of "Files to sort": it belongs to the record it is attached to
    add_audit(db, 'receipt_image_uploaded', 'intake_item', item.id,
              f'Receipt file received ({item.media_type}, {item.size_bytes} bytes)', actor=user.username)
    db.commit()
    return view(item)


@router.get('/{item_id}')
def show(item_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    item = db.get(IntakeItem, item_id)
    if not item or item.status != STATUS or not can_see(db, user, item):
        raise HTTPException(404, 'Not found')
    from .intake_documents import verified_source
    try:
        path, _, _ = verified_source(item)
    except (ValueError, OSError):
        raise HTTPException(404, 'No verified source file')
    inline = item.media_type.startswith('image/')          # a photo shows in the page; a PDF is downloaded, never run
    return FileResponse(path, media_type=item.media_type if inline else 'application/octet-stream', filename=item.filename,
                        content_disposition_type='inline' if inline else 'attachment',
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=300',
                                 'Content-Security-Policy': "default-src 'none'; sandbox"})
