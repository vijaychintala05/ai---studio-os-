"""v0.13.0 Admin APIs for safe type changes: draft from words (offline, or the AI through the
gateway), preview the impact and blockers, the change history, and business pack upgrades.
Every change itself is an Admin-approved ticket (metadata_type_change / _undo / metadata_pack_upgrade)."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import restructure_core as RC
from . import restructure_wiring as W
from .db import SessionLocal, User
from .security import permit

router = APIRouter(prefix='/api/restructure', tags=['Safe type changes (Admin)'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


class ChangeIn(BaseModel):
    change: dict


class WordsIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


@router.post('/preview')
def preview(v: ChangeIn, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        return W.preview(db, v.change)
    except (RC.ChangeError, ValueError) as ex:
        raise HTTPException(422, str(ex))


def _ai_change(db, text, world):
    from . import ai_wiring
    from .ai_gateway import GatewayRefused, mark_outcome
    gw = ai_wiring.gateway(db)
    if not gw.is_on():
        return None
    types = {k: {'title': t['title'], 'fields': [{'name': f['name'], 'kind': f['type']} for f in t['fields']]}
             for k, t in world['types'].items() if t.get('status', 'active') == 'active'}
    try:
        out = gw.call('restructure', 'Turn the request into ONE JSON change for StudioOS types. Keys: op (' + ', '.join(RC.OPS) +
                      '), type_key, and per op: field, new_name, new_type, options, new_title, into, field_map, new_key, condition. '
                      'Never SQL. If unclear return {"unsure": "why"}. Types: ' + json.dumps(types), text, masked=False)
    except GatewayRefused:
        return None
    try:
        d = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', out['text'].strip()))
        RC.check_change(d, world)
        return d
    except Exception:
        gw.log.append(mark_outcome(out['row'], 'invalid'))
        return None
    finally:
        db.commit()


@router.post('/draft')
def draft(v: WordsIn, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    """'rename field severity to priority in work issue' -> a change and its preview (not a ticket yet)."""
    world = W.build_world(db)
    try:
        change, source = RC.change_from_words(v.text, world), 'offline'
    except RC.ChangeError as ex:
        change, source = _ai_change(db, v.text, world), 'ai'
        if change is None:
            raise HTTPException(422, str(ex))
    return {**W.preview(db, change), 'source': source}


@router.get('/changes')
def changes(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    return {'changes': W.history(db)}


@router.get('/pack-upgrade/{pack}')
def pack_upgrade(pack: str, user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    try:
        return W.pack_upgrade_items(db, pack)
    except (RC.ChangeError, ValueError) as ex:
        raise HTTPException(422, str(ex))
