"""StudioOS MCP endpoint (v0.9.3): lets an AI assistant such as Claude (custom
connector) or ChatGPT (plugin) read StudioOS for one person, through a personal
access key. Off unless STUDIOOS_MCP_ENABLED=true.

Safety rules:
- Each key acts as one StudioOS person, with that person's role and project access.
- Read tools never change anything. The single writing tool, create_draft, only
  prepares an approval-ticket draft. Nothing can be approved, saved, changed or
  deleted through this endpoint.
- Keys are stored as fingerprints, expire, can be revoked, and stop working when
  the person is deactivated. Every request is logged.
- Optional address allowlist, request-rate limit, browser-origin check, output size cap.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import secrets
import uuid
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import (SessionLocal, User, ConnectorToken, McpCall, Project, Task, SiteReport, Document, ApprovalTicket,
                 ApprovalTicketItem, ChatSession, ChatMessage, RecordType, add_audit, now)
from .security import current_user, permit, password_ok, admin_needs_2fa, FINANCE_READ
from . import mcp_protocol as P
from . import chat_ux

router = APIRouter(tags=['AI connector (MCP)'])
UTC = dt.timezone.utc
TOKEN_PREFIX = 'sos_'


def enabled() -> bool:
    return os.getenv('STUDIOOS_MCP_ENABLED', 'false').strip().lower() == 'true'


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(t):
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


def _today():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(os.getenv('STUDIOOS_TIMEZONE', 'Asia/Kolkata'))).date()
    except Exception:
        return dt.date.today()


# ------------------------------------------------------------------ access keys (web app)

class TokenIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scope: str = Field(default='read', pattern='^(read|read_draft)$')
    days: int = Field(default=90, ge=1, le=365)
    password: str = Field(min_length=1, max_length=200)


def _token_out(t: ConnectorToken, owner: str | None = None) -> dict:
    state = 'revoked' if t.revoked_at else 'expired' if _aware(t.expires_at) < now() else 'active'
    return {'id': t.id, 'name': t.name, 'prefix': t.prefix, 'scope': t.scope, 'state': state, 'owner': owner,
            'created_at': t.created_at.isoformat(), 'expires_at': _aware(t.expires_at).isoformat(),
            'last_used_at': t.last_used_at.isoformat() if t.last_used_at else None}


def _db():
    with SessionLocal() as db:
        db.info['write_source'] = 'api:connector-keys'
        yield db


@router.get('/api/connector-tokens')
def list_tokens(user: User = Depends(current_user), db: Session = Depends(_db)):
    q = select(ConnectorToken).order_by(ConnectorToken.id.desc())
    if user.role != 'admin':
        q = q.where(ConnectorToken.user_id == user.id)
    names = {u.id: u.display_name or u.username for u in db.scalars(select(User)).all()}
    return {'enabled': enabled(), 'endpoint_path': '/mcp',
            'tokens': [_token_out(t, names.get(t.user_id)) for t in db.scalars(q).all()]}


@router.post('/api/connector-tokens')
def create_token(v: TokenIn, user: User = Depends(current_user), db: Session = Depends(_db)):
    me = db.get(User, user.id)
    if not password_ok(v.password, me.password_hash):
        raise HTTPException(403, 'Password is not correct')
    if admin_needs_2fa(me):
        raise HTTPException(403, 'Finish two-factor setup first')
    if v.scope == 'read_draft' and me.role == 'viewer':
        raise HTTPException(403, 'Viewers can only create read-only keys')
    active = db.scalar(select(func.count()).select_from(ConnectorToken).where(
        ConnectorToken.user_id == me.id, ConnectorToken.revoked_at.is_(None), ConnectorToken.expires_at > now())) or 0
    if active >= 5:
        raise HTTPException(409, 'You already have 5 active keys. Revoke one first.')
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ConnectorToken(user_id=me.id, name=v.name.strip(), token_hash=_hash(token), prefix=token[:10], scope=v.scope,
                         expires_at=now() + dt.timedelta(days=v.days))
    db.add(row); db.flush()
    add_audit(db, 'connector_key_created', 'connector_token', row.id,
              f"AI connector key '{row.name}' ({'read and draft' if v.scope == 'read_draft' else 'read only'}, {v.days} days) for {me.username}",
              actor=me.username)
    db.commit()
    return {**_token_out(row), 'token': token,
            'note': 'Copy this key now. StudioOS keeps only a fingerprint and cannot show it again.'}


@router.post('/api/connector-tokens/{token_id}/revoke')
def revoke_token(token_id: int, user: User = Depends(current_user), db: Session = Depends(_db)):
    row = db.get(ConnectorToken, token_id)
    if row is None or (row.user_id != user.id and user.role != 'admin'):
        raise HTTPException(404, 'Key not found')
    if row.revoked_at is None:
        row.revoked_at = now()
        add_audit(db, 'connector_key_revoked', 'connector_token', row.id, f"AI connector key '{row.name}' revoked", actor=user.username)
        db.commit()
    return _token_out(row)


@router.get('/api/connector-calls')
def recent_calls(user: User = Depends(permit('admin')), db: Session = Depends(_db)):
    names = {u.id: u.username for u in db.scalars(select(User)).all()}
    keys = {t.id: t.name for t in db.scalars(select(ConnectorToken)).all()}
    rows = db.scalars(select(McpCall).order_by(McpCall.id.desc()).limit(200)).all()
    return [{'time': r.created_at.isoformat(), 'person': names.get(r.user_id), 'key': keys.get(r.token_id), 'method': r.method,
             'tool': r.tool, 'ok': r.ok, 'detail': r.detail, 'address': r.ip} for r in rows]


# ------------------------------------------------------------------ the MCP endpoint

def _allowed_ip(ip: str) -> bool:
    spec = os.getenv('STUDIOOS_MCP_ALLOWED_IPS', '').strip()
    if not spec:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for part in re.split(r'[,\s]+', spec):
        if not part:
            continue
        try:
            if addr in ipaddress.ip_network(part, strict=False):
                return True
        except ValueError:
            continue
    return False


def _log(token_id, user_id, method, tool, ok, detail, ip):
    with SessionLocal() as db:
        db.info['write_source'] = 'api:mcp-log'
        db.add(McpCall(token_id=token_id, user_id=user_id, method=(method or '')[:60], tool=(tool or '')[:60], ok=ok,
                       detail=str(detail or '')[:300], ip=ip[:120]))
        db.commit()


def _deny(status, message, ip, token_id=None, user_id=None, extra_headers=None, log=True):
    if log:
        _log(token_id, user_id, '', '', False, message, ip)
    headers = {'Cache-Control': 'no-store', **(extra_headers or {})}
    return JSONResponse(status_code=status, content={'error': message}, headers=headers)


_BAD_KEYS: dict[str, list[float]] = {}
_BAD_LOCK = __import__('threading').Lock()
_PRUNED = {'at': 0.0}


def _too_many_bad_keys(ip: str) -> bool:
    """v0.9.4 (review H7): an address that sends 20 wrong keys in 10 minutes is refused
    without touching the database at all."""
    import time
    with _BAD_LOCK:
        recent = [t for t in _BAD_KEYS.get(ip, []) if time.monotonic() - t < 600]
        _BAD_KEYS[ip] = recent
        if len(_BAD_KEYS) > 5000:                      # never grows without bound
            _BAD_KEYS.clear()
        return len(recent) >= 20


def _note_bad_key(ip: str) -> None:
    import time
    with _BAD_LOCK:
        _BAD_KEYS.setdefault(ip, []).append(time.monotonic())


def _prune_calls() -> None:
    """Keep 90 days of connector request history (STUDIOOS_MCP_KEEP_DAYS). Runs at most hourly."""
    import time
    if time.monotonic() - _PRUNED['at'] < 3600 and _PRUNED['at']:
        return
    _PRUNED['at'] = time.monotonic()
    days = max(7, int(os.getenv('STUDIOOS_MCP_KEEP_DAYS', '90')))
    from sqlalchemy import delete
    with SessionLocal() as db:
        db.info['write_source'] = 'api:mcp-prune'
        db.execute(delete(McpCall).where(McpCall.created_at < now() - dt.timedelta(days=days)))
        db.commit()


def _authenticate(request: Request, ip: str):
    """-> (token row, user) or a ready error response."""
    if _too_many_bad_keys(ip):
        return None, JSONResponse(status_code=429, content={'error': 'Too many wrong keys from this address; wait 10 minutes'},
                                  headers={'Retry-After': '600', 'Cache-Control': 'no-store'})
    _prune_calls()
    raw = P.bearer(request.headers.get('authorization'))
    if raw is None or not raw.startswith(TOKEN_PREFIX):
        _note_bad_key(ip)
        return None, _deny(401, 'A StudioOS connector key is required (Authorization: Bearer sos_...)', ip,
                           extra_headers={'WWW-Authenticate': 'Bearer realm="StudioOS"'},
                           log=bool(request.headers.get('authorization')))   # bare probes are not logged
    with SessionLocal() as db:
        row = db.scalar(select(ConnectorToken).where(ConnectorToken.token_hash == _hash(raw)))
        if row is None or row.revoked_at is not None or _aware(row.expires_at) < now():
            _note_bad_key(ip)
            return None, _deny(401, 'This connector key is not valid (unknown, revoked or expired)', ip,
                               token_id=row.id if row else None, extra_headers={'WWW-Authenticate': 'Bearer error="invalid_token"'})
        user = db.get(User, row.user_id)
        if user is None or not user.active or admin_needs_2fa(user):
            return None, _deny(403, 'The person this key belongs to cannot use StudioOS right now', ip, row.id, row.user_id)
        limit = int(os.getenv('STUDIOOS_MCP_MAX_PER_MINUTE', '60'))
        recent = db.scalar(select(func.count()).select_from(McpCall).where(
            McpCall.token_id == row.id, McpCall.created_at > now() - dt.timedelta(minutes=1))) or 0
        if recent >= limit:
            return None, _deny(429, 'Too many requests from this key; wait a minute', ip, row.id, row.user_id,
                               extra_headers={'Retry-After': '60'})
        token = SimpleNamespace(id=row.id, name=row.name, scope=row.scope)
        person = SimpleNamespace(id=user.id, username=user.username)
        row.last_used_at = now()
        db.info['write_source'] = 'api:mcp-auth'
        db.commit()
        return (token, person), None


@router.api_route('/mcp', methods=['GET', 'DELETE', 'PUT', 'PATCH'])
def mcp_other(request: Request):
    if not enabled():
        return Response(status_code=404)
    # This server never streams to the client; one POST gets one JSON answer.
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post('/mcp')
async def mcp_post(request: Request):
    if not enabled():
        return Response(status_code=404)
    from .main import client_ip, APP_VERSION
    ip = client_ip(request)
    if not _allowed_ip(ip):
        return _deny(403, f'Requests from {ip} are not allowed (STUDIOOS_MCP_ALLOWED_IPS)', ip)
    origins = [o.strip() for o in os.getenv('STUDIOOS_MCP_ALLOWED_ORIGINS', '').split(',')]
    if not P.origin_ok(request.headers.get('origin'), origins):
        return _deny(403, 'Requests from web pages on other sites are not allowed', ip)
    # Database work runs in a worker thread so one slow request never blocks the others.
    auth, failure = await run_in_threadpool(_authenticate, request, ip)
    if failure is not None:
        return failure
    token, user = auth
    try:   # v0.9.5 (review F21): refuse an oversized request before reading it
        declared = int(request.headers.get('content-length') or 0)
    except ValueError:
        declared = 0
    if declared > 64 * 1024:
        return _deny(413, 'Request too large', ip, token.id, user.id)
    body = await request.body()
    if len(body) > 64 * 1024:
        return _deny(413, 'Request too large', ip, token.id, user.id)
    message = P.parse(body)
    if message is None:
        _log(token.id, user.id, '', '', False, 'unreadable JSON', ip)
        return JSONResponse(status_code=400, content={'jsonrpc': '2.0', 'id': None,
                                                      'error': {'code': P.PARSE_ERROR, 'message': 'Not valid JSON'}})
    method = message.get('method') if isinstance(message, dict) else ''
    tool_name = ((message.get('params') or {}).get('name') if isinstance(message, dict) and isinstance(message.get('params'), dict) else '') or ''

    def call(tool, args):
        return _run_tool(tool, args, user, token)

    try:
        response = await run_in_threadpool(P.handle, message, TOOLS, token.scope, APP_VERSION, call)
    except Exception as err:  # never leak internals to the AI
        _log(token.id, user.id, method, tool_name, False, f'internal error: {type(err).__name__}', ip)
        return JSONResponse(status_code=500, content={'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                                                      'error': {'code': P.INTERNAL_ERROR, 'message': 'StudioOS could not complete this request'}})
    ok = response is None or ('error' not in response and not (response.get('result') or {}).get('isError'))
    detail = '' if ok else (response.get('error', {}).get('message') or (response['result']['content'][0]['text']))
    await run_in_threadpool(_log, token.id, user.id, method, tool_name if method == 'tools/call' else '', ok, detail, ip)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(content=response, headers={'Cache-Control': 'no-store'})


# ------------------------------------------------------------------ tools

def _visible(db, user):
    from .access import visible_project_ids
    allowed = visible_project_ids(db, user)
    return allowed, [p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)).all()
                     if allowed is None or p.id in allowed]


def _project(db, user, name):
    _, projects = _visible(db, user)
    exact = [p for p in projects if p.name.casefold() == name.strip().casefold()]
    if exact:
        return exact[0]
    near = [p for p in projects if name.strip().casefold() in p.name.casefold()]
    if len(near) == 1:
        return near[0]
    if near:
        raise P.ToolError('Which project? ' + ' or '.join(p.name for p in near[:6]))
    raise P.ToolError(f'No project called "{name}" that you can see')


def _finance(user):
    return user.role in FINANCE_READ


def _overdue(t) -> bool:
    try:
        return t.status != 'done' and bool(t.due_date) and dt.date.fromisoformat(t.due_date[:10]) < _today()
    except ValueError:
        return False


def _task(t, project_name=None):
    return {'title': t.title, 'project': project_name, 'assignee': t.assignee or None, 'due_date': t.due_date or None,
            'progress_percent': t.progress or 0, 'status': t.status, 'overdue': _overdue(t)}


def _budget(db, p):
    """v0.9.5 (review F25): costs incurred and money actually paid are different things."""
    from .main import cost_totals, money, payment_sums
    from .db import Cost
    c = cost_totals(db, p.id)
    budget = money(p.budget_paise)
    paid_by_cost = payment_sums(db)
    cost_ids = [x for x in db.scalars(select(Cost.id).where(Cost.project_id == p.id, Cost.deleted_at.is_(None))).all()]
    paid = money(sum(paid_by_cost.get(i, 0) for i in cost_ids))
    return {'approved_budget': budget, 'costs_incurred': c['actual'], 'purchase_orders_open': c['commitments'],
            'known_costs': c['known_costs'], 'paid_to_vendors': paid, 'still_payable': round(c['known_costs'] - paid, 2),
            'remaining_budget': round(budget - c['known_costs'], 2), 'over_budget': c['known_costs'] > budget,
            'note': 'Approved entries only. Costs incurred and purchase orders are not the same as money paid.'}


def t_list_projects(db, user, args):
    allowed, projects = _visible(db, user)
    rows = []
    for p in projects:
        open_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id, Task.deleted_at.is_(None), Task.status != 'done')) or 0
        row = {'name': p.name, 'client': p.client or None, 'stage': p.stage, 'location': p.location or None, 'open_tasks': open_tasks}
        if _finance(user):
            row['approved_budget'] = _budget(db, p)['approved_budget']
        rows.append(row)
    lines = [f"{len(rows)} project{'s' if len(rows) != 1 else ''}:"] + [
        f"- {r['name']} · {r['stage']}" + (f" · client {r['client']}" if r['client'] else '') + f" · {r['open_tasks']} open tasks"
        + (f" · budget {chat_ux.inr(int(r['approved_budget'] * 100))}" if 'approved_budget' in r else '') for r in rows]
    return P.tool_result({'projects': rows}, '\n'.join(lines))


def t_project_status(db, user, args):
    p = _project(db, user, args['project'])
    tasks = db.scalars(select(Task).where(Task.project_id == p.id, Task.deleted_at.is_(None)).order_by(Task.due_date)).all()
    open_ = [t for t in tasks if t.status != 'done']
    reports = db.scalars(select(SiteReport).where(SiteReport.project_id == p.id, SiteReport.deleted_at.is_(None))
                         .order_by(SiteReport.id.desc()).limit(5)).all()
    data = {'project': p.name, 'client': p.client or None, 'stage': p.stage, 'location': p.location or None,
            'tasks': {'open': len(open_), 'done': len(tasks) - len(open_), 'overdue': sum(_overdue(t) for t in open_)},
            'open_tasks': [_task(t) for t in open_[:15]],
            'recent_site_reports': [{'date': r.created_at.date().isoformat(), 'note': r.note[:400]} for r in reports]}
    if _finance(user):
        data['budget'] = _budget(db, p)
    lines = [f"**{p.name}** · {p.stage}" + (f" · client {p.client}" if p.client else ''),
             f"Tasks: {data['tasks']['open']} open ({data['tasks']['overdue']} overdue), {data['tasks']['done']} done."]
    lines += [f"- {t['title']}: {t['progress_percent']}%" + (f", due {t['due_date']}" if t['due_date'] else '') + (' **overdue**' if t['overdue'] else '')
              for t in data['open_tasks']]
    if 'budget' in data:
        b = data['budget']
        lines.append(f"Budget {chat_ux.inr(int(b['approved_budget'] * 100))}; costs incurred {chat_ux.inr(int(b['costs_incurred'] * 100))}; "
                     f"open purchase orders {chat_ux.inr(int(b['purchase_orders_open'] * 100))}; paid {chat_ux.inr(int(b['paid_to_vendors'] * 100))}; "
                     f"budget left {chat_ux.inr(int(b['remaining_budget'] * 100))}" + (' — **over budget**' if b['over_budget'] else '') + '.')
    if reports:
        lines.append('Latest site reports:')
        lines += [f"- {r['date']}: {r['note'][:200]}" for r in data['recent_site_reports']]
    return P.tool_result(data, '\n'.join(lines))


def t_budget_summary(db, user, args):
    if not _finance(user):
        raise P.ToolError('Budgets are visible to Admin, managers and accounts only')
    projects = [_project(db, user, args['project'])] if args.get('project') else _visible(db, user)[1]
    rows = [{'project': p.name, **_budget(db, p)} for p in projects]
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ('approved_budget', 'costs_incurred', 'purchase_orders_open', 'known_costs',
                                                              'paid_to_vendors', 'still_payable', 'remaining_budget')}
    over = [r['project'] for r in rows if r['over_budget']]
    lines = [f"- {r['project']}: budget {chat_ux.inr(int(r['approved_budget'] * 100))}, known costs {chat_ux.inr(int(r['known_costs'] * 100))}, "
             f"paid {chat_ux.inr(int(r['paid_to_vendors'] * 100))}, budget left {chat_ux.inr(int(r['remaining_budget'] * 100))}"
             + (' **over budget**' if r['over_budget'] else '') for r in rows]
    lines.append(f"Total known costs {chat_ux.inr(int(totals['known_costs'] * 100))} of {chat_ux.inr(int(totals['approved_budget'] * 100))}."
                 + (f" Over budget: {', '.join(over)}." if over else ''))
    lines.append('Only approved entries count. "Known costs" are costs incurred plus open purchase orders; "paid" is money actually paid.')
    return P.tool_result({'projects': rows, 'totals': totals, 'over_budget': over}, '\n'.join(lines))


def t_open_tasks(db, user, args):
    allowed, projects = _visible(db, user)
    names = {p.id: p.name for p in projects}
    if args.get('project'):
        p = _project(db, user, args['project'])
        names = {p.id: p.name}
    q = select(Task).where(Task.deleted_at.is_(None), Task.status != 'done', Task.project_id.in_(list(names) or [-1]))
    tasks = db.scalars(q.order_by(Task.due_date)).all()
    if args.get('assignee'):
        tasks = [t for t in tasks if args['assignee'].casefold() in (t.assignee or '').casefold()]
    if args.get('overdue_only'):
        tasks = [t for t in tasks if _overdue(t)]
    rows = [_task(t, names.get(t.project_id)) for t in tasks[:50]]
    lines = [f"{len(tasks)} open task{'s' if len(tasks) != 1 else ''}" + (' (first 50)' if len(tasks) > 50 else '') + ':'] + [
        f"- {r['project']}: {r['title']} · {r['progress_percent']}%" + (f" · {r['assignee']}" if r['assignee'] else '')
        + (f" · due {r['due_date']}" if r['due_date'] else '') + (' · **overdue**' if r['overdue'] else '') for r in rows]
    return P.tool_result({'tasks': rows, 'total': len(tasks)}, '\n'.join(lines))


def t_search_documents(db, user, args):
    allowed, projects = _visible(db, user)
    names = {p.id: p.name for p in projects}
    words = [w for w in re.findall(r'[\w\-]+', args['query'].casefold()) if len(w) > 1][:8]
    if not words:
        raise P.ToolError('Give a word to search for, like "kitchen elevation"')
    q = select(Document).order_by(Document.id.desc())
    if args.get('project'):
        q = q.where(Document.project_id == _project(db, user, args['project']).id)
    found = []
    for d in db.scalars(q.limit(5000)).all():
        if allowed is not None and d.project_id not in allowed:
            continue
        hay = (d.name + ' ' + d.relative_path).casefold()
        if all(w in hay for w in words):
            found.append({'name': d.name, 'path': d.relative_path, 'project': names.get(d.project_id), 'type': d.doc_type,
                          'size_kb': round((d.size_bytes or 0) / 1024)})
        if len(found) >= 30:
            break
    lines = [f"{len(found)} file{'s' if len(found) != 1 else ''} found (names only; StudioOS does not open the files here):"] + [
        f"- {f['path']}" + (f" ({f['project']})" if f['project'] else '') for f in found]
    return P.tool_result({'files': found}, '\n'.join(lines))


def t_waiting_approvals(db, user, args):
    q = select(ApprovalTicket).where(ApprovalTicket.status.notin_(('committed', 'reversed'))).order_by(ApprovalTicket.id.desc())
    if user.role not in ('admin', 'manager'):
        q = q.where(ApprovalTicket.submitter_id == user.id)
    rows = []
    for t in db.scalars(q.limit(200)).all():
        items = db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == t.id)).all()
        pending = [i for i in items if i.status == 'pending']
        if not pending:
            continue
        rows.append({'ticket': t.id, 'summary': (t.summary or '')[:200], 'waiting_items': len(pending),
                     'kinds': sorted({chat_ux.ITEM_TITLES.get(i.item_type, i.item_type) for i in pending}),
                     'created': t.created_at.date().isoformat()})
        if len(rows) >= 30:
            break
    lines = [f"{len(rows)} draft{'s' if len(rows) != 1 else ''} waiting for approval in StudioOS:"] + [
        f"- #{r['ticket']} ({', '.join(r['kinds'])}): {r['summary'][:120]}" for r in rows]
    return P.tool_result({'drafts': rows}, '\n'.join(lines))


def t_record_types(db, user, args):
    from . import record_types as rtypes
    from .access import visible_project_ids
    allowed = visible_project_ids(db, user)
    if args.get('record_type'):
        key = args['record_type'].strip()
        rt = db.get(RecordType, key) or next((r for r in db.scalars(select(RecordType)).all() if r.title.casefold() == key.casefold()), None)
        if rt is None:
            raise P.ToolError(f'No record type called "{key}"')
        rows = rtypes.records_of(db, rt.key, allowed, _finance(user))
        if args.get('project'):
            pname = _project(db, user, args['project']).name
            rows = [r for r in rows if r['project'] == pname]
        rows = rows[:50]
        data = {'record_type': rt.title, 'records': [{'project': r['project'], 'saved': r['created_at'][:10],
                                                      **{v['label']: v['display'] for v in r['values']}} for r in rows]}
        lines = [f"{len(rows)} {rt.title}:"] + [f"- {r['project'] or 'Not project related'}, {r['saved']}: " +
                                               '; '.join(f'{k} {v}' for k, v in r.items() if k not in ('project', 'saved') and v != '—')
                                               for r in data['records']]
        return P.tool_result(data, '\n'.join(lines))
    types = db.scalars(select(RecordType).where(RecordType.status == 'active').order_by(RecordType.title)).all()
    data = {'record_types': [{'key': r.key, 'title': r.title, 'fields': [rtypes.field_label(f) for f in rtypes.user_fields(r.design)]} for r in types]}
    lines = [f"{len(types)} kinds of records built in StudioOS:"] + [f"- {t['title']} ({', '.join(t['fields'])})" for t in data['record_types']]
    return P.tool_result(data, '\n'.join(lines))


def t_create_draft(db, user, args, token):
    """Same path as typing the message into StudioOS's own chat: drafts only."""
    from fastapi import HTTPException as _HTTP
    from .main import ChatIn, _chat_turn, enrich_chat_reply
    if user.role == 'viewer':
        raise P.ToolError('Viewers cannot create drafts')
    sid = 'mcp-' + uuid.uuid4().hex[:24]
    session = ChatSession(id=sid, user_id=user.id, pending=None)
    db.add(session); db.flush()
    db.add(ChatMessage(session_id=sid, user_id=user.id, speaker='system',
                       content=f"Received through the AI connector '{token.name}' · {chat_ux.when_text(now())}"))
    db.commit()
    try:
        reply = enrich_chat_reply(db, user, _chat_turn(ChatIn(message=args['message'], session_id=sid), user, db))
    except _HTTP as err:
        db.rollback()
        raise P.ToolError(str(err.detail))
    preview = reply.get('preview') or {}
    items = [{'kind': i.get('title'), 'summary': i.get('line'), 'needs': [f['label'] for f in i.get('fields', []) if f.get('marker') == 'missing']}
             for i in preview.get('items', [])]
    data = {'reply': reply.get('reply'), 'ticket': reply.get('ticket_id'), 'drafts': items,
            'questions': [a['text'] for a in reply.get('ask') or []],
            'kept_in_waiting_area': bool(reply.get('holding_item')), 'saved': False}
    lines = [str(reply.get('reply') or '').replace('**', ''),
             'Nothing has been saved. The person must review and approve this in StudioOS (Chats, or the Ticket Inbox).']
    if data['questions']:
        lines.append('StudioOS asks: ' + ' / '.join(data['questions']))
    return P.tool_result(data, '\n'.join(lines))


