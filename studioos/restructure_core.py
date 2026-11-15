"""v0.13.0 safe restructuring of universal types. Standard library only.

A change is one ticket item (``metadata_type_change``) with an ``op``:

  rename_field  {type_key, field, new_name}
  retype_field  {type_key, field, new_type, options?, units?, target?}
  remove_field  {type_key, field}                 hidden; stored values are kept
  rename_type   {type_key, new_title}             the key stays; the old title becomes another name
  merge_types   {type_key (source), into, field_map {source field: into field}}
  split_type    {type_key, new_key, new_title, condition}   matching records move to the new type

Every change is worked out on a *world*: plain data the app reads from the database (types,
records, links, reports, rules, saved views, layouts, dashboards, formulas, document templates).
``preview`` lists everything it touches and the **blockers** that refuse approval;
``apply`` returns the objects as they were before and as they will be after, so the app writes
them in the same ticket (references are updated together with the type) and an undo ticket can
put back exactly the "before" objects. Nothing here touches the ledger: finance types and the
chart of accounts are not universal types and are refused.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re

try:
    from . import graph_core as G
except ImportError:                          # stand-alone (stdlib tests)
    import graph_core as G                   # type: ignore

OPS = ('rename_field', 'retype_field', 'remove_field', 'rename_type', 'merge_types', 'split_type')
OP_KEYS = {
    'rename_field': {'op', 'type_key', 'field', 'new_name'},
    'retype_field': {'op', 'type_key', 'field', 'new_type', 'options', 'units', 'target'},
    'remove_field': {'op', 'type_key', 'field'},
    'rename_type': {'op', 'type_key', 'new_title'},
    'merge_types': {'op', 'type_key', 'into', 'field_map'},
    'split_type': {'op', 'type_key', 'new_key', 'new_title', 'condition'},
}
REQUIRED = {'rename_field': {'field', 'new_name'}, 'retype_field': {'field', 'new_type'}, 'remove_field': {'field'},
            'rename_type': {'new_title'}, 'merge_types': {'into', 'field_map'}, 'split_type': {'new_key', 'new_title', 'condition'}}
STORES = ('types', 'records', 'relations', 'reports', 'rules', 'views', 'layouts', 'dashboards', 'calculations', 'templates')
MAX_RECORDS = 50000


class ChangeError(ValueError):
    pass


def dumps(obj) -> str:
    """The one serialisation used for snapshots and the byte-identical round-trip check."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


# ------------------------------------------------------------------ checking the request

