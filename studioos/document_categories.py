"""Governed business categories for files (Document.category), keeping Document.doc_type strictly for file formats."""
from __future__ import annotations

from .access import can_access_project
from .db import Document, add_audit

DOC_CATEGORY_TYPE = 'document_categorize'
DOC_CATEGORY_FIELDS = {'document_id', 'category'}

# Shared business file categories (always includes 'Other'; aligned with client_deliverable.kind).
FILE_CATEGORIES: tuple[str, ...] = (
    'Drawing',
    'Render',
    'Material selection',
    'Quotation',
    'Contract',
    'Invoice',
    'Site photo',
    'Report',
    'Other',
)
RETIRED_FILE_CATEGORIES: tuple[str, ...] = ()

DELIVERABLE_KIND_MAP: dict[str, str] = {
    'Drawing': 'Drawing',
    'Render': 'Render',
    'Material selection': 'Material selection',
    'Report': 'Report',
    'Other': 'Other',
}


def active_file_categories() -> list[str]:
    return list(FILE_CATEGORIES)


def deliverable_kind_for_document(doc: Document | None) -> str | None:
    """Return matching client_deliverable.kind for a Document.category, if any."""
    if doc is None or not doc.category:
        return None
    return DELIVERABLE_KIND_MAP.get(doc.category)


def validate(db, data: dict, actor=None):
    if not isinstance(data, dict) or set(data) != DOC_CATEGORY_FIELDS:
        raise ValueError('Choose the file and its category.')
    doc_id = data.get('document_id')
    if type(doc_id) is not int or doc_id <= 0:
        raise ValueError('Choose an existing file.')
    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError('File not found.')
    if actor is not None:
        if doc.project_id is not None:
            if not can_access_project(db, actor, doc.project_id):
                raise ValueError('Choose a file on a project you can access.')
        elif actor.role not in ('admin', 'manager'):
            raise ValueError('Only Admin or Manager can categorize unassigned files.')
    cat = data.get('category')
    if cat is not None:
        if not isinstance(cat, str) or cat not in FILE_CATEGORIES:
            raise ValueError('Choose an approved file category: ' + ', '.join(FILE_CATEGORIES))
    return doc, cat


def apply(db, item, actor: str):
    doc, cat = validate(db, item.after_data)
    doc.category = cat
    db.flush()
    label = cat or 'cleared'
    add_audit(db, DOC_CATEGORY_TYPE, 'document', doc.id,
              f'Set file category to "{label}" from ticket #{item.ticket_id}.', actor=actor)
    return {'type': 'document', 'id': doc.id, 'category': doc.category, 'item_id': item.id}
