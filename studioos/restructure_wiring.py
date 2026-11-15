"""v0.13.0: safe restructuring connected to the database (thin; the logic is in restructure_core).

* ``build_world`` reads universal types, their records, links, reports (newest version), rules,
  saved views, layouts, dashboards, formulas and document templates into plain data.
* ``metadata_type_change`` (Admin ticket): preview again at approval, refuse on any blocker, take a
  verified backup (the same hook as schema upgrades), then write every changed object in the same
  transaction: types (with a metadata version), records (with a record revision each), links,
  reports (a new report version: report rows are append-only), rules, saved views, layouts. The
  change and its before/after objects go to the append-only universal_type_changes.
* ``metadata_type_change_undo`` (Admin ticket): puts back exactly the "before" objects, refused if
  any of them changed since.
* ``metadata_pack_upgrade`` (Admin ticket): a business pack's next version as one ticket.
Nothing here touches finance tables, journals, recipes or the chart of accounts.
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import graph_query as gq
from . import restructure_core as RC
from . import universal_engine as u
from .db import (FlexibleRecord, RecordType, UniversalCalculation, UniversalDocumentTemplate, UniversalEdge,
                 UniversalMetadataVersion, UniversalPackInstall, UniversalRecordRevision, UniversalRelationshipType,
                 UniversalReport, UniversalSavedView, UniversalTypeChange, UniversalViewDefinition, UniversalWorkflow,
                 add_audit, engine)

TYPE_DESIGN_KEYS = ('aliases', 'label_field', 'self_read', 'removed_fields', 'merged_into')


def _type_world(rt) -> dict | None:
    d = rt.design or {}
    if d.get('runtime_fields') is None:
        return None
    if rt.status != 'active' and not d.get('merged_into'):
        return None                       # retired (or a split undone): not part of the world
    out = {'title': rt.title, 'fields': d['runtime_fields'], 'version': int(d.get('version', 1)),
           'status': 'active' if rt.status == 'active' else 'merged'}
    for k in TYPE_DESIGN_KEYS:
        if k in d:
            out[k] = d[k]
    return out


def build_world(db: Session) -> dict:
    types = {}
    for rt in db.scalars(select(RecordType)):
        t = _type_world(rt)
        if t is not None:
            types[rt.key] = t
    records = {r.id: {'type': r.record_type, 'data': r.data or {}, 'project_id': r.project_id}
               for r in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type.in_(list(types) or ['-']),
                                                                 FlexibleRecord.deleted_at.is_(None)).limit(RC.MAX_RECORDS + 1))}
    relations = {r.key: {'source_type': r.source_type, 'target_type': r.target_type}
                 for r in db.scalars(select(UniversalRelationshipType))}
    edges = [{'id': e.id, 'rel': e.relation_key, 'source': e.source_id, 'target': e.target_record_id}
             for e in db.scalars(select(UniversalEdge).where(UniversalEdge.removed_at.is_(None)))]
    from .views_wiring import latest
    return {'types': types, 'records': records, 'relations': relations, 'edges': edges,
            'reports': {r.key: gq.report_definition(db, r) for r in db.scalars(select(UniversalReport))},
            'rules': {w.key: {'type_key': w.type_key, 'definition': w.definition} for w in db.scalars(select(UniversalWorkflow))},
            'views': {v.key: {'type_key': v.type_key, 'definition': v.definition} for v in db.scalars(select(UniversalSavedView))},
            'layouts': {k: {kk: vv for kk, vv in v.items() if kk != 'version'} for k, v in latest(db, 'layout').items()},
            'dashboards': {k: {kk: vv for kk, vv in v.items() if kk != 'version'} for k, v in latest(db, 'dashboard').items()},
            'calculations': {c.key: {'type_key': c.type_key, 'definition': c.definition} for c in db.scalars(select(UniversalCalculation))},
            'templates': {t.key: {'type_key': t.type_key, 'definition': t.definition} for t in db.scalars(select(UniversalDocumentTemplate))}}


def preview(db: Session, change: dict) -> dict:
    p = RC.plan(change, build_world(db), u._today())
    return {'change': change, 'summary': RC.summary(p), 'impact': p['impact'], 'blockers': p['blockers'],
            'unconvertible': p['unconvertible'], 'unconvertible_total': p['unconvertible_total']}


def validate_change(db: Session, d: dict):
    try:
        p = RC.plan(d, build_world(db), u._today())
    except (RC.ChangeError, ValueError) as ex:
        raise ValueError(str(ex)) from None
    if p['blockers']:
        raise ValueError('This change cannot be approved yet: ' + '; '.join(p['blockers'][:5]))
    return p


def validate_undo(db: Session, d: dict):
    if not isinstance(d, dict) or set(d) != {'change_id'} or type(d['change_id']) is not int:
        raise ValueError('Name the change to undo')
    row = db.get(UniversalTypeChange, d['change_id'])
    if row is None or row.undo_of is not None:
        raise ValueError('Change not found (an undo itself is undone with a new change)')
    if db.scalar(select(UniversalTypeChange.id).where(UniversalTypeChange.undo_of == row.id)):
        raise ValueError('This change was already undone')
    p = RC.inverse(build_world(db), {'id': row.id, 'before': _from_json(json.loads(row.before)), 'after': _from_json(json.loads(row.after)),
                                     'impact': row.impact})
    if p['blockers']:
        raise ValueError('Cannot undo: ' + '; '.join(p['blockers'][:5]))
    return row, p


def _backup(reason: str):
    """The verified pre-upgrade snapshot hook; a failure stops the change."""
    from .hooks import before_schema_migration
    before_schema_migration(engine, reason)


def _write(db: Session, p: dict, ticket_id: int, actor: str):
    after = p['after']
    for key, t in after['types'].items():
        rt = db.get(RecordType, key)
        if t is None:
            if rt is not None:
                rt.status = 'retired'
            continue
        design = dict(rt.design) if rt is not None else {}
        design['runtime_fields'] = copy.deepcopy(t['fields'])
        design['version'] = t['version']
        for k in TYPE_DESIGN_KEYS:
            if k in t:
                design[k] = copy.deepcopy(t[k])
            else:
                design.pop(k, None)
        if rt is None:
            rt = RecordType(key=key, title=t['title'], design=design, status='active', activated_by=actor)
            db.add(rt)
        else:
            rt.title, rt.design = t['title'], design
            rt.status = 'active' if t.get('status', 'active') == 'active' else 'retired'
        db.flush()
        if not db.scalar(select(UniversalMetadataVersion.id).where(UniversalMetadataVersion.type_key == key,
                                                                   UniversalMetadataVersion.version == t['version'])):
            db.add(UniversalMetadataVersion(type_key=key, version=t['version'], definition=dict(design), ticket_id=ticket_id, actor=actor))
    for rid, r in after['records'].items():
        rec = db.get(FlexibleRecord, int(rid))
        if rec is None or r is None:
            continue
        before_data = dict(rec.data or {})
        rec.data, rec.record_type = copy.deepcopy(r['data']), r['type']
        version = int(db.scalar(select(func.coalesce(func.max(UniversalRecordRevision.version), 0))
                                .where(UniversalRecordRevision.record_id == rec.id)) or 0) + 1
        defn = after['types'].get(r['type']) or {}
        db.add(UniversalRecordRevision(record_id=rec.id, version=version, before_data=before_data, after_data=dict(rec.data),
                                       definition_version=int(defn.get('version', 1)), ticket_id=ticket_id, actor=actor))
    for key, rel in after['relations'].items():
        row = db.get(UniversalRelationshipType, key)
        if row is not None and rel is not None:
            row.source_type, row.target_type = rel['source_type'], rel['target_type']
    for key, rep in after['reports'].items():
        version = int(db.scalar(select(func.coalesce(func.max(UniversalViewDefinition.version), 0))
                                .where(UniversalViewDefinition.kind == 'report', UniversalViewDefinition.key == key)) or 0) + 1
        db.add(UniversalViewDefinition(kind='report', key=key, version=version, definition=copy.deepcopy(rep), ticket_id=ticket_id))
    for key, x in after['rules'].items():
        row = db.get(UniversalWorkflow, key)
        if row is not None and x is not None:
            row.type_key, row.definition = x['type_key'], copy.deepcopy(x['definition'])
    for key, x in after['views'].items():
        row = db.get(UniversalSavedView, key)
        if row is not None and x is not None:
            row.type_key, row.definition = x['type_key'], copy.deepcopy(x['definition'])
    for key, lay in after['layouts'].items():
        if lay is None:
            continue
        version = int(db.scalar(select(func.coalesce(func.max(UniversalViewDefinition.version), 0))
                                .where(UniversalViewDefinition.kind == 'layout', UniversalViewDefinition.key == key)) or 0) + 1
        db.add(UniversalViewDefinition(kind='layout', key=key, version=version, definition=copy.deepcopy(lay), ticket_id=ticket_id))
    db.flush()


def apply_change(db: Session, item, actor: str):
    d = item.after_data or {}
    if item.item_type == 'metadata_type_change_undo':
        row, p = validate_undo(db, d)
        _backup(f'Undo type change #{row.id} (ticket #{item.ticket_id})')
        _write(db, p, item.ticket_id, actor)
        out = UniversalTypeChange(ticket_id=item.ticket_id, type_key=row.type_key, op='undo', change={'undo_of': row.id},
                                  before=row.after, after=row.before, impact=row.impact, undo_of=row.id)
        label = f'undid change #{row.id}'
    else:
        p = validate_change(db, d)
        _backup(f'Type change {d.get("op")} on {d.get("type_key")} (ticket #{item.ticket_id})')
        _write(db, p, item.ticket_id, actor)
        out = UniversalTypeChange(ticket_id=item.ticket_id, type_key=d['type_key'], op=d['op'], change=dict(d),
                                  before=_jsonable(p['before']), after=_jsonable(p['after']), impact=p['impact'])
        label = f'{d["op"]} on {d["type_key"]}: {RC.summary(p)}'
    db.add(out)
    db.flush()
    add_audit(db, 'universal_type_change', 'universal_type_change', out.id, f'Ticket #{item.ticket_id} {label}', actor=actor)
    return {'type': 'universal_type_change', 'id': out.id, 'item_id': item.id}


def _jsonable(stores: dict) -> str:
    """Stored as text with the keys in their original order (record ids become text keys)."""
    return json.dumps({s: {str(k): v for k, v in objs.items()} for s, objs in stores.items()}, ensure_ascii=False)


def _from_json(stores: dict) -> dict:
    return {s: ({int(k): v for k, v in objs.items()} if s == 'records' else dict(objs)) for s, objs in (stores or {}).items()}


def history(db: Session, limit: int = 50) -> list[dict]:
    undone = {r.undo_of for r in db.scalars(select(UniversalTypeChange).where(UniversalTypeChange.undo_of.is_not(None)))}
    return [{'id': r.id, 'ticket_id': r.ticket_id, 'type_key': r.type_key, 'op': r.op, 'change': r.change, 'impact': r.impact,
             'undo_of': r.undo_of, 'undone': r.id in undone, 'at': r.created_at.isoformat() if r.created_at else None}
            for r in db.scalars(select(UniversalTypeChange).order_by(UniversalTypeChange.id.desc()).limit(limit))]


# ------------------------------------------------------------------ business pack upgrades

def pack_upgrade_items(db: Session, pack_key: str) -> dict:
    packs = gq.available_packs()
    found = packs.get(pack_key)
    done = gq.installed_packs(db)
    if found is None or pack_key not in done:
        raise ValueError('Install the pack first')
    installed_version = max(p.version for p in db.scalars(select(UniversalPackInstall).where(UniversalPackInstall.pack_key == pack_key)))
    if installed_version >= found['pack']['version']:
        raise ValueError('This pack is up to date')
    items = RC.pack_upgrade_plan({'key': pack_key, 'version': installed_version}, found['pack'], build_world(db))
    return {'pack': pack_key, 'from_version': installed_version, 'version': found['pack']['version'], 'sha256': found['sha256'],
            'items': items[:-1]}


def validate_pack_upgrade(db: Session, d: dict):
    if not isinstance(d, dict) or set(d) != {'pack', 'version', 'sha256'}:
        raise ValueError('A pack upgrade names the pack, the new version and its fingerprint')
    plan = pack_upgrade_items(db, d['pack'])
    if plan['version'] != d['version'] or plan['sha256'] != d['sha256']:
        raise ValueError('The pack file changed after this ticket was opened; open a new ticket')
    return plan


def apply_pack_upgrade(db: Session, item, actor: str):
    plan = validate_pack_upgrade(db, item.after_data or {})
    for sub in plan['items']:
        fake = SimpleNamespace(after_data=sub['data'], item_type=sub['kind'], ticket_id=item.ticket_id, id=item.id)
        from .tickets import validate_item
        validate_item(db, fake)
        u.apply_item(db, fake, actor)
    db.add(UniversalPackInstall(pack_key=plan['pack'], version=plan['version'], sha256=plan['sha256'], ticket_id=item.ticket_id))
    db.flush()
    add_audit(db, 'universal_pack_upgrade', 'universal_pack', 0,
              f'Ticket #{item.ticket_id} upgraded pack {plan["pack"]} {plan["from_version"]} → {plan["version"]}', actor=actor)
    return {'type': 'universal_pack_upgrade', 'id': 0, 'item_id': item.id}
