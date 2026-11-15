"""v0.10.0 read APIs for the generic screens: records, record pages with links, pickers,
reports, business packs and notices. Every change still goes through
POST /api/universal/proposals (an approval ticket); nothing here writes business data.
The one write is the once-a-day check of 'daily' rules, which only adds notices."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import graph_core as G
from . import graph_query as gq
from . import universal_engine as u
from .db import SessionLocal, User, UniversalReport, RecordType
from .security import current_user

router = APIRouter(prefix='/api/graph', tags=['One graph: records, links, reports'])


def _db(request: Request):
    with SessionLocal() as db:
        db.info['write_source'] = f'api:{request.method} {request.url.path}'
        yield db


@router.get('/catalog')
def catalog(user: User = Depends(current_user), db: Session = Depends(_db)):
    return gq.catalog_public(db, user)


@router.get('/packs/{key}')
def pack(key: str, user: User = Depends(current_user), db: Session = Depends(_db)):
    found = gq.available_packs().get(key)
    if not found:
        raise HTTPException(404, 'Unknown business pack')
    return {'pack': found['pack'], 'sha256': found['sha256'],
            'installed': key in gq.installed_packs(db)}


@router.get('/records/{type_key}')
def records(type_key: str, q: str = '', project_id: int | None = None, limit: int = 50, offset: int = 0,
            user: User = Depends(current_user), db: Session = Depends(_db)):
    rt = db.get(RecordType, type_key)
    if not rt or rt.status != 'active' or (rt.design or {}).get('runtime_fields') is None:
        raise HTTPException(404, 'Unknown type')
    if not 1 <= limit <= 200 or not 0 <= offset <= 50000:
        raise HTTPException(422, 'Invalid page')
    res = gq.Resolver(db, user)
    try:
        nodes = res.base_rows(type_key)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    fields = rt.design['runtime_fields']
    shown = fields[:6]
    term = q.strip().casefold()[:80]
    rows = []
    for n in reversed(nodes):
        if project_id and n.get('project_id') != project_id:
            continue
        cells = [gq._display(f, n['values'].get(f['name']), res) for f in shown]
        if term and term not in n['label'].casefold() and not any(term in c.casefold() for c in cells):
            continue
        rows.append({'id': n['id'], 'label': n['label'], 'project_id': n.get('project_id'), 'cells': cells})
    return {'type_key': type_key, 'title': rt.title, 'columns': [f.get('meaning') or f['name'] for f in shown],
            'total': len(rows), 'records': rows[offset:offset + limit]}


@router.get('/record/{record_id}')
def record(record_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    try:
        return gq.record_page(db, user, record_id)
    except LookupError:
        raise HTTPException(404, 'Record not found')


@router.get('/links-from/{kind}/{obj_id}')
def links_from(kind: str, obj_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    """v0.11.0: links that start at a task (system.task) or a staff member (system.user)."""
    try:
        return gq.system_links(db, user, kind, obj_id)
    except LookupError:
        raise HTTPException(404, 'Not found')


@router.get('/targets/{target}')
def targets(target: str, q: str = '', project_id: int | None = None,
            user: User = Depends(current_user), db: Session = Depends(_db)):
    try:
        return gq.targets(db, user, target, q, project_id)
    except LookupError:
        raise HTTPException(404, 'Unknown target')
    except ValueError as ex:
        raise HTTPException(422, str(ex))


@router.get('/reports')
def reports(user: User = Depends(current_user), db: Session = Depends(_db)):
    return gq.report_list(db, user)


def _visible_report(db, user, key):
    """v0.12.0: a report saved for some roles is not run for others (Admin sees all)."""
    rep = db.get(UniversalReport, key)
    roles = gq.report_definition(db, rep).get('visible_to') if rep else None
    if not rep or (roles and user.role != 'admin' and user.role not in roles):
        raise HTTPException(404, 'Unknown report')
    return rep


@router.get('/reports/{key}/run')
def run_report(key: str, user: User = Depends(current_user), db: Session = Depends(_db)):
    rep = _visible_report(db, user, key)
    try:
        return gq.run_report(db, user, gq.report_definition(db, rep))
    except ValueError as ex:
        raise HTTPException(422, str(ex))


class ReportPreview(BaseModel):
    definition: dict


@router.post('/reports/preview')
def preview_report(body: ReportPreview, user: User = Depends(current_user), db: Session = Depends(_db)):
    """Try a report definition on the data you can see, before proposing it. Writes nothing."""
    if user.role == 'viewer':
        raise HTTPException(403, 'Viewers cannot design reports')
    try:
        return gq.run_report(db, user, body.definition)
    except ValueError as ex:
        raise HTTPException(422, str(ex))


@router.get('/reports/{key}/export.csv')
def export_report(key: str, user: User = Depends(current_user), db: Session = Depends(_db)):
    rep = _visible_report(db, user, key)
    try:
        out = gq.run_report(db, user, gq.report_definition(db, rep))
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    buf = io.StringIO()
    w = csv.writer(buf)

    def safe(x):   # spreadsheet formula injection guard
        x = str(x)
        return "'" + x if x[:1] in ('=', '+', '-', '@') else x
    if out['mode'] == 'figure':
        w.writerow([f['label'] for f in out['figures']])
        w.writerow([safe(f['value']) for f in out['figures']])
    elif out['mode'] == 'grouped':
        w.writerow(out['group_labels'] + out['measure_labels'])
        for r in out['rows']:
            w.writerow([safe(x) for x in r['group'] + r['values']])
    else:
        w.writerow(out['column_labels'])
        for r in out['rows']:
            w.writerow([safe(x) for x in r['cells']])
    return Response(buf.getvalue(), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{key}.csv"'})


@router.get('/notices')
def notices(user: User = Depends(current_user), db: Session = Depends(_db)):
    gq.maybe_run_daily_rules(db)
    return {'notices': gq.notices_for(db, user)}


@router.post('/rules/run')
def run_rules(user: User = Depends(current_user), db: Session = Depends(_db)):
    if user.role not in ('admin', 'manager'):
        raise HTTPException(403, 'Admin or manager only')
    made = u.run_daily_rules(db)
    db.commit()
    return {'notices_created': made, 'as_of': u._today().isoformat()}


@router.get('/systems')
def systems(user: User = Depends(current_user)):
    return [{'key': k, 'title': v['title'], 'readable': sorted(v['attrs'])} for k, v in G.SYSTEM_TYPES.items()]
