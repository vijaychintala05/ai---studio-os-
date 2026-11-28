"""Compact, access-filtered ontology and taxonomy context for AI parsing (Step 6)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import ALL_PROJECT_ROLES
from .db import AccountingEntity, Project, RecordType
from .document_categories import active_file_categories
from .expense_categories import categories as active_expense_categories
from .security import FINANCE_READ
from .universal_engine import type_options


def _can_see_type(user, rt, allowed_projects) -> bool:
    if user is None or user.role in ALL_PROJECT_ROLES or allowed_projects is None:
        return True
    opts = type_options(rt)
    if user.role in (opts.get('company_read_roles') or []) or opts.get('self_read'):
        return True
    return bool(allowed_projects)


def build_ai_context(db: Session, user, allowed_projects=None) -> dict:
    """Return active categories and universal type schemas visible to this user.

    Never exposes retired options, hidden company expense categories, or types the user cannot read.
    """
    expense_cats: list[str] = []
    if user is not None and user.role in FINANCE_READ:
        if allowed_projects is None:
            entity_ids = list(db.scalars(select(AccountingEntity.id).order_by(AccountingEntity.id)))
        else:
            entity_ids = sorted({
                cid for cid in db.scalars(
                    select(Project.company_id).where(
                        Project.id.in_(allowed_projects), Project.deleted_at.is_(None), Project.company_id.is_not(None),
                    )
                ) if cid is not None
            })
        seen: set[str] = set()
        for eid in entity_ids:
            for row in active_expense_categories(db, eid):
                key = row['name'].casefold()
                if key not in seen:
                    seen.add(key)
                    expense_cats.append(row['name'])

    record_types: list[dict] = []
    for rt in db.scalars(select(RecordType).where(RecordType.status == 'active').order_by(RecordType.key)):
        if not _can_see_type(user, rt, allowed_projects):
            continue
        fields = (rt.design or {}).get('runtime_fields')
        if not fields:
            continue
        compact_fields = []
        for f in fields:
            entry = {'name': f['name'], 'type': f['type']}
            if f.get('type') == 'enum' and f.get('options'):
                entry['options'] = list(f['options'])
            compact_fields.append(entry)
        record_types.append({
            'key': rt.key,
            'title': rt.title,
            'aliases': list((rt.design or {}).get('aliases') or []),
            'fields': compact_fields,
        })

    return {
        'expense_categories': expense_cats,
        'file_categories': active_file_categories(),
        'record_types': record_types,
    }


def match_active_category(raw: str | None, active: list[str]) -> str | None:
    """Match raw text to an active governed category (case-insensitive), falling back to 'Other' if present."""
    if not isinstance(raw, str) or not raw.strip() or not active:
        return None
    cleaned = ' '.join(raw.split()).casefold()
    for choice in active:
        if choice.casefold() == cleaned:
            return choice
    for choice in active:
        if choice.casefold() == 'other':
            return choice
    return None
