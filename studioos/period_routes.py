"""v0.20 APIs: area locks, legal holds, party registration type. Reads for owner, accounts and manager; every change is a
draft ticket for the owner to approve."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import User
from .deps import get_db
from .period_models import LegalHold, PartyTaxProfile, PeriodAreaLock
from .period_rules import PERIOD_TYPES, ROLES, check_document_date
from .security import permit

router = APIRouter(prefix='/api/period', tags=['Period locks and holds'])
READERS = ('admin', 'accounts', 'manager')


class Proposal(BaseModel):
    kind: str
    data: dict


@router.get('/locks')
def locks(entity_id: int, user: User = Depends(permit(*READERS)), db: Session = Depends(get_db)):
    rows = db.scalars(select(PeriodAreaLock).where(PeriodAreaLock.entity_id == entity_id).order_by(PeriodAreaLock.year_month, PeriodAreaLock.id))
    return [{'id': r.id, 'year_month': r.year_month, 'area': r.area, 'locked_by': r.locked_by, 'reason': r.reason,
             'open': r.reopened_at is None, 'reopen_reason': r.reopen_reason} for r in rows]


@router.get('/check')
def check(entity_id: int, area: str, document_date: str, user: User = Depends(permit(*READERS)), db: Session = Depends(get_db)):
    try:
        check_document_date(db, entity_id, area, document_date)
    except ValueError as e:
        return {'locked': True, 'why': str(e)}
    return {'locked': False}


@router.get('/holds')
def holds(user: User = Depends(permit('admin', 'accounts')), db: Session = Depends(get_db)):
    return [{'id': h.id, 'project_id': h.project_id, 'reason': h.reason, 'placed_by': h.placed_by, 'active': h.released_at is None}
            for h in db.scalars(select(LegalHold).order_by(LegalHold.id))]


@router.get('/tax-profiles')
def tax_profiles(party_id: int, user: User = Depends(permit('admin', 'accounts')), db: Session = Depends(get_db)):
    return [{'id': r.id, 'registration_type': r.registration_type, 'effective_from': r.effective_from}
            for r in db.scalars(select(PartyTaxProfile).where(PartyTaxProfile.party_id == party_id).order_by(PartyTaxProfile.effective_from))]


@router.post('/propose')
def propose(v: Proposal, user: User = Depends(permit('admin', 'accounts')), db: Session = Depends(get_db)):
    if v.kind not in PERIOD_TYPES:
        raise HTTPException(400, 'Unknown kind of period change')
    from .main import _manual_draft
    try:
        return _manual_draft(db, user, v.kind, v.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
