"""v0.17 work rules: tables (schema v28). Every table is new, so the upgrade is additive and existing tasks are untouched.

Stages, links, workflows, templates and baselines are business data: they are written only by approved ticket
items (see work_rules.py), never directly by a route. Workflows and templates keep their rules as data in one
JSON definition, so changing a rule is an approved data update and not a release.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, JSON_TYPE, now


class ProjectStage(Base):
    """A stage of a project (for example a design or a site phase). client_visible decides what client updates may include."""
    __tablename__ = 'project_stages'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    client_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    template_key: Mapped[str] = mapped_column(String(60), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskStructure(Base):
    """Where a task sits: its stage, its parent task (a subtask has one), its start date and its client-visible flag."""
    __tablename__ = 'task_structure'
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), primary_key=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey('project_stages.id'), nullable=True, index=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey('tasks.id'), nullable=True, index=True)
    client_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[str] = mapped_column(String(30), default='')
    template_key: Mapped[str] = mapped_column(String(60), default='')
    template_task_key: Mapped[str] = mapped_column(String(60), default='')


class TaskLink(Base):
    """A dependency between two tasks. hard links block; soft links only warn; related and duplicate restrict nothing.
    A link is retired, never deleted, so the history stays."""
    __tablename__ = 'task_links'
    id: Mapped[int] = mapped_column(primary_key=True)
    predecessor_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    successor_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    link_type: Mapped[str] = mapped_column(String(20), default='finish_to_start')
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str] = mapped_column(String(100), default='')


class WorkWorkflow(Base):
    """A named status machine for tasks or for one record type. The definition (statuses and named transitions) is data."""
    __tablename__ = 'work_workflows'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    applies_to: Mapped[dict] = mapped_column(JSON_TYPE)      # {"target":"task"} or {"target":"record","type":"...","status_field":"..."}
    status: Mapped[str] = mapped_column(String(12), default='live', index=True)   # live | retired
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkTemplate(Base):
    """A project template: stages, tasks with day offsets, and the links between them."""
    __tablename__ = 'work_templates'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), default='live', index=True)   # live | retired
    definition: Mapped[dict] = mapped_column(JSON_TYPE)
    created_by: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectBaseline(Base):
    """Append-only: the dates of a project's tasks at the moment it was frozen. Later slips show as variance."""
    __tablename__ = 'project_baselines'
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
    label: Mapped[str] = mapped_column(String(120), default='')
    data: Mapped[dict] = mapped_column(JSON_TYPE)
    frozen_by: Mapped[str] = mapped_column(String(100), default='')
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkDeletion(Base):
    """The recycle list: a deleted task stays restorable until restore_until."""
    __tablename__ = 'work_deletions'
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    deleted_by: Mapped[str] = mapped_column(String(100), default='')
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    restore_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, default='')
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[str] = mapped_column(String(100), default='')


class WorkTransitionLog(Base):
    """Append-only: every status change made through a named transition, with who and what evidence."""
    __tablename__ = 'work_transition_log'
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_key: Mapped[str] = mapped_column(String(60), index=True)
    workflow_version: Mapped[int] = mapped_column(Integer, default=1)
    target: Mapped[str] = mapped_column(String(12))          # task | record
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    transition: Mapped[str] = mapped_column(String(60))
    from_status: Mapped[str] = mapped_column(String(60))
    to_status: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(100), default='')
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON_TYPE)
    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
