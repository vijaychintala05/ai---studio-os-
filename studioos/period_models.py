"""v0.20 tables (schema v30), all new: lock areas, legal holds, and an empty tax profile for parties.
Written only by approved ticket items (see period_rules.py). Locks and holds are retired, never deleted."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class PeriodAreaLock(Base):
    __tablename__ = 'period_area_locks'
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey('accounting_entities.id'), index=True)
    year_month: Mapped[str] = mapped_column(String(7))
    area: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(Text, default='')
    locked_by: Mapped[str] = mapped_column(String(100), default='')
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[str] = mapped_column(String(100), default='')
    reopen_reason: Mapped[str] = mapped_column(Text, default='')


class LegalHold(Base):
    __tablename__ = 'legal_holds'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    reason: Mapped[str] = mapped_column(Text)
    placed_by: Mapped[str] = mapped_column(String(100), default='')
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str] = mapped_column(String(100), default='')
    release_reason: Mapped[str] = mapped_column(Text, default='')


class PartyTaxProfile(Base):
    """An empty field set for later tax rules: only the registration type is held, with its effective date. No logic reads it yet."""
    __tablename__ = 'party_tax_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(ForeignKey('parties.id'), index=True)
    registration_type: Mapped[str] = mapped_column(String(20), default='')
    effective_from: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