def t_catalog(db, user, args):
    """v0.15.0: the kinds of records (universal engine) with their fields, options, links and saved reports."""
    from . import graph_query as gq
    types = gq.universal_types(db)
    rels = gq.relations(db)
    data = {'types': [{'key': k, 'title': t.title, 'aliases': (t.design or {}).get('aliases', []),
                       'fields': [{'name': f['name'], 'kind': f['type'], 'meaning': f.get('meaning', ''), 'required': bool(f.get('required')),
                                   **({'options': f['options']} if f.get('options') else {}), **({'points_to': f['target']} if f.get('target') else {})}
                                  for f in t.design['runtime_fields']]} for k, t in types.items()],
            'links': [{'key': k, 'from': r.source_type, 'to': r.target_type} for k, r in rels.items()],
            'reports': [{'key': r['key'], 'title': r['title']} for r in gq.report_list(db, user)]}
    lines = [f"{len(data['types'])} kinds of records, {len(data['links'])} links, {len(data['reports'])} saved reports."] + \
            [f"- {t['title']} ({t['key']}): " + ', '.join(f['name'] for f in t['fields']) for t in data['types']]
    return P.tool_result(data, '\n'.join(lines))


def t_run_report(db, user, args):
    from . import graph_query as gq
    from .db import UniversalReport
    rep = db.get(UniversalReport, args['report'])
    d = gq.report_definition(db, rep) if rep else None
    if d is None or (d.get('visible_to') and user.role != 'admin' and user.role not in d['visible_to']):
        raise P.ToolError('No saved report with that key')
    try:
        out = gq.run_report(db, user, d)
    except ValueError as ex:
        raise P.ToolError(str(ex))
    if out.get('rows'):
        out['rows'] = out['rows'][:100]
    return P.tool_result(out, f"{out['title']}: {out.get('matched', 0)} matching record(s) you may see.")