def check_change(d: dict, world: dict) -> dict:
    if not isinstance(d, dict) or d.get('op') not in OPS:
        raise ChangeError('Choose what to change: ' + ', '.join(OPS))
    op = d['op']
    if set(d) - OP_KEYS[op] or not ({'type_key'} | REQUIRED[op]) <= set(d):
        raise ChangeError(f'{op} needs ' + ', '.join(sorted({'type_key'} | REQUIRED[op])))
    t = world['types'].get(d['type_key'])
    if t is None or t.get('status', 'active') != 'active':
        raise ChangeError('Only active universal types can be changed (accounting is never changed here)')
    names = [f['name'] for f in t['fields']]
    if op in ('rename_field', 'retype_field', 'remove_field') and d['field'] not in names:
        raise ChangeError(f'{t["title"]} has no field "{d["field"]}"')
    if op == 'rename_field':
        G.check_key(d['new_name'], 'New field name')
        if d['new_name'] in names or d['new_name'] in G.RESERVED_FIELDS or d['new_name'] in {f['name'] for f in t.get('removed_fields', [])}:
            raise ChangeError('That name is already used or reserved')
    if op == 'retype_field':
        spec = new_field_spec(t, d)
        G.check_field_specs([spec], own_key=d['type_key'], known_targets=set(world['types']))
    if op == 'rename_type':
        if not isinstance(d['new_title'], str) or not 2 <= len(d['new_title'].strip()) <= 120:
            raise ChangeError('New title: 2–120 characters')
        if any(x.get('title', '').casefold() == d['new_title'].strip().casefold() for k, x in world['types'].items() if k != d['type_key']):
            raise ChangeError('Another type already has that title')
    if op == 'merge_types':
        into = world['types'].get(d['into'])
        if into is None or d['into'] == d['type_key'] or into.get('status', 'active') != 'active':
            raise ChangeError('Merge into another active type')
        fm = d['field_map']
        into_names = {f['name']: f for f in into['fields']}
        if not isinstance(fm, dict) or set(fm) != set(names):
            raise ChangeError('Say where every field goes (the field map must name each field of the type being merged)')
        if len(set(fm.values())) != len(fm):
            raise ChangeError('Two fields cannot go to the same field')
        for a, b in fm.items():
            if b not in into_names:
                raise ChangeError(f'{into["title"]} has no field "{b}"')
    if op == 'split_type':
        G.check_key(d['new_key'], 'New type key')
        if d['new_key'] in world['types']:
            raise ChangeError('A type with that key already exists')
        if not isinstance(d['new_title'], str) or not 2 <= len(d['new_title'].strip()) <= 120:
            raise ChangeError('New title: 2–120 characters')
        if d['condition'] is None:
            raise ChangeError('Say which records move (a condition)')
        try:
            G.check_condition(d['condition'], G.field_map(t['fields']))
        except G.GraphError as ex:
            raise ChangeError(str(ex)) from None
    return d


def new_field_spec(t: dict, d: dict) -> dict:
    old = next(f for f in t['fields'] if f['name'] == d['field'])
    spec = {'name': old['name'], 'type': d['new_type'], 'required': bool(old.get('required'))}
    if old.get('meaning'):
        spec['meaning'] = old['meaning']
    for k in ('options', 'units', 'target'):
        if k in d:
            spec[k] = d[k]
    return spec


# ------------------------------------------------------------------ converting values

def _as_text(value, f) -> str | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, dict):
        if 'amount' in value:
            return str(value['amount'])
        if 'value' in value:
            return f'{value["value"]} {value.get("unit", "")}'.strip()
    return str(value)


def convert(value, old: dict, new: dict, today: dt.date):
    """One stored value to the new field kind. Returns (ok, new_value). Empty stays empty."""
    s = _as_text(value, old)
    if s is None:
        return True, None
    if new['type'] == old['type'] and new['type'] not in ('enum', 'quantity', 'reference'):
        return True, value
    if new['type'] == 'reference':
        return (True, value) if type(value) is int and old['type'] == 'reference' and old.get('target') == new.get('target') else (False, None)
    try:
        out = G.coerce_text(new, s, today)
    except G.GraphError:
        return False, None
    if new['type'] == 'decimal' and old['type'] == 'money':
        out = str(G.as_number(value) if isinstance(value, dict) else out)
    # a number must not change on the way (no rounding, no floating point)
    if old['type'] in G.NUMERIC and new['type'] in G.NUMERIC:
        a, b = G.as_number(value), G.as_number(out)
        if a is None or b is None or a != b:
            return False, None
    return True, out


# ------------------------------------------------------------------ path rewriting (reports, dashboards)

def rewrite_path(path: str, base: str, world: dict, mapping: dict) -> str:
    """mapping: {(type_key, old field): new field}. Walks the path type by type."""
    if not isinstance(path, str):
        return path
    node, out = base, []
    for seg in path.split('.'):
        if seg.startswith(('@', '~')):
            rel = world['relations'].get(seg[1:])
            out.append(seg)
            if rel:
                node = rel['target_type'] if seg[0] == '@' else rel['source_type']
            continue
        t = world['types'].get(node)
        new = mapping.get((node, seg), seg)
        out.append(new)
        f = next((x for x in t['fields'] if x['name'] == seg), None) if t else None
        node = f['target'] if f and f.get('type') == 'reference' else ('system.project' if seg == 'project' else None)
    return '.'.join(out)


