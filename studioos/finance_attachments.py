"""M2-6: Append-only document attachments across all money entries (direct bills,
supplier bills, payments, transfers, manual journals, expenses) with SHA-256
duplicate receipt detection. Every link travels through an approval ticket.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, Document, FinanceAttachment, FinanceDirectBill,
                 FinanceDirectBillPayment, FinanceExpense, FinanceManualJournal,
                 FinanceSupplierBill, FinanceSupplierPayment, FinanceTransfer)

ATTACHMENT_TYPES = frozenset({'finance_attach_document'})
ATTACHMENT_FIELDS = {
    'finance_attach_document': {'entity_id', 'target_kind', 'target_id', 'document_id', 'note'},
}

TARGET_MODELS = {
    'direct_bill': FinanceDirectBill,
    'supplier_bill': FinanceSupplierBill,
    'payment': FinanceSupplierPayment,
    'direct_bill_payment': FinanceDirectBillPayment,
    'transfer': FinanceTransfer,
    'manual_journal': FinanceManualJournal,
    'expense': FinanceExpense,
}


def compute_doc_sha256(doc: Document) -> str:
    path = Path(doc.stored_path) if doc.stored_path else None
    if path and path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(f'doc:{doc.id}:{doc.name}:{doc.stored_path}'.encode('utf-8')).hexdigest()


def find_duplicates(db: Session, entity_id: int, sha256: str, exclude_kind: str = '', exclude_id: int = 0) -> list[dict]:
    rows = db.scalars(select(FinanceAttachment).where(
        FinanceAttachment.entity_id == entity_id,
        FinanceAttachment.sha256 == sha256,
    ).order_by(FinanceAttachment.id)).all()
    return [
        {'id': r.id, 'target_kind': r.target_kind, 'target_id': r.target_id, 'document_id': r.document_id}
        for r in rows if not (r.target_kind == exclude_kind and r.target_id == exclude_id)
    ]


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ != 'finance_attach_document':
        raise ValueError(f'Unknown attachment item type: {typ}')
    ent_id = int(d.get('entity_id') or 0)
    if not db.get(AccountingEntity, ent_id):
        raise ValueError('Choose a valid company.')
    kind = str(d.get('target_kind') or '').strip().lower()
    model = TARGET_MODELS.get(kind)
    if not model:
        raise ValueError(f'Unsupported money entry type: {kind!r}.')
    target_id = int(d.get('target_id') or 0)
    target = db.get(model, target_id)
    if not target:
        raise ValueError(f'{kind.replace("_", " ").title()} #{target_id} not found.')
    doc_id = int(d.get('document_id') or 0)
    doc = db.get(Document, doc_id)
    if not doc:
        raise ValueError('Attached document not found.')
    sha = compute_doc_sha256(doc)
    return {
        'entity_id': ent_id,
        'target_kind': kind,
        'target_id': target_id,
        'document_id': doc.id,
        'sha256': sha,
        'note': str(d.get('note') or '').strip()[:250],
    }


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    dups = find_duplicates(db, clean['entity_id'], clean['sha256'], clean['target_kind'], clean['target_id'])
    warn = f' (Warning: same file already attached to {len(dups)} other entry)' if dups else ''
    return {
        'summary': f"Attach document #{clean['document_id']} to {clean['target_kind']} #{clean['target_id']}{warn}",
        'lines': [],
        'duplicate_warning': bool(dups),
        'existing_targets': dups,
    }


def apply(db: Session, item, actor) -> dict:
    clean = validate(db, item.item_type, item.after_data, actor)
    row = FinanceAttachment(
        entity_id=clean['entity_id'],
        target_kind=clean['target_kind'],
        target_id=clean['target_id'],
        document_id=clean['document_id'],
        sha256=clean['sha256'],
        note=clean['note'],
        ticket_id=item.ticket_id,
    )
    db.add(row)
    db.flush()
    return {'record_type': 'finance_attachment', 'id': row.id}


def list_attachments(db: Session, target_kind: str, target_id: int) -> list[dict]:
    rows = db.scalars(select(FinanceAttachment).where(
        FinanceAttachment.target_kind == target_kind,
        FinanceAttachment.target_id == target_id,
    ).order_by(FinanceAttachment.id)).all()
    out = []
    for r in rows:
        doc = db.get(Document, r.document_id)
        dups = find_duplicates(db, r.entity_id, r.sha256, r.target_kind, r.target_id)
        out.append({
            'id': r.id,
            'document_id': r.document_id,
            'document_name': doc.name if doc else '',
            'sha256': r.sha256,
            'note': r.note,
            'duplicate_elsewhere': bool(dups),
            'ticket_id': r.ticket_id,
        })
    return out
