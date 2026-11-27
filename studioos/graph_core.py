"""v0.10.0 "One graph": the database-free core of the universal engine.

Everything here is pure Python (standard library only), so it can be tested on its own:

* the system types (staff, tasks, projects, clients, suppliers, files) that universal
  records may point to, and what may be read from each;
* field specifications, including the new ``reference`` primitive and type options;
* relative dates ("today-7") used by filters, reports and daily rules;
* rule conditions (``all`` of up to four field tests);
* the report planner: a base type, filters, up to two group-by paths and measures, where
  a path may follow reference fields and links in either direction (at most 4 steps);
* conversion of older Stage A designs into universal fields (one registry);
* business-pack checking (types, links, views, reports, rules as one data file);
* a small, offline reader that fills a type's fields from a typed sentence.

No function here executes metadata, builds SQL, or reads the database. The database
adapter is ``graph_query``.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

KEY = re.compile(r'^[a-z][a-z0-9_]{1,59}$')
PRIMITIVES = ('text', 'integer', 'boolean', 'date', 'datetime', 'enum', 'decimal', 'money', 'quantity', 'reference')
NUMERIC = ('integer', 'decimal', 'money', 'quantity')
ROLES = ('admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer')
APPROVER_ROLES = ('manager', 'accounts')          # Admin can always approve
RESERVED_FIELDS = {'project_id', 'id', 'status', 'created_at', 'deleted_at', 'source_ticket_id',
                   'record_type', 'reference', 'version'}
MAX_PATH = 4
MAX_GROUPS = 2
MAX_MEASURES = 6
MAX_FILTERS = 8
MAX_REPORT_ROWS = 500

# What a universal record may point to besides other universal records. ``attrs`` are the
# only columns ever read from the underlying table; nothing else (passwords, budgets,
# phone numbers of staff ...) is reachable through the engine.
SYSTEM_TYPES = {
    'system.user': {'title': 'Staff member', 'label': 'display_name',
                    'attrs': {'display_name': 'text', 'username': 'text', 'role': 'text'}},
    'system.task': {'title': 'Task', 'label': 'title',
                    'attrs': {'title': 'text', 'assignee': 'text', 'due_date': 'date', 'status': 'text', 'progress': 'integer'}},
    'system.project': {'title': 'Project', 'label': 'name',
                       'attrs': {'name': 'text', 'client': 'text', 'stage': 'text', 'location': 'text', 'start_date': 'date'}},
    'system.client': {'title': 'Client', 'label': 'name', 'attrs': {'name': 'text', 'trade': 'text'}},
    'system.supplier': {'title': 'Supplier', 'label': 'name', 'attrs': {'name': 'text', 'trade': 'text', 'gstin': 'text'}},
    'system.document': {'title': 'File', 'label': 'name', 'attrs': {'name': 'text', 'doc_type': 'text', 'relative_path': 'text'}},
}


class GraphError(ValueError):
    pass


def check_key(value, label='Key'):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise GraphError(f'{label} must be lower_snake_case, 2–60 characters')
    if value.startswith(('system_', 'finance_', 'gl_', 'audit_', 'ticket_', 'approval_')) or value in {
            'system', 'accounting', 'audit', 'security', 'approval', 'ledger', 'journal'}:
        raise GraphError('This key is reserved for protected system types')
    return value


# ------------------------------------------------------------------ type definitions

TYPE_KEYS = {'key', 'title', 'fields', 'description', 'aliases', 'approver_roles', 'company_read_roles',
             'company_propose_roles', 'label_field', 'self_read'}
# v0.11.0: links may also START at a task or a staff member (not only at a universal record).
SYSTEM_SOURCES = ('system.task', 'system.user')
FIELD_KEYS = {'name', 'type', 'required', 'meaning', 'options', 'retired_options', 'units', 'target'}


def enum_all_options(f: dict) -> list[str] | None:
    """All valid enum values for reporting/filtering: active options plus retired_options."""
    opts = f.get('options')
    if opts is None:
        return None
    retired = f.get('retired_options') or []
    return list(opts) + [o for o in retired if o not in opts]


def check_type_options(d: dict):
    """The optional, security-relevant parts of a type definition."""
    for name in ('approver_roles',):
        roles = d.get(name, [])
        if not isinstance(roles, list) or any(r not in APPROVER_ROLES for r in roles) or len(set(roles)) != len(roles):
            raise GraphError('Approver roles may only add manager or accounts; Admin always approves')
    for name in ('company_read_roles', 'company_propose_roles'):
        roles = d.get(name, [])
        if not isinstance(roles, list) or any(r not in ROLES for r in roles) or len(set(roles)) != len(roles):
            raise GraphError(f'{name}: unknown role')
        if 'viewer' in roles and name == 'company_propose_roles':
            raise GraphError('Viewers can never propose records')
    label = d.get('label_field')
    if label is not None and label not in {f.get('name') for f in d.get('fields') or [] if isinstance(f, dict)}:
        raise GraphError('label_field must be one of the type\'s fields')
    check_self_read(d.get('self_read'), d.get('fields') or [])


def check_self_read(opt, fields):
    """v0.11.0: ``{'field': <staff reference>, 'when': <condition or None>}`` lets the staff member a
    record names read that record (their own attendance, leave, shared weekly review) without a
    manager role. Nobody else gains anything from it."""
    if opt is None:
        return None
    if not isinstance(opt, dict) or set(opt) - {'field', 'when'} or 'field' not in opt:
        raise GraphError('self_read names the staff field and, optionally, when the person may read it')
    spec = {f.get('name'): f for f in fields if isinstance(f, dict)}
    f = spec.get(opt['field'])
    if not f or f.get('type') != 'reference' or f.get('target') != 'system.user':
        raise GraphError('self_read must name a field that points to a staff member')
    check_condition(opt.get('when'), spec)
    return opt


def self_read_allows(opt, values, user_id, fields, today) -> bool:
    """Does the type's self_read option let this person read a record with these values?"""
    if not opt or type(user_id) is not int:
        return False
    if (values or {}).get(opt['field']) != user_id:
        return False
    try:
        return condition_matches(opt.get('when'), values or {}, field_map(fields), today)
    except (GraphError, KeyError):
        return False


