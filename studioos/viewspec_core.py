"""ViewSpec v1: the one JSON shape every saved view, widget, template and role home screen is stored as (UI/UX plan, track UI-1).

Pure functions, no database. A spec is data only: no HTML, CSS, script, URL or expression. validate_spec checks it against a
whitelist schema (unknown keys are refused) and against a catalog of record types, and says which view types fit which fields.
diff_specs gives a deterministic, structural list of changes for the approval ticket. from_report converts a v0.12 saved report
and its display setting into a spec, so the existing views can be migrated.

catalog = {record_type: {field_name: {'kind': <KINDS>, 'label': str, 'target': record_type (relations), 'options': [..]}}}
KINDS: text, number, date, select, boolean, relation, image
"""
from __future__ import annotations

import hashlib
import json
import re

SPEC_VERSION = 1
PRIMITIVES = ('table', 'list', 'board', 'calendar', 'timeline', 'gallery', 'record', 'form', 'feed', 'metric', 'chart', 'progress')
KINDS = ('text', 'number', 'date', 'select', 'boolean', 'relation', 'image')
OPS = ('eq', 'neq', 'in', 'not_in', 'contains', 'empty', 'not_empty', 'gt', 'gte', 'lt', 'lte', 'before', 'after', 'between',
       'within_last', 'within_next', 'relation_has', 'relation_count')
OPS_BY_KIND = {
    'text': {'eq', 'neq', 'in', 'not_in', 'contains', 'empty', 'not_empty'},
    'number': {'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'between', 'empty', 'not_empty'},
    'date': {'eq', 'neq', 'before', 'after', 'between', 'within_last', 'within_next', 'empty', 'not_empty'},
    'select': {'eq', 'neq', 'in', 'not_in', 'empty', 'not_empty'},
    'boolean': {'eq', 'neq'},
    'relation': {'eq', 'neq', 'in', 'not_in', 'empty', 'not_empty', 'relation_has', 'relation_count'},
    'image': {'empty', 'not_empty'},
}
TOKENS = ('danger', 'warning', 'success', 'info', 'muted', 'accent1', 'accent2', 'accent3', 'accent4', 'accent5', 'accent6')
AGG_FNS = ('count', 'sum', 'avg', 'min', 'max', 'count_distinct')
SHOW = ('chips', 'count', 'cover', 'first')
ACTIONS = ('open', 'quick_add', 'move_status', 'add_photo', 'approve', 'reject', 'edit', 'comment')
CARDS = ('compact', 'standard', 'photo')
DENSITIES = ('comfortable', 'compact')
ROLES = ('admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer', 'client')
RELATIVE = ('today', 'yesterday', 'tomorrow', 'this_week', 'last_week', 'next_week', 'this_month', 'last_month')

MAX_BYTES = 32 * 1024
MAX_ITEMS = 4
MAX_FIELDS = 40
MAX_DEPTH = 4
MAX_COLOUR_RULES = 10
MAX_PATH_HOPS = 2
MAX_LABEL = 80
ID_RE = re.compile(r'^[a-z][a-z0-9_.]{1,59}$')
KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,59}$')
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

TOP_KEYS = {'spec_version', 'id', 'name', 'labels', 'primitive', 'source', 'group', 'colour', 'aggregate', 'relations', 'layout',
            'actions', 'mobile', 'audience'}
REQUIRED_TOP = {'spec_version', 'id', 'name', 'primitive', 'source'}


class SpecError(ValueError):
    """errors: [{'path': 'source.items[0].filter', 'message': '...'}]"""

    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(f"{e['path']}: {e['message']}" for e in errors[:5]))


class _Check:
    def __init__(self):
        self.errors = []

    def add(self, path, message):
        self.errors.append({'path': path, 'message': message})

    def fail_if_any(self):
        if self.errors:
            raise SpecError(self.errors)


def canonical(spec) -> str:
    return json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def spec_hash(spec) -> str:
    return hashlib.sha256(canonical(spec).encode('utf-8')).hexdigest()


def _text(c, path, value, maxlen=MAX_LABEL, required=True):
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maxlen or CONTROL.search(value):
        c.add(path, f'plain text of 1 to {maxlen} characters, no control characters')
        return False
    return True


