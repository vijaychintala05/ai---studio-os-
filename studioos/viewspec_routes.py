"""View APIs: the catalogue of view types, the views a person may see, one view with its versions, a dry-run check with a
deterministic diff, and a draft proposal (a ticket a person approves). Nothing here writes a live view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import viewspec_core as core
from .db import User
from .deps import get_db
from .security import current_user, permit
from .viewspec_catalog import for_db
from .viewspec_models import ViewSpecRow, ViewSpecVersion
from .viewspec_rules import PROPOSERS, VIEW_TYPES

router = APIRouter(prefix='/api/viewspecs', tags=['Views'])


class Proposal(BaseModel):
    kind: str
    data: dict


class Check(BaseModel):
    spec: dict


def _spec_of(db, row, version=None):
    n = version or row.current_version
    v = db.scalar(select(ViewSpecVersion).where(ViewSpecVersion.view_id == row.id, ViewSpecVersion.version == n))
    return v


def _visible(user, row, spec):
    if user.role == 'admin':
        return True
    if row.scope == 'user':
        return row.owner_user_id == user.id
    roles = (spec.get('audience') or {}).get('roles')
    return not roles or user.role in roles


def _row_or_404(db, user, key):
    row = db.scalar(select(ViewSpecRow).where(ViewSpecRow.spec_key == key, ViewSpecRow.archived_at.is_(None)))
    cur = _spec_of(db, row) if row else None
    if not row or not cur or not _visible(user, row, cur.spec):
        raise HTTPException(404, 'View not found')
    return row, cur


@router.get('/primitives')
def primitives(user: User = Depends(current_user)):
    """What a person (or an AI client) may build: the view types, the filter operators per kind of field, colour tokens, limits."""
    return {'spec_version': core.SPEC_VERSION, 'primitives': list(core.PRIMITIVES), 'field_kinds': list(core.KINDS),
            'operators_by_kind': {k: sorted(v) for k, v in core.OPS_BY_KIND.items()}, 'colour_tokens': list(core.TOKENS),
            'aggregates': list(core.AGG_FNS), 'actions': list(core.ACTIONS),
            'limits': {'bytes': core.MAX_BYTES, 'items': core.MAX_ITEMS, 'fields': core.MAX_FIELDS, 'filter_depth': core.MAX_DEPTH,
                       'colour_rules': core.MAX_COLOUR_RULES, 'relation_hops': core.MAX_PATH_HOPS}}


@router.get('')
def list_views(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for row in db.scalars(select(ViewSpecRow).where(ViewSpecRow.archived_at.is_(None)).order_by(ViewSpecRow.id)):
        cur = _spec_of(db, row)
        if cur and _visible(user, row, cur.spec):
            out.append({'key': row.spec_key, 'name': cur.spec.get('name'), 'primitive': cur.spec.get('primitive'), 'scope': row.scope,
                        'version': row.current_version})
    return out


@router.get('/{key}')
def get_view(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row, cur = _row_or_404(db, user, key)
    versions = db.scalars(select(ViewSpecVersion).where(ViewSpecVersion.view_id == row.id).order_by(ViewSpecVersion.version.desc())).all()
    return {'key': row.spec_key, 'scope': row.scope, 'version': row.current_version, 'spec': cur.spec,
            'versions': [{'version': v.version, 'hash': v.spec_hash, 'created_by': v.created_by, 'ticket_id': v.ticket_id,
                          'created_at': v.created_at.isoformat()} for v in versions]}


@router.get('/{key}/versions/{version}')
def get_version(key: str, version: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row, _ = _row_or_404(db, user, key)
    v = _spec_of(db, row, version)
    if not v:
        raise HTTPException(404, 'Version not found')
    return {'key': row.spec_key, 'version': v.version, 'spec': v.spec, 'hash': v.spec_hash}


@router.post('/validate')
def validate(v: Check, user: User = Depends(permit(*PROPOSERS)), db: Session = Depends(get_db)):
    """A dry run: every problem with the spec, and what would change against the stored version of the same view."""
    try:
        core.validate_spec(v.spec, for_db(db))
    except core.SpecError as e:
        return {'valid': False, 'errors': e.errors, 'diff': []}
    row = db.scalar(select(ViewSpecRow).where(ViewSpecRow.spec_key == v.spec['id']))
    cur = _spec_of(db, row) if row else None
    return {'valid': True, 'errors': [], 'base_version': row.current_version if row else None, 'diff': core.diff_specs(cur.spec if cur else None, v.spec),
            'fits': core.fitting_primitives(v.spec, for_db(db))}


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit(*PROPOSERS)), db: Session = Depends(get_db)):
    if v.kind not in VIEW_TYPES:
        raise HTTPException(400, 'Unknown kind of view change')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
