"""v0.12.0: questions, displays, dashboards and layouts connected to the database (thin; the logic is
in views_core). Nothing here writes business data: dashboards and layouts are saved by Admin
tickets (metadata_dashboard, metadata_layout) into the append-only universal_view_definitions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import graph_core as G
from . import graph_query as gq
from . import universal_engine as u
from . import views_core as V
from .access import visible_project_ids
from .db import Project, RecordType, UniversalReport, UniversalViewDefinition, add_audit

PREVIEW_ROWS = 10


def _people(db):
    return [{'id': p['id'], 'name': p['name']} for p in gq.people(db)]


def _aliases(db):
    return {k: (rt.design or {}).get('aliases', []) for k, rt in gq.universal_types(db).items()}


def ask(db: Session, user, question: str) -> dict:
    """Question -> report definition (AI if on, else offline), described in words, run on what this
    person may see, with the first rows. Saves nothing."""
    from . import ai_wiring
    cat = gq.catalog(db)
    projects = select(Project.name).where(Project.deleted_at.is_(None)).order_by(Project.name)
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        projects = projects.where(Project.id.in_(allowed))
    out = V.question_to_report(question, cat, u._today(), ai_wiring.gateway(db), _aliases(db), _people(db),
                               user_id=getattr(user, 'id', None), projects=db.scalars(projects).all())
    from .improve_wiring import log_question       # v0.15.0: "asked often" becomes a suggestion
    log_question(db, user, question, out.get('report') if out['status'] == 'ok' else None)
    db.commit()       # keep the call-log rows even though nothing else is written
    if out['status'] != 'ok':
        return out
    try:
        result = gq.run_report(db, user, out['report'])
    except ValueError as ex:
        return {'status': 'unsure', 'ask': str(ex)}
    total = len(result.get('rows') or []) if result.get('mode') != 'figure' else 1
    if result.get('rows'):
        result = {**result, 'rows': result['rows'][:PREVIEW_ROWS]}
    return {**out, 'result': result, 'total_rows': total, 'displays': possible_displays(cat, out['report'])}


def possible_displays(cat: dict, defn: dict) -> list[dict]:
    """The display forms this answer can take, with the columns they would use."""
    out: list[dict] = [{'kind': 'table'}, {'kind': 'print'}]
    if defn.get('figure'):
        return out + [{'kind': 'tiles'}]
    if defn.get('group_by'):
        out += [{'kind': 'bar'}, {'kind': 'tiles'}]
        if G.compile_path(cat, defn['base'], defn['group_by'][0])['kind'] == 'date':
            out.append({'kind': 'line'})
        return out
    cols = defn.get('columns') or []
    kinds = [G.compile_path(cat, defn['base'], c)['kind'] for c in cols]
    enums = sorted([i for i, k in enumerate(kinds) if k == 'enum'], key=lambda i: 'status' not in cols[i])   # a status first
    dates = [i for i, k in enumerate(kinds) if k == 'date']
    if enums:
        out.append({'kind': 'board', 'column': enums[0]})
    if dates:
        out.append({'kind': 'calendar', 'date_column': dates[0]})
    if len(dates) >= 2:
        out.append({'kind': 'timeline', 'start_column': dates[0], 'end_column': dates[1]})
    return out


def show(db: Session, user, definition: dict, display: dict | None) -> dict:
    cat = gq.catalog(db)
    try:
        disp = V.check_display(display, definition, cat)
        result = gq.run_report(db, user, definition)
    except G.GraphError as ex:
        raise ValueError(str(ex)) from None
    return V.shape(disp, result, definition, cat, u._today())


def show_union(db: Session, user, definitions: list, display: dict | None) -> dict:
    """'Match any': run each report, keep every record that any of them found once, then shape the result as one report.
    Only lists of records can be joined this way; totals would count a record twice."""
    if len(definitions) == 1:
        return show(db, user, definitions[0], display)
    cat = gq.catalog(db)
    merged, first, largest, incomplete = {}, None, 0, False
    try:
        for definition in definitions:
            wide = dict(definition, limit=G.MAX_REPORT_ROWS)        # every branch at the engine's own cap, so the union is exact below it
            disp = V.check_display(display, wide, cat)
            result = gq.run_report(db, user, wide)
            if result.get('mode') != 'list':
                raise ValueError('"Match any" works on lists of records, not on totals.')
            first = first or result
            if result['matched'] > len(result['rows']):             # this branch was cut off: the union may be larger than what we hold
                incomplete, largest = True, max(largest, result['matched'])
            for row in result['rows']:
                merged.setdefault(row['record_id'], row)
    except G.GraphError as ex:
        raise ValueError(str(ex)) from None
    rows = list(merged.values())
    if definitions[0].get('sort') == 'first_column':
        rows.sort(key=lambda r: r['cells'][0].casefold() if r['cells'] else '')
    limit = definitions[0].get('limit', 200)
    # exact when no branch was cut off; otherwise a lower bound, and the result says so
    result = dict(first, rows=rows[:limit], matched=max(len(rows), largest) if incomplete else len(rows), incomplete=incomplete)
    return V.shape(disp, result, definitions[0], cat, u._today())


# ------------------------------------------------------------------ saved definitions

def latest(db: Session, kind: str) -> dict:
    """{key: newest definition} for one kind."""
    out = {}
    for row in db.scalars(select(UniversalViewDefinition).where(UniversalViewDefinition.kind == kind)
                          .order_by(UniversalViewDefinition.key, UniversalViewDefinition.version)):
        out[row.key] = dict(row.definition, version=row.version)
    return out


def home(db: Session, user) -> dict:
    """The dashboard for this person's role, each tile run with their access."""
    boards = list(latest(db, 'dashboard').values())
    d = V.dashboard_for(user.role, boards)
    if not d:
        return {'dashboard': None, 'tiles': []}
    reports = {r.key: r for r in db.scalars(select(UniversalReport))}
    tiles = []
    for t in d['tiles']:
        rep = reports.get(t['report'])
        rdef = gq.report_definition(db, rep) if rep else {}
        roles = rdef.get('visible_to')
        if not rep or (roles and user.role != 'admin' and user.role not in roles):
            continue
        display = t.get('display') or rdef.get('display') or {'kind': 'table'}
        try:
            shaped = show(db, user, rdef, display)
        except ValueError as ex:
            shaped = {'kind': 'error', 'message': str(ex)}
        tiles.append({'report': rep.key, 'title': t.get('title') or rep.title, 'view': shaped})
    return {'dashboard': {'key': d['key'], 'title': d['title'], 'version': d['version']}, 'tiles': tiles}