def _keys(c, path, obj, allowed, required=()):
    if not isinstance(obj, dict):
        c.add(path, 'must be an object')
        return False
    for k in sorted(set(obj) - set(allowed)):
        c.add(f'{path}.{k}' if path else k, 'is not allowed here')
    ok = True
    for k in required:
        if k not in obj:
            c.add(f'{path}.{k}' if path else k, 'is required')
            ok = False                      # the caller must not read a key that is missing
    return ok


# ------------------------------------------------------------------ catalog helpers

def field_of(catalog, record_type, name):
    return (catalog.get(record_type) or {}).get(name)


def resolve_path(catalog, record_type, path):
    """path: a field name, or a list of up to 2 relation hops ending in a field. Returns the leaf field dict or raises ValueError."""
    steps = [path] if isinstance(path, str) else path
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PATH_HOPS + 1 or not all(isinstance(s, str) for s in steps):
        raise ValueError(f'a field name, or up to {MAX_PATH_HOPS} relations then a field')
    cur = record_type
    for hop in steps[:-1]:
        f = field_of(catalog, cur, hop)
        if not f or f['kind'] != 'relation' or f.get('target') not in catalog:
            raise ValueError(f'{hop} is not a relation on {cur}')
        cur = f['target']
    leaf = field_of(catalog, cur, steps[-1])
    if not leaf:
        raise ValueError(f'{steps[-1]} is not a field of {cur}')
    return leaf


# ------------------------------------------------------------------ filters, values

