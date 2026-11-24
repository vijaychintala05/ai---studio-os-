"""Client portal step 4: the chat between a client and the studio, one thread per project.

Rules this file keeps:
- It is NOT the internal project chat (`projectchat.py`) and never reads or writes it. Internal talk cannot leak here.
- Nothing a client types is ever given to the AI by this module: it has no AI imports and nothing else reads this table.
- Messages are plain text, never edited or deleted, and fingerprinted per project (each fingerprint covers the one before it).
- Clients see only their own project's thread (the project comes from the web address); staff need access to the project.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from .access import can_access_project
from .chain import GENESIS, norm_time
from .client_portal_models import ClientChatMessage
from .client_portal_routes import PortalContext, portal_context
from .db import SessionLocal, Project, add_audit, lock_history_chain, now
from .deps import get_db
from .security import permit

router = APIRouter()

PAGE = 50
CLIENT_PER_HOUR = 30
STAFF_ROLES = ('admin', 'manager', 'architect')     # who may speak to the client for the studio


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _clean(body: str) -> str:
    text = (body or '').replace('\x00', '').strip()
    if not text:
        raise HTTPException(422, 'Write a message first')
    return text


def _fingerprint(previous: str | None, m: ClientChatMessage) -> str:
    payload = json.dumps(['client_chat_messages', m.id, m.project_id, m.sender_kind, m.contact_id, m.user_id, m.author, m.body,
                          norm_time(m.created_at)], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(((previous or GENESIS) + '|' + payload).encode()).hexdigest()


def _append(db, project_id, **fields) -> ClientChatMessage:
    lock_history_chain(db)      # one writer at a time on PostgreSQL, so two messages never fork a project's chain
    m = ClientChatMessage(project_id=project_id, **fields)
    db.add(m)
    db.flush()
    previous = db.scalar(select(ClientChatMessage.chain_hash).where(
        ClientChatMessage.project_id == project_id, ClientChatMessage.id < m.id, ClientChatMessage.chain_hash.is_not(None)
    ).order_by(ClientChatMessage.id.desc()).limit(1))
    m.chain_hash = _fingerprint(previous, m)
    return m


def _page(db, project_id, after):
    stmt = select(ClientChatMessage).where(ClientChatMessage.project_id == project_id)
    if after:
        return db.scalars(stmt.where(ClientChatMessage.id > after).order_by(ClientChatMessage.id).limit(PAGE)).all()
    return list(reversed(db.scalars(stmt.order_by(ClientChatMessage.id.desc()).limit(PAGE)).all()))


def _out(m):
    # No user or contact ids: the client does not learn staff accounts, and staff see names as written.
    return {'id': m.id, 'from': m.sender_kind, 'author': m.author, 'body': m.body, 'at': m.created_at.isoformat()}


# ------------------------------------------------------------------ the client's side

@router.get('/portal-api/chat')
def client_read(after: int = 0, ctx: PortalContext = Depends(portal_context)):
    with SessionLocal() as db:
        return {'messages': [_out(m) for m in _page(db, ctx.project_id, after)]}


@router.post('/portal-api/chat')
def client_post(v: MessageIn, ctx: PortalContext = Depends(portal_context)):
    body = _clean(v.body)
    with SessionLocal() as db:
        since = now() - dt.timedelta(hours=1)
        if db.scalar(select(func.count(ClientChatMessage.id)).where(
                ClientChatMessage.contact_id == ctx.contact_id, ClientChatMessage.created_at >= since)) >= CLIENT_PER_HOUR:
            raise HTTPException(429, 'Too many messages in the last hour. Please try again later.')
        m = _append(db, ctx.project_id, sender_kind='client', contact_id=ctx.contact_id, author=ctx.contact_name, body=body)
        add_audit(db, 'client_chat', 'project', ctx.project_id, f'Client message #{m.id} posted', actor=f'client:{ctx.contact_id}')
        db.commit()
        return _out(m)


# ------------------------------------------------------------------ the studio's side

def _staff_project(db, user, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at is not None or not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')      # not confirming that a project you cannot see exists
    return p


@router.get('/api/portal/{project_id}/chat')
def staff_read(project_id: int, after: int = 0, user=Depends(permit(*STAFF_ROLES)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    return {'messages': [_out(m) for m in _page(db, project_id, after)]}


@router.post('/api/portal/{project_id}/chat')
def staff_post(project_id: int, v: MessageIn, user=Depends(permit(*STAFF_ROLES)), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    m = _append(db, project_id, sender_kind='staff', user_id=user.id, author=user.display_name or user.username, body=_clean(v.body))
    add_audit(db, 'client_chat', 'project', project_id, f'Studio message #{m.id} to the client posted', actor=user.username)
    db.commit()
    return _out(m)


def verify_thread(db, project_id: int) -> dict:
    """Re-computes every fingerprint in one project's client thread and reports the first message that does not match."""
    previous, first_bad, checked = None, None, 0
    for m in db.scalars(select(ClientChatMessage).where(ClientChatMessage.project_id == project_id).order_by(ClientChatMessage.id)):
        if m.chain_hash != _fingerprint(previous, m) and first_bad is None:
            first_bad = m.id
        previous = m.chain_hash
        checked += 1
    return {'checked': checked, 'ok': first_bad is None, 'first_broken_id': first_bad}


@router.get('/api/portal/{project_id}/chat/verify')
def staff_verify(project_id: int, user=Depends(permit('admin', 'manager')), db=Depends(get_db)):
    _staff_project(db, user, project_id)
    return verify_thread(db, project_id)
