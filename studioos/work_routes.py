"""v0.17 work rules APIs. Reads are open to anyone who can see the project. Every change is a draft ticket for a
person to approve (nothing here writes a business table), and the dry run writes nothing at all."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import work_rules_core as core
from .access import can_access_project
from .db import Task, User
from .deps import get_db
from .security import ROLES, current_user, permit
from .work_models import (ProjectBaseline, ProjectStage, TaskLink, TaskStructure, WorkDeletion, WorkTemplate, WorkTransitionLog,
                          WorkWorkflow)
from .work_rules import WORK_TYPES, active_links, restore_days

router = APIRouter(prefix='/api/work', tags=['Work rules'])


class Proposal(BaseModel):
    kind: str
    data: dict


@router.get('/projects/{project_id}/structure')
def structure(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not can_access_project(db, user, project_id):
        raise HTTPException(404, 'Project not found')
    stages = db.scalars(select(ProjectStage).where(ProjectStage.project_id == project_id, ProjectStage.deleted_at.is_(None))
                        .order_by(ProjectStage.position, ProjectStage.id)).all()
    tasks = db.execute(select(Task, TaskStructure).outerjoin(TaskStructure, TaskStructure.task_id == Task.id)
                       .where(Task.project_id == project_id, Task.deleted_at.is_(None)).order_by(Task.id)).all()
    ids = {t.id for t, _ in tasks}
    links = [l for l in active_links(db, ids)]
    base = db.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id).order_by(ProjectBaseline.id.desc()))
    status = {t.id: t.status for t, _ in tasks}
    return {
        'stages': [{'id': s.id, 'name': s.name, 'position': s.position, 'client_visible': s.client_visible} for s in stages],
        'tasks': [{'id': t.id, 'title': t.title, 'status': t.status, 'due_date': t.due_date,
                   'stage_id': s.stage_id if s else None, 'parent_task_id': s.parent_task_id if s else None,
                   'start_date': s.start_date if s else '', 'client_visible': bool(s and s.client_visible),
                   'blocked_by': core.blocking_open_predecessors(t.id, links, status),
                   'slipped_days': core.variance_days(((base.data or {}).get(str(t.id)) or {}).get('due_date'), t.due_date) if base else None}
                  for t, s in tasks],
        'links': links,
        'baseline': {'label': base.label, 'frozen_at': base.frozen_at.isoformat()} if base else None,
    }


@router.get('/workflows')
def workflows(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkWorkflow).where(WorkWorkflow.status == 'live').order_by(WorkWorkflow.key)).all()
    return [{'key': r.key, 'version': r.version, 'name': r.name, 'applies_to': r.applies_to, 'definition': r.definition} for r in rows]


@router.get('/templates')
def templates(user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkTemplate).where(WorkTemplate.status == 'live').order_by(WorkTemplate.key)).all()
    return [{'key': r.key, 'version': r.version, 'name': r.name, 'definition': r.definition} for r in rows]


@router.get('/workflows/{key}/available')
def available(key: str, status: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(WorkWorkflow).where(WorkWorkflow.key == key, WorkWorkflow.status == 'live'))
    if not row:
        raise HTTPException(404, 'No live workflow with that key')
    return {'transitions': core.available_transitions(row.definition, status, user.role)}


@router.get('/recycle')
def recycle(user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkDeletion).where(WorkDeletion.restored_at.is_(None)).order_by(WorkDeletion.id.desc())).all()
    return {'restore_days': restore_days(db),
            'items': [{'task_id': r.task_id, 'deleted_by': r.deleted_by, 'deleted_at': r.deleted_at.isoformat(),
                       'restore_until': r.restore_until.isoformat(), 'reason': r.reason} for r in rows]}


@router.get('/transitions')
def transitions(workflow_key: str, target_id: int, user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkTransitionLog).where(WorkTransitionLog.workflow_key == workflow_key,
                                                      WorkTransitionLog.target_id == target_id).order_by(WorkTransitionLog.id)).all()
    return [{'transition': r.transition, 'from': r.from_status, 'to': r.to_status, 'actor': r.actor,
             'evidence': r.evidence, 'at': r.created_at.isoformat()} for r in rows]


class DryRun(BaseModel):
    definition: dict
    path: list[dict] = []


@router.post('/workflows/dry-run')
def dry_run(v: DryRun, user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    """Walk sample steps through a workflow definition. Nothing is written."""
    try:
        return {'ok': True, 'visited': core.dry_run(v.definition, ROLES, v.path)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit('admin', 'manager', 'architect', 'site_engineer')), db: Session = Depends(get_db)):
    """Draft a ticket for one work change. A person approves it before anything is written."""
    if v.kind not in WORK_TYPES:
        raise HTTPException(400, 'Unknown kind of work change')
    if v.kind != 'work_transition' and user.role not in ('admin', 'manager'):
        raise HTTPException(403, 'You do not have permission for this action')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
