"""The filter bar and the view builder (App Flows: Saved views).

Two things a person can do with a view without a ticket, because neither one stores anything:
* narrow a saved view with a temporary filter ("Match all" or "Match any" of a short list of conditions), and
* look at the same view as a table, a board or a calendar, when its fields allow it.

Both go through the same checks as a saved view (viewspec_core), then run through the permission-aware report engine, so a person only
ever sees records and fields they may see. A temporary filter is joined to the view's own filter with AND, so it can only narrow a view.
Saving a view, for yourself or for everyone, still goes through viewspec_rules and an approval ticket.

What the report engine can run is smaller than what a view may say (see viewspec_core.spec_to_report), so this module offers only what
can be run: no "me", no deeper nesting, and no operators the engine lacks."""
from __future__ import annotations

import copy
import json
import re

from . import graph_core as G
from . import viewspec_core as core

SWITCH_KEY = 'feature.view_builder'      # a setting, off until the owner turns it on (Config, like the AI provider choice)
MAX_FILTER_BYTES = 2000
MAX_CONDITIONS = 6
# Operators a person may use in the bar; each one has an equivalent in the report engine (core._OP_TO_REPORT).
RUNNABLE_OPS = ('eq', 'neq', 'in', 'contains', 'empty', 'not_empty', 'gt', 'gte', 'lt', 'lte', 'before', 'after')
RUNNABLE_BY_KIND = {kind: sorted(set(ops) & set(RUNNABLE_OPS)) for kind, ops in core.OPS_BY_KIND.items()}
RUNNABLE_BY_KIND['relation'] = ['empty', 'not_empty']      # matching one particular linked record is not supported by the runner yet
LOOKS = ('table', 'board', 'calendar')
LOOK_WORDS = {'table': 'Table', 'board': 'Board', 'calendar': 'Calendar'}
# Views the look can be switched on: a plain list of records. Charts, figures and feeds have no other look.
SWITCHABLE = ('table', 'list', 'board', 'calendar')
HIDDEN_TYPES = ('system.user',)          # staff accounts are not listed for building views


def enabled(db):
    from .db import Config
    row = db.get(Config, SWITCH_KEY)
    return bool(row and row.value == 'on')


def set_enabled(db, on, actor):
    """The owner's switch. It only shows or hides the screens; no view, record or filter is changed or removed."""
    from .db import Config, add_audit
    row = db.get(Config, SWITCH_KEY)
    if row:
        row.value = 'on' if on else 'off'
    else:
        db.add(Config(key=SWITCH_KEY, value='on' if on else 'off'))
    add_audit(db, 'update', 'setting', 0, f"Turned the filter bar and view builder {'on' if on else 'off'}", actor=actor)
    db.commit()
    return on


class FilterError(ValueError):
    """A plain-words reason, shown to the person as it is."""


def _plain(errors):
    first = errors[0]
    where = first['path'].replace('filter.', '').replace('and[', 'condition ').replace('or[', 'condition ').replace(']', '')
    return f"{where}: {first['message']}" if where and where != 'filter' else first['message']


def parse(text, catalog, record_type):
    """Text from the browser -> ('and' | 'or', [condition, ...]), or None for no filter. Raises FilterError.

    Accepted: one condition, or {"and": [conditions]} / {"or": [conditions]} with nothing nested inside. A condition is
    {field|path, op, value}; a date value may be a day, "today", "today-7", "week_start+6", "month_start" or {"relative": ...}."""
    if text is None or not str(text).strip():
        return None
    if len(str(text).encode('utf-8')) > MAX_FILTER_BYTES:
        raise FilterError('That filter is too long.')
    try:
        node = json.loads(text)
    except ValueError:
        raise FilterError('That filter could not be read.') from None
    if not isinstance(node, dict):
        raise FilterError('That filter could not be read.')
    mode, conds = 'and', [node]
    if set(node) in ({'and'}, {'or'}):
        mode = next(iter(node))
        conds = node[mode]
    if not isinstance(conds, list) or not 1 <= len(conds) <= MAX_CONDITIONS:
        raise FilterError(f'Use between 1 and {MAX_CONDITIONS} conditions.')
    for i, cond in enumerate(conds):
        if not isinstance(cond, dict) or set(cond) & {'and', 'or'}:
            raise FilterError('Groups inside a group are not supported here.')
        check = core._Check()
        core._check_filter(check, 'filter', cond, catalog, record_type, 1)
        if check.errors:
            raise FilterError(f'Condition {i + 1}: ' + check.errors[0]['message'])
        if cond['op'] not in RUNNABLE_OPS:
            raise FilterError(f"Condition {i + 1}: {cond['op']} cannot be used in a filter bar.")
        leaf = core.resolve_path(catalog, record_type, cond.get('field', cond.get('path')))
        if cond['op'] not in RUNNABLE_BY_KIND.get(leaf['kind'], ()):
            raise FilterError(f"Condition {i + 1}: that cannot be used on a {leaf['kind']} field in a filter bar.")
        value = cond.get('value')
        if isinstance(value, dict) and 'relative' not in value:
            raise FilterError(f'Condition {i + 1}: "me" and view values cannot be used in a filter bar yet.')
    return mode, conds