def paths_of_report(r: dict) -> list[str]:
    return [f.get('path') for f in r.get('filters') or []] + list(r.get('group_by') or []) + \
        [m.get('path') for m in r.get('measures') or [] if m.get('path')] + list(r.get('columns') or [])


def path_touches(path: str, base: str, world: dict, type_key: str, field: str) -> bool:
    marker = '\x00'
    return rewrite_path(path, base, world, {(type_key, field): marker}) != path or \
        marker in rewrite_path(path, base, world, {(type_key, field): marker})


def rewrite_report(r: dict, world: dict, mapping: dict, base_map: dict | None = None) -> dict:
    out = copy.deepcopy(r)
    base = r['base']
    for f in out.get('filters') or []:
        f['path'] = rewrite_path(f['path'], base, world, mapping)
    if 'group_by' in r:
        out['group_by'] = [rewrite_path(p, base, world, mapping) for p in r['group_by']]
    for m in out.get('measures') or []:
        if m.get('path'):
            m['path'] = rewrite_path(m['path'], base, world, mapping)
    if 'columns' in r:
        out['columns'] = [rewrite_path(p, base, world, mapping) for p in r['columns']]
    if base_map and base in base_map:
        out['base'] = base_map[base]
    return out


# ------------------------------------------------------------------ generic JSON references (formulas, templates)

def mentions(obj, field: str) -> bool:
    """Does a stored definition name this field (as a value, a placeholder or a key)?"""
    text = dumps(obj)
    return bool(re.search(r'"' + re.escape(field) + r'"|\{\{\s*' + re.escape(field) + r'\s*\}\}|\b' + re.escape(field) + r'\.', text))


# ------------------------------------------------------------------ preview and apply

def _blank():
    return {k: {} for k in STORES}