def check_field_specs(fields, own_key=None, known_targets=()):
    """Structure of a type's fields. ``known_targets`` are universal type keys a reference may
    point to (besides system types and the type itself). Raises GraphError."""
    if not isinstance(fields, list) or not 1 <= len(fields) <= 36:
        raise GraphError('Define 1–36 fields')
    seen = set()
    for f in fields:
        if not isinstance(f, dict) or set(f) - FIELD_KEYS:
            raise GraphError('Unsupported field specification')
        name = check_key(f.get('name'), 'Field name')
        if name in RESERVED_FIELDS:
            raise GraphError('Universal field cannot be redefined')
        if name in seen:
            raise GraphError('Duplicate field')
        seen.add(name)
        typ = f.get('type')
        if typ not in PRIMITIVES:
            raise GraphError(f'Unsupported primitive: {typ}')
        if type(f.get('required', False)) is not bool:
            raise GraphError('Required must be boolean')
        meaning = f.get('meaning', name)
        if not isinstance(meaning, str) or len(meaning) > 240:
            raise GraphError('Invalid meaning')
        if typ == 'enum':
            opts = f.get('options')
            if not isinstance(opts, list) or not 1 <= len(opts) <= 32 or any(
                    not isinstance(o, str) or not 1 <= len(o) <= 70 for o in opts) or len(set(opts)) != len(opts):
                raise GraphError('Enum needs unique controlled options')
            if 'retired_options' in f and f['retired_options'] is not None:
                retired = f['retired_options']
                if not isinstance(retired, list) or len(retired) > 64 or any(
                        not isinstance(o, str) or not 1 <= len(o) <= 70 for o in retired) or len(set(retired)) != len(retired):
                    raise GraphError('Retired options must be unique controlled values')
                if set(retired) & set(opts):
                    raise GraphError('A category cannot be both active and retired')
        elif 'retired_options' in f:
            raise GraphError('Only enum fields have retired options')
        if typ == 'quantity':
            units = f.get('units')
            if not isinstance(units, list) or not 1 <= len(units) <= 20 or any(
                    not isinstance(u, str) or not re.fullmatch(r'[A-Za-z0-9_/-]{1,20}', u) for u in units):
                raise GraphError('Quantity requires explicitly allowed units')
        if typ == 'reference':
            target = f.get('target')
            if not (target in SYSTEM_TYPES or target == own_key or target in known_targets):
                raise GraphError(f'{name}: reference target must be a system type, an active type, or this type')
        elif 'target' in f:
            raise GraphError('Only reference fields have a target')
    return True


def field_map(fields):
    return {f['name']: f for f in fields}


# ------------------------------------------------------------------ dates

REL_DATE = re.compile(r'^(today|week_start|month_start)(?:([+-])(\d{1,4}))?$')


def resolve_date(value, today: dt.date) -> str:
    """'2026-11-14', 'today', 'today-7', 'month_start', 'week_start+7' -> ISO date."""
    if isinstance(value, str):
        m = REL_DATE.fullmatch(value.strip())
        if m:
            base = {'today': today, 'week_start': today - dt.timedelta(days=today.weekday()),
                    'month_start': today.replace(day=1)}[m.group(1)]
            if m.group(2):
                days = int(m.group(3)) * (1 if m.group(2) == '+' else -1)
                base = base + dt.timedelta(days=days)
            return base.isoformat()
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            pass
    raise GraphError('Date must be YYYY-MM-DD or today, today-7, week_start, month_start')


