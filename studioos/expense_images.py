"""Stage private receipt files and link them only when a Books item is approved."""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import intake_core, intake_wiring
from .db import ApprovalTicket, ApprovalTicketItem, IntakeItem, RecordAttachment, User, add_audit
from .deps import get_db
from .intake_documents import verified_source
from .security import FINANCE_READ, current_user

router = APIRouter(prefix='/api/expense-images', tags=['Books receipts'])
RECEIPT_STATUS = intake_core.BOOKS_RECEIPT_STATUS
RECEIPT_TYPES = {'image/jpeg', 'image/png', 'application/pdf'}
MAX_RECEIPTS = 5
BOOKS_ITEM_KINDS = {'finance_expense': 'expense', 'finance_direct_bill': 'direct_bill'}


class ReceiptUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    base64: str = Field(min_length=4, max_length=12_000_000)


def public_receipt(item):
    return {'id': item.id, 'filename': item.filename, 'media_type': item.media_type,
            'size_bytes': item.size_bytes, 'is_image': item.media_type.startswith('image/')}


def _is_receipt(item):
    return bool(item and item.status == RECEIPT_STATUS and item.media_type in RECEIPT_TYPES
                and item.scan not in ('infected', 'scan_error'))


def validate_receipts(db, ids, submitter):
    if ids is None or ids == []:
        return []
    if (not isinstance(ids, list) or len(ids) > MAX_RECEIPTS or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Attach up to five different photos or PDFs.')
    rows = {item.id: item for item in db.scalars(select(IntakeItem).where(IntakeItem.id.in_(ids)))}
    if any(not _is_receipt(rows.get(ident)) or (submitter and rows[ident].uploaded_by != submitter.id)
           for ident in ids):
        raise ValueError('Attach a photo or PDF you uploaded yourself.')
    return [rows[ident] for ident in ids]


def link_receipts(db, item, record_id, receipts):
    kind = BOOKS_ITEM_KINDS[item.item_type]
    for receipt in receipts:
        try:
            verified_source(receipt)
        except (ValueError, OSError):
            raise ValueError('A receipt is missing or has changed. Upload it again before saving.') from None
    db.add_all(RecordAttachment(kind=kind, record_id=record_id, intake_item_id=receipt.id, ticket_item_id=item.id)
               for receipt in receipts)


def for_record(db, kind, record_id):
    rows = db.scalars(select(IntakeItem).join(RecordAttachment, RecordAttachment.intake_item_id == IntakeItem.id)
                      .where(RecordAttachment.kind == kind, RecordAttachment.record_id == record_id)
                      .order_by(RecordAttachment.id))
    return [public_receipt(row) for row in rows if _is_receipt(row)]


def for_ticket_item(db, ticket, item):
    ids = (item.after_data or {}).get('receipt_ids')
    if item.item_type not in BOOKS_ITEM_KINDS or not isinstance(ids, list) or not ids:
        return {}
    rows = db.scalars(select(IntakeItem).where(
        IntakeItem.id.in_(ids), IntakeItem.uploaded_by == ticket.submitter_id,
    ).order_by(IntakeItem.id))
    return {'attachments': [{**public_receipt(row), 'ticket_id': ticket.id} for row in rows if _is_receipt(row)]}


def _can_download(db, user, receipt, ticket_id):
    if receipt.uploaded_by == user.id:
        return True
    if user.role not in FINANCE_READ:
        return False
    from .main import check_proposal_access

    linked = select(ApprovalTicketItem).join(RecordAttachment, RecordAttachment.ticket_item_id == ApprovalTicketItem.id)
    items = list(db.scalars(linked.where(RecordAttachment.intake_item_id == receipt.id)))
    if ticket_id is not None and user.role in ('admin', 'manager'):
        ticket = db.get(ApprovalTicket, ticket_id)
        if ticket and ticket.submitter_id == receipt.uploaded_by:
            items.extend(db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == ticket_id)))
    for item in items:
        data = item.after_data or {}
        if item.item_type not in BOOKS_ITEM_KINDS or receipt.id not in (data.get('receipt_ids') or []):
            continue
        try:
            check_proposal_access(db, user, item.item_type, data)
        except HTTPException:
            continue
        return True
    return False


@router.post('')
def upload_receipt(body: ReceiptUpload, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot attach files.')
    try:
        data = base64.b64decode(body.base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'The file did not arrive whole.') from None
    try:
        if intake_core.check_file(data, body.filename)['media_type'] not in RECEIPT_TYPES:
            raise intake_core.IntakeError('Attach a JPG, PNG or PDF.')
        item = intake_wiring.receive_file(
            db, data, body.filename, 'upload', sender=user.username,
            sender_match={'kind': 'staff', 'id': user.id}, uploaded_by=user.id, note='Books receipt', read=False,
        )
    except intake_core.IntakeError as error:
        raise HTTPException(422, str(error)) from None
    if item.scan in ('infected', 'scan_error'):
        raise HTTPException(422, 'This file did not pass the safety scan.')
    item.status = RECEIPT_STATUS
    add_audit(db, 'receipt_uploaded', 'intake_item', item.id, 'Staged a file for Books review.', actor=user.username)
    db.commit()
    return public_receipt(item)


@router.get('/{item_id}')
def download_receipt(item_id: int, ticket_id: int | None = None,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(IntakeItem, item_id)
    if not _is_receipt(item) or not _can_download(db, user, item, ticket_id):
        raise HTTPException(404, 'Receipt not found.')
    try:
        path, _, _ = verified_source(item)
    except (ValueError, OSError):
        raise HTTPException(404, 'Receipt not found.') from None
    inline = item.media_type.startswith('image/')
    return FileResponse(path, media_type=item.media_type if inline else 'application/octet-stream',
                        filename=item.filename, content_disposition_type='inline' if inline else 'attachment',
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Security-Policy': "default-src 'none'; sandbox"})