def plan(d: dict, world: dict, today: dt.date) -> dict:
    """Everything the change touches, the new versions of those objects, and the blockers.
    Returns {'before': {store: {id: obj}}, 'after': {...}, 'impact': {...}, 'blockers': [...],
    'unconvertible': [...]} ."""
    check_change(d, world)
    op, tk = d['op'], d['type_key']
    t = world['types'][tk]
    before, after = _blank(), _blank()
    blockers, unconvertible = [], []
    impact = {'records': 0, 'links': 0, 'reports': [], 'rules': [], 'views': [], 'layouts': [], 'dashboards': [],
              'calculations': [], 'templates': [], 'relations': []}

    def touch(store, key, new):
        if key not in before[store]:
            before[store][key] = copy.deepcopy(world[store].get(key))
        after[store][key] = new

    records = {i: r for i, r in world['records'].items() if r['type'] == tk}
    if len(records) > MAX_RECORDS:
        blockers.append(f'More than {MAX_RECORDS:,} records: change in smaller steps')
    field = d.get('field')

    if op == 'rename_field':
        new = d['new_name']
        mapping = {(tk, field): new}
        nt = copy.deepcopy(t)
        for f in nt['fields']:
            if f['name'] == field:
                f['name'] = new
        for k in ('label_field',):
            if nt.get(k) == field:
                nt[k] = new
        if (nt.get('self_read') or {}).get('field') == field:
            nt['self_read']['field'] = new
        if nt.get('self_read') and nt['self_read'].get('when'):
            nt['self_read']['when'] = _rewrite_condition(nt['self_read']['when'], field, new)
        nt['version'] = int(t.get('version', 1)) + 1
        touch('types', tk, nt)
        for i, r in records.items():
            if field in r['data']:
                nr = copy.deepcopy(r)
                nr['data'] = {(new if k == field else k): v for k, v in r['data'].items()}
                touch('records', i, nr)
        _rewrite_refs(world, tk, field, mapping, touch, impact, blockers, rename_to=new)
    elif op == 'remove_field':
        nt = copy.deepcopy(t)
        spec = next(f for f in nt['fields'] if f['name'] == field)
        nt['fields'] = [f for f in nt['fields'] if f['name'] != field]
        nt.setdefault('removed_fields', []).append(spec)
        nt['version'] = int(t.get('version', 1)) + 1
        if not nt['fields']:
            blockers.append('A type needs at least one field')
        if t.get('label_field') == field:
            blockers.append('This field names each record (label field): choose another label first')
        if (t.get('self_read') or {}).get('field') == field or mentions((t.get('self_read') or {}).get('when'), str(field)):
            blockers.append('Staff use this field to read their own records: change that option first')
        touch('types', tk, nt)
        impact['records'] = sum(1 for r in records.values() if r['data'].get(field) not in (None, ''))
        _rewrite_refs(world, tk, field, None, touch, impact, blockers, rename_to=None)
    elif op == 'retype_field':
        old = next(f for f in t['fields'] if f['name'] == field)
        spec = new_field_spec(t, d)
        nt = copy.deepcopy(t)
        nt['fields'] = [spec if f['name'] == field else f for f in nt['fields']]
        nt['version'] = int(t.get('version', 1)) + 1
        touch('types', tk, nt)
        for i, r in records.items():
            if r['data'].get(field) in (None, ''):
                continue
            ok, val = convert(r['data'][field], old, spec, today)
            if not ok:
                unconvertible.append({'record_id': i, 'value': _as_text(r['data'][field], old)})
                continue
            if val != r['data'][field]:
                nr = copy.deepcopy(r)
                nr['data'][field] = val
                touch('records', i, nr)
        if unconvertible:
            blockers.append(f'{len(unconvertible)} record(s) cannot be converted: correct them first (listed)')
        if t.get('label_field') == field and spec['type'] not in ('text', 'enum', 'date', 'reference'):
            blockers.append('The label field must stay text, an option, a date or a reference')
        # saved definitions are checked again against the new kind
        nworld = _with(world, 'types', tk, nt)
        _recheck_definitions(nworld, tk, field, impact, blockers)
    elif op == 'rename_type':
        nt = copy.deepcopy(t)
        nt['aliases'] = list(dict.fromkeys(list(t.get('aliases') or []) + [t['title']]))[:12]
        nt['title'] = d['new_title'].strip()
        nt['version'] = int(t.get('version', 1)) + 1
        touch('types', tk, nt)
    elif op == 'merge_types':
        into = d['into']
        it = world['types'][into]
        fm = d['field_map']
        ispec = {f['name']: f for f in it['fields']}
        for i, r in records.items():
            nr = copy.deepcopy(r)
            nd = {}
            for k, v in r['data'].items():
                if k not in fm:
                    nd[k] = v          # a hidden (removed) field's value travels unchanged
                    continue
                src = next(f for f in t['fields'] if f['name'] == k)
                ok, val = convert(v, src, ispec[fm[k]], today)
                if not ok:
                    unconvertible.append({'record_id': i, 'field': k, 'value': _as_text(v, src)})
                    continue
                if val is not None:
                    nd[fm[k]] = val
            nr['data'], nr['type'] = nd, into
            touch('records', i, nr)
        missing = [f['name'] for f in it['fields'] if f.get('required') and f['name'] not in fm.values()]
        if missing and records:
            blockers.append(f'{it["title"]} requires {", ".join(missing)}, which the merged records do not have')
        if unconvertible:
            blockers.append(f'{len(unconvertible)} value(s) cannot be converted: correct them first (listed)')
        nt = copy.deepcopy(t)
        nt['status'] = 'merged'
        nt['merged_into'] = into
        nt['version'] = int(t.get('version', 1)) + 1
        touch('types', tk, nt)
        mapping = {(tk, a): b for a, b in fm.items()}
        for key, rel in world['relations'].items():
            if tk in (rel['source_type'], rel['target_type']):
                nrel = dict(rel)
                if nrel['source_type'] == tk:
                    nrel['source_type'] = into
                if nrel['target_type'] == tk:
                    nrel['target_type'] = into
                touch('relations', key, nrel)
                impact['relations'].append(key)
        impact['links'] = sum(1 for e in world.get('edges', []) if world['relations'].get(e['rel'], {}).get('source_type') == tk
                              or world['relations'].get(e['rel'], {}).get('target_type') == tk)
        for other_key, ot in world['types'].items():
            if any(f.get('type') == 'reference' and f.get('target') == tk for f in ot['fields']):
                not2 = copy.deepcopy(world['types'].get(other_key) if other_key not in after['types'] else after['types'][other_key])
                for f in not2['fields']:
                    if f.get('type') == 'reference' and f.get('target') == tk:
                        f['target'] = into
                touch('types', other_key, not2)
        for key, r in world['reports'].items():
            if r['base'] == tk or any(path_touches(p, r['base'], world, tk, a) for p in paths_of_report(r) for a in fm):
                touch('reports', key, rewrite_report(r, world, mapping, {tk: into}))
                impact['reports'].append(key)
        for store in ('rules', 'views'):
            for key, x in world[store].items():
                if x.get('type_key') == tk:
                    nx = copy.deepcopy(x)
                    nx['type_key'] = into
                    nx['definition'] = _rename_in(nx.get('definition'), mapping_fields={a: b for a, b in fm.items()})
                    touch(store, key, nx)
                    impact[store].append(key)
        if tk in world['layouts']:
            impact['layouts'].append(tk)       # stays with the merged (inactive) type as history
        for store in ('calculations', 'templates'):
            for key, x in world[store].items():
                if x.get('type_key') == tk:
                    blockers.append(f'{store[:-1].capitalize()} "{key}" belongs to the merged type: recreate it on {it["title"]} first')
                    impact[store].append(key)
    elif op == 'split_type':
        nk = d['new_key']
        moving = [i for i, r in records.items() if G.condition_matches(d['condition'], r['data'], G.field_map(t['fields']), today)]
        nt = copy.deepcopy(t)
        nt.update(title=d['new_title'].strip(), version=1, aliases=[], status='active')
        nt.pop('merged_into', None)
        touch('types', nk, nt)
        for i in moving:
            nr = copy.deepcopy(records[i])
            nr['type'] = nk
            touch('records', i, nr)
        linked = [e for e in world.get('edges', []) if (e['source'] in moving or e.get('target') in moving)]
        if linked:
            blockers.append(f'{len(linked)} link(s) touch records that would move: remove those links first, then link them again')
        if not moving:
            blockers.append('No record matches the condition: nothing would move')
        impact['records'] = len(moving)
    impact['records'] = impact['records'] or sum(1 for k in after['records'])
    return {'change': d, 'before': before, 'after': after, 'impact': impact, 'blockers': [b for b in blockers if b],
            'unconvertible': unconvertible[:200], 'unconvertible_total': len(unconvertible)}