def as_date(value):
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def as_number(value):
    """Exact Decimal from a stored value; None when not numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):
        value = value.get('amount', value.get('value'))
    if isinstance(value, float):
        return None
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return n if n.is_finite() else None


# ------------------------------------------------------------------ comparisons (filters, rules)

OPS_BY_KIND = {
    'text': {'eq', 'ne', 'contains', 'in', 'empty', 'not_empty'},
    'enum': {'eq', 'ne', 'in', 'empty', 'not_empty'},
    'label': {'eq', 'ne', 'contains', 'in', 'empty', 'not_empty'},
    'boolean': {'eq', 'empty', 'not_empty'},
    'number': {'eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'empty', 'not_empty'},
    'date': {'eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'empty', 'not_empty', 'before_today', 'within_days'},
    'datetime': {'empty', 'not_empty'},
}
NO_VALUE_OPS = {'empty', 'not_empty', 'before_today'}


def kind_of(primitive: str) -> str:
    if primitive in NUMERIC:
        return 'number'
    if primitive in ('reference', 'label'):
        return 'label'
    return primitive if primitive in OPS_BY_KIND else 'text'


def check_comparison(kind: str, op, value, options=None):
    if op not in OPS_BY_KIND.get(kind, set()):
        raise GraphError(f'Operation {op!r} is not available for {kind} values')
    if op in NO_VALUE_OPS:
        if value not in (None, '', True):
            raise GraphError(f'{op} takes no value')
        return
    if op == 'within_days':
        if type(value) is not int or not 0 <= value <= 3660:
            raise GraphError('within_days needs a whole number of days (0–3660)')
        return
    if op == 'in':
        if not isinstance(value, list) or not 1 <= len(value) <= 32 or any(not isinstance(x, str) for x in value):
            raise GraphError('in needs a list of up to 32 values')
        if options and any(x not in options for x in value):
            raise GraphError('in: value not among the field options')
        return
    if kind == 'number':
        if as_number(value) is None or isinstance(value, float):
            raise GraphError('Number filter needs an exact number (no floating point)')
    elif kind == 'date':
        resolve_date(value, dt.date(2000, 1, 1))
    elif kind == 'boolean':
        if type(value) is not bool:
            raise GraphError('Yes/no filter needs true or false')
    else:
        if not isinstance(value, str) or not 1 <= len(value) <= 200:
            raise GraphError('Text filter needs 1–200 characters')
        if kind == 'enum' and options and value not in options:
            raise GraphError('Value is not one of the field options')


def compare(kind: str, op: str, current, value, today: dt.date) -> bool:
    """Does one stored value satisfy the test? Missing values satisfy only 'empty'."""
    missing = current is None or (isinstance(current, str) and not current.strip())
    if op == 'empty':
        return missing
    if op == 'not_empty':
        return not missing
    if missing:
        return op == 'ne'
    if kind == 'number':
        a = as_number(current)
        b = as_number(value)
        if a is None or b is None:
            return False
    elif kind == 'date':
        a = as_date(current)
        if a is None:
            return False
        if op == 'before_today':
            return a < today
        if op == 'within_days':
            return today <= a <= today + dt.timedelta(days=value)
        b = dt.date.fromisoformat(resolve_date(value, today))
    elif kind == 'boolean':
        return current is value if op == 'eq' else False
    else:
        a, b = str(current).casefold(), value
        if op == 'contains':
            return str(value).casefold() in a
        if op == 'in':
            return a in {str(x).casefold() for x in value}
        b = str(value).casefold()
    return {'eq': a == b, 'ne': a != b, 'lt': a < b, 'lte': a <= b, 'gt': a > b, 'gte': a >= b}.get(op, False)


def check_condition(cond, fields: dict):
    """A rule condition: None, one {'field','op','value'} test, or {'all': [tests]} (1–4)."""
    if cond is None:
        return []
    tests = cond['all'] if isinstance(cond, dict) and set(cond) == {'all'} else [cond]
    if not isinstance(tests, list) or not 1 <= len(tests) <= 4:
        raise GraphError('A condition has 1–4 tests')
    for t in tests:
        if not isinstance(t, dict) or set(t) - {'field', 'op', 'value'} or 'field' not in t or 'op' not in t:
            raise GraphError('Each test is a field, an operation and (usually) a value')
        f = fields.get(t['field'])
        if not f:
            raise GraphError('Unknown field in condition: ' + str(t['field']))
        check_comparison(kind_of(f['type']), t['op'], t.get('value'), enum_all_options(f))
    return tests


def condition_matches(cond, values: dict, fields: dict, today: dt.date) -> bool:
    for t in check_condition(cond, fields):
        f = fields[t['field']]
        if not compare(kind_of(f['type']), t['op'], (values or {}).get(t['field']), t.get('value'), today):
            return False
    return True


# ------------------------------------------------------------------ catalog and paths

def catalog_from(types: dict, relations: dict) -> dict:
    """types: {key: {'title', 'fields': [...]}}, relations: {key: {'source_type','target_type'}}."""
    return {'types': {k: {'title': v.get('title', k), 'fields': field_map(v['fields']),
                          'label_field': v.get('label_field')} for k, v in types.items()},
            'relations': dict(relations)}


def node_title(catalog, node_type):
    if node_type in SYSTEM_TYPES:
        return SYSTEM_TYPES[node_type]['title']
    return catalog['types'].get(node_type, {}).get('title', node_type)


def compile_path(catalog: dict, base: str, path):
    """'severity', 'assigned_to.display_name', '@action_for.title', '~inspection_of.severity',
    'project.name'  ->  {'steps': [...], 'leaf': (kind, primitive, options), 'label': text}.

    Steps are ('ref', field, target), ('out', relation, target), ('in', relation, source),
    ('project',). The leaf is ('attr', name) or ('label',)."""
    if not isinstance(path, str) or not path or len(path) > 200:
        raise GraphError('Path must be text')
    segments = path.split('.')
    if len(segments) > MAX_PATH:
        raise GraphError(f'A path follows at most {MAX_PATH - 1} links')
    node = base
    steps = []
    words = []
    for i, seg in enumerate(segments):
        last = i == len(segments) - 1
        if seg.startswith(('@', '~')):
            rel = catalog['relations'].get(seg[1:])
            if not rel:
                raise GraphError('Unknown link: ' + seg[1:])
            if seg[0] == '@':
                if rel['source_type'] != node:
                    raise GraphError(f'{seg[1:]} does not start at {node_title(catalog, node)}')
                steps.append(('out', seg[1:], rel['target_type']))
                node = rel['target_type']
            else:
                if rel['target_type'] != node:
                    raise GraphError(f'{seg[1:]} does not point to {node_title(catalog, node)}')
                steps.append(('in', seg[1:], rel['source_type']))
                node = rel['source_type']
            words.append(node_title(catalog, node))
            if last:
                return {'steps': steps, 'leaf': ('label',), 'kind': 'label', 'primitive': 'label',
                        'options': None, 'label': ' › '.join(words)}
            continue
        own = catalog['types'].get(node, {}).get('fields', {}) if node not in SYSTEM_TYPES else {}
        if seg == 'project' and seg not in own:
            if node in SYSTEM_TYPES and node != 'system.task':
                raise GraphError('Only records and tasks belong to a project')
            steps.append(('project',))
            node = 'system.project'
            words.append('Project')
            if last:
                return {'steps': steps, 'leaf': ('label',), 'kind': 'label', 'primitive': 'label',
                        'options': None, 'label': ' › '.join(words)}
            continue
        if node in SYSTEM_TYPES:
            attrs = SYSTEM_TYPES[node]['attrs']
            if seg not in attrs or not last:
                raise GraphError(f'{node_title(catalog, node)} has no readable detail "{seg}"')
            words.append(seg.replace('_', ' '))
            return {'steps': steps, 'leaf': ('attr', seg), 'kind': kind_of(attrs[seg]), 'primitive': attrs[seg],
                    'options': None, 'label': ' › '.join(words)}
        t = catalog['types'].get(node)
        if not t:
            raise GraphError('Unknown type: ' + str(node))
        if (node, seg) in catalog.get('finance_only_fields', ()):
            raise GraphError('This report uses a field that is finance only')
        f = t['fields'].get(seg)
        if not f:
            raise GraphError(f'{t["title"]} has no field "{seg}"')
        words.append(f.get('meaning') or seg.replace('_', ' '))
        if f['type'] == 'reference':
            steps.append(('ref', seg, f['target']))
            node = f['target']
            if last:
                return {'steps': steps, 'leaf': ('label',), 'kind': 'label', 'primitive': 'reference',
                        'options': None, 'label': ' › '.join(words)}
            continue
        if not last:
            raise GraphError(f'"{seg}" is not a reference, so the path cannot continue past it')
        return {'steps': steps, 'leaf': ('attr', seg), 'kind': kind_of(f['type']), 'primitive': f['type'],
                'options': enum_all_options(f), 'label': ' › '.join(words)}
    raise GraphError('Empty path')


# ------------------------------------------------------------------ reports

REPORT_KEYS = {'key', 'title', 'base', 'filters', 'group_by', 'measures', 'columns', 'sort', 'limit', 'description'}
# v0.12.0: saved view settings next to a report (checked by views_core): one number, how it is
# shown, and which roles see it in their list (rows are still limited by access).
VIEW_KEYS = {'figure', 'display', 'visible_to'}
AGGS = ('count', 'sum', 'avg', 'min', 'max')


def check_report(catalog: dict, d: dict, *, require_columns: bool = True):
    if not isinstance(d, dict) or set(d) - REPORT_KEYS or not {'key', 'title', 'base'} <= set(d):
        raise GraphError('A report needs key, title and base, and may have filters, group_by, measures, columns, sort, limit')
    check_key(d['key'], 'Report key')
    if not isinstance(d['title'], str) or not 2 <= len(d['title'].strip()) <= 120:
        raise GraphError('Report title required (2–120 characters)')
    base = d['base']
    if base not in catalog['types'] and base not in ('system.task',):
        raise GraphError('A report starts from an active type or from tasks')
    compiled = {'filters': [], 'group_by': [], 'measures': [], 'columns': []}
    filters = d.get('filters', [])
    if not isinstance(filters, list) or len(filters) > MAX_FILTERS:
        raise GraphError(f'At most {MAX_FILTERS} filters')
    for flt in filters:
        if not isinstance(flt, dict) or set(flt) - {'path', 'op', 'value'} or not {'path', 'op'} <= set(flt):
            raise GraphError('A filter is a path, an operation and (usually) a value')
        c = compile_path(catalog, base, flt['path'])
        check_comparison(c['kind'], flt['op'], flt.get('value'), c['options'])
        compiled['filters'].append((c, flt['op'], flt.get('value')))
    groups = d.get('group_by', [])
    if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
        raise GraphError(f'Group by at most {MAX_GROUPS} paths')
    for g in groups:
        c = compile_path(catalog, base, g)
        if c['kind'] == 'number':
            raise GraphError('Group by a name, option, date or yes/no, not by an amount')
        compiled['group_by'].append(c)
    measures = d.get('measures', [{'agg': 'count'}] if groups else [])
    if not isinstance(measures, list) or len(measures) > MAX_MEASURES:
        raise GraphError(f'At most {MAX_MEASURES} measures')
    for m in measures:
        if not isinstance(m, dict) or set(m) - {'agg', 'path', 'label'} or m.get('agg') not in AGGS:
            raise GraphError('A measure is count, sum, avg, min or max (with a path for all but count)')
        if m['agg'] == 'count':
            if 'path' in m:
                raise GraphError('count takes no path')
            compiled['measures'].append(('count', None, m.get('label') or 'Count'))
        else:
            c = compile_path(catalog, base, m.get('path'))
            if c['kind'] != 'number':
                raise GraphError(f'{m["agg"]} needs a number, amount or quantity')
            compiled['measures'].append((m['agg'], c, m.get('label') or f'{m["agg"].capitalize()} of {c["label"]}'))
        if 'label' in m and (not isinstance(m['label'], str) or len(m['label']) > 80):
            raise GraphError('Measure label up to 80 characters')
    columns = d.get('columns', [])
    if groups and columns:
        raise GraphError('A grouped report shows its groups and measures; leave columns empty')
    if require_columns and not groups and not columns:
        raise GraphError('A report without groups needs columns to show')
    if not isinstance(columns, list) or len(columns) > 12:
        raise GraphError('At most 12 columns')
    for col in columns:
        compiled['columns'].append(compile_path(catalog, base, col))
    if d.get('sort', 'group') not in ('group', 'measure_desc', 'measure_asc', 'first_column'):
        raise GraphError('sort is group, measure_desc, measure_asc or first_column')
    limit = d.get('limit', 200)
    if type(limit) is not int or not 1 <= limit <= MAX_REPORT_ROWS:
        raise GraphError(f'limit is 1–{MAX_REPORT_ROWS}')
    return compiled


def leaf_values(resolver, node: dict, compiled: dict) -> list:
    """All values a path reaches from one node (a path through 'many' links can reach several)."""
    nodes = [node]
    for step in compiled['steps']:
        nxt = []
        for n in nodes:
            nxt.extend(resolver.follow(n, step))
        nodes = nxt[:200]
        if not nodes:
            return []
    leaf = compiled['leaf']
    out = []
    for n in nodes:
        if leaf[0] == 'label':
            out.append(n.get('label'))
        else:
            out.append((n.get('values') or {}).get(leaf[1]))
    return out


def _display(value, primitive):
    if value is None or value == '':
        return '(none)'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if primitive == 'money' and isinstance(value, dict):
        n = as_number(value)
        return f'₹{n:,.2f}' if n is not None else '(invalid)'
    if primitive == 'quantity' and isinstance(value, dict):
        return f'{value.get("value")} {value.get("unit")}'
    return str(value)


def _fmt_number(n: Decimal, money: bool):
    if money:
        return f'₹{n.quantize(Decimal("0.01")):,.2f}'
    q = n.normalize()
    return format(q if q == q.to_integral() else n.quantize(Decimal('0.01')), 'f')


def run_report(resolver, catalog: dict, d: dict, today: dt.date) -> dict:
    """Execute a checked report with a resolver offering ``base_rows(base)`` and
    ``follow(node, step)``. Bounded: base rows are capped by the resolver."""
    compiled = check_report(catalog, d)
    rows = resolver.base_rows(d['base'])
    kept = []
    for node in rows:
        ok = True
        for c, op, value in compiled['filters']:
            vals = leaf_values(resolver, node, c) or [None]
            if op == 'ne':
                if any(compare(c['kind'], 'eq', v, value, today) for v in vals):
                    ok = False
            elif not any(compare(c['kind'], op, v, value, today) for v in vals):
                ok = False
            if not ok:
                break
        if ok:
            kept.append(node)
    result = {'key': d['key'], 'title': d['title'], 'base': d['base'], 'matched': len(kept),
              'scanned': len(rows), 'as_of': today.isoformat()}
    if compiled['group_by']:
        buckets = {}
        for node in kept:
            parts = []
            for c in compiled['group_by']:
                vals = sorted({_display(v, c['primitive']) for v in leaf_values(resolver, node, c)}) or ['(none)']
                parts.append(vals[:20])
            combos = [()]
            for vals in parts:
                combos = [x + (v,) for x in combos for v in vals]
            for combo in combos[:40]:
                buckets.setdefault(combo, []).append(node)
        out_rows = []
        for combo, members in buckets.items():
            cells = []
            for agg, c, _label in compiled['measures']:
                if agg == 'count':
                    cells.append({'value': str(len(members)), 'n': Decimal(len(members))})
                    continue
                nums = [n for m in members for n in (as_number(v) for v in leaf_values(resolver, m, c)) if n is not None]
                money = c['primitive'] == 'money'
                if not nums:
                    cells.append({'value': '—', 'n': None})
                    continue
                n = {'sum': sum(nums, Decimal(0)), 'avg': sum(nums, Decimal(0)) / len(nums),
                     'min': min(nums), 'max': max(nums)}[agg]
                cells.append({'value': _fmt_number(n, money), 'n': n})
            out_rows.append({'group': list(combo), 'cells': cells, 'record_ids': [m['id'] for m in members][:50]})
        sort = d.get('sort', 'group')
        if sort.startswith('measure') and compiled['measures']:
            sign = -1 if sort == 'measure_desc' else 1
            out_rows.sort(key=lambda r: (r['cells'][0]['n'] is None, sign * (r['cells'][0]['n'] or 0),
                                         [x.casefold() for x in r['group']]))
        else:
            out_rows.sort(key=lambda r: [x.casefold() for x in r['group']])
        limit = d.get('limit', 200)
        result.update({'mode': 'grouped', 'group_labels': [c['label'] for c in compiled['group_by']],
                       'measure_labels': [m[2] for m in compiled['measures']],
                       'rows': [{'group': r['group'], 'values': [c['value'] for c in r['cells']],
                                 # v0.12.0: plain numbers for charts (exact decimals as text)
                                 'numbers': [None if c['n'] is None else str(c['n']) for c in r['cells']],
                                 'record_ids': r['record_ids']} for r in out_rows[:limit]],
                       'groups': len(out_rows)})
        return result
    table = []
    for node in kept:
        cells = []
        for c in compiled['columns']:
            vals = [_display(v, c['primitive']) for v in leaf_values(resolver, node, c)]
            cells.append(', '.join(dict.fromkeys(vals)) if vals else '(none)')
        table.append({'record_id': node['id'], 'label': node.get('label'), 'cells': cells})
    if d.get('sort') == 'first_column':
        table.sort(key=lambda r: r['cells'][0].casefold() if r['cells'] else '')
    result.update({'mode': 'list', 'column_labels': [c['label'] for c in compiled['columns']],
                   'rows': table[:d.get('limit', 200)]})
    return result


# ------------------------------------------------------------------ one registry (Stage A designs)

LEGACY_MAP = {'text': 'text', 'integer': 'integer', 'decimal': 'decimal', 'date': 'date',
              'boolean': 'boolean', 'timestamp': 'datetime'}


def legacy_to_runtime(design: dict) -> list:
    """Universal fields for a design built through the chat's Stage A flow. Fields the engine
    cannot type exactly (free JSON, system columns) are left out, never guessed."""
    out = []
    for f in (design or {}).get('fields', []):
        if f.get('universal') or not isinstance(f.get('name'), str):
            continue
        name = f['name']
        if name in RESERVED_FIELDS or name in ('not_project_related', 'created_by', 'extra_attributes', 'updated_at', 'status'):
            continue
        try:
            check_key(name)
        except GraphError:
            continue
        typ = LEGACY_MAP.get(f.get('type'))
        if typ is None:
            continue
        spec = {'name': name, 'type': typ, 'required': f.get('required_level') == 'draft',
                'meaning': str(f.get('meaning') or f.get('description') or name)[:240]}
        allowed = f.get('allowed_values')
        if typ == 'text' and isinstance(allowed, list) and allowed and all(isinstance(x, str) and 1 <= len(x) <= 70 for x in allowed) \
                and len(set(allowed)) == len(allowed) and len(allowed) <= 32:
            spec.update(type='enum', options=list(allowed))
        out.append(spec)
    return out[:36]


# ------------------------------------------------------------------ business packs

PACK_KEYS = {'key', 'title', 'version', 'description', 'types', 'relations', 'views', 'reports', 'workflows', 'upgrade',
             'calculations', 'requires'}


def check_pack(pack: dict, existing_types=(), existing_relations=None, installed_packs=()):
    """Internal consistency of a business pack. The engine validators run again, item by item,
    when the Admin's ticket is approved; this check catches mistakes before a ticket exists."""
    if not isinstance(pack, dict) or set(pack) - PACK_KEYS or not {'key', 'title', 'version', 'types'} <= set(pack):
        raise GraphError('A pack needs key, title, version and types')
    check_key(pack['key'], 'Pack key')
    if type(pack['version']) is not int or pack['version'] < 1:
        raise GraphError('Pack version is a positive whole number')
    up = pack.get('upgrade')       # v0.13.0: how an installed earlier version is brought up to this one
    if up is not None and (not isinstance(up, dict) or set(up) - {'from', 'note', 'changes'} or up.get('from') != pack['version'] - 1
                           or not isinstance(up.get('changes'), list)):
        raise GraphError('upgrade names the version it upgrades from (one less) and its changes')
    for req in pack.get('requires', []):
        if req not in installed_packs:
            raise GraphError(f'Install the "{req}" pack first')
    existing_types = set(existing_types)
    types = {}
    for t in pack['types']:
        if not isinstance(t, dict) or set(t) - TYPE_KEYS:
            raise GraphError('Unsupported type-definition keys in pack')
        key = check_key(t.get('key'), 'Type key')
        if key in types or key in existing_types:
            raise GraphError(f'Type {key} already exists')
        check_field_specs(t.get('fields'), own_key=key, known_targets=set(types) | existing_types)
        check_type_options(t)
        types[key] = t
    rels = dict(existing_relations or {})
    for r in pack.get('relations', []):
        if not isinstance(r, dict) or set(r) - {'key', 'source_type', 'target_type', 'inverse_label', 'cardinality', 'order_by', 'label'}:
            raise GraphError('Unsupported relation keys in pack')
        key = check_key(r.get('key'), 'Relation key')
        if key in rels:
            raise GraphError(f'Link {key} already exists')
        if r.get('source_type') not in types and r.get('source_type') not in existing_types \
                and r.get('source_type') not in SYSTEM_SOURCES:
            raise GraphError(f'{key}: source must be a type, a task or a staff member')
        if r.get('target_type') not in types and r.get('target_type') not in existing_types and r.get('target_type') not in SYSTEM_TYPES:
            raise GraphError(f'{key}: target must be a type or a system type')
        if r.get('cardinality', 'many') not in ('one', 'many'):
            raise GraphError('Cardinality is one or many')
        if 'order_by' in r:
            src = types.get(r.get('source_type'))
            if src is None or r['order_by'] not in {f['name'] for f in src['fields']}:
                raise GraphError(f'{key}: order_by must be a field of the source type')
        rels[key] = {'source_type': r['source_type'], 'target_type': r['target_type']}
    # Reports, views and rules may only use types known after the pack is installed.
    catalog = catalog_from({**{k: v for k, v in types.items()}}, rels)
    for k in existing_types:
        catalog['types'].setdefault(k, {'title': k, 'fields': {}, 'label_field': None})
    for rep in pack.get('reports', []):
        check_report(catalog, rep)
    for v in pack.get('views', []):
        if not isinstance(v, dict) or set(v) != {'key', 'type_key', 'title', 'filters', 'columns'}:
            raise GraphError('A view needs key, type_key, title, filters and columns')
        check_key(v['key'], 'View key')
        t = types.get(v['type_key'])
        if t is None:
            raise GraphError('A pack view must use a type from the same pack')
        names = {f['name'] for f in t['fields']}
        if not v['columns'] or any(c not in names for c in v['columns']):
            raise GraphError(f'View {v["key"]}: columns must be fields of {v["type_key"]}')
    for w in pack.get('workflows', []):
        if not isinstance(w, dict) or set(w) - {'key', 'type_key', 'event', 'condition', 'message', 'action', 'notify_field'}:
            raise GraphError('Unsupported rule keys in pack')
        check_key(w.get('key'), 'Rule key')
        t = types.get(w.get('type_key'))
        if t is None:
            raise GraphError('A pack rule must use a type from the same pack')
        fields = field_map(t['fields'])
        if w.get('event') not in ('record_created', 'record_updated', 'daily'):
            raise GraphError('Rule event is record_created, record_updated or daily')
        if w.get('action', 'notify') != 'notify':
            raise GraphError('Rules can only notify')
        check_condition(w.get('condition'), fields)
        nf = w.get('notify_field')
        if nf is not None and (nf not in fields or fields[nf]['type'] != 'reference' or fields[nf]['target'] != 'system.user'):
            raise GraphError('notify_field must be a reference to a staff member')
        if not isinstance(w.get('message'), str) or not 5 <= len(w['message']) <= 400:
            raise GraphError('Rule message 5–400 characters')
    for c in pack.get('calculations', []):
        if not isinstance(c, dict) or c.get('type_key') not in types:
            raise GraphError('A pack formula must use a type from the same pack')
    return {'types': list(types), 'relations': [r['key'] for r in pack.get('relations', [])],
            'views': [v['key'] for v in pack.get('views', [])], 'reports': [r['key'] for r in pack.get('reports', [])],
            'workflows': [w['key'] for w in pack.get('workflows', [])],
            'calculations': [c['key'] for c in pack.get('calculations', [])]}


