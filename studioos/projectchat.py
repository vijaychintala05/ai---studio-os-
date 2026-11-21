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


# ---------------------------------------------------------------- offering to move a project message to the team chat
# Owner's answer (16 Nov): a person's own tasks and notes stay private; anything about a project or other people belongs in that project's
# chat. StudioOS never posts for the person: when a private message names exactly one project they are on, is a statement (not a question
# and not something that became a draft) and they may use the team chat, the reply carries an offer, and only their own tap sends it.
QUESTION_START = ('how ', 'what ', 'which ', 'who ', 'when ', 'where ', 'why ', 'show ', 'list ', 'give me', 'tell me', 'can you', 'could you', 'is there', 'are there', 'do we', 'does ')


def team_chat_offer(db, user, message):
    """-> {'project_id', 'name', 'body'} or None."""
    text = (message or '').strip()
    low = text.casefold()
    if user.role not in CHAT_ROLES or len(text) < 8 or len(text) > 2000 or text.endswith('?') or low.startswith(QUESTION_START):
        return None
    named, rest = [], low
    for p in sorted(db.scalars(select(Project).where(Project.deleted_at.is_(None))).all(), key=lambda x: -len(x.name)):
        if p.name.casefold() in rest:                                              # longest names first, each mention counted once, so
            named.append(p)                                                        # "Villa A" inside "Villa A Annex" is not a second project
            rest = rest.replace(p.name.casefold(), ' ')
    if len(named) != 1 or not can_access_project(db, user, named[0].id):
        return None
    return {'project_id': named[0].id, 'name': named[0].name, 'body': text}