def _with(world, store, key, obj):
    w = dict(world)
    w[store] = dict(world[store])
    w[store][key] = obj
    return w


def _rewrite_condition(cond, old, new):
    if cond is None:
        return None
    if isinstance(cond, dict) and set(cond) == {'all'}:
        return {'all': [_rewrite_condition(c, old, new) for c in cond['all']]}
    c = dict(cond)
    if c.get('field') == old:
        c['field'] = new
    return c


def _rename_in(defn, mapping_fields: dict):
    """Field names inside a rule or saved-view definition (field, notify_field, columns, filters)."""
    if defn is None:
        return None
    out = copy.deepcopy(defn)

    def fix(x):
        if isinstance(x, dict):
            for k, v in list(x.items()):
                if k in ('field', 'notify_field', 'path') and isinstance(v, str) and v in mapping_fields:
                    x[k] = mapping_fields[v]
                elif k in ('columns', 'fields', 'list_columns') and isinstance(v, list):
                    x[k] = [mapping_fields.get(c, c) if isinstance(c, str) else fix(c) for c in v]
                else:
                    fix(v)
        elif isinstance(x, list):
            for v in x:
                fix(v)
        return x
    return fix(out)


def _uses_field(defn, field) -> bool:
    if defn is None:
        return False
    hit = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ('field', 'notify_field', 'path') and v == field:
                    hit.append(1)
                elif k in ('columns', 'fields', 'list_columns') and isinstance(v, list) and field in v:
                    hit.append(1)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(defn)
    return bool(hit)