# ------------------------------------------------------------------ reading a sentence into a type's fields

MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}


def _norm(s) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(s).casefold()).strip()


def find_date(text: str, today: dt.date):
    low = text.casefold()
    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
    if m:
        try:
            return dt.date.fromisoformat(m.group(1)).isoformat(), m.group(1)
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', text)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(), m.group(0)
        except ValueError:
            pass
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(\d{4}))?\b', low)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            return dt.date(year, MONTHS[m.group(2)], int(m.group(1))).isoformat(), m.group(0)
        except ValueError:
            pass
    for word, delta in (('day after tomorrow', 2), ('yesterday', -1), ('tomorrow', 1), ('today', 0)):
        if re.search(r'\b' + word + r'\b', low):
            return (today + dt.timedelta(days=delta)).isoformat(), word
    m = re.search(r'\b(?:next|this coming)\s+(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b', low)
    if m:
        target = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].index(m.group(1))
        days = (target - today.weekday()) % 7 or 7
        return (today + dt.timedelta(days=days)).isoformat(), m.group(0)
    return None, None


def _words_of(f) -> set:
    words = set(_norm(f['name']).split()) | set(_norm(f.get('meaning', '')).split())
    return {w for w in words if len(w) > 2 and w not in {'the', 'and', 'for', 'with', 'date', 'name', 'who'}}


