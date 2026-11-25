"""v0.21 APIs: project budgets, actual cost, forecast and health (with a "calculated at" time), breaches, the money view.
Owner, manager and accounts only: a site engineer never sees a budget, a rate or a cost. Changes are draft tickets."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import budget_rules as rules
from .budget_models import BudgetBreach
from .db import Project, User
from .deps import get_db
from .security import permit

router = APIRouter(prefix='/api/budgets', tags=['Budgets and project money'])


class Proposal(BaseModel):
    kind: str
    data: dict


def _project(db, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at:
        raise HTTPException(404, 'Project not found')
    return p


def _with_baseline(db, project_id, rows):
    from .work_models import ProjectBaseline
    base = db.scalar(select(ProjectBaseline).where(ProjectBaseline.project_id == project_id).order_by(ProjectBaseline.id.desc()))
    frozen = ((base.data or {}).get('_budgets') or {}) if base else {}
    for r in rows:
        was = frozen.get(f"{r['scope']}:{r['ref_id']}") if base else None
        r['baseline_paise'] = was
        r['baseline_variance_paise'] = None if was is None else r['budget_paise'] - was
    return rows


@router.get('/project/{project_id}')
def project_budgets(project_id: int, user: User = Depends(permit(*rules.READ_ROLES)), db: Session = Depends(get_db)):
    _project(db, project_id)
    breaches = db.scalars(select(BudgetBreach).where(BudgetBreach.project_id == project_id).order_by(BudgetBreach.id))
    return {'calculated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'breach_rule': rules.breach_mode(db),
            'budgets': _with_baseline(db, project_id, rules.evaluate(db, project_id)),
            'breaches': [{'id': b.id, 'budget_id': b.budget_id, 'actual_paise': b.actual_paise, 'budget_paise': b.budget_paise,
                          'open': b.acknowledged_at is None, 'note': b.note} for b in breaches]}


@router.get('/project/{project_id}/money')
def money_view(project_id: int, user: User = Depends(permit(*rules.READ_ROLES)), db: Session = Depends(get_db)):
    """Contract value beside cost to date. Invoiced and received are not shown: there is no client invoicing in the
    project tracker, and reading them from the books waits for the accountant (see HELD_FOR_OWNER.md)."""
    p = _project(db, project_id)
    actual = rules.actuals(db, project_id)
    return {'calculated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'contract_value_paise': p.budget_paise,
            'cost_to_date_paise': actual['project'], 'expense_basis': actual['expense_basis'],
            'invoiced_paise': None, 'received_paise': None}


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    if v.kind not in rules.BUDGET_TYPES:
        raise HTTPException(400, 'Unknown kind of budget change')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