def _rewrite_refs(world, tk, field, mapping, touch, impact, blockers, rename_to):
    """Reports, rules, views, layouts, dashboards (and formulas/templates) that use the field.
    rename: rewritten in the same ticket. remove: layouts and view columns drop it; anything whose
    meaning would change (report filters/groups/measures, rule conditions) blocks."""
    for key, r in world['reports'].items():
        if any(path_touches(p, r['base'], world, tk, field) for p in paths_of_report(r) if p):
            impact['reports'].append(key)
            if rename_to:
                touch('reports', key, rewrite_report(r, world, mapping))
            else:
                blockers.append(f'Report "{r.get("title", key)}" uses this field')
    for store in ('rules', 'views'):
        for key, x in world[store].items():
            if x.get('type_key') == tk and _uses_field(x.get('definition'), field):
                impact[store].append(key)
                if rename_to:
                    nx = copy.deepcopy(x)
                    nx['definition'] = _rename_in(x['definition'], {field: rename_to})
                    touch(store, key, nx)
                elif store == 'views' and not _uses_field({k: v for k, v in (x.get('definition') or {}).items() if k != 'columns'}, field):
                    nx = copy.deepcopy(x)
                    nx['definition']['columns'] = [c for c in x['definition'].get('columns', []) if c != field]
                    if not nx['definition']['columns']:
                        blockers.append(f'Saved view "{key}" would have no columns left')
                    touch(store, key, nx)
                else:
                    blockers.append(f'{"Rule" if store == "rules" else "Saved view"} "{key}" uses this field')
    lay = world['layouts'].get(tk)
    if lay and _uses_field(lay, field):
        impact['layouts'].append(tk)
        nl = copy.deepcopy(lay)
        if rename_to:
            nl = _rename_in(nl, {field: rename_to})
        else:
            for s in nl['sections']:
                s['fields'] = [f for f in s['fields'] if f != field]
            nl['sections'] = [s for s in nl['sections'] if s['fields']]
            nl['list_columns'] = [c for c in nl.get('list_columns', []) if c != field]
            if not nl['sections']:
                blockers.append('The form layout would be empty')
        touch('layouts', tk, nl)
    for key, dsh in world['dashboards'].items():
        if any(t.get('report') in impact['reports'] for t in dsh.get('tiles', [])):
            impact['dashboards'].append(key)       # tiles follow their report; nothing to rewrite
    for store in ('calculations', 'templates'):
        for key, x in world[store].items():
            if x.get('type_key') == tk and mentions(x.get('definition'), field):
                impact[store].append(key)
                blockers.append(f'{"Formula" if store == "calculations" else "Document template"} "{key}" uses this field: '
                                'change it first (these keep every version and are not rewritten automatically)')