def coerce_text(f: dict, raw, today: dt.date, people=()):
    """A typed or tapped answer for one field, checked for its primitive. Raises GraphError."""
    typ = f['type']
    s = raw.strip() if isinstance(raw, str) else raw
    if s is None or s == '':
        raise GraphError('A value is needed')
    if typ == 'text':
        return str(s)[:8000]
    if typ == 'enum':
        match = [o for o in f['options'] if _norm(o) == _norm(s)] or [o for o in f['options'] if _norm(s) and _norm(s) in _norm(o)]
        if len(match) != 1:
            raise GraphError('Choose one of: ' + ', '.join(f['options']))
        return match[0]
    if typ == 'integer':
        if type(s) is int:
            return s
        m = re.fullmatch(r'-?\d{1,12}', str(s).replace(',', ''))
        if not m:
            raise GraphError('A whole number is needed')
        return int(m.group(0))
    if typ in ('decimal',):
        n = as_number(str(s).replace(',', '').strip()) if not isinstance(s, float) else None
        if n is None:
            raise GraphError('A number is needed')
        return str(n)
    if typ == 'money':
        n = as_number(re.sub(r'(?i)rs\.?|inr|₹|,', '', str(s)).strip()) if not isinstance(s, float) else None
        if n is None:
            raise GraphError('An amount in rupees is needed')
        return {'amount': str(n), 'currency': 'INR'}
    if typ == 'boolean':
        if isinstance(s, bool):
            return s
        if _norm(s) in ('yes', 'y', 'true', 'done', 'ok'):
            return True
        if _norm(s) in ('no', 'n', 'false', 'not done'):
            return False
        raise GraphError('Answer yes or no')
    if typ == 'date':
        iso, _ = find_date(str(s), today)
        if not iso:
            try:
                iso = resolve_date(str(s), today)
            except GraphError:
                raise GraphError('A date is needed, for example 2026-11-20, today or 20 Nov') from None
        return iso
    if typ == 'quantity':
        m = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*([A-Za-z0-9_/-]*)\s*', str(s))
        if not m:
            raise GraphError('A quantity is needed, for example 12 bags')
        unit = m.group(2) or (f['units'][0] if len(f['units']) == 1 else '')
        if unit not in f['units']:
            raise GraphError('Unit must be one of: ' + ', '.join(f['units']))
        return {'value': m.group(1), 'unit': unit}
    if typ == 'reference':
        if type(s) is int and s > 0:
            return s
        if isinstance(s, str) and re.fullmatch(r'[1-9]\d{0,9}', s):
            return int(s)          # a choice tapped on the card (its id)
        if f['target'] == 'system.user':
            hit = [p for p in people if _norm(s) in (_norm(p['name']), _norm(p.get('username', '')))] or \
                  [p for p in people if _norm(s) and _norm(s) in _norm(p['name'])]
            if len(hit) == 1:
                return hit[0]['id']
            raise GraphError('Choose the staff member from the list' if hit else 'No staff member by that name')
        raise GraphError('Choose from the list')
    raise GraphError('This kind of value cannot be typed')


