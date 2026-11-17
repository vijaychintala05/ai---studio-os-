"""v0.11.0: Admin-only AI settings, the recent call log, and alias suggestions.

Keys are never accepted, stored or returned here: they are set by Vijay in the server's
environment file. Turning AI on needs this screen's switch AND STUDIOOS_ALLOW_LIVE_AI=true.
"""
from __future__ import annotations
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select,func

from . import ai_wiring as W
from .db import SessionLocal, User,AiCallLog
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
            'status': gw.status(), 'providers': ['openai', 'claude', 'gemini']+(['recorded']if os.getenv('STUDIOOS_ENV')=='test'else[]),
            'keys_note': 'Keys are set in the server settings file by the owner, never on this screen.'}


@router.get('/settings')
def get_settings(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return _view(db)


@router.get('/replay-status')
def replay_status(user:User=Depends(permit('admin')),db:Session=Depends(_db)):
    """Counts only. Recorded transport events are not fresh provider inference."""
    if os.getenv('STUDIOOS_ENV')!='test':raise HTTPException(404,'Recorded replay status is test-only')
    from .recorded_transport import RECORDINGS_ROOT
    path=RECORDINGS_ROOT/'reader-replay-calls.jsonl'
    if RECORDINGS_ROOT.is_symlink()or path.is_symlink():raise HTTPException(409,'Unsafe recording trace path')
    attempts=replayed=nonempty=network=0
    if path.exists():
        if path.stat().st_size>64*1024*1024:raise HTTPException(409,'Recording trace is too large to verify')
        try:
            with path.open(encoding='utf-8')as trace:
                for line in trace:
                    event=json.loads(line);attempts+=1
                    replayed+=event['outcome']=='replayed'
                    nonempty+=event['outcome']=='replayed'and event.get('response_fields',0)>0
                    network+=int(event['network_calls'])
        except (OSError,ValueError,KeyError,TypeError):raise HTTPException(409,'Recording trace is incomplete or invalid')
    outcomes=dict(db.execute(select(AiCallLog.outcome,func.count()).where(
        AiCallLog.provider=='recorded',AiCallLog.purpose=='reader').group_by(AiCallLog.outcome)).all())
    paid=db.scalar(select(func.count()).select_from(AiCallLog).where(
        AiCallLog.provider.in_(('openai','claude','gemini')),AiCallLog.purpose=='reader'))or 0
    return {'mode':'recorded_fixture_replay','transport_attempts':attempts,'transport_replayed':replayed,
            'transport_failures':attempts-replayed,'nonempty_replies':nonempty,'network_calls':network,
            'gateway_ok':outcomes.get('ok',0),'gateway_invalid':outcomes.get('invalid',0),
            'gateway_other_failures':sum(n for key,n in outcomes.items()if key not in ('ok','invalid')),
            'paid_provider_gateway_rows':paid,
            'paid_server_switch':os.getenv('STUDIOOS_ALLOW_LIVE_AI','false').strip().lower()=='true'}


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
