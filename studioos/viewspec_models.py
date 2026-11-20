"""Stored views (schema v34): one row per view and an immutable row per version. Every change, including a rollback, adds a version
through an approved ticket; nothing is ever edited in place. New tables only."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import JSON_TYPE, Base, now


class ViewSpecRow(Base):
    __tablename__ = 'view_specs'
    id: Mapped[int] = mapped_column(primary_key=True)
    spec_key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(10), default='user')            # system | role | user
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ViewSpecVersion(Base):
    __tablename__ = 'view_spec_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    view_id: Mapped[int] = mapped_column(ForeignKey('view_specs.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON_TYPE)
    spec_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(100), default='')
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey('approval_tickets.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('view_id', 'version', name='ux_view_spec_version'),)