def read_values(fields: list, text: str, today: dt.date, people=(), projects=(), title=''):
    """Fill what can be read with confidence; everything else stays empty and is asked.
    Returns (values, evidence, project_name)."""
    values, evidence = {}, {}
    spec = field_map(fields)
    low = text.casefold()
    # 1. explicit "label: value" parts
    for part in re.split(r'[;\n]|,(?=\s*[A-Za-z][A-Za-z _]{1,40}\s*[:=])', text):
        m = re.match(r'\s*([A-Za-z][A-Za-z _/]{1,40}?)\s*[:=]\s*(.+?)\s*$', part)
        if not m:
            continue
        label = _norm(m.group(1))
        f = next((x for x in fields if label in (_norm(x['name']), _norm(x.get('meaning', '')))), None) or \
            next((x for x in fields if label and set(label.split()) <= _words_of(x) | set(_norm(x['name']).split())), None)
        if f is None or f['name'] in values:
            continue
        try:
            values[f['name']] = coerce_text(f, m.group(2), today, people)
            evidence[f['name']] = m.group(0).strip()[:200]
        except GraphError:
            pass
    # 2. enum options named in the sentence (only when exactly one field offers that word)
    for f in fields:
        if f['type'] != 'enum' or f['name'] in values:
            continue
        hits = [o for o in f['options'] if re.search(r'(?<![a-z0-9])' + re.escape(o.casefold()) + r'(?![a-z0-9])', low)]
        if len(hits) == 1:
            others = [g for g in fields if g is not f and g['type'] == 'enum' and hits[0] in g['options']]
            if not others:
                values[f['name']] = hits[0]
                evidence[f['name']] = hits[0]
    # 3. staff named in the sentence -> first open staff reference (required first)
    named = [p for p in people if p.get('name') and re.search(r'\b' + re.escape(p['name'].casefold()) + r'\b', low)]
    if not named:
        named = [p for p in people if p.get('first') and re.search(r'\b' + re.escape(p['first'].casefold()) + r'\b', low)]
        if len({p['id'] for p in named}) != 1:
            named = []
    refs = sorted([f for f in fields if f['type'] == 'reference' and f['target'] == 'system.user' and f['name'] not in values],
                  key=lambda f: not f.get('required'))
    if named and refs and len({p['id'] for p in named}) == 1:
        values[refs[0]['name']] = named[0]['id']
        evidence[refs[0]['name']] = named[0]['name']
    # 4. one date in the sentence -> first open date field (required first)
    iso, words = find_date(text, today)
    dates = sorted([f for f in fields if f['type'] == 'date' and f['name'] not in values], key=lambda f: not f.get('required'))
    if iso and dates:
        values[dates[0]['name']] = iso
        evidence[dates[0]['name']] = words
    # 5. "6 hours", "hours 6", "₹4,500" next to a word of a numeric field
    for f in fields:
        if f['type'] not in ('integer', 'decimal', 'money') or f['name'] in values:
            continue
        for w in _words_of(f):
            stem = re.escape(w.rstrip('s'))
            m = re.search(r'(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*' + stem + r's?\b', low) or \
                re.search(r'\b' + stem + r's?\s*(?:of|:)?\s*(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\b', low)
            if m:
                try:
                    values[f['name']] = coerce_text(f, m.group(1), today, people)
                    evidence[f['name']] = m.group(0)
                    break
                except GraphError:
                    continue
    # 6. project named in the sentence
    project = None
    for name in sorted(projects, key=len, reverse=True):
        if re.search(r'\b' + re.escape(name.casefold()) + r'\b', low):
            project = name
            break
    # 7. the rest of the sentence -> the first required text field, marked as a guess
    texts = [f for f in fields if f['type'] == 'text' and f.get('required') and f['name'] not in values]
    if texts:
        rest = text
        for w in sorted(set(evidence.values()) | ({project} if project else set()) | {title}, key=lambda x: -len(str(x))):
            if w:
                rest = re.sub(re.escape(str(w)), ' ', rest, flags=re.I)
        rest = re.sub(r'^\s*(?:add|new|log|record|create|note)\b', ' ', rest, flags=re.I)
        rest = re.sub(r'\s+', ' ', rest).strip(' .,:;-')
        if len(rest) >= 3:
            values[texts[0]['name']] = rest[:8000]
            evidence[texts[0]['name']] = '(rest of the message)'
    return {k: v for k, v in values.items() if k in spec}, evidence, project
