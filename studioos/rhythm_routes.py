"""v0.19 daily rhythm APIs: your list for today, the project health view, and a by-hand run of a rhythm job (owner)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import rhythm
from .deps import get_db
from .security import current_user, permit
from .db import User

router = APIRouter(prefix='/api/rhythm', tags=['Daily rhythm'])


def _today():
    from . import universal_engine as u
    return u._today()


@router.get('/mine')
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'date': _today().isoformat(), 'items': rhythm.person_todos(db, user, _today())}


@router.get('/projects')
def projects(user: User = Depends(permit('admin', 'manager')), db: Session = Depends(get_db)):
    return {'date': _today().isoformat(), 'projects': rhythm.project_healths(db, _today())}


@router.post('/run/{job}')
def run(job: str, user: User = Depends(permit('admin'))):
    if job not in rhythm.JOBS:
        raise HTTPException(404, 'Unknown job')
    return rhythm.run_job(job, _today())