def _recheck_definitions(nworld, tk, field, impact, blockers):
    cat = catalog_of(nworld)
    for key, r in nworld['reports'].items():
        if any(path_touches(p, r['base'], nworld, tk, field) for p in paths_of_report(r) if p):
            impact['reports'].append(key)
            try:
                G.check_report(cat, {k: v for k, v in r.items() if k in G.REPORT_KEYS})
            except G.GraphError as ex:
                blockers.append(f'Report "{r.get("title", key)}" would no longer work: {ex}')
    t = nworld['types'][tk]
    fmap = G.field_map(t['fields'])
    for key, x in nworld['rules'].items():
        if x.get('type_key') == tk and _uses_field(x.get('definition'), field):
            impact['rules'].append(key)
            try:
                G.check_condition((x.get('definition') or {}).get('condition'), fmap)
            except G.GraphError as ex:
                blockers.append(f'Rule "{key}" would no longer work: {ex}')
    for store in ('calculations', 'templates'):
        for key, x in nworld[store].items():
            if x.get('type_key') == tk and mentions(x.get('definition'), field):
                impact[store].append(key)
                blockers.append(f'{"Formula" if store == "calculations" else "Document template"} "{key}" uses this field: change it first')


def catalog_of(world) -> dict:
    return G.catalog_from({k: {'title': t['title'], 'fields': t['fields'], 'label_field': t.get('label_field')}
                           for k, t in world['types'].items() if t.get('status', 'active') == 'active'},
                          {k: {'source_type': r['source_type'], 'target_type': r['target_type']} for k, r in world['relations'].items()})


def apply(world: dict, p: dict) -> dict:
    """The world after the change (for tests and for the app's checks). Refuses with blockers."""
    if p['blockers']:
        raise ChangeError('Blocked: ' + '; '.join(p['blockers']))
    out: dict = {k: dict(v) if isinstance(v, dict) else list(v) for k, v in world.items()}
    for store, objs in p['after'].items():
        for key, obj in objs.items():
            if obj is None:
                out[store].pop(key, None)
            else:
                out[store][key] = copy.deepcopy(obj)
    return out


def inverse(world_now: dict, change_row: dict) -> dict:
    """The undo of an applied change: put back exactly the 'before' objects. Refused when anything
    the change wrote has changed since (the current object differs from what the change wrote)."""
    blockers = []
    for store, objs in change_row['after'].items():
        for key, obj in objs.items():
            if dumps(world_now[store].get(key)) != dumps(obj):
                blockers.append(f'{store} {key} has changed since; undo by hand or with a new change')
    return {'change': {'undo_of': change_row.get('id')}, 'before': copy.deepcopy(change_row['after']),
            'after': copy.deepcopy(change_row['before']), 'impact': change_row.get('impact', {}), 'blockers': blockers,
            'unconvertible': [], 'unconvertible_total': 0}


def summary(p: dict) -> str:
    i = p['impact']
    parts = [f'{i["records"]} record(s)']
    for k in ('links', 'reports', 'rules', 'views', 'layouts', 'dashboards', 'calculations', 'templates', 'relations'):
        n = i[k] if isinstance(i[k], int) else len(set(i[k]))
        if n:
            parts.append(f'{n} {k}')
    return 'Touches ' + ', '.join(parts) + ('.' if not p['blockers'] else f'. Blocked: {len(p["blockers"])} problem(s).')


# ------------------------------------------------------------------ business pack version 2

def pack_upgrade_plan(installed: dict, new_pack: dict, world: dict) -> list[dict]:
    """Ticket items that bring an installed pack (version N) to version N+1. The new pack declares
    ``upgrade: {from: N, changes: [...]}``; each change is a type change (above), a type options
    change (``metadata_type_options``) or new fields (``metadata_type_extend``). New types in the
    new pack become ``metadata_type`` items. Every item is still checked when the Admin approves."""
    up = new_pack.get('upgrade') or {}
    if new_pack.get('version') != installed.get('version', 0) + 1 or up.get('from') != installed.get('version'):
        raise ChangeError('A pack upgrades one version at a time, from the installed version')
    items = []
    for t in new_pack['types']:
        if t['key'] not in world['types']:
            items.append({'kind': 'metadata_type', 'data': {k: v for k, v in t.items()}})
    for c in up.get('changes', []):
        if not isinstance(c, dict) or 'kind' not in c or 'data' not in c:
            raise ChangeError('Each upgrade change names its kind and data')
        if c['kind'] not in ('metadata_type_change', 'metadata_type_options', 'metadata_type_extend'):
            raise ChangeError('A pack upgrade can change types, their options or add fields only')
        if c['kind'] == 'metadata_type_change':
            check_change(c['data'], world)
        items.append({'kind': c['kind'], 'data': c['data']})
    items.append({'kind': 'metadata_pack_install', 'data': {'pack': new_pack['key'], 'version': new_pack['version'], 'upgrade': True}})
    return items


