"""v0.11.0: Admin-only AI settings, the recent call log, and alias suggestions.

Keys are never accepted, stored or returned here: they are set by Vijay in the server's
environment file. Turning AI on needs this screen's switch AND STUDIOOS_ALLOW_LIVE_AI=true.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import ai_wiring as W
from .db import SessionLocal, User
from .security import permit

router = APIRouter(prefix='/api/ai', tags=['AI reader settings (Admin)'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


class SettingsIn(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    monthly_cap_usd: str | None = None
    masking: bool | None = None
    input_usd_per_1m: str | None = None
    output_usd_per_1m: str | None = None
    max_output_tokens: int | None = None
    few_shot: bool | None = None


class AliasIn(BaseModel):
    data: dict


def _view(db):
    gw = W.gateway(db)
    s = gw.settings
    return {'settings': {k: s[k] for k in ('enabled', 'provider', 'model', 'monthly_cap_usd', 'masking',
                                           'input_usd_per_1m', 'output_usd_per_1m', 'max_output_tokens', 'few_shot')},
            'status': gw.status(), 'providers': ['openai', 'claude', 'gemini'],
            'keys_note': 'Keys are set in the server settings file by the owner, never on this screen.'}


@router.get('/settings')
def get_settings(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return _view(db)


@router.put('/settings')
def put_settings(v: SettingsIn, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    raw = {k: val for k, val in v.model_dump().items() if val is not None}
    try:
        W.save_settings(db, raw, user.username)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return _view(db)


@router.get('/calls')
def calls(limit: int = 50, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return {'calls': W.recent_calls(db, limit)}


@router.get('/alias-suggestions')
def suggestions(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return {'suggestions': W.alias_suggestions(db)}


@router.post('/alias-suggestions/dismiss')
def dismiss(v: AliasIn, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        W.dismiss_suggestion(db, v.data, user.username)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return {'dismissed': True}