def _value_ok(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return not isinstance(v, str) or (len(v) <= 200 and not CONTROL.search(v))
    if isinstance(v, list):
        return len(v) <= 50 and all(isinstance(x, (str, int, float, bool)) and (not isinstance(x, str) or (len(x) <= 200 and not CONTROL.search(x))) for x in v)
    if isinstance(v, dict):
        if set(v) == {'param'}:
            return isinstance(v['param'], str) and bool(KEY_RE.match(v['param']))
        if set(v) == {'relative'}:
            return v['relative'] in RELATIVE
        if set(v) == {'me'}:
            return v['me'] is True
    return False


def _check_filter(c, path, node, catalog, rtype, depth):
    if depth > MAX_DEPTH:
        c.add(path, f'filters nest at most {MAX_DEPTH} deep')
        return
    if not isinstance(node, dict):
        c.add(path, 'must be an object')
        return
    if set(node) in ({'and'}, {'or'}):
        kind = next(iter(node))
        if not isinstance(node[kind], list) or not 1 <= len(node[kind]) <= 20:
            c.add(f'{path}.{kind}', 'a list of 1 to 20 conditions')
            return
        for i, sub in enumerate(node[kind]):
            _check_filter(c, f'{path}.{kind}[{i}]', sub, catalog, rtype, depth + 1)
        return
    if not _keys(c, path, node, {'field', 'path', 'op', 'value'}, ('op',)) or ('field' in node) == ('path' in node):
        if isinstance(node, dict) and ('field' in node) == ('path' in node):
            c.add(path, 'give either field or path')
        return
    op = node['op']
    if op not in OPS:
        c.add(f'{path}.op', 'is not an allowed operator')
        return
    try:
        leaf = resolve_path(catalog, rtype, node.get('field', node.get('path')))
    except ValueError as e:
        c.add(f'{path}.field', str(e))
        return
    if op not in OPS_BY_KIND[leaf['kind']]:
        c.add(f'{path}.op', f"{op} cannot be used on a {leaf['kind']} field")
    if op in ('empty', 'not_empty'):
        if 'value' in node:
            c.add(f'{path}.value', 'is not used with this operator')
    elif 'value' not in node or not _value_ok(node['value']):
        c.add(f'{path}.value', 'a plain value, a list, {"param":..}, {"relative":..} or {"me":true}')


# ------------------------------------------------------------------ the spec

def validate_spec(spec, catalog, *, readable=None):
    """Return the spec unchanged if it is valid; raise SpecError listing every problem. readable(record_type, field) -> bool, if
    given, is asked about every field the spec uses (the caller passes the role check)."""
    c = _Check()
    if not isinstance(spec, dict):
        raise SpecError([{'path': '', 'message': 'a view spec is an object'}])
    try:
        size = len(canonical(spec).encode('utf-8'))
    except (TypeError, ValueError):
        raise SpecError([{'path': '', 'message': 'must be plain JSON data'}])
    if size > MAX_BYTES:
        raise SpecError([{'path': '', 'message': f'larger than {MAX_BYTES // 1024} KB'}])
    _keys(c, '', spec, TOP_KEYS, REQUIRED_TOP)
    if spec.get('spec_version') != SPEC_VERSION:
        c.add('spec_version', f'must be {SPEC_VERSION}')
    if not (isinstance(spec.get('id'), str) and ID_RE.match(spec['id'])):
        c.add('id', 'lowercase letters, digits, dots and underscores, 2 to 60 characters')
    if 'name' in spec:
        _text(c, 'name', spec['name'])
    if 'labels' in spec:
        if _keys(c, 'labels', spec['labels'], {'hi', 'en'}):
            for k, v in spec['labels'].items():
                _text(c, f'labels.{k}', v)
    prim = spec.get('primitive')
    if prim not in PRIMITIVES:
        c.add('primitive', 'one of ' + ', '.join(PRIMITIVES))
    items = []
    src = spec.get('source')
    if _keys(c, 'source', src, {'items', 'context'}, ('items',)):
        items = src['items'] if isinstance(src['items'], list) else []
        if not items or len(items) > MAX_ITEMS:
            c.add('source.items', f'1 to {MAX_ITEMS} items')
        if 'context' in src and _keys(c, 'source.context', src['context'], {'param', 'record_type', 'optional'}, ('param', 'record_type')):
            ctx = src['context']
            if not (isinstance(ctx.get('param'), str) and KEY_RE.match(ctx['param'])):
                c.add('source.context.param', 'a short lowercase name')
            if ctx.get('record_type') not in catalog:
                c.add('source.context.record_type', 'is not a record type')
    used = []        # (record_type, field) for the read check
    first_type = None
    for i, item in enumerate(items):
        p = f'source.items[{i}]'
        if not _keys(c, p, item, {'record_type', 'fields', 'filter', 'sort'}, ('record_type', 'fields')):
            continue
        rt = item['record_type']
        if rt not in catalog:
            c.add(f'{p}.record_type', 'is not a record type')
            continue
        first_type = first_type or rt
        fields = item['fields'] if isinstance(item['fields'], list) else []
        if not 1 <= len(fields) <= MAX_FIELDS:
            c.add(f'{p}.fields', f'1 to {MAX_FIELDS} fields')
        for j, f in enumerate(fields):
            fp = f'{p}.fields[{j}]'
            if not _keys(c, fp, f, {'field', 'path', 'show'}, ()) or ('field' in f) == ('path' in f):
                if isinstance(f, dict) and ('field' in f) == ('path' in f):
                    c.add(fp, 'give either field or path')
                continue
            try:
                leaf = resolve_path(catalog, rt, f.get('field', f.get('path')))
            except ValueError as e:
                c.add(fp, str(e))
                continue
            used.append((rt, f.get('field') or f['path'][0]))
            if 'show' in f:
                if f['show'] not in SHOW:
                    c.add(f'{fp}.show', 'one of ' + ', '.join(SHOW))
                elif f['show'] == 'cover' and leaf['kind'] != 'image':
                    c.add(f'{fp}.show', 'cover needs an image field')
                elif f['show'] in ('chips', 'count', 'first') and leaf['kind'] != 'relation':
                    c.add(f'{fp}.show', f"{f['show']} needs a relation field")
        if 'filter' in item:
            _check_filter(c, f'{p}.filter', item['filter'], catalog, rt, 1)
        for j, s in enumerate(item.get('sort', []) if isinstance(item.get('sort', []), list) else []):
            if not _keys(c, f'{p}.sort[{j}]', s, {'field', 'dir'}, ('field',)) or not field_of(catalog, rt, s.get('field')):
                c.add(f'{p}.sort[{j}]', 'a field of this record type, with dir asc or desc')
            elif s.get('dir', 'asc') not in ('asc', 'desc'):
                c.add(f'{p}.sort[{j}].dir', 'asc or desc')
        if 'sort' in item and not isinstance(item['sort'], list):
            c.add(f'{p}.sort', 'must be a list')
    # grouping
    group = spec.get('group')
    group_kinds = set()
    if group is not None and _keys(c, 'group', group, {'columns', 'rows', 'hide_empty'}):
        for axis in ('columns', 'rows'):
            if axis not in group:
                continue
            ax = group[axis]
            if not _keys(c, f'group.{axis}', ax, {'field'}, ('field',)):
                continue
            for i, item in enumerate(items):
                f = field_of(catalog, item.get('record_type'), ax.get('field')) if isinstance(item, dict) else None
                if not f:
                    c.add(f'group.{axis}.field', f"{ax.get('field')} is not a field of every record type in the view")
                elif f['kind'] not in ('select', 'relation', 'date', 'boolean', 'text'):
                    c.add(f'group.{axis}.field', 'group by a name, option, relation, date or yes/no, not by an amount')
                else:
                    group_kinds.add((axis, f['kind'], f.get('target')))
        for axis in ('columns', 'rows'):
            kinds = {(k, t) for a, k, t in group_kinds if a == axis}
            if len(kinds) > 1:
                c.add(f'group.{axis}', 'record types shown together must group by the same kind of field (all options, or all relations to the same type)')
    # colour rules
    colour = spec.get('colour', [])
    if not isinstance(colour, list) or len(colour) > MAX_COLOUR_RULES:
        c.add('colour', f'a list of at most {MAX_COLOUR_RULES} rules')
    else:
        for i, rule in enumerate(colour):
            if _keys(c, f'colour[{i}]', rule, {'when', 'token'}, ('when', 'token')):
                if rule['token'] not in TOKENS:
                    c.add(f'colour[{i}].token', 'one of ' + ', '.join(TOKENS))
                if first_type:
                    _check_filter(c, f'colour[{i}].when', rule['when'], catalog, first_type, 1)
    # aggregates
    aggs = spec.get('aggregate', [])
    if not isinstance(aggs, list) or len(aggs) > 6:
        c.add('aggregate', 'a list of at most 6 aggregates')
        aggs = []
    for i, a in enumerate(aggs):
        if not _keys(c, f'aggregate[{i}]', a, {'fn', 'field', 'as'}, ('fn', 'as')):
            continue
        if a['fn'] not in AGG_FNS:
            c.add(f'aggregate[{i}].fn', 'one of ' + ', '.join(AGG_FNS))
        elif a['fn'] != 'count':
            f = field_of(catalog, first_type, a.get('field')) if first_type else None
            if not f or (a['fn'] != 'count_distinct' and f['kind'] != 'number'):
                c.add(f'aggregate[{i}].field', f"{a['fn']} needs a number field" if a['fn'] != 'count_distinct' else 'a field of the record type')
        if not (isinstance(a.get('as'), str) and KEY_RE.match(a['as'])):
            c.add(f'aggregate[{i}].as', 'a short lowercase name')
    # relations, layout, actions, mobile, audience
    for i, r in enumerate(spec.get('relations', []) if isinstance(spec.get('relations', []), list) else []):
        if _keys(c, f'relations[{i}]', r, {'via', 'primitive', 'limit'}, ('via', 'primitive')):
            f = field_of(catalog, first_type, r['via']) if first_type else None
            if not f or f['kind'] != 'relation':
                c.add(f'relations[{i}].via', 'a relation field of the record type')
            if r['primitive'] not in ('list', 'table', 'gallery', 'feed'):
                c.add(f'relations[{i}].primitive', 'list, table, gallery or feed')
            if 'limit' in r and not (type(r['limit']) is int and 1 <= r['limit'] <= 25):
                c.add(f'relations[{i}].limit', '1 to 25')
    if 'relations' in spec and not isinstance(spec['relations'], list):
        c.add('relations', 'must be a list')
    layout = spec.get('layout', {})
    if _keys(c, 'layout', layout, {'card', 'density', 'date_field', 'end_field', 'start_field'}):
        if layout.get('card', 'standard') not in CARDS:
            c.add('layout.card', 'one of ' + ', '.join(CARDS))
        if layout.get('density', 'comfortable') not in DENSITIES:
            c.add('layout.density', 'comfortable or compact')
        for k in ('date_field', 'start_field', 'end_field'):
            if k in layout:
                f = field_of(catalog, first_type, layout[k]) if first_type else None
                if not f or f['kind'] != 'date':
                    c.add(f'layout.{k}', 'a date field of the record type')
    acts = spec.get('actions', [])
    if not isinstance(acts, list) or len(acts) > 8 or any(a not in ACTIONS for a in acts):
        c.add('actions', 'a list of at most 8 of ' + ', '.join(ACTIONS))
    mobile = spec.get('mobile', {})
    if _keys(c, 'mobile', mobile, {'default_column', 'primary_fields'}):
        for k in mobile.get('primary_fields', []) if isinstance(mobile.get('primary_fields', []), list) else []:
            if not (first_type and field_of(catalog, first_type, k)):
                c.add('mobile.primary_fields', f'{k} is not a field of the record type')
        if 'primary_fields' in mobile and (not isinstance(mobile['primary_fields'], list) or len(mobile['primary_fields']) > 6):
            c.add('mobile.primary_fields', 'a list of at most 6 fields')
    aud = spec.get('audience', {})
    if _keys(c, 'audience', aud, {'roles'}):
        roles = aud.get('roles', [])
        if not isinstance(roles, list) or len(roles) > len(ROLES) or any(r not in ROLES for r in roles):
            c.add('audience.roles', 'a list of ' + ', '.join(ROLES))
    # fit rules: which primitive can show these fields
    if prim in PRIMITIVES and first_type and not c.errors:        # the fit rules assume every part above is well formed
        _fit(c, prim, spec, catalog, first_type, items, aggs)
    # reading permission, asked once per distinct field
    if readable is not None:
        for rt, f in sorted(set(used)):
            if not readable(rt, f):
                c.add('source', f'{rt}.{f} is not readable by everyone this view is for')
    c.fail_if_any()
    return spec


def _fit(c, prim, spec, catalog, rt, items, aggs):
    group = spec.get('group') or {}
    layout = spec.get('layout') or {}
    kinds = lambda name: (field_of(catalog, rt, (group.get(name) or {}).get('field')) or {}).get('kind')
    fields = [f.get('field') for f in (items[0].get('fields') or []) if isinstance(f, dict)] if items and isinstance(items[0], dict) else []
    all_kinds = {(field_of(catalog, rt, n) or {}).get('kind') for n in fields}
    if prim == 'board' and kinds('columns') not in ('select', 'relation', 'text'):
        c.add('primitive', 'a board needs group.columns on an option, relation or text field')
    if prim == 'calendar' and 'date_field' not in layout:
        c.add('primitive', 'a calendar needs layout.date_field (a date field)')
    if prim == 'timeline' and not ({'start_field', 'end_field'} <= set(layout)):
        c.add('primitive', 'a timeline needs layout.start_field and layout.end_field (date fields)')
    if prim == 'gallery' and 'image' not in all_kinds:
        c.add('primitive', 'a gallery needs an image field among the fields')
    if prim == 'feed' and 'date_field' not in layout:
        c.add('primitive', 'a feed needs layout.date_field (the date field it is ordered by)')
    if prim in ('metric', 'progress') and not aggs:
        c.add('primitive', f'a {prim} needs an aggregate')
    if prim == 'chart' and not (aggs and group.get('columns')):
        c.add('primitive', 'a chart needs group.columns and an aggregate')
    if prim in ('record', 'form') and len(items) != 1:
        c.add('source.items', f'a {prim} shows exactly one record type')


def fitting_primitives(spec, catalog):
    """Which primitives would accept this spec's fields, for the 'switch view' choice: tries each and keeps those that validate."""
    out = []
    for p in PRIMITIVES:
        try:
            validate_spec({**spec, 'primitive': p}, catalog)
            out.append(p)
        except SpecError:
            pass
    return out


# ------------------------------------------------------------------ diff

def _flatten(o, path=''):
    if isinstance(o, dict):
        for k in sorted(o):
            yield from _flatten(o[k], f'{path}.{k}' if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _flatten(v, f'{path}[{i}]')
    else:
        yield path, o


def diff_specs(old, new):
    """A deterministic list of change lines between two specs (never written by a model). old may be None for a new view."""
    a = dict(_flatten(old or {}))
    b = dict(_flatten(new or {}))
    lines = []
    for p in sorted(set(a) | set(b)):
        if p not in a:
            lines.append(f'added {p}: {b[p]!r}')
        elif p not in b:
            lines.append(f'removed {p} (was {a[p]!r})')
        elif a[p] != b[p]:
            lines.append(f'changed {p}: {a[p]!r} -> {b[p]!r}')
    return lines


# ------------------------------------------------------------------ migration from a v0.12 report

_OP_FROM_REPORT = {'eq': 'eq', 'ne': 'neq', 'in': 'in', 'contains': 'contains', 'empty': 'empty', 'not_empty': 'not_empty',
                   'gt': 'gt', 'gte': 'gte', 'lt': 'lt', 'lte': 'lte'}
_PRIMITIVE_FROM_DISPLAY = {'table': 'table', 'bar': 'chart', 'line': 'chart', 'tiles': 'metric', 'board': 'board', 'calendar': 'calendar',
                           'timeline': 'timeline', 'print': 'table'}


def _path(p):
    return {'field': p} if '.' not in p else {'path': p.split('.')}


def from_report(report, display=None, *, spec_id=None):
    """Convert a v0.12 report definition ({key,title,base,filters,group_by,measures,columns,sort,limit}) and its display setting
    ({kind, column, date_column, ...}) into a ViewSpec dict. Raises ValueError if it uses something a spec cannot say."""
    if not isinstance(report, dict) or not {'key', 'title', 'base'} <= set(report):
        raise ValueError('not a report definition')
    display = display or {'kind': 'table'}
    kind = display.get('kind', 'table')
    if kind not in _PRIMITIVE_FROM_DISPLAY:
        raise ValueError(f'unknown display {kind}')
    cols = report.get('columns') or []
    flt = []
    for f in report.get('filters', []):
        op = _OP_FROM_REPORT.get(f.get('op'))
        if not op:
            raise ValueError(f"filter operation {f.get('op')} has no ViewSpec equivalent")
        node = {**_path(f['path']), 'op': op}
        if 'value' in f and op not in ('empty', 'not_empty'):
            node['value'] = f['value']
        flt.append(node)
    item = {'record_type': report['base'], 'fields': [_path(c) for c in cols] or [{'field': 'title'}]}
    if flt:
        item['filter'] = {'and': flt}
    spec = {'spec_version': SPEC_VERSION, 'id': spec_id or f"report.{report['key']}", 'name': report['title'][:MAX_LABEL],
            'primitive': _PRIMITIVE_FROM_DISPLAY[kind], 'source': {'items': [item]}}
    groups = report.get('group_by') or []
    if groups:
        spec['group'] = {'columns': {'field': groups[0]}}
        if len(groups) > 1:
            spec['group']['rows'] = {'field': groups[1]}
    aggs = []
    for i, m in enumerate(report.get('measures') or ([{'agg': 'count'}] if groups else [])):
        aggs.append({'fn': m['agg'], 'as': f'm{i}', **({'field': m['path']} if m.get('path') else {})})
    if aggs:
        spec['aggregate'] = aggs
    layout = {}
    if kind == 'board' and 'column' in display and cols:
        spec['group'] = {'columns': {'field': cols[display['column']]}}
    if kind == 'calendar' and 'date_column' in display and cols:
        layout['date_field'] = cols[display['date_column']]
    if kind == 'timeline' and cols:
        layout['start_field'], layout['end_field'] = cols[display['start_column']], cols[display['end_column']]
    if layout:
        spec['layout'] = layout
    return spec


# ------------------------------------------------------------------ running a spec through the existing report engine

_OP_TO_REPORT = {'eq': 'eq', 'neq': 'ne', 'in': 'in', 'contains': 'contains', 'empty': 'empty', 'not_empty': 'not_empty',
                 'gt': 'gt', 'gte': 'gte', 'lt': 'lt', 'lte': 'lte', 'before': 'lt', 'after': 'gt'}
_RELATIVE_TO_REPORT = {'today': 'today', 'this_week': 'week_start', 'this_month': 'month_start'}
_KIND_FROM_PRIMITIVE = {'table': 'table', 'list': 'table', 'feed': 'table', 'record': 'table', 'board': 'board', 'calendar': 'calendar', 'timeline': 'timeline', 'chart': 'bar',
                        'metric': 'tiles', 'progress': 'tiles'}


class Unsupported(ValueError):
    """The spec is valid but cannot be run by the report engine (for example a gallery, or a filter on the signed-in person)."""


def _flat_path(f):
    return f['field'] if 'field' in f else '.'.join(f['path'])


def _report_value(v, params):
    if isinstance(v, dict):
        if 'param' in v:
            if v['param'] not in params:
                raise KeyError(v['param'])
            return params[v['param']]
        if 'relative' in v:
            if v['relative'] not in _RELATIVE_TO_REPORT:
                raise Unsupported(f"the date {v['relative']} is not supported when running a view")
            return _RELATIVE_TO_REPORT[v['relative']]
        raise Unsupported('a filter on the signed-in person is not supported when running a view')
    return v


def _conditions(node, params, out):
    if 'and' in node:
        for sub in node['and']:
            _conditions(sub, params, out)
        return
    if 'or' in node:
        raise Unsupported('or-filters are not supported when running a view')
    op = node['op']
    if op not in _OP_TO_REPORT:
        raise Unsupported(f'the operator {op} is not supported when running a view')
    cond = {'path': _flat_path(node), 'op': _OP_TO_REPORT[op]}
    if 'value' in node:
        try:
            cond['value'] = _report_value(node['value'], params)
        except KeyError:
            return                                   # an optional context that was not given: the condition is left out
    out.append(cond)


def spec_to_report(spec, params=None):
    """-> (report definition, display setting) for views_wiring.show, so a stored view runs through the permission-aware report
    engine. Raises Unsupported for specs the engine cannot express (several record types, gallery/feed/record/form, or filters
    on the signed-in person). The caller validates the spec first."""
    params = params or {}
    prim = spec['primitive']
    if prim not in _KIND_FROM_PRIMITIVE:
        raise Unsupported(f'a {prim} cannot be run yet')
    items = spec['source']['items']
    if len(items) != 1:
        raise Unsupported('a view over several record types cannot be run yet')
    item = items[0]
    conds = []
    if 'filter' in item:
        _conditions(item['filter'], params, conds)
    group = spec.get('group') or {}
    layout = spec.get('layout') or {}
    cols = [_flat_path(f) for f in item['fields']]
    report = {'key': 'spec_' + re.sub(r'[^a-z0-9]+', '_', spec['id']).strip('_')[:50], 'title': spec['name'][:120], 'base': item['record_type']}
    if conds:
        report['filters'] = conds
    kind = _KIND_FROM_PRIMITIVE[prim]
    display = {'kind': kind}
    if prim in ('chart', 'metric', 'progress'):
        groups = [group[a]['field'] for a in ('columns', 'rows') if a in group]
        report['measures'] = []
        for a in spec.get('aggregate') or [{'fn': 'count', 'as': 'n'}]:
            if a['fn'] == 'count_distinct':
                raise Unsupported('count_distinct cannot be run yet')
            report['measures'].append({'agg': a['fn'], **({'path': a['field']} if a.get('field') else {}), 'label': a['as']})
        if groups:
            report['group_by'] = groups
        else:
            report['figure'] = True
    else:
        need = []
        if prim == 'board':
            need = [group['columns']['field']]
        if prim == 'calendar':
            need = [layout['date_field']]
        if prim == 'timeline':
            need = [layout['start_field'], layout['end_field']]
        for n in need:
            if n not in cols:
                cols.append(n)
        if prim == 'feed':                       # the date leads, so the report orders by it (the screen shows newest first)
            cols = [layout['date_field']] + [c for c in cols if c != layout['date_field']]
            report['sort'] = 'first_column'
        report['columns'] = cols[:12]
        if prim == 'board':
            display['column'] = report['columns'].index(group['columns']['field'])
        if prim == 'calendar':
            display['date_column'] = report['columns'].index(layout['date_field'])
        if prim == 'timeline':
            display['start_column'] = report['columns'].index(layout['start_field'])
            display['end_column'] = report['columns'].index(layout['end_field'])
    return report, display