def _joined(base, conds):
    parts = ([base] if base else []) + list(conds)
    return {'and': parts}


def branches(spec, parsed):
    """The specs to run: the view itself, or the view narrowed by the person's conditions. 'Match any' is one spec per condition."""
    if not parsed:
        return [spec]
    mode, conds = parsed
    if len(spec['source']['items']) != 1:
        raise core.Unsupported('a view over several record types cannot be filtered yet')
    groups = [conds] if mode == 'and' else [[c] for c in conds]
    out = []
    for group in groups:
        narrowed = copy.deepcopy(spec)
        item = narrowed['source']['items'][0]
        item['filter'] = _joined(item.get('filter'), group)
        out.append(narrowed)
    return out


# ------------------------------------------------------------------ looks

def _item_fields(spec, catalog):
    item = spec['source']['items'][0]
    out = []
    for f in item['fields']:
        name = f.get('field', '.'.join(f.get('path', [])))
        try:
            out.append((name, core.resolve_path(catalog, item['record_type'], f.get('field', f.get('path')))))
        except ValueError:
            continue
    return out


def look_spec(spec, look, catalog):
    """The same view shown as another look. Raises core.Unsupported with a plain reason when its fields cannot show that look."""
    if look not in LOOKS:
        raise core.Unsupported('That look is not available.')
    if spec['primitive'] not in SWITCHABLE:
        raise core.Unsupported('This view cannot be shown another way.')
    if len(spec['source']['items']) != 1:
        raise core.Unsupported('A view over several record types cannot be shown another way yet.')
    out = copy.deepcopy(spec)
    out['primitive'] = look
    fields = _item_fields(out, catalog)
    if look == 'table':
        out.pop('group', None)
        out.pop('layout', None)
        out.pop('aggregate', None)
    elif look == 'board':
        column = (out.get('group') or {}).get('columns', {}).get('field')
        if not column:
            column = next((n for n, f in fields if f['kind'] == 'select'), None) or next(
                (n for n, f in fields if f['kind'] == 'text' and n.endswith(('status', 'stage'))), None)
        if not column:
            raise core.Unsupported("This view has no status-like field, so it can't be shown as a board.")
        out['group'] = {'columns': {'field': column}}
        out.pop('layout', None)
        out.pop('aggregate', None)
    else:
        date_field = (out.get('layout') or {}).get('date_field')
        if not date_field:
            date_field = next((n for n, f in fields if f['kind'] == 'date'), None)
        if not date_field:
            raise core.Unsupported("This view has no date field, so it can't be shown as a calendar.")
        out['layout'] = {'date_field': date_field}
        out.pop('group', None)
        out.pop('aggregate', None)
    try:
        core.validate_spec(out, catalog)
    except core.SpecError:
        raise core.Unsupported("This view's fields can't be shown that way.") from None
    return out


def available_looks(spec, catalog):
    out = []
    for look in LOOKS:
        try:
            look_spec(spec, look, catalog)
            out.append(look)
        except core.Unsupported:
            continue
    return out


# ------------------------------------------------------------------ what the builder offers

def _words(name):
    return re.sub(r'[_.]+', ' ', name).strip().capitalize()


def builder_catalog(db, user):
    """Record types and fields this person may build on, with the operators each kind of field allows.
    Money fields are left out for roles that may not read money, the same rule the report engine applies when it runs."""
    from . import graph_query as gq
    from . import universal_engine as u
    full = gq.catalog(db)
    types = []
    for key, spec in G.SYSTEM_TYPES.items():
        if key in HIDDEN_TYPES:
            continue
        fields = [{'name': n, 'label': _words(n), 'kind': _kind(t)} for n, t in spec['attrs'].items()]
        types.append({'key': key, 'title': spec['title'], 'fields': fields})
    for key, rt in gq.universal_types(db).items():
        fields = []
        for f in (rt.design or {}).get('runtime_fields', []):
            if not u.can_read_field(user, f):
                continue
            item = {'name': f['name'], 'label': (f.get('meaning') or _words(f['name']))[:60], 'kind': _kind(f.get('type'))}
            if f.get('options'):
                item['options'] = list(f['options'])
            fields.append(item)
        types.append({'key': key, 'title': full['types'][key]['title'], 'fields': fields})
    return {'types': [t for t in types if t['fields']], 'operators': RUNNABLE_BY_KIND,
            'dates': ['today', 'week_start', 'week_start+6', 'month_start'], 'looks': list(LOOKS),
            'limits': {'conditions': MAX_CONDITIONS, 'fields': core.MAX_FIELDS}}


_KINDS = {'text': 'text', 'integer': 'number', 'decimal': 'number', 'money': 'number', 'quantity': 'number', 'date': 'date',
          'datetime': 'date', 'enum': 'select', 'boolean': 'boolean', 'reference': 'relation'}


def _kind(t):
    return _KINDS.get(t, 'text')