def layout_for(db: Session, type_key: str):
    return latest(db, 'layout').get(type_key)


def validate_dashboard(db: Session, d: dict) -> dict:
    reports = {r.key: gq.report_definition(db, r) for r in db.scalars(select(UniversalReport))}
    try:
        V.check_dashboard(d, reports)
        cat = gq.catalog(db)
        for t in d['tiles']:
            if 'display' in t:
                V.check_display(t['display'], reports[t['report']], cat)
    except G.GraphError as ex:
        raise ValueError(str(ex)) from None
    return d


def validate_layout(db: Session, d: dict) -> dict:
    rt = db.get(RecordType, d.get('type_key')) if isinstance(d, dict) and isinstance(d.get('type_key'), str) else None
    if not rt or rt.status != 'active' or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('A layout is for an active type')
    try:
        return V.check_layout(d, rt.design['runtime_fields'])
    except G.GraphError as ex:
        raise ValueError(str(ex)) from None


def apply_definition(db: Session, item, actor):
    kind = {'metadata_dashboard': 'dashboard', 'metadata_layout': 'layout'}[item.item_type]
    d = item.after_data or {}
    (validate_dashboard if kind == 'dashboard' else validate_layout)(db, d)
    key = d['key'] if kind == 'dashboard' else d['type_key']
    version = int(db.scalar(select(func.coalesce(func.max(UniversalViewDefinition.version), 0))
                            .where(UniversalViewDefinition.kind == kind, UniversalViewDefinition.key == key)) or 0) + 1
    row = UniversalViewDefinition(kind=kind, key=key, version=version, definition=dict(d), ticket_id=item.ticket_id)
    db.add(row)
    db.flush()
    add_audit(db, f'universal_{kind}', 'universal_view_definition', row.id,
              f'Ticket #{item.ticket_id} saved {kind} {key} version {version}', actor=actor)
    return {'type': f'universal_{kind}', 'id': row.id, 'item_id': item.id}


def suggest_layout(db: Session, type_key: str) -> dict:
    """Offline suggestion (the AI may propose one too through the gateway); it is only a draft for an
    Admin ticket."""
    import json
    from . import ai_wiring
    rt = db.get(RecordType, type_key)
    if not rt or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Unknown type')
    fields = rt.design['runtime_fields']
    gw = ai_wiring.gateway(db)
    if gw.is_on():
        from .ai_gateway import GatewayRefused, mark_outcome
        try:
            out = gw.call('layout', 'Group these fields of one record type into 1-6 titled sections for a phone form. '
                          'Return JSON {"sections":[{"title","fields":[names]}],"list_columns":[up to 5 names]}. Use only the '
                          'names given. Fields: ' + json.dumps([{'name': f['name'], 'kind': f['type'], 'meaning': f.get('meaning', '')}
                                                                for f in fields]), rt.title, masked=False)
            try:
                data = json.loads(out['text'])
                lay = V.check_layout({'type_key': type_key, 'sections': data['sections'], 'list_columns': data.get('list_columns', [])}, fields)
                db.commit()
                return {'layout': lay, 'source': 'ai'}
            except (ValueError, KeyError, TypeError, G.GraphError):
                gw.log.append(mark_outcome(out['row'], 'invalid'))
        except GatewayRefused:
            pass
        db.commit()
    return {'layout': V.suggest_layout(type_key, fields), 'source': 'offline'}
