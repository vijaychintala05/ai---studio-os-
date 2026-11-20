"""v0.22 foundation APIs: read the stored tax rules, resolve one for a date, propose a rule change (a draft ticket).
The store starts empty; the accountant supplies the content."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import taxdata_core as core
from .db import User
from .deps import get_db
from .security import permit
from .taxdata import ROLES, TAX_TYPES, live_rules

router = APIRouter(prefix='/api/tax-rules', tags=['Tax rule data (empty until supplied)'])


class Proposal(BaseModel):
    kind: str
    data: dict


@router.get('')
def rules(user: User = Depends(permit('admin', 'accounts', 'manager')), db: Session = Depends(get_db)):
    return live_rules(db)


@router.get('/resolve')
def resolve(kind: str, key: str, on_date: str, scope: str = '', user: User = Depends(permit('admin', 'accounts', 'manager')),
            db: Session = Depends(get_db)):
    try:
        found = core.resolve(live_rules(db), kind, key, on_date, (scope,) if scope else ())
    except ValueError:
        raise HTTPException(400, 'on_date must be a date like 2026-04-01')
    return {'rule': found}


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit(*ROLES)), db: Session = Depends(get_db)):
    if v.kind not in TAX_TYPES:
        raise HTTPException(400, 'Unknown kind of rule change')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
