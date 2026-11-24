"""Conversation records, seen from three sides: staff propose them, staff list them, and the client reads the shared ones.

Every proof tag is re-checked each time it is shown: the tagged message must still carry the fingerprint and text digest it had
when it was tagged, AND the project's whole client thread must still verify. A tag that fails is shown as NOT verified.
A client sees a record only when staff marked it "show to the client"; they never see unshared records, other projects' records,
or files that are not approved uploads of this project.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .access import can_access_project
from .client_conversation import PROPOSERS, body_digest
from .client_portal_chat import verify_thread
from .client_portal_content import client_visible, DELIVERABLE_TYPE
from .client_portal_models import ClientChatMessage, ClientConversationProof
from .client_portal_routes import PortalContext, portal_context
from .client_portal_content import current_version
from .db import Document, FlexibleRecord, Project, SessionLocal, UniversalRecordRevision, User, add_audit
from .deps import get_db
from .security import permit

router = APIRouter()
RECORD_TYPE, ACTION_TYPE = 'conversation_record', 'conversation_action'


class ActionIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    owner: int | None = None
    due_date: str | None = None
    message_ids: list[int] = Field(min_length=1, max_length=60)


class RecordIn(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    summary: str = Field(min_length=3, max_length=4000)
    message_ids: list[int] = Field(min_length=1, max_length=60)
    shared_with_client: bool = False
    actions: list[ActionIn] = Field(default_factory=list, max_length=30)


def _live(db, project_id, type_key):
    return [r for r in db.scalars(select(FlexibleRecord).where(
        FlexibleRecord.record_type == type_key, FlexibleRecord.project_id == project_id,
        FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id.desc()).limit(2000))]


def _proof_ok(proof, message, thread_ok):
    return bool(thread_ok and message is not None and message.project_id == proof.project_id
                and message.chain_hash == proof.chain_hash and body_digest(message.body) == proof.body_digest)


def _build(db, project_id, records, thread_ok, for_client):
    """-> list of records with their checklist and proof messages."""
    ids = [r.id for r in records]
    proofs = db.scalars(select(ClientConversationProof).where(ClientConversationProof.record_id.in_(ids)).order_by(
        ClientConversationProof.message_id)).all() if ids else []
    messages = {m.id: m for m in db.scalars(select(ClientChatMessage).where(
        ClientChatMessage.id.in_({p.message_id for p in proofs})))} if proofs else {}
    actions = [a for a in _live(db, project_id, ACTION_TYPE) if (a.data or {}).get('record') in ids]
    users = {u.id: (u.display_name or u.username) for u in db.scalars(select(User).where(User.id.in_(
        {(a.data or {}).get('owner') for a in actions if (a.data or {}).get('owner')})))} if actions else {}
    out = []
    for rec in records:
        mine = [p for p in proofs if p.record_id == rec.id]
        msgs = {}
        for p in mine:
            m = messages.get(p.message_id)
            if m is not None:
                msgs[p.message_id] = {'id': m.id, 'from': m.sender_kind, 'author': m.author, 'at': m.created_at.isoformat(),
                                      'body': m.body, 'verified': _proof_ok(p, m, thread_ok)}
        acts = []
        for a in sorted((x for x in actions if (x.data or {}).get('record') == rec.id), key=lambda x: x.id):
            d = a.data or {}
            item = {'id': a.id, 'text': d.get('text', ''), 'owner': users.get(d.get('owner'), ''), 'due_date': d.get('due_date', ''),
                    'state': d.get('progress', 'Open'), 'note': d.get('resolution_note', ''),
                    'message_ids': [p.message_id for p in mine if p.action_id == a.id]}
            doc = db.get(Document, d['resolution_file']) if type(d.get('resolution_file')) is int else None
            item['file'] = {'id': a.id, 'name': doc.name} if doc is not None and doc.project_id == project_id else None
            dv = db.get(FlexibleRecord, d['resolution_deliverable']) if type(d.get('resolution_deliverable')) is int else None
            ok_dv = dv is not None and dv.record_type == DELIVERABLE_TYPE and dv.project_id == project_id and not dv.deleted_at
            if for_client:
                ok_dv = ok_dv and client_visible(dv)       # a client is only pointed at files they may actually open
            item['deliverable'] = {'id': dv.id, 'title': (dv.data or {}).get('title', '')} if ok_dv else None
            acts.append(item)
        last = db.scalar(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id == rec.id).order_by(
            UniversalRecordRevision.version.desc()).limit(1))
        row = {'id': rec.id, 'title': (rec.data or {}).get('title', ''), 'summary': (rec.data or {}).get('summary', ''),
               'created': rec.created_at.isoformat() if rec.created_at else '',
               'updated': last.created_at.isoformat() if last is not None and last.version > 1 else '', 'actions': acts,
               'messages': [msgs[k] for k in sorted(msgs)]}
        if not for_client:
            row['shared_with_client'] = (rec.data or {}).get('shared_with_client') is True
        out.append(row)
    return out


# ------------------------------------------------------------------ staff

def _staff_project(db, user, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at is not None or not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')
    return p


@router.post('/api/portal/{project_id}/conversation-records')
def staff_propose(project_id: int, v: RecordIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    """Makes a DRAFT ticket. Nothing is saved until a person approves it."""
    _staff_project(db, user, project_id)
    from .main import _manual_draft
    data = {'project_id': project_id, 'title': v.title, 'summary': v.summary, 'message_ids': v.message_ids,
            'shared_with_client': v.shared_with_client, 'actions': [a.model_dump() for a in v.actions]}
    try:
        return _manual_draft(db, user, 'client_conversation_record', data, evidence='Conversation record drafted from the client chat')
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get('/api/portal/{project_id}/conversations')
def staff_list(project_id: int, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    thread = verify_thread(db, project_id)
    return {'thread_ok': thread['ok'], 'records': _build(db, project_id, _live(db, project_id, RECORD_TYPE), thread['ok'], False)}


class RecordEditIn(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=150)
    summary: str | None = Field(default=None, min_length=3, max_length=4000)
    shared_with_client: bool | None = None


class ActionEditIn(BaseModel):
    text: str | None = Field(default=None, min_length=3, max_length=500)
    owner: int | None = None
    due_date: str | None = None
    progress: Literal['Open', 'Done'] | None = None
    resolution_note: str | None = Field(default=None, max_length=4000)
    resolution_file: int | None = None
    resolution_deliverable: int | None = None
    clear: list[Literal['owner', 'due_date', 'resolution_note', 'resolution_file', 'resolution_deliverable']] = Field(default_factory=list)


class AddItemsIn(BaseModel):
    message_ids: list[int] = Field(default_factory=list, max_length=60)
    actions: list[ActionIn] = Field(min_length=1, max_length=30)


def _own_record(db, project_id, record_id, type_key):
    rec = db.get(FlexibleRecord, record_id)
    if rec is None or rec.record_type != type_key or rec.deleted_at or rec.project_id != project_id:
        raise HTTPException(404, 'Not found')
    return rec


def _draft_update(db, user, rec, type_key, values):
    """A DRAFT edit ticket against the version the editor saw. Nothing changes until a person approves it."""
    from .main import _manual_draft
    data = {'type_key': type_key, 'record_id': rec.id, 'project_id': rec.project_id,
            'expected_version': current_version(db, rec), 'values': values}
    try:
        return _manual_draft(db, user, 'metadata_record_update', data, evidence='Client portal record edit')
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post('/api/portal/{project_id}/conversations/{record_id}/edit')
def staff_edit_record(project_id: int, record_id: int, v: RecordEditIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    rec = _own_record(db, project_id, record_id, RECORD_TYPE)
    changes = v.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, 'Nothing to change')
    return _draft_update(db, user, rec, RECORD_TYPE, {**(rec.data or {}), **changes})


@router.post('/api/portal/{project_id}/conversation-actions/{action_id}/edit')
def staff_edit_action(project_id: int, action_id: int, v: ActionEditIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    act = _own_record(db, project_id, action_id, ACTION_TYPE)
    changes = v.model_dump(exclude_none=True, exclude={'clear'})
    if not changes and not v.clear:
        raise HTTPException(422, 'Nothing to change')
    values = {**(act.data or {}), **changes}
    for name in v.clear:
        values.pop(name, None)
    return _draft_update(db, user, act, ACTION_TYPE, values)


@router.post('/api/portal/{project_id}/conversations/{record_id}/add-items')
def staff_add_items(project_id: int, record_id: int, v: AddItemsIn, user=Depends(permit(*PROPOSERS)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    _own_record(db, project_id, record_id, RECORD_TYPE)
    from .main import _manual_draft
    data = {'project_id': project_id, 'record_id': record_id, 'message_ids': v.message_ids, 'actions': [a.model_dump() for a in v.actions]}
    try:
        return _manual_draft(db, user, 'client_conversation_add_items', data, evidence='Checklist items added to a conversation record')
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(422, str(e))


# ------------------------------------------------------------------ the client (READ ONLY: no route below changes anything about a record)

def _shared(db, project_id):
    return [r for r in _live(db, project_id, RECORD_TYPE) if (r.data or {}).get('shared_with_client') is True]


@router.get('/portal-api/conversations')
def client_list(ctx: PortalContext = Depends(portal_context)):
    with SessionLocal() as db:
        thread = verify_thread(db, ctx.project_id)
        return {'records': _build(db, ctx.project_id, _shared(db, ctx.project_id), thread['ok'], True)}


@router.get('/portal-api/conversations/actions/{action_id}/file')
def client_action_file(action_id: int, ctx: PortalContext = Depends(portal_context)):
    from .intake_documents import approved_source
    with SessionLocal() as db:
        action = db.get(FlexibleRecord, action_id)
        d = (action.data or {}) if action is not None else {}
        parent = db.get(FlexibleRecord, d.get('record')) if type(d.get('record')) is int else None
        doc = db.get(Document, d['resolution_file']) if type(d.get('resolution_file')) is int else None
        if (action is None or action.record_type != ACTION_TYPE or action.deleted_at or action.project_id != ctx.project_id
                or parent is None or parent.record_type != RECORD_TYPE or parent.deleted_at or parent.project_id != ctx.project_id
                or (parent.data or {}).get('shared_with_client') is not True
                or doc is None or doc.project_id != ctx.project_id):
            raise HTTPException(404, 'Not found')
        try:
            path, filename, _ = approved_source(db, doc)
        except ValueError:
            raise HTTPException(404, 'Not found')
        add_audit(db, 'portal_file_opened', 'conversation_action', action.id,
                  f'{ctx.contact_name} opened the file for "{d.get("text", "")[:80]}"', actor=f'client:{ctx.contact_id}')
        db.commit()
    return FileResponse(path, media_type='application/octet-stream', filename=filename,
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox"})
