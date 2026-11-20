"""View changes on the ticket path: create a view, change it (against the version it was based on), or roll back to an earlier
version. Every one is a draft ticket a person approves; the validator runs both when the draft is made and again when it is saved."""
from __future__ import annotations

from sqlalchemy import select

from . import viewspec_core as core
from .db import ApprovalTicket, TicketRecordEvent, User, add_audit
from .viewspec_catalog import for_db
from .viewspec_models import ViewSpecRow, ViewSpecVersion

VIEW_TYPES = {'view_create', 'view_change', 'view_rollback'}
VIEW_FIELDS = {'view_create': {'spec', 'scope'}, 'view_change': {'view_id', 'base_version', 'spec'}, 'view_rollback': {'view_id', 'to_version'}}
PROPOSERS = ('admin', 'manager', 'architect', 'site_engineer', 'accounts')
BROAD_SCOPE_ROLES = ('admin', 'manager')          # a system or role view changes what other people see


def _actor(db, item):
    t = db.get(ApprovalTicket, item.ticket_id) if item.ticket_id else None
    u = db.get(User, t.submitter_id) if t and t.submitter_id else None
    if not u:
        raise ValueError('The person making this change is not known')
    return u


def _row(db, d):
    row = db.get(ViewSpecRow, d.get('view_id')) if type(d.get('view_id')) is int else None
    if not row or row.archived_at:
        raise ValueError('That view does not exist or was archived')
    return row


def _version(db, row, n):
    return db.scalar(select(ViewSpecVersion).where(ViewSpecVersion.view_id == row.id, ViewSpecVersion.version == n))


def _can_touch(user, row):
    return user.role in BROAD_SCOPE_ROLES or (row.scope == 'user' and row.owner_user_id == user.id)


def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in VIEW_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - VIEW_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    user = _actor(db, item)
    if user.role not in PROPOSERS:
        raise ValueError('Your role may not change views')
    if kind == 'view_create':
        scope = d.get('scope', 'user')
        if scope not in ('system', 'role', 'user'):
            raise ValueError('A view is for the system, a role or one user')
        if scope != 'user' and user.role not in BROAD_SCOPE_ROLES:
            raise ValueError('Only an owner or a manager can make a view for everyone or for a role')
        spec = core.validate_spec(d.get('spec'), for_db(db))
        if db.scalar(select(ViewSpecRow.id).where(ViewSpecRow.spec_key == spec['id'])):
            raise ValueError('A view with that id already exists; change it instead')
    elif kind == 'view_change':
        row = _row(db, d)
        if not _can_touch(user, row):
            raise ValueError('You may change only your own views')
        if d.get('base_version') != row.current_version:
            raise ValueError(f'The view has moved on to version {row.current_version}; base the change on that version')
        spec = core.validate_spec(d.get('spec'), for_db(db))
        if spec['id'] != row.spec_key:
            raise ValueError('A change cannot rename the view id')
    else:
        row = _row(db, d)
        if not _can_touch(user, row):
            raise ValueError('You may roll back only your own views')
        target = _version(db, row, d.get('to_version')) if type(d.get('to_version')) is int else None
        if not target or target.version == row.current_version:
            raise ValueError('Choose an earlier version of this view')
        core.validate_spec(target.spec, for_db(db))      # the old version must still be valid against today's record types


def apply(db, item, actor):
    validate(db, item)
    d = item.after_data
    user = _actor(db, item)
    if item.item_type == 'view_create':
        spec = d['spec']
        scope = d.get('scope', 'user')
        row = ViewSpecRow(spec_key=spec['id'], scope=scope, owner_user_id=user.id if scope == 'user' else None)
        db.add(row)
        db.flush()
        version, content, op = 1, spec, 'create'
    elif item.item_type == 'view_change':
        row = _row(db, d)
        version, content, op = row.current_version + 1, d['spec'], 'update'
    else:
        row = _row(db, d)
        version, content, op = row.current_version + 1, _version(db, row, d['to_version']).spec, 'update'
    row.current_version = version
    db.add(ViewSpecVersion(view_id=row.id, version=version, spec=content, spec_hash=core.spec_hash(content), created_by=actor, ticket_id=item.ticket_id))
    db.flush()
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type='view_spec', entity_id=row.id, operation=op))
    add_audit(db, 'ticket_commit', 'view_spec', row.id, f'Ticket #{item.ticket_id}, item #{item.id}: {item.item_type} (version {version})', actor=actor)
    db.flush()
    return {'type': 'view_spec', 'id': row.id, 'item_id': item.id, 'version': version}
