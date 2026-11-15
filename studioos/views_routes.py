"""v0.12.0 APIs: ask a question, show an answer in any form, your dashboard, per-type layouts.
Everything here reads; saving a report, dashboard or layout is a ticket (POST /api/universal/proposals)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import graph_query as gq
from . import views_core as V
from . import views_wiring as W
from .db import SessionLocal, User
from .security import current_user, permit

router = APIRouter(prefix='/api/views', tags=['Questions, displays, dashboards'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class ShowIn(BaseModel):
    definition: dict
    display: dict | None = None


@router.post('/classify')
def classify(v: MessageIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    words = [w for rt in gq.universal_types(db).values() for w in [rt.title] + list((rt.design or {}).get('aliases') or [])]
    return V.classify(v.message, words)


@router.post('/ask')
def ask(v: QuestionIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    return W.ask(db, user, v.question)


@router.post('/show')
def show(v: ShowIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    try:
        return W.show(db, user, v.definition, v.display)
    except ValueError as ex:
        raise HTTPException(422, str(ex))


@router.get('/home')
def home(user: User = Depends(current_user), db: Session = Depends(_db)):
    return W.home(db, user)


@router.get('/dashboards')
def dashboards(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return {'dashboards': list(W.latest(db, 'dashboard').values())}


@router.get('/layout/{type_key}')
def layout(type_key: str, user: User = Depends(current_user), db: Session = Depends(_db)):
    return {'layout': W.layout_for(db, type_key)}


@router.post('/layout/{type_key}/suggest')
def suggest(type_key: str, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        return W.suggest_layout(db, type_key)
    except ValueError as ex:
        raise HTTPException(404, str(ex))
