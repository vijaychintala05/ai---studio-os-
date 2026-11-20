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
from .viewspec_rules import PROPOSERS, VIEW_TYPES, maybe_auto_approve

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


@router.get('/templates')
def templates(user: User = Depends(permit(*PROPOSERS)), db: Session = Depends(get_db)):
    """Ready-made views this firm can use (only those whose record types and fields exist here), and whether each is already in use."""
    from . import view_templates as T
    have = set(db.scalars(select(ViewSpecRow.spec_key)))
    return [{'key': t['key'], 'title': t['title'], 'about': t['about'], 'primitive': t['spec']['primitive'], 'spec_id': t['spec']['id'], 'in_use': t['spec']['id'] in have}
            for t in T.available(for_db(db))]


class TemplateUse(BaseModel):
    scope: str = 'user'


@router.post('/templates/{key}/propose')
def propose_template(key: str, v: TemplateUse, user: User = Depends(permit(*PROPOSERS)), db: Session = Depends(get_db)):
    """Draft a ticket that adds a ready-made view. A person approves it; nothing goes live from here. A personal copy gets the person's own id."""
    from . import view_templates as T
    t = T.by_key(key)
    if not t or t['key'] not in {x['key'] for x in T.available(for_db(db))}:
        raise HTTPException(404, 'That template is not available here')
    spec = dict(t['spec'])
    if v.scope == 'user':
        spec['id'] = f"{spec['id']}.u{user.id}"[:60]
    from .main import _manual_draft
    data = {'spec': spec, 'scope': v.scope}
    try:
        draft = _manual_draft(db, user, 'view_create', data, evidence=f"Ready-made view: {t['title']}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**draft, **maybe_auto_approve(db, user, draft, 'view_create', data)}


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


@router.get('/{key}/run')
def run_view(key: str, project_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Run a stored view for this person through the report engine (so only records they may see are counted) and shape it for the
    browser. project_id fills the view's project context, if it has one."""
    row, cur = _row_or_404(db, user, key)
    spec = cur.spec
    try:
        report, display = core.spec_to_report(spec, {'project_id': project_id} if project_id else {})
    except core.Unsupported as e:
        raise HTTPException(422, str(e))
    from . import views_wiring as W
    try:
        shown = W.show(db, user, report, display)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {'key': row.spec_key, 'version': row.current_version, 'name': spec['name'], 'primitive': spec['primitive'], 'shown': shown}


class PreviewIn(BaseModel):
    spec: dict | None = None
    view_id: int | None = None
    to_version: int | None = None
    as_role: str | None = None
    project_id: int | None = None


def _preview_user(user, as_role):
    """The person themselves, or (owner only) a stand-in for a role: that role's reach with no project assignments of its own."""
    if not as_role:
        return user
    if user.role != 'admin':
        raise HTTPException(403, 'Only the owner can preview as another role')
    if as_role not in core.ROLES or as_role == 'client':
        raise HTTPException(422, 'Unknown role')
    return User(id=-1, username='preview', display_name='Preview', role=as_role, active=True, password_hash='')


def preview(db, user, spec, as_role=None, project_id=None, base_row=None):
    """A dry run of a spec that is not stored: problems, the diff against the stored version, who may see it and what it would show.
    Nothing is written. Used by the approval ticket, the MCP preview tool and the owner's role preview."""
    who = _preview_user(user, as_role)
    out = {'valid': True, 'errors': [], 'warnings': [], 'diff': [], 'shown': None, 'as_role': as_role}
    try:
        core.validate_spec(spec, for_db(db))
    except core.SpecError as e:
        return {**out, 'valid': False, 'errors': e.errors}
    row = base_row or db.scalar(select(ViewSpecRow).where(ViewSpecRow.spec_key == spec['id']))
    cur = _spec_of(db, row) if row else None
    out['base_version'] = row.current_version if row else None
    out['diff'] = core.diff_specs(cur.spec if cur else None, spec)
    roles = (spec.get('audience') or {}).get('roles')
    if roles and who.role not in roles and who.role != 'admin':
        out['warnings'].append(f'The audience of this view does not include {who.role.replace("_", " ")}, so they would not see it')
    try:
        report, display = core.spec_to_report(spec, {'project_id': project_id} if project_id else {})
        from . import views_wiring as W
        out['shown'] = W.show(db, who, report, display)
    except core.Unsupported as e:
        out['warnings'].append(str(e))
    except ValueError as e:
        out['warnings'].append(str(e))
    return out


@router.post('/preview')
def preview_route(v: PreviewIn, user: User = Depends(permit(*PROPOSERS)), db: Session = Depends(get_db)):
    """What a draft would look like, for the approver: from a spec, or from a view and a version to roll back to."""
    spec, base = v.spec, None
    if spec is None:
        row = db.get(ViewSpecRow, v.view_id) if v.view_id else None
        target = _spec_of(db, row, v.to_version) if row and v.to_version else None
        if not target:
            raise HTTPException(404, 'Nothing to preview')
        spec, base = target.spec, row
    return preview(db, user, spec, v.as_role, v.project_id, base)


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
        draft = _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**draft, **maybe_auto_approve(db, user, draft, v.kind, v.data)}
