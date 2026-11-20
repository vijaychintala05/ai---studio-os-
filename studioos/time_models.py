"""v0.18 time and workload tables (schema v29). All new, so the upgrade is additive.

Time entries, leave, holidays, rates and estimates are written only by approved ticket items (see time_rules.py).
Only the timer's running state is written directly: it holds no business fact until stopping drafts a ticket.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class TimeEntry(Base):
    """Minutes worked on a task or a named general activity. Approved entries are frozen and carry the rate in force."""
    __tablename__ = 'time_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('tasks.id'), nullable=True, index=True)
    activity: Mapped[str] = mapped_column(String(80), default='')
    work_date: Mapped[str] = mapped_column(String(10), index=True)
    minutes: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(10), default='manual')          # manual | timer
    status: Mapped[str] = mapped_column(String(12), default='draft', index=True)  # draft | submitted | approved | rejected
    rate_paise_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TimeEntryLog(Base):
    """Append-only: every step an entry went through, with who and why."""
    __tablename__ = 'time_entry_log'
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(100), default='')
    reason: Mapped[str] = mapped_column(Text, default='')
    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CostRate(Base):
    """Cost per hour in paise from an effective date. Rows are only added, so history keeps the rate of the time."""
    __tablename__ = 'cost_rates'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    rate_paise_per_hour: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkHoliday(Base):
    __tablename__ = 'work_holidays'
    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkLeave(Base):
    __tablename__ = 'work_leave'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(20), default='leave')
    note: Mapped[str] = mapped_column(Text, default='')
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskEstimate(Base):
    """The planned effort of a task in minutes: what the workload warning spreads across the working days."""
    __tablename__ = 'task_estimates'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), primary_key=True)
    minutes: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str] = mapped_column(String(100), default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TimerRun(Base):
    """A running or finished stopwatch. Stopping drafts a time entry ticket; the timer alone records no business fact."""
    __tablename__ = 'time_timers'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey('tasks.id'), nullable=True)
    activity: Mapped[str] = mapped_column(String(80), default='')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discarded: Mapped[bool] = mapped_column(Boolean, default=False)
