"""v0.21 tables (schema v31), all new. Budgets and breach acknowledgements are written only by approved ticket items."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class WorkBudget(Base):
    """A cost budget in paise for a project, one of its stages or one of its tasks. Replaced by retiring and adding."""
    __tablename__ = 'work_budgets'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    scope: Mapped[str] = mapped_column(String(10))                 # project | stage | task
    ref_id: Mapped[int] = mapped_column(Integer, default=0)        # stage id or task id; 0 for the project
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    set_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetBreach(Base):
    """A logged breach: actual cost passed a budget. One open row per budget until someone acknowledges it."""
    __tablename__ = 'budget_breaches'
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey('work_budgets.id'), index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    actual_paise: Mapped[int] = mapped_column(BigInteger)
    budget_paise: Mapped[int] = mapped_column(BigInteger)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acknowledged_by: Mapped[str] = mapped_column(String(100), default='')
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default='')
