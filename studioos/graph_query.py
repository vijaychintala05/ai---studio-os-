"""v0.10.0 "One graph": the database side of the universal engine.

* ``Resolver``      – hands records, staff, tasks, projects, clients, suppliers and files to the
                       report planner (graph_core), applying the reader's access on every step;
* ``record_page``   – one record with readable values, history and its links in both directions;
* ``targets``       – choices for a reference field or a new link (pickers instead of typed IDs);
* ``catalog_public``/``notices_for`` – what the generic screens and the chat need;
* ``apply_item``    – approved tickets that install a business pack, add a report, or adopt a
                       Stage A type into the universal engine.

Nothing here builds SQL from metadata. Every read is a fixed SQLAlchemy query on a known table.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import graph_core as G
from . import universal_engine as u
from .access import can_access_project, visible_project_ids, ALL_PROJECT_ROLES
from .db import (RecordType, FlexibleRecord, UniversalRelationshipType, UniversalEdge, UniversalRecordRevision,
                 UniversalMetadataVersion, UniversalWorkflow, UniversalWorkflowNotice, UniversalReport,
                 UniversalPackInstall, UniversalSavedView, UniversalCalculation, User, Task, Project, Party,
                 Document, Config, add_audit)

PACK_DIR = Path(__file__).with_name('business_packs')
MAX_BASE_ROWS = 50000   # v0.12.0: was 10,000; filters on direct fields are now applied by the database first
SYSTEM_EDGE = {'user': 'system.user', 'task': 'system.task', 'document': 'system.document'}


# ------------------------------------------------------------------ catalog

def universal_types(db: Session) -> dict:
    return {rt.key: rt for rt in db.scalars(select(RecordType).where(RecordType.status == 'active'))
            if (rt.design or {}).get('runtime_fields') is not None}


def relations(db: Session) -> dict:
    return {r.key: r for r in db.scalars(select(UniversalRelationshipType).where(UniversalRelationshipType.status == 'active'))}


def catalog(db: Session) -> dict:
    types = {k: {'title': rt.title, 'fields': rt.design['runtime_fields'], 'label_field': rt.design.get('label_field')}
             for k, rt in universal_types(db).items()}
    rels = {k: {'source_type': r.source_type, 'target_type': r.target_type} for k, r in relations(db).items()}
    return G.catalog_from(types, rels)


def available_packs() -> dict:
    out = {}
    for path in sorted(PACK_DIR.glob('*.json')):
        raw = path.read_bytes()
        pack = json.loads(raw)
        out[pack['key']] = {'pack': pack, 'sha256': hashlib.sha256(raw).hexdigest()}
    return out


def installed_packs(db: Session) -> dict:
    return {p.pack_key: p for p in db.scalars(select(UniversalPackInstall).order_by(UniversalPackInstall.id))}


# ------------------------------------------------------------------ nodes and the resolver

class Resolver:
    """Everything the report planner and the record page read, with the reader's access applied.
    Records the reader may not see are never returned; a link to one is simply not followed."""

    def __init__(self, db: Session, user):
        self.db, self.user = db, user
        self.pushed = {}            # v0.12.0: base type -> [(field, op, value)] the database applies first
        self.types = universal_types(db)
        self.allowed = visible_project_ids(db, user)
        self._nodes, self._edges_out, self._edges_in = {}, {}, {}
        self._party_ids=None

    # -- access
    def can_project(self, pid):
        return pid is None and self.user.role in ALL_PROJECT_ROLES or (
            pid is not None and (self.allowed is None or pid in self.allowed))

    def can_party(self,party_id):
        if self.allowed is None:return True
        if self._party_ids is None:
            from .party_access import visible_party_ids
            self._party_ids=visible_party_ids(self.db,self.user)
        return party_id in self._party_ids

    def can_record(self, rec):
        rt = self.types.get(rec.record_type)
        return rt is not None and u.can_read_record(self.db, self.user, rt, rec)

    # -- nodes
    def record_node(self, rec):
        key = ('record', rec.id)
        if key in self._nodes:
            return self._nodes[key]
        rt = self.types[rec.record_type]
        node = {'type': rec.record_type, 'id': rec.id, 'values': dict(rec.data or {}), 'project_id': rec.project_id,
                'label': f'{rt.title} #{rec.id}'}
        self._nodes[key] = node
        node['label'] = self.label_of(rt, rec)
        return node

    def label_of(self, rt, rec):
        design = rt.design or {}
        name = design.get('label_field')
        fields = {f['name']: f for f in design['runtime_fields']}
        if not name:
            name = next((f['name'] for f in design['runtime_fields'] if f['type'] == 'text'), None)
        value = (rec.data or {}).get(name) if name else None
        if value is None:
            return f'{rt.title} #{rec.id}'
        f = fields.get(name, {})
        if f.get('type') == 'reference':
            target = self.node_for(f['target'], value)
            text = target['label'] if target else f'#{value}'
            return f'{text}'
        if f.get('type') == 'date':
            return f'{rt.title} {value}'
        return str(value)[:120]

    def system_node(self, kind, obj_id):
        key = (kind, obj_id)
        if key in self._nodes:
            return self._nodes[key]
        db = self.db
        node = None
        if kind == 'system.user':
            x = db.get(User, obj_id)
            if x:
                node = {'values': {'display_name': x.display_name or x.username, 'username': x.username, 'role': x.role},
                        'label': x.display_name or x.username}
        elif kind == 'system.task':
            x = db.get(Task, obj_id)
            if x and not x.deleted_at and self.can_project(x.project_id):
                node = {'values': {'title': x.title, 'assignee': x.assignee, 'due_date': x.due_date, 'status': x.status,
                                   'progress': x.progress}, 'label': x.title, 'project_id': x.project_id}
        elif kind == 'system.project':
            x = db.get(Project, obj_id)
            if x and not x.deleted_at and self.can_project(x.id):
                node = {'values': {'name': x.name, 'client': x.client, 'stage': x.stage,
                                   'location': getattr(x, 'location', ''), 'start_date': getattr(x, 'start_date', '')},
                        'label': x.name}
        elif kind in ('system.client', 'system.supplier'):
            if not self.can_party(obj_id):
                self._nodes[key]=None
                return None
            x = db.get(Party, obj_id)
            if x and not x.deleted_at and x.kind == ('client' if kind == 'system.client' else 'vendor'):
                node = {'values': {'name': x.name, 'trade': x.trade, 'gstin': x.gstin if kind == 'system.supplier' else ''},
                        'label': x.name}
        elif kind == 'system.document':
            x = db.get(Document, obj_id)
            if x and (x.project_id is None or self.can_project(x.project_id)):
                node = {'values': {'name': x.name, 'doc_type': x.doc_type, 'relative_path': x.relative_path},
                        'label': x.name, 'project_id': x.project_id}
        if node is not None:
            node.update(type=kind, id=obj_id)
        self._nodes[key] = node
        return node

    def node_for(self, kind, obj_id):
        if type(obj_id) is not int:
            return None
        if kind in G.SYSTEM_TYPES:
            return self.system_node(kind, obj_id)
        rec = self.db.get(FlexibleRecord, obj_id)
        if not rec or rec.deleted_at or rec.record_type != kind or not self.can_record(rec):
            return None
        return self.record_node(rec)

    # -- the planner's interface
    def base_rows(self, base):
        if base == 'system.task':
            q = select(Task).where(Task.deleted_at.is_(None))
            if self.allowed is not None:
                q = q.where(Task.project_id.in_(self.allowed or {-1}))
            return [n for n in (self.system_node('system.task', t.id) for t in self.db.scalars(q.order_by(Task.id).limit(MAX_BASE_ROWS))) if n]
        rt = self.types.get(base)
        if rt is None:
            return []
        q = select(FlexibleRecord).where(FlexibleRecord.record_type == base, FlexibleRecord.deleted_at.is_(None))
        q = u.visible_records_clause(self.db, self.user, rt, q)
        for name, op, value in self.pushed.get(base, []):
            q = q.where(_pushed_clause(self.db, name, op, value))
        rows = self.db.scalars(q.order_by(FlexibleRecord.id).limit(MAX_BASE_ROWS + 1)).all()
        if len(rows) > MAX_BASE_ROWS:
            raise ValueError('Report exceeds the 50,000-record limit; add a filter or a date range')
        return [self.record_node(r) for r in rows]

    def _edges(self, rel_key):
        if rel_key not in self._edges_out:
            out, inc = {}, {}
            for e in self.db.scalars(select(UniversalEdge).where(UniversalEdge.relation_key == rel_key,
                                                                 UniversalEdge.removed_at.is_(None)).limit(20000)):
                tkind, tid = edge_target(e)
                skey = edge_source(e)
                out.setdefault(skey, []).append((tkind, tid))
                inc.setdefault((tkind, tid), []).append(skey[1])
            self._edges_out[rel_key], self._edges_in[rel_key] = out, inc
        return self._edges_out[rel_key], self._edges_in[rel_key]

    def follow(self, node, step):
        if step[0] == 'ref':
            target = self.node_for(step[2], (node.get('values') or {}).get(step[1]))
            return [target] if target else []
        if step[0] == 'project':
            pid = node.get('project_id')
            target = self.system_node('system.project', pid) if pid else None
            return [target] if target else []
        if step[0] == 'out':
            out, _ = self._edges(step[1])
            if node['type'] in G.SYSTEM_TYPES and node['type'] not in G.SYSTEM_SOURCES:
                return []
            skey = ('record', node['id']) if node['type'] not in G.SYSTEM_TYPES else (node['type'], node['id'])
            found = [self.node_for(step[2], tid) for _kind, tid in out.get(skey, [])]
            return [n for n in found if n]
        if step[0] == 'in':
            _, inc = self._edges(step[1])
            kind = 'record' if node['type'] not in G.SYSTEM_TYPES else _incoming_key(node['type'])
            found = [self.node_for(step[2], sid) for sid in inc.get((kind, node['id']), [])]
            return [n for n in found if n]
        return []


def edge_target(e):
    if e.target_record_id:
        return 'record', e.target_record_id
    if e.target_project_id:
        return 'system.project', e.target_project_id
    if e.target_party_id:
        return 'party', e.target_party_id
    return SYSTEM_EDGE.get(e.target_system, e.target_system), e.target_system_id


SOURCE_EDGE = {'task': 'system.task', 'user': 'system.user'}


def edge_source(e):
    """v0.11.0: ('record', id) or ('system.task' | 'system.user', id)."""
    if e.source_id is not None:
        return 'record', e.source_id
    return SOURCE_EDGE.get(e.source_system, e.source_system), e.source_system_id


def _incoming_key(kind):
    """How an incoming link names a node of this kind (see edge_target)."""
    return 'party' if kind in ('system.client', 'system.supplier') else kind


# ------------------------------------------------------------------ reports

def json_field(db: Session, name: str):
    """v0.12.0: one JSON field of flexible_records as text, written exactly like the expression
    indexes (views_core.index_statement) so the database can use them. ``name`` passes the strict
    key check first; nothing else is placed in the SQL."""
    from sqlalchemy import func, literal_column
    G.check_key(name, 'Field')
    if db.get_bind().dialect.name == 'postgresql':
        return FlexibleRecord.data.op('->>')(literal_column(f"'{name}'"))
    return func.json_extract(FlexibleRecord.data, literal_column(f"'$.{name}'"))


def _pushed_clause(db: Session, name, op, value):
    col = json_field(db, name)
    if op == 'in':
        return col.in_([str(v) for v in value])
    return {'eq': col == str(value), 'gte': col >= str(value), 'lte': col <= str(value),
            'gt': col > str(value), 'lt': col < str(value)}[op]


def run_report(db: Session, user, definition: dict) -> dict:
    from . import views_core as V
    res = Resolver(db, user)
    cat = catalog(db)
    today = u._today()
    try:
        V.checked(cat, definition)
        res.pushed[definition['base']] = V.pushable_filters(cat, definition, today)
        return V.run(res, cat, definition, today)
    except G.GraphError as ex:
        raise ValueError(str(ex)) from None


def ensure_report_indexes(db: Session, definition: dict) -> list:
    """v0.12.0: expression indexes for the fields an approved report filters or groups on.
    Runs inside a savepoint so a failure never undoes the approval; returns the index names made."""
    from sqlalchemy import text as sql_text
    from . import views_core as V
    dialect = db.get_bind().dialect.name
    if dialect not in ('postgresql', 'sqlite'):
        return []
    import logging
    made = []
    db.info['report_index_ddl'] = True
    try:
        for type_key, field in V.indexed_fields(catalog(db), definition):
            try:
                with db.begin_nested():
                    db.execute(sql_text(V.index_statement(dialect, type_key, field)))
                made.append(V.index_name(type_key, field))
            except Exception as ex:      # an index is only a speed-up; the report works without it
                logging.getLogger('studioos').warning('report index %s.%s not made: %s', type_key, field, ex)
                if dialect == 'postgresql':
                    # v0.16.0: the restricted app role owns no tables; the owner's upgrade step
                    # (python -m studioos.migrate) makes the index later.
                    from .db import Config
                    key = 'report_index_pending:' + V.index_name(type_key, field)
                    if db.get(Config, key) is None:
                        db.add(Config(key=key, value=f'{type_key}.{field}'))
    finally:
        db.info.pop('report_index_ddl', None)
    return made


def report_definition(db: Session, rep) -> dict:
    """v0.13.0: a report whose fields were renamed by a type change has a newer version in
    universal_view_definitions (kind 'report'); report rows themselves are append-only."""
    from .db import UniversalViewDefinition
    row = db.scalar(select(UniversalViewDefinition).where(UniversalViewDefinition.kind == 'report', UniversalViewDefinition.key == rep.key)
                    .order_by(UniversalViewDefinition.version.desc()).limit(1))
    return dict(row.definition) if row is not None else dict(rep.definition or {})


def report_list(db: Session, user=None):
    """v0.12.0: a report with ``visible_to`` is listed only for those roles (and Admin). Rows are
    limited by access whoever runs it; this only keeps the list short and relevant."""
    out = []
    for r in db.scalars(select(UniversalReport).order_by(UniversalReport.title)):
        d = report_definition(db, r)
        roles = d.get('visible_to')
        if user is not None and roles and user.role != 'admin' and user.role not in roles:
            continue
        out.append({'key': r.key, 'title': r.title, 'base': r.base, 'pack': r.pack_key, 'ticket_id': r.ticket_id,
                    'definition': d, 'display': d.get('display') or {'kind': 'table'}})
    return out


# ------------------------------------------------------------------ record page

def _display(f, value, res: Resolver):
    if value is None:
        return ''
    if f['type'] == 'reference':
        n = res.node_for(f['target'], value)
        return n['label'] if n else '(not visible to you)'
    if f['type'] == 'money' and isinstance(value, dict):
        n = G.as_number(value)
        return f'₹{n:,.2f}' if n is not None else ''
    if f['type'] == 'quantity' and isinstance(value, dict):
        return f'{value.get("value")} {value.get("unit")}'
    if f['type'] == 'boolean':
        return 'Yes' if value else 'No'
    return str(value)


def record_values(rt, rec, res: Resolver):
    return [{'name': f['name'], 'label': f.get('meaning') or f['name'].replace('_', ' ').capitalize(),
             'type': f['type'], 'target': f.get('target'), 'raw': (rec.data or {}).get(f['name']),
             'display': _display(f, (rec.data or {}).get(f['name']), res), 'required': bool(f.get('required')),
             'options': f.get('options'), 'units': f.get('units')}
            for f in rt.design['runtime_fields']]


def record_page(db: Session, user, record_id: int) -> dict:
    rec = db.get(FlexibleRecord, record_id)
    rt = db.get(RecordType, rec.record_type) if rec else None
    if not rec or not rt or (rt.design or {}).get('runtime_fields') is None or not u.can_read_record(db, user, rt, rec):
        raise LookupError('Record not found')
    res = Resolver(db, user)
    node = res.record_node(rec)
    history = db.scalars(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id == rec.id)
                         .order_by(UniversalRecordRevision.version)).all()
    rels = relations(db)
    outgoing, incoming = [], []
    for key, r in rels.items():
        if r.source_type == rec.record_type:
            items = []
            for e in db.scalars(select(UniversalEdge).where(UniversalEdge.relation_key == key, UniversalEdge.source_id == rec.id,
                                                            UniversalEdge.removed_at.is_(None)).order_by(UniversalEdge.id).limit(200)):
                kind, tid = edge_target(e)
                kind = r.target_type if kind in ('party', 'record') else kind
                n = res.node_for(kind, tid)
                if n:
                    items.append({'edge_id': e.id, 'id': tid, 'type': kind, 'label': n['label'],
                                  'is_record': kind not in G.SYSTEM_TYPES})
            outgoing.append({'relation': key, 'label': (r.definition or {}).get('label') or key.replace('_', ' '),
                             'target_type': r.target_type, 'target_title': G.node_title(catalog_stub(res), r.target_type),
                             'cardinality': r.cardinality, 'items': items})
        if r.target_type == rec.record_type:
            q = select(UniversalEdge).where(UniversalEdge.relation_key == key, UniversalEdge.target_record_id == rec.id,
                                            UniversalEdge.removed_at.is_(None))
            items = []
            for e in db.scalars(q.order_by(UniversalEdge.id).limit(500)):
                n = res.node_for(r.source_type, edge_source(e)[1])
                if n:
                    items.append({'edge_id': e.id, 'id': n['id'], 'type': r.source_type, 'label': n['label'],
                                  'values': n['values'], 'is_record': r.source_type not in G.SYSTEM_TYPES})
            order = (r.definition or {}).get('order_by')
            if order:
                items.sort(key=lambda x: (G.as_number(x['values'].get(order)) is None, G.as_number(x['values'].get(order)) or 0))
            for x in items:
                x.pop('values', None)
            incoming.append({'relation': key, 'label': r.inverse_label or key.replace('_', ' '),
                             'source_type': r.source_type, 'source_title': res.types[r.source_type].title
                             if r.source_type in res.types else G.node_title(catalog_stub(res), r.source_type), 'items': items})
    project = res.system_node('system.project', rec.project_id) if rec.project_id else None
    users = {x.id: (x.display_name or x.username) for x in db.scalars(select(User))}
    return {'id': rec.id, 'type_key': rt.key, 'type_title': rt.title, 'label': node['label'],
            'project_id': rec.project_id, 'project': project['label'] if project else None,
            'values': record_values(rt, rec, res), 'current_version': max([h.version for h in history], default=0),
            'history': [{'version': h.version, 'ticket_id': h.ticket_id, 'actor': users.get(h.actor) if isinstance(h.actor, int) else h.actor,
                         'at': h.created_at.isoformat() if getattr(h, 'created_at', None) else None,
                         'changed': sorted(k for k in set((h.before_data or {})) | set((h.after_data or {}))
                                           if (h.before_data or {}).get(k) != (h.after_data or {}).get(k))}
                        for h in history],
            'outgoing': outgoing, 'incoming': incoming,
            'approver_roles': ['admin'] + list((rt.design or {}).get('approver_roles') or [])}


def system_links(db: Session, user, kind: str, obj_id: int) -> dict:
    """v0.11.0 (Phase 0): the links that start at a task or a staff member, for the screens. Access is
    checked for the task (its project) and for every target."""
    if kind not in G.SYSTEM_SOURCES:
        raise LookupError('Links start only at records, tasks and staff members')
    res = Resolver(db, user)
    node = res.system_node(kind, obj_id)
    if node is None:
        raise LookupError('Not found')
    source_name = {'system.task': 'task', 'system.user': 'user'}[kind]
    groups = []
    for key, r in relations(db).items():
        if r.source_type != kind:
            continue
        items = []
        for e in db.scalars(select(UniversalEdge).where(UniversalEdge.relation_key == key, UniversalEdge.source_system == source_name,
                                                        UniversalEdge.source_system_id == obj_id,
                                                        UniversalEdge.removed_at.is_(None)).order_by(UniversalEdge.id).limit(200)):
            tkind, tid = edge_target(e)
            tkind = r.target_type if tkind in ('party', 'record') else tkind
            n = res.node_for(tkind, tid)
            if n:
                items.append({'edge_id': e.id, 'id': tid, 'type': tkind, 'label': n['label'], 'is_record': tkind not in G.SYSTEM_TYPES})
        groups.append({'relation': key, 'label': (r.definition or {}).get('label') or key.replace('_', ' '),
                       'target_type': r.target_type, 'target_title': G.node_title(catalog_stub(res), r.target_type),
                       'cardinality': r.cardinality, 'items': items})
    return {'kind': kind, 'id': obj_id, 'label': node['label'], 'project_id': node.get('project_id'), 'outgoing': groups}


def catalog_stub(res: Resolver):
    return {'types': {k: {'title': rt.title} for k, rt in res.types.items()}}


# ------------------------------------------------------------------ pickers

def targets(db: Session, user, target: str, q: str = '', project_id=None, limit: int = 50) -> list:
    """Choices for a reference field or a link, already limited to what this person may see."""
    q = (q or '').strip().casefold()[:80]
    res = Resolver(db, user)
    out = []
    if target == 'system.user':
        for x in db.scalars(select(User).where(User.active.is_(True)).order_by(User.display_name)):
            out.append({'id': x.id, 'label': x.display_name or x.username, 'detail': x.role.replace('_', ' ')})
    elif target == 'system.task':
        sel = select(Task).where(Task.deleted_at.is_(None))
        if project_id:
            sel = sel.where(Task.project_id == project_id)
        for t in db.scalars(sel.order_by(Task.id.desc()).limit(1000)):
            if res.can_project(t.project_id):
                out.append({'id': t.id, 'label': t.title, 'detail': t.status})
    elif target == 'system.project':
        for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)):
            if res.can_project(p.id):
                out.append({'id': p.id, 'label': p.name, 'detail': p.stage})
    elif target in ('system.client', 'system.supplier'):
        kind = 'client' if target == 'system.client' else 'vendor'
        from .party_access import visible_party_ids
        permitted=visible_party_ids(db,user)
        stmt=select(Party).where(Party.kind==kind,Party.deleted_at.is_(None)).order_by(Party.name)
        if permitted is not None:stmt=stmt.where(Party.id.in_(permitted or [-1]))
        for p in db.scalars(stmt):
            out.append({'id': p.id, 'label': p.name, 'detail': p.trade})
    elif target == 'system.document':
        for d in db.scalars(select(Document).order_by(Document.id.desc()).limit(2000)):
            if (d.project_id is None or res.can_project(d.project_id)) and (not project_id or d.project_id in (None, project_id)):
                out.append({'id': d.id, 'label': d.name, 'detail': d.doc_type})
    elif target in res.types:
        for n in res.base_rows(target):
            if project_id and n.get('project_id') not in (None, project_id):
                continue
            out.append({'id': n['id'], 'label': n['label'], 'detail': ''})
    else:
        raise LookupError('Unknown target')
    if q:
        out = [x for x in out if q in x['label'].casefold() or q in str(x.get('detail', '')).casefold()]
    return out[:limit]


def people(db: Session):
    """Active staff for the sentence reader: full name, first name, username."""
    out = []
    for x in db.scalars(select(User).where(User.active.is_(True))):
        name = (x.display_name or x.username).strip()
        out.append({'id': x.id, 'name': name, 'first': name.split()[0] if name else '', 'username': x.username})
    return out


# ------------------------------------------------------------------ catalog for the screens

def catalog_public(db: Session, user) -> dict:
    types = universal_types(db)
    rels = relations(db)
    packs = available_packs()
    done = installed_packs(db)
    pack_of = {}
    for p in done.values():
        for k in (p.contents or {}).get('types', []):
            pack_of[k] = p.pack_key
    titles = {**{k: v['title'] for k, v in G.SYSTEM_TYPES.items()}, **{k: rt.title for k, rt in types.items()}}
    return {
        'types': [{'key': k, 'title': rt.title, 'description': (rt.design or {}).get('purpose') or '',
                   'pack': pack_of.get(k), 'label_field': (rt.design or {}).get('label_field'),
                   'approver_roles': ['admin'] + list((rt.design or {}).get('approver_roles') or []),
                   'company_propose_roles': (rt.design or {}).get('company_propose_roles') or [],
                   'fields': [{**f, 'target_title': titles.get(f.get('target'))} for f in rt.design['runtime_fields']],
                   'version': int((rt.design or {}).get('version', 1))}
                  for k, rt in sorted(types.items(), key=lambda kv: kv[1].title.casefold())],
        'relations': [{'key': k, 'source_type': r.source_type, 'target_type': r.target_type, 'cardinality': r.cardinality,
                       'label': (r.definition or {}).get('label') or k.replace('_', ' '), 'inverse_label': r.inverse_label,
                       'target_title': titles.get(r.target_type, r.target_type), 'source_title': titles.get(r.source_type, r.source_type)}
                      for k, r in sorted(rels.items())],
        'system_types': [{'key': k, 'title': v['title']} for k, v in G.SYSTEM_TYPES.items()],
        'packs': [{'key': k, 'title': v['pack']['title'], 'description': v['pack'].get('description', ''),
                   'version': v['pack']['version'], 'sha256': v['sha256'],
                   'installed_version': done[k].version if k in done else None,
                   'contents': {x: len(v['pack'].get(x, [])) for x in ('types', 'relations', 'reports', 'workflows')},
                   'type_titles': [t['title'] for t in v['pack']['types']]} for k, v in packs.items()],
        'reports': [{'key': r['key'], 'title': r['title'], 'base': r['base'], 'pack': r['pack'],
                     'base_title': titles.get(r['base'], r['base'])} for r in report_list(db)],
        'legacy_types': [{'key': rt.key, 'title': rt.title} for rt in db.scalars(select(RecordType).where(RecordType.status == 'active'))
                         if (rt.design or {}).get('runtime_fields') is None] if user.role == 'admin' else [],
    }


# ------------------------------------------------------------------ notices

def maybe_run_daily_rules(db: Session) -> int:
    today = u._today().isoformat()
    mark = db.get(Config, 'graph_daily_rules_ran')
    if mark is not None and mark.value == today:
        return 0
    made = u.run_daily_rules(db)
    if mark is None:
        db.add(Config(key='graph_daily_rules_ran', value=today))
    else:
        mark.value = today
    db.commit()
    return made


def notices_for(db: Session, user, limit: int = 100) -> list:
    """Notices addressed to this person, plus general ones for managers; only for records they can read."""
    res = Resolver(db, user)
    q = select(UniversalWorkflowNotice).order_by(UniversalWorkflowNotice.id.desc()).limit(2000)
    out = []
    for n in db.scalars(q):
        if n.for_user_id is not None and n.for_user_id != user.id:
            continue
        if n.for_user_id is None and user.role not in ALL_PROJECT_ROLES:
            continue
        rec = db.get(FlexibleRecord, n.record_id)
        if not rec or not res.can_record(rec):
            continue
        node = res.record_node(rec)
        out.append({'id': n.id, 'rule': n.workflow_key, 'message': n.message, 'record_id': rec.id, 'record': node['label'],
                    'type_title': res.types[rec.record_type].title, 'for_me': n.for_user_id == user.id,
                    'at': n.created_at.isoformat() if n.created_at else None})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ approved tickets

def validate_item(db: Session, typ: str, d: dict, actor=None):
    if typ == 'metadata_report':
        if not isinstance(d, dict):
            raise ValueError('Report definition required')
        if db.get(UniversalReport, d.get('key')) is not None:
            raise ValueError('A report with this key already exists')
        from . import views_core as V
        try:
            cat = catalog(db)
            V.checked(cat, d)
            if 'display' in d:
                V.check_display(d['display'], d, cat)
            roles = d.get('visible_to')
            if roles is not None and (not isinstance(roles, list) or not roles or any(x not in G.ROLES for x in roles)):
                raise G.GraphError('visible_to lists roles')
        except G.GraphError as ex:
            raise ValueError(str(ex)) from None
        return d
    if typ == 'metadata_pack_install':
        if not isinstance(d, dict) or set(d) != {'pack', 'version', 'sha256'}:
            raise ValueError('Pack install names the pack, its version and its fingerprint')
        packs = available_packs()
        found = packs.get(d['pack'])
        if found is None:
            raise ValueError('Unknown business pack')
        if found['pack']['version'] != d['version'] or found['sha256'] != d['sha256']:
            raise ValueError('The pack file changed after this ticket was opened; open a new ticket')
        done = installed_packs(db)
        if d['pack'] in done:
            raise ValueError('This pack is already installed')
        existing = set(universal_types(db)) | {rt.key for rt in db.scalars(select(RecordType))}
        try:
            return G.check_pack(found['pack'], existing_types=existing,
                                existing_relations={k: {'source_type': r.source_type, 'target_type': r.target_type}
                                                    for k, r in relations(db).items()},
                                installed_packs=set(done))
        except G.GraphError as ex:
            raise ValueError(str(ex)) from None
    if typ == 'metadata_type_adopt':
        if not isinstance(d, dict) or set(d) != {'type_key'}:
            raise ValueError('Name the record type to bring into the universal engine')
        rt = db.get(RecordType, d['type_key']) if isinstance(d.get('type_key'), str) else None
        if not rt or rt.status != 'active':
            raise ValueError('Active record type required')
        if (rt.design or {}).get('runtime_fields') is not None:
            raise ValueError('This type already uses the universal engine')
        fields = G.legacy_to_runtime(rt.design)
        if not fields:
            raise ValueError('None of this type\'s fields can be typed exactly; nothing to adopt')
        return fields
    raise ValueError('Unsupported item')


def _sub(item, typ, data):
    return SimpleNamespace(after_data=data, item_type=typ, ticket_id=item.ticket_id, id=item.id)


def apply_item(db: Session, item, actor):
    d, typ = item.after_data, item.item_type
    if typ == 'metadata_report':
        validate_item(db, typ, d)
        db.add(UniversalReport(key=d['key'], title=d['title'], base=d['base'], definition=dict(d), ticket_id=item.ticket_id))
        db.flush()
        ensure_report_indexes(db, d)      # v0.12.0
        add_audit(db, 'universal_metadata_report', 'universal_report', 0, f'Ticket #{item.ticket_id} added report {d["key"]}', actor=actor)
        return {'type': 'universal_report', 'id': 0, 'item_id': item.id}
    if typ == 'metadata_type_adopt':
        fields = validate_item(db, typ, d)
        rt = db.get(RecordType, d['type_key'])
        design = dict(rt.design)
        design['runtime_fields'] = fields
        design['version'] = int(design.get('version', 1)) + 1
        design['adopted_by_ticket_id'] = item.ticket_id
        if rt.source_inbox_id is None:
            design.setdefault('runtime_approval_ticket_id', item.ticket_id)
        rt.design = design
        db.add(UniversalMetadataVersion(type_key=rt.key, version=design['version'], definition=dict(design),
                                        ticket_id=item.ticket_id, actor=actor))
        db.flush()
        add_audit(db, 'universal_type_adopted', 'record_type', 0,
                  f'Ticket #{item.ticket_id}: {rt.key} now uses the universal engine ({len(fields)} fields); stored records unchanged', actor=actor)
        return {'type': 'record_type', 'id': 0, 'item_id': item.id}
    if typ == 'metadata_pack_install':
        validate_item(db, typ, d)
        pack = available_packs()[d['pack']]['pack']
        # Each part goes through the SAME validator and apply code as a single ticket item would.
        for t in pack['types']:
            u.apply_item(db, _sub(item, 'metadata_type', t), actor)
            db.flush()
        for r in pack.get('relations', []):
            u.apply_item(db, _sub(item, 'metadata_relation', r), actor)
        for v in pack.get('views', []):
            u.apply_item(db, _sub(item, 'metadata_view', v), actor)
        for w in pack.get('workflows', []):
            u.apply_item(db, _sub(item, 'metadata_workflow', w), actor)
        for c in pack.get('calculations', []):
            u.apply_item(db, _sub(item, 'metadata_calculation', c), actor)
        db.flush()
        for rep in pack.get('reports', []):
            G.check_report(catalog(db), rep)
            db.add(UniversalReport(key=rep['key'], title=rep['title'], base=rep['base'], definition=dict(rep),
                                   pack_key=pack['key'], ticket_id=item.ticket_id))
        summary = G.check_pack(pack)
        db.add(UniversalPackInstall(pack_key=pack['key'], version=pack['version'], sha256=d['sha256'],
                                    contents=summary, ticket_id=item.ticket_id, actor=str(actor)))
        db.flush()
        add_audit(db, 'universal_pack_installed', 'universal_pack', 0,
                  f'Ticket #{item.ticket_id} installed {pack["title"]} v{pack["version"]}: '
                  f'{len(summary["types"])} types, {len(summary["relations"])} links, {len(summary["reports"])} reports, '
                  f'{len(summary["workflows"])} rules; no tables created', actor=actor)
        return {'type': 'universal_pack', 'id': 0, 'item_id': item.id}
    raise ValueError('Unsupported item')
