"""v0.11.0: the AI reader connected to the database (thin; the logic is in the stdlib modules
ai_gateway, ai_reader, name_match, privacy_mask and ai_learning).

* Settings: one JSON value in the settings table ('ai_reader_settings'), Admin only, merged over
  the existing model switch in the environment. Keys are never stored here.
* Call log: ai_call_log rows (append-only by database trigger).
* Context for the reader: the type from the catalog, staff, the projects this person may see,
  client names (for masking), approved aliases and recent corrections.
* Corrections: ai_corrections rows (append-only); alias suggestions; metadata_alias tickets.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai_gateway as GW
from . import ai_learning as L
from . import ai_reader as R
from .access import visible_project_ids
from .party_access import visible_party_ids
from .record_types import is_money_field
from .security import FINANCE_READ
from .db import AiCallLog, AiCorrection, Config, NameAlias, Party, Project, User, add_audit

SETTINGS_KEY = 'ai_reader_settings'
DISMISS_PREFIX = 'ai_alias_dismissed:'


# ------------------------------------------------------------------ settings and the gateway

def load_settings(db: Session) -> dict:
    base = GW.defaults_from_environment()
    row = db.get(Config, SETTINGS_KEY)
    stored = {}
    if row:
        try:
            stored = json.loads(row.value)
        except (ValueError, TypeError):
            stored = {}
    try:
        return GW.check_settings({k: v for k, v in stored.items() if k in GW.SETTING_KEYS}, base)
    except ValueError:
        return GW.check_settings({}, {**base, 'enabled': False})      # a broken value: AI off


def save_settings(db: Session, raw: dict, actor: str) -> dict:
    merged = GW.check_settings(raw, load_settings(db))
    value = json.dumps(merged, sort_keys=True)
    row = db.get(Config, SETTINGS_KEY)
    if row:
        row.value = value
    else:
        db.add(Config(key=SETTINGS_KEY, value=value))
    changed = ', '.join(sorted(raw))
    add_audit(db, 'ai_settings_changed', 'settings', 0, f'AI settings changed ({changed})', actor=actor)
    return merged


class DbLog:
    def __init__(self, db: Session):
        self.db = db

    def append(self, row: dict):
        created = dt.datetime.fromisoformat(row['created_at']) if isinstance(row.get('created_at'), str) else None
        self.db.add(AiCallLog(**{k: row.get(k) for k in ('purpose', 'provider', 'model', 'prompt_bytes', 'prompt_tokens',
                                                          'output_tokens', 'latency_ms', 'cost_micro_usd', 'outcome',
                                                          'masked', 'user_id')},
                              **({'created_at': created} if created else {})))
        self.db.flush()

    def month_spent_micro(self, month: str) -> int:
        start = dt.datetime.fromisoformat(month + '-01T00:00:00+00:00')
        end = (start + dt.timedelta(days=32)).replace(day=1)
        return int(self.db.scalar(select(func.coalesce(func.sum(AiCallLog.cost_micro_usd), 0))
                                  .where(AiCallLog.created_at >= start, AiCallLog.created_at < end)) or 0)


def gateway(db: Session, transport=None) -> GW.Gateway:
    settings=load_settings(db)
    if transport is None and settings['provider']=='recorded':
        from .recorded_transport import RecordedTransport,RECORDINGS_ROOT
        transport=RecordedTransport(RECORDINGS_ROOT/'reader-responses.json',
                                    os.environ.get('STUDIOOS_RECORDED_RESPONSES_SHA256',''))
    return GW.Gateway(settings, transport or GW.HttpTransport(), DbLog(db))


def recent_calls(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(select(AiCallLog).order_by(AiCallLog.id.desc()).limit(max(1, min(limit, 200))))
    return [{'id': r.id, 'at': r.created_at.isoformat() if r.created_at else None, 'purpose': r.purpose, 'provider': r.provider,
             'model': r.model, 'prompt_bytes': r.prompt_bytes, 'prompt_tokens': r.prompt_tokens, 'output_tokens': r.output_tokens,
             'latency_ms': r.latency_ms, 'cost_usd': GW._usd(r.cost_micro_usd or 0), 'outcome': r.outcome, 'masked': r.masked}
            for r in rows]


# ------------------------------------------------------------------ the reader's context

def approved_aliases(db: Session) -> list[dict]:
    users = {u.id: (u.display_name or u.username) for u in db.scalars(select(User))}
    out = []
    for a in db.scalars(select(NameAlias).order_by(NameAlias.id)):
        out.append({'kind': a.kind, 'target_id': a.target_id, 'type_key': a.type_key, 'field_name': a.field_name,
                    'option': a.option, 'alias': a.alias,
                    'target_name': users.get(a.target_id, '') if a.kind == 'staff' else ''})
    return out


def reader_context(db: Session, user, rt, projects: list[dict], people: list[dict]) -> dict:
    from . import graph_query as gq
    allowed = visible_project_ids(db, user)
    permitted_parties = visible_party_ids(db, user)
    if allowed is not None:
        projects = [p for p in projects if p['id'] in allowed]
    aliases = [a for a in approved_aliases(db)
               if (a['kind'] != 'project' or allowed is None or a['target_id'] in allowed)
               and (a['kind'] not in ('client', 'supplier') or permitted_parties is None
                    or a['target_id'] in permitted_parties)]
    by_staff, by_project = {}, {}
    for a in aliases:
        if a['kind'] == 'staff':
            by_staff.setdefault(a['target_id'], []).append(a['alias'])
        elif a['kind'] == 'project':
            by_project.setdefault(a['target_id'], []).append(a['alias'])
    contacts = select(Party).where(Party.kind == 'client', Party.deleted_at.is_(None))
    project_rows = select(Project).where(Project.deleted_at.is_(None))
    if permitted_parties is not None:
        contacts = contacts.where(Party.id.in_(permitted_parties or {-1}))
    if allowed is not None:
        project_rows = project_rows.where(Project.id.in_(allowed or {-1}))
    clients = [p.name for p in db.scalars(contacts)]
    clients += [p.client for p in db.scalars(project_rows) if p.client]
    design = rt.design or {}
    return {'key': rt.key, 'title': rt.title, 'description': design.get('purpose', ''), 'type_aliases': design.get('aliases', []),
            'fields': design['runtime_fields'],
            'links': [{'key': k, 'target_type': r.target_type} for k, r in gq.relations(db).items() if r.source_type == rt.key],
            'people': [{**p, 'aliases': by_staff.get(p['id'], [])} for p in people],
            'projects': [{'id': p['id'], 'name': p['name'], 'aliases': by_project.get(p['id'], [])} for p in projects],
            'clients': sorted(set(clients)), 'aliases': aliases}


def correction_rows(db: Session, type_key: str | None = None, limit: int = 500, *,
                    project_ids: set[int] | None = None) -> list[dict]:
    q = select(AiCorrection).order_by(AiCorrection.id.desc()).limit(limit)
    if type_key:
        q = q.where(AiCorrection.type_key == type_key)
    if project_ids is not None:
        q = q.where(AiCorrection.project_id.in_(project_ids or {-1}))
    return [{'id': c.id, 'type_key': c.type_key, 'field_name': c.field_name, 'field_type': c.field_type, 'target': c.target,
             'source_text': c.source_text, 'proposed': c.proposed, 'chosen': c.chosen} for c in db.scalars(q)]


def read_message(db: Session, user, rt, text: str, today: dt.date, projects: list[dict], people: list[dict]) -> dict:
    """The one call graph_card makes. AI only when both switches are on; offline otherwise."""
    ctx = reader_context(db, user, rt, projects, people)
    gw = gateway(db)
    examples = []
    if gw.is_on():
        rows = correction_rows(db, rt.key, 100, project_ids=visible_project_ids(db, user))
        if user.role not in FINANCE_READ:
            fields = {f['name'] for f in rt.design['runtime_fields'] if not is_money_field(f)}
            rows = [row for row in rows if row['field_name'] in fields]
        examples = L.few_shot_examples(rows, rt.key)
    return R.read(ctx, text, today, gw, examples=examples, user_id=getattr(user, 'id', None))


def record_corrections(db: Session, user, item, rt, old_values: dict, new_values: dict, marks: dict):
    """Called when a person changes a value the reader proposed (append-only)."""
    spec = {f['name']: f for f in rt.design['runtime_fields']}
    for name, chosen in new_values.items():
        f = spec.get(name)
        mark = marks.get('values.' + name) or {}
        if f is None or mark.get('marker') not in ('sourced', 'guessed'):
            continue
        row = L.correction_row(rt.key, f, mark.get('source_words'), old_values.get(name), chosen,
                               getattr(user, 'id', None), item.id)
        if row:
            project_id = mark.get('source_project_id')
            if type(project_id) is not int or project_id != (item.after_data or {}).get('project_id'):
                project_id = None
            db.add(AiCorrection(**row, project_id=project_id))
    db.flush()


# ------------------------------------------------------------------ aliases

def _dismiss_key(data: dict) -> str:
    return DISMISS_PREFIX + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:40]


def option_map(db: Session) -> dict:
    """{(type_key, field_name): [options]} of every option field, so a word that already is an option
    is not suggested as another name for one."""
    from .db import RecordType
    out = {}
    for rt in db.scalars(select(RecordType)):
        for f in (rt.design or {}).get('runtime_fields') or []:
            if f.get('type') == 'enum':
                out[(rt.key, f['name'])] = list(f.get('options') or [])
    return out


def alias_suggestions(db: Session) -> list[dict]:
    existing = approved_aliases(db)
    out = []
    for s in L.alias_suggestions(correction_rows(db, None, 2000), existing=existing, options=option_map(db)):
        if db.get(Config, _dismiss_key(s['data'])) is None:
            out.append(s)
    return out[:10]


def dismiss_suggestion(db: Session, data: dict, actor: str):
    data = L.check_alias(data)
    key = _dismiss_key(data)
    if db.get(Config, key) is None:
        db.add(Config(key=key, value=json.dumps({'alias': data['alias'], 'kind': data['kind']})))
        add_audit(db, 'ai_alias_dismissed', 'settings', 0, f'Alias suggestion "{data["alias"]}" dismissed', actor=actor)


def validate_alias(db: Session, d: dict):
    """metadata_alias ticket item (Admin approves)."""
    from . import graph_core as G
    data = L.check_alias(d)
    if data['kind'] == 'staff':
        u = db.get(User, data['target_id'])
        if not u or not u.active:
            raise ValueError('Staff member not found or inactive')
    elif data['kind'] == 'project':
        p = db.get(Project, data['target_id'])
        if not p or p.deleted_at:
            raise ValueError('Project not found')
    elif data['kind'] in ('client', 'supplier'):
        p = db.get(Party, data['target_id'])
        if not p or p.deleted_at or p.kind != ('client' if data['kind'] == 'client' else 'vendor'):
            raise ValueError('Not found')
    else:
        from .db import RecordType
        rt = db.get(RecordType, data['type_key'])
        f = next((x for x in ((rt.design or {}).get('runtime_fields') or []) if x['name'] == data['field_name']), None) if rt else None
        if not f or f['type'] != 'enum' or data['option'] not in f['options']:
            raise ValueError('Choose an option of an option field')
        if G._norm(data['alias']) in {G._norm(o) for o in f['options']}:
            raise ValueError('That is already an option')
    clash = db.scalar(select(NameAlias).where(NameAlias.kind == data['kind'], NameAlias.type_key == data.get('type_key', ''),
                                              NameAlias.field_name == data.get('field_name', ''),
                                              func.lower(NameAlias.alias) == data['alias'].lower()))
    if clash is not None:
        raise ValueError('That other name is already in use')
    return data


def apply_alias(db: Session, item, actor):
    data = validate_alias(db, item.after_data or {})
    row = NameAlias(kind=data['kind'], target_id=data.get('target_id'), type_key=data.get('type_key', ''),
                    field_name=data.get('field_name', ''), option=data.get('option', ''), alias=data['alias'],
                    ticket_id=item.ticket_id)
    db.add(row)
    db.flush()
    add_audit(db, 'name_alias_added', 'name_alias', row.id, f'Ticket #{item.ticket_id}: "{data["alias"]}" is another name ({data["kind"]})', actor=actor)
    return {'type': 'name_alias', 'id': row.id, 'item_id': item.id}
