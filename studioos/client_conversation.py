"""Conversation records from the client chat: a summary, a checklist, and PROOF TAGS to the exact messages.

One ticket kind, `client_conversation_record`. A person (or the AI, as a draft) proposes it; a person approves it. On approval
ONE transaction creates the `conversation_record`, one `conversation_action` per checklist line, and the proof tags (each
keeps the message's fingerprint and a digest of its text). Later updates (mark done, attach the file that shows it was done)
use the ordinary record-update ticket on the action. Only the CLIENT chat can be recorded here, never internal chats.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy import select

from .access import can_access_project
from .client_portal_models import ClientChatMessage, ClientConversationProof
from .db import (ApprovalTicket, FlexibleRecord, Project, RecordType, TicketRecordEvent, UniversalRecordRevision, User, add_audit)

CONVERSATION_TYPES = {'client_conversation_record', 'client_conversation_add_items'}
CONVERSATION_FIELDS = {'client_conversation_record': {'project_id', 'title', 'summary', 'message_ids', 'shared_with_client', 'actions'},
                       'client_conversation_add_items': {'project_id', 'record_id', 'message_ids', 'actions'}}
PORTAL_RECORD_TYPES = {'client_deliverable', 'conversation_record', 'conversation_action'}   # only PROPOSERS may change these
ACTION_KEYS = {'text', 'owner', 'due_date', 'message_ids'}
PROPOSERS = ('admin', 'manager', 'architect')
MAX_MESSAGES = 60
MAX_ACTIONS = 30


def body_digest(body: str) -> str:
    return hashlib.sha256((body or '').encode('utf-8')).hexdigest()


def _actor(db, item):
    t = db.get(ApprovalTicket, item.ticket_id) if item.ticket_id else None
    u = db.get(User, t.submitter_id) if t and t.submitter_id else None
    if not u:
        raise ValueError('The person making this change is not known')
    return u


def _ids(value, label, limit):
    if not isinstance(value, list) or not 1 <= len(value) <= limit or any(type(x) is not int or x <= 0 for x in value) or len(set(value)) != len(value):
        raise ValueError(f'{label}: choose between 1 and {limit} different messages')
    return value


def _types(db):
    rec, act = db.get(RecordType, 'conversation_record'), db.get(RecordType, 'conversation_action')
    if not rec or rec.status != 'active' or not act or act.status != 'active':
        raise ValueError('Install the "client_portal" business pack first')
    return rec, act


def validate(db, item):
    d = item.after_data
    if item.item_type not in CONVERSATION_TYPES or not isinstance(d, dict) or set(d) - CONVERSATION_FIELDS[item.item_type]:
        raise ValueError('Unrecognized ticket data')
    user = _actor(db, item)
    if user.role not in PROPOSERS:
        raise ValueError('Your role may not record client conversations')
    _types(db)
    pid = d.get('project_id')
    project = db.get(Project, pid) if type(pid) is int else None
    if not project or project.deleted_at is not None or not can_access_project(db, user, pid):
        raise ValueError('Valid project required')
    if item.item_type == 'client_conversation_add_items':
        return _validate_add(db, d, pid)
    for key, low, high in (('title', 3, 150), ('summary', 3, 4000)):
        if not isinstance(d.get(key), str) or not low <= len(d[key].strip()) <= high:
            raise ValueError(f'{key} is required ({low} to {high} characters)')
    if type(d.get('shared_with_client')) is not bool:
        raise ValueError('Say whether the client should see this record')
    ids = _ids(d.get('message_ids'), 'Messages', MAX_MESSAGES)
    found = {m.id for m in db.scalars(select(ClientChatMessage).where(ClientChatMessage.id.in_(ids), ClientChatMessage.project_id == pid))}
    if found != set(ids):
        raise ValueError('Every tagged message must be in this project\'s client chat')
    _check_actions(db, pid, d.get('actions', []), set(ids))


def _check_actions(db, pid, actions, tagged, minimum=0):
    if not isinstance(actions, list) or not minimum <= len(actions) <= MAX_ACTIONS:
        raise ValueError(f'Between {minimum} and {MAX_ACTIONS} checklist items')
    for a in actions:
        if not isinstance(a, dict) or set(a) - ACTION_KEYS:
            raise ValueError('Unrecognized checklist item data')
        if not isinstance(a.get('text'), str) or not 3 <= len(a['text'].strip()) <= 500:
            raise ValueError('Each checklist item needs a description (3 to 500 characters)')
        cited = _ids(a.get('message_ids'), 'Each checklist item', MAX_MESSAGES)
        if not set(cited) <= set(tagged):
            raise ValueError('A checklist item can only cite messages that are tagged on the record')
        if a.get('owner') is not None:
            owner = db.get(User, a['owner']) if type(a['owner']) is int else None
            if not owner or not owner.active or not can_access_project(db, owner, pid):
                raise ValueError('The person doing a checklist item must be active staff on this project')
        if a.get('due_date') is not None:
            try:
                dt.date.fromisoformat(a['due_date'])
            except (TypeError, ValueError):
                raise ValueError('A due date must be a real date (YYYY-MM-DD)')


def _validate_add(db, d, pid):
    rec = db.get(FlexibleRecord, d.get('record_id')) if type(d.get('record_id')) is int else None
    if rec is None or rec.record_type != 'conversation_record' or rec.deleted_at or rec.project_id != pid:
        raise ValueError('That conversation record does not exist in this project')
    extra = d.get('message_ids', [])
    if extra:
        extra = _ids(extra, 'Messages', MAX_MESSAGES)
        found = {m.id for m in db.scalars(select(ClientChatMessage).where(ClientChatMessage.id.in_(extra), ClientChatMessage.project_id == pid))}
        if found != set(extra):
            raise ValueError('Every tagged message must be in this project\'s client chat')
    already = {p.message_id for p in db.scalars(select(ClientConversationProof).where(ClientConversationProof.record_id == rec.id))}
    _check_actions(db, pid, d.get('actions'), already | set(extra), minimum=1)


def _create(db, rt, pid, values, item, actor):
    from .universal_engine import normalize_values
    vals = normalize_values(rt.design['runtime_fields'], values)
    obj = FlexibleRecord(record_type=rt.key, project_id=pid, data=vals)
    db.add(obj)
    db.flush()
    db.add(UniversalRecordRevision(record_id=obj.id, version=1, before_data=None, after_data=dict(vals),
                                   definition_version=int((rt.design or {}).get('version', 1)), ticket_id=item.ticket_id, actor=actor))
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type='flexible_record', entity_id=obj.id, operation='create'))
    return obj


def _tag(db, pid, record_id, action_id, message_ids, item):
    for m in db.scalars(select(ClientChatMessage).where(ClientChatMessage.id.in_(message_ids)).order_by(ClientChatMessage.id)):
        if m.project_id != pid or not m.chain_hash:
            raise ValueError('A tagged message is missing its fingerprint')
        db.add(ClientConversationProof(project_id=pid, record_id=record_id, action_id=action_id, message_id=m.id,
                                       chain_hash=m.chain_hash, body_digest=body_digest(m.body), ticket_id=item.ticket_id))


def _apply_add(db, item, actor):
    d = item.after_data
    pid = d['project_id']
    _, act_type = _types(db)
    record = db.get(FlexibleRecord, d['record_id'])
    already = {p.message_id for p in db.scalars(select(ClientConversationProof).where(ClientConversationProof.record_id == record.id))}
    fresh = [m for m in d.get('message_ids', []) if m not in already]
    if fresh:
        _tag(db, pid, record.id, None, fresh, item)
    for a in d['actions']:
        values = {'text': a['text'].strip(), 'record': record.id, 'progress': 'Open'}
        if a.get('owner') is not None:
            values['owner'] = a['owner']
        if a.get('due_date') is not None:
            values['due_date'] = a['due_date']
        action = _create(db, act_type, pid, values, item, actor)
        _tag(db, pid, record.id, action.id, a['message_ids'], item)
    add_audit(db, 'client_conversation_items_added', 'flexible_record', record.id,
              f'Ticket #{item.ticket_id}: {len(d["actions"])} checklist item(s) added to conversation record #{record.id}', actor=actor)
    db.flush()
    return {'type': 'flexible_record', 'id': record.id, 'item_id': item.id}


def apply(db, item, actor):
    validate(db, item)
    if item.item_type == 'client_conversation_add_items':
        return _apply_add(db, item, actor)
    d = item.after_data
    pid = d['project_id']
    rec_type, act_type = _types(db)
    record = _create(db, rec_type, pid, {'title': d['title'].strip(), 'summary': d['summary'].strip(),
                                         'shared_with_client': d['shared_with_client']}, item, actor)
    _tag(db, pid, record.id, None, d['message_ids'], item)
    for a in d.get('actions', []):
        values = {'text': a['text'].strip(), 'record': record.id, 'progress': 'Open'}
        if a.get('owner') is not None:
            values['owner'] = a['owner']
        if a.get('due_date') is not None:
            values['due_date'] = a['due_date']
        action = _create(db, act_type, pid, values, item, actor)
        _tag(db, pid, record.id, action.id, a['message_ids'], item)
    add_audit(db, 'client_conversation_record', 'flexible_record', record.id,
              f'Ticket #{item.ticket_id}: conversation record "{d["title"].strip()}" with {len(d.get("actions", []))} checklist item(s) '
              f'and {len(d["message_ids"])} tagged message(s)', actor=actor)
    db.flush()
    return {'type': 'flexible_record', 'id': record.id, 'item_id': item.id}