def t_propose_record(db, user, args, token):
    """v0.15.0: a draft record of a universal type, as a ticket. Every value is checked; nothing is saved."""
    from . import graph_query as gq
    from . import improve_wiring as iw
    from . import universal_engine as u
    if user.role == 'viewer':
        raise P.ToolError('Viewers cannot propose')
    rt = gq.universal_types(db).get(args['type_key'])
    if rt is None:
        raise P.ToolError('Unknown kind of record')
    project_id = _project(db, user, args['project']).id if args.get('project') else None
    data = {'type_key': rt.key, 'project_id': project_id, 'values': args.get('values') or {}}
    try:
        u.validate_record_item(db, data, actor=user)
        ticket = iw.propose(db, 'metadata_record', data, f"Proposed through the AI connector '{token.name}'", user)
        db.commit()
    except (ValueError, Exception) as ex:
        db.rollback()
        raise P.ToolError(str(ex)[:300])
    return P.tool_result({'ticket': ticket.id, 'saved': False}, f'Draft ticket #{ticket.id} opened. Nothing is saved until it is approved in StudioOS.')


PROJECT_ARG = {'type': 'string', 'description': 'Project name as used in StudioOS', 'maxLength': 200}
TOOLS = {t.name: t for t in [
    P.Tool('list_projects', 'List projects', 'Projects the person can see, with stage, client, open task count and (for finance roles) budget.',
           handler=t_list_projects),
    P.Tool('get_project_status', 'Project status', 'One project: open and overdue tasks with progress, latest site reports and, for finance roles, budget versus known costs.',
           {'project': PROJECT_ARG}, ['project'], handler=t_project_status),
    P.Tool('get_budget_summary', 'Budget summary', 'Approved budget, spent, committed and remaining per project (finance roles only). Leave project empty for all projects.',
           {'project': PROJECT_ARG}, handler=t_budget_summary),
    P.Tool('list_open_tasks', 'Open tasks', 'Open tasks across the projects the person can see, optionally for one project, one person, or overdue only.',
           {'project': PROJECT_ARG, 'assignee': {'type': 'string', 'maxLength': 150}, 'overdue_only': {'type': 'boolean'}},
           handler=t_open_tasks),
    P.Tool('search_documents', 'Search NAS file names', 'Search the indexed NAS file names and folders (drawings, PDFs). Returns names and paths only.',
           {'query': {'type': 'string', 'maxLength': 200}, 'project': PROJECT_ARG}, ['query'], handler=t_search_documents),
    P.Tool('list_waiting_approvals', 'Drafts waiting for approval', 'Drafts in StudioOS that still need a decision.',
           handler=t_waiting_approvals),
    P.Tool('get_records', 'Records of built types', 'Without record_type: the kinds of records built in StudioOS. With record_type: its saved records (optionally for one project).',
           {'record_type': {'type': 'string', 'maxLength': 120}, 'project': PROJECT_ARG}, handler=t_record_types),
    P.Tool('create_draft', 'Create a draft for approval', 'Send a business update (an expense, a task, a site note, progress) exactly as the person would type it into StudioOS chat. '
           'StudioOS prepares a DRAFT only; nothing is saved until the person approves it inside StudioOS. Use only when the person asks to record something.',
           {'message': {'type': 'string', 'maxLength': 2000, 'description': "The person's own words"}}, ['message'],
           handler=t_create_draft, read_only=False, scope='read_draft'),
    P.Tool('get_catalog', 'Kinds of records and reports', 'Every kind of record StudioOS knows (fields, options, what references point to), the links between them and the saved reports this person may run.',
           {}, handler=t_catalog),
    P.Tool('run_report', 'Run a saved report', 'Run one saved report by its key; only records this person may see are counted.',
           {'report': {'type': 'string', 'maxLength': 60}}, ['report'], handler=t_run_report),
    P.Tool('propose_record', 'Propose a record for approval', 'Propose one record of a kind from get_catalog with its field values. StudioOS checks every value and opens a DRAFT ticket; nothing is saved until the person approves it in StudioOS.',
           {'type_key': {'type': 'string', 'maxLength': 60}, 'project': PROJECT_ARG, 'values': {'type': 'object'}}, ['type_key', 'values'],
           handler=t_propose_record, read_only=False, scope='read_draft'),
]}
from .viewspec_mcp import VIEW_TOOLS as _VIEW_TOOLS, VIEW_WRITE_TOOLS as _VIEW_WRITE_TOOLS   # UI-3: view drafting tools
TOOLS.update({t.name: t for t in _VIEW_TOOLS})
WRITE_TOOLS = ('create_draft', 'propose_record') + _VIEW_WRITE_TOOLS


def _run_tool(tool, args, user, token):
    with SessionLocal() as db:
        db.info['write_source'] = 'api:mcp-read'
        me = db.get(User, user.id)
        if tool.name in WRITE_TOOLS:
            return tool.handler(db, me, args, token)
        result = tool.handler(db, me, args)
        if db.new or db.dirty or db.deleted:   # read tools must never write
            db.rollback()
            raise P.ToolError('Refused: a read-only tool tried to change data')
        return result
