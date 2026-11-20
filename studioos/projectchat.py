"""Project chat (App Flows map): one shared chat per project that the whole project team reads. Project work is talked about here; a
person's private notes stay in their own chat. Plain text only, no AI, no business record is written (a message is not a ticket).
Who may read and post: anyone who can see the project except Accounts (who see Money only) and viewers. At most 60 messages an hour
per person. Messages are never edited or deleted here (a record of what the team said), and an author's name is kept as written."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .access import can_access_project
from .db import Base, Project, User, add_audit, now
from .deps import get_db
from .security import current_user

router = APIRouter(prefix='/api/projects', tags=['Project chat'])

CHAT_ROLES = ('admin', 'manager', 'architect', 'site_engineer')
PER_HOUR = 60
PAGE = 50


class ProjectChatMessage(Base):
    __tablename__ = 'project_chat_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    author: Mapped[str] = mapped_column(String(150), default='')
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _project_or_404(db, user, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at or user.role not in CHAT_ROLES or not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')        # not confirming that a project you cannot see exists
    return p


def _out(m):
    return {'id': m.id, 'author': m.author, 'user_id': m.user_id, 'body': m.body, 'created_at': m.created_at.isoformat()}


@router.get('/{project_id}/chat')
def read_chat(project_id: int, after: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, user, project_id)
    stmt = select(ProjectChatMessage).where(ProjectChatMessage.project_id == project_id)
    if after:
        rows = db.scalars(stmt.where(ProjectChatMessage.id > after).order_by(ProjectChatMessage.id).limit(PAGE)).all()
    else:
        rows = list(reversed(db.scalars(stmt.order_by(ProjectChatMessage.id.desc()).limit(PAGE)).all()))
    return {'project_id': project_id, 'messages': [_out(m) for m in rows]}


@router.post('/{project_id}/chat')
def post_message(project_id: int, v: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, user, project_id)
    body = v.body.strip()
    if not body:
        raise HTTPException(422, 'Write a message first')
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    if db.scalar(select(func.count(ProjectChatMessage.id)).where(ProjectChatMessage.user_id == user.id, ProjectChatMessage.created_at >= since)) >= PER_HOUR:
        raise HTTPException(429, f'Too many messages in the last hour (limit {PER_HOUR})')
    m = ProjectChatMessage(project_id=project_id, user_id=user.id, author=user.display_name or user.username, body=body)
    db.add(m)
    db.flush()
    add_audit(db, 'project_chat', 'project', project_id, f'Message #{m.id} posted', actor=user.username)
    db.commit()
    return _out(m)
