"""Client portal tables (schema v40), all new. A client is NOT a staff user: they have no row in `users`,
no role, and can reach exactly one project through that project's own web address."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class ProjectPortal(Base):
    """One portal per project. `slug` is the web-address label: <slug>.<STUDIOOS_PORTAL_DOMAIN>."""
    __tablename__ = 'project_portals'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), unique=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientContact(Base):
    """A person at the client who may sign in to one project's portal (by phone or email code)."""
    __tablename__ = 'client_contacts'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(10), default='', index=True)   # 10 digits, as elsewhere
    email: Mapped[str] = mapped_column(String(200), default='', index=True)  # lower-case
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientLoginCode(Base):
    """A one-time sign-in code. Only a keyed hash is stored, never the code."""
    __tablename__ = 'client_login_codes'
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey('client_contacts.id'), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    wrong_tries: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientSession(Base):
    """A signed-in client. Tied to one contact AND one project; checked against the web address on every call."""
    __tablename__ = 'client_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey('client_contacts.id'), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientDecision(Base):
    """A client's answer on one deliverable: approved, or changes requested. Append-only: a changed mind is a NEW row
    (the newest row for the current version wins) and nothing is ever edited or deleted. Each row is also written to the
    fingerprinted audit history. `record_version` is the version of the deliverable the client was looking at."""
    __tablename__ = 'client_decisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    record_id: Mapped[int] = mapped_column(ForeignKey('flexible_records.id'), index=True)
    record_version: Mapped[int] = mapped_column(Integer)
    contact_id: Mapped[int] = mapped_column(ForeignKey('client_contacts.id'), index=True)
    contact_name: Mapped[str] = mapped_column(String(150))        # the name as it was when the client answered
    decision: Mapped[str] = mapped_column(String(20))             # approved | changes_requested
    comment: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientChatMessage(Base):
    """The conversation between a client and the studio on ONE project. Separate from the internal project chat: nothing
    here is ever copied from, or into, internal chats. Append-only and fingerprinted per project (`chain_hash`)."""
    __tablename__ = 'client_chat_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    sender_kind: Mapped[str] = mapped_column(String(10))                       # client | staff
    contact_id: Mapped[int | None] = mapped_column(ForeignKey('client_contacts.id'), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    author: Mapped[str] = mapped_column(String(150), default='')              # the name as written at the time
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    chain_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


from sqlalchemy import event as _event  # noqa: E402
from sqlalchemy.orm import Session as _Session  # noqa: E402


@_event.listens_for(_Session, 'before_flush')
def _client_decisions_are_permanent(session, flush_context, instances):
    for o in session.dirty:
        if type(o) is ClientDecision and session.is_modified(o):
            raise PermissionError('A client decision is part of the permanent record and cannot be changed')
        if type(o) is ClientChatMessage and session.is_modified(o):
            from sqlalchemy import inspect as _insp
            hist = _insp(o).attrs.chain_hash.history
            was_hashed = (hist.deleted and hist.deleted[0]) or (not hist.added and o.chain_hash)
            others = [k for k in ('project_id', 'sender_kind', 'contact_id', 'user_id', 'author', 'body', 'created_at', 'chain_hash')
                      if _insp(o).attrs[k].history.has_changes()]
            if was_hashed and others:
                raise PermissionError('A chat message is part of the permanent record and cannot be changed')
    for o in session.deleted:
        if type(o) is ClientDecision:
            raise PermissionError('A client decision cannot be deleted')
        if type(o) is ClientChatMessage:
            raise PermissionError('A chat message cannot be deleted')