# ------------------------------------------------------------------ from words (offline; the AI may draft too)

CHANGE_PATTERNS = (
    (re.compile(r'^\s*rename (?:the )?(?:field )?"?([a-z_ ]+?)"? (?:to|as) "?([a-z_ ]+?)"? in (?:the )?(.+?)\s*$', re.I), 'rename_field'),
    (re.compile(r'^\s*(?:remove|hide|drop) (?:the )?(?:field )?"?([a-z_ ]+?)"? from (?:the )?(.+?)\s*$', re.I), 'remove_field'),
    (re.compile(r'^\s*(?:make|change) (?:the )?(?:field )?"?([a-z_ ]+?)"? in (?:the )?(.+?) (?:a|an|into a|into an|to a|to an|to) (text|number|whole number|date|yes/no|amount|decimal)\s*$', re.I), 'retype_field'),
    (re.compile(r'^\s*rename (?:the )?type (.+?) to (.+?)\s*$', re.I), 'rename_type'),
)
KIND_WORDS = {'text': 'text', 'number': 'decimal', 'decimal': 'decimal', 'whole number': 'integer', 'date': 'date',
              'yes/no': 'boolean', 'amount': 'money'}


def _type_by_words(words, world):
    w = G._norm(words).rstrip('s')
    hits = [k for k, t in world['types'].items() if t.get('status', 'active') == 'active' and
            (G._norm(t['title']).rstrip('s') == w or k.replace('_', ' ') == w or w in [G._norm(a) for a in t.get('aliases') or []])]
    if len(hits) != 1:
        raise ChangeError(f'Which type is "{words}"?')
    return hits[0]


def _field_by_words(words, t):
    w = G._norm(words)
    hits = [f['name'] for f in t['fields'] if w in (G._norm(f['name']), G._norm(f.get('meaning', '')))]
    if len(hits) != 1:
        raise ChangeError(f'Which field is "{words}"?')
    return hits[0]


def change_from_words(text: str, world: dict) -> dict:
    """'rename field severity to priority in work issue', 'remove notes from meeting note',
    'make hours in timesheet a whole number', 'rename type work issue to snag'. Merges and splits
    are drafted on the screen or by the AI, not from one sentence."""
    for rx, op in CHANGE_PATTERNS:
        m = rx.match(str(text or ''))
        if not m:
            continue
        if op == 'rename_type':
            return {'op': op, 'type_key': _type_by_words(m.group(1), world), 'new_title': m.group(2).strip().strip('"')[:120]}
        if op == 'rename_field':
            tk = _type_by_words(m.group(3), world)
            return {'op': op, 'type_key': tk, 'field': _field_by_words(m.group(1), world['types'][tk]),
                    'new_name': re.sub(r'[^a-z0-9]+', '_', m.group(2).strip().casefold()).strip('_')}
        if op == 'remove_field':
            tk = _type_by_words(m.group(2), world)
            return {'op': op, 'type_key': tk, 'field': _field_by_words(m.group(1), world['types'][tk])}
        tk = _type_by_words(m.group(2), world)
        return {'op': op, 'type_key': tk, 'field': _field_by_words(m.group(1), world['types'][tk]),
                'new_type': KIND_WORDS[m.group(3).casefold()]}
    raise ChangeError('Say it like: rename field severity to priority in work issue')
