"""v0.15.0 APIs: weekly suggestions (accept = a ticket, dismiss = never again), your summaries, a
weekly review draft (facts only), the self-check, and running a scheduled job by hand (Admin)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import improve_core as IM
from . import improve_wiring as W
from .db import ImproveSuggestion, SessionLocal, User
from .security import current_user, permit

router = APIRouter(prefix='/api/improve', tags=['Suggestions, summaries, self-check'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


class ReviewIn(BaseModel):
    employee_id: int
    week_start: str


@router.get('/suggestions')
def suggestions(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    rows = db.scalars(select(ImproveSuggestion).order_by(ImproveSuggestion.id.desc()).limit(50))
    return {'suggestions': [{'id': s.id, 'kind': s.kind, 'title': s.title, 'evidence': s.evidence, 'proposal': s.proposal,
                             'status': s.status, 'week': s.week, 'ticket_id': s.ticket_id} for s in rows]}


@router.post('/suggestions/{sid}/accept')
def accept(sid: int, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        t = W.accept_suggestion(db, user, sid)
    except ValueError as ex:
        db.rollback()
        raise HTTPException(422, str(ex))
    db.commit()
    return {'ticket_id': t.id}


@router.post('/suggestions/{sid}/dismiss')
def dismiss(sid: int, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        W.dismiss_suggestion(db, user, sid)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return {'dismissed': True}


@router.get('/summaries/mine')
def my_summaries(user: User = Depends(current_user), db: Session = Depends(_db)):
    return {'summaries': W.my_summaries(db, user)}


@router.post('/review-draft')
def review_draft(v: ReviewIn, user: User = Depends(permit('admin', 'manager')), db: Session = Depends(_db)):
    try:
        start = IM.week_of(dt.date.fromisoformat(v.week_start))[0]
        ticket, facts = W.review_draft(db, user, v.employee_id, start)
    except ValueError as ex:
        db.rollback()
        raise HTTPException(422, str(ex))
    db.commit()
    return {'ticket_id': ticket.id, 'facts': facts}


@router.get('/health')
def health(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return W.health(db)


@router.post('/jobs/{job}/run')
def run_job(job: str, user: User = Depends(permit('admin'))):
    if job not in IM.JOBS:
        raise HTTPException(404, 'Unknown job')
    return W.run_job(job)
