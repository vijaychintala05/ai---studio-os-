"""View changes on the ticket path: create a view, change it (against the version it was based on), or roll back to an earlier
version. Every one is a draft ticket a person approves; the validator runs both when the draft is made and again when it is saved."""
from __future__ import annotations

import re

from sqlalchemy import select

from . import viewspec_core as core
from .db import ApprovalTicket, Config, TicketRecordEvent, User, add_audit
from .viewspec_catalog import for_db
from .viewspec_models import ViewSpecRow, ViewSpecVersion

VIEW_TYPES = {'view_create', 'view_change', 'view_rollback', 'view_setting'}
VIEW_FIELDS = {'view_create': {'spec', 'scope'}, 'view_change': {'view_id', 'base_version', 'spec'}, 'view_rollback': {'view_id', 'to_version'},
               'view_setting': {'key', 'value'}}
AUTO_KEY = 'view_auto_approve_personal'
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
    if kind == 'view_setting':
        if user.role != 'admin':
            raise ValueError('Only the owner can change the view approval setting')
        if d.get('key') != AUTO_KEY or d.get('value') not in ('on', 'off'):
            raise ValueError('The setting is view_auto_approve_personal, on or off')
        return
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
    if item.item_type == 'view_setting':
        row = db.get(Config, AUTO_KEY)
        if row:
            row.value = d['value']
        else:
            db.add(Config(key=AUTO_KEY, value=d['value']))
        db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type='setting', entity_id=0, operation='update'))
        add_audit(db, 'ticket_commit', 'setting', 0, f"Ticket #{item.ticket_id}, item #{item.id}: view auto-approve {d['value']}", actor=actor)
        db.flush()
        return {'type': 'setting', 'id': 0, 'item_id': item.id}
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


# ---------------------------------------------------------------- automatic approval of a person's own personal view
# Owner decision: a personal view (not shared, no client in its audience, no money field) is approved automatically once it passes
# validation, so people are not held up for their own screens. Views for everyone, for a role or for the system always need a person.
# Drafts opened by an AI client over MCP are never auto-approved: an AI proposes, a person approves.
MONEYISH = re.compile(r'amount|cost|rate|budget|price|paise|payment|bill|invoice|salary|balance|rupee|inr|gst|tax', re.I)


def auto_enabled(db):
    row = db.get(Config, AUTO_KEY)
    return (row.value if row else 'on') != 'off'


def _names_used(spec):
    names = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ('field', 'path', 'via', 'date_field', 'start_field', 'end_field'):
                    names.update(v if isinstance(v, list) else [v])
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)
    walk(spec)
    return {str(n) for n in names}


def spec_is_plain(spec):
    """No client audience and no field that looks like money."""
    if 'client' in ((spec.get('audience') or {}).get('roles') or []):
        return False
    return not any(MONEYISH.search(n) for n in _names_used(spec))


def auto_reason(db, user, kind, data):
    """None when this draft may be approved automatically, otherwise why not."""
    if not auto_enabled(db):
        return 'automatic approval is switched off'
    if user.role not in PROPOSERS:
        return 'your role may not change views'
    if kind == 'view_create':
        spec, scope_ok = data.get('spec'), data.get('scope', 'user') == 'user'
    elif kind in ('view_change', 'view_rollback'):
        row = db.get(ViewSpecRow, data.get('view_id')) if type(data.get('view_id')) is int else None
        scope_ok = bool(row and row.scope == 'user' and row.owner_user_id == user.id)
        if kind == 'view_change':
            spec = data.get('spec')
        else:
            v = _version(db, row, data.get('to_version')) if row and type(data.get('to_version')) is int else None
            spec = v.spec if v else None
    else:
        return 'this kind of change always needs a person'
    if not scope_ok:
        return 'only your own personal views are approved automatically'
    if not isinstance(spec, dict) or not spec_is_plain(spec):
        return 'it uses a money field or a client audience'
    return None


def auto_eligible_item(db, item):
    """can_review asks this only while a server-side automatic approval is running."""
    if item.item_type not in ('view_create', 'view_change', 'view_rollback'):
        return False
    try:
        user = _actor(db, item)
    except ValueError:
        return False
    return auto_reason(db, user, item.item_type, item.after_data or {}) is None


def maybe_auto_approve(db, user, draft, kind, data):
    """Called after a person drafts a view in the app. Returns {'auto_approved': bool, 'reason': text|None, 'result': saved or None}.
    The approval is made by the same code path as a person's own tap, recorded as theirs with a note saying it was automatic."""
    why = auto_reason(db, user, kind, data)
    if why:
        return {'auto_approved': False, 'reason': why, 'result': None}
    from fastapi import HTTPException
    from .intake_documents import evidence_operation
    from .main import ApproveSaveIn, _approve_and_save
    db.info['auto_approve_view'] = True
    try:
        with evidence_operation(db):
            result = _approve_and_save(draft['ticket_id'], ApproveSaveIn(confirmed=[], note='Approved automatically: a personal view with no money or client fields'), user, db)
        return {'auto_approved': True, 'reason': None, 'result': result}
    except HTTPException as e:
        db.rollback()
        return {'auto_approved': False, 'reason': str(e.detail), 'result': None}
    finally:
        db.info.pop('auto_approve_view', None)
