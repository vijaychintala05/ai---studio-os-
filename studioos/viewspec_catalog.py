"""Adapter: the record-type catalog the views engine already has (graph_query.catalog) -> the simple catalog ViewSpec checks against.

{record_type: {field: {'kind': 'text|number|date|select|boolean|relation|image', 'target': type (relations), 'options': [...]}}}
Tasks, projects and the other built-in types are included with the fields graph_core knows for them."""
from __future__ import annotations

from . import graph_core as G

_KIND = {'text': 'text', 'integer': 'number', 'decimal': 'number', 'money': 'number', 'quantity': 'number', 'date': 'date',
         'datetime': 'date', 'enum': 'select', 'boolean': 'boolean', 'reference': 'relation'}


def _field(f):
    out = {'kind': _KIND.get(f.get('type'), 'text')}
    if out['kind'] == 'relation' and f.get('target'):
        out['target'] = f['target']
    if f.get('options'):
        out['options'] = list(f['options'])
    return out


def from_graph(cat):
    out = {}
    for key, spec in G.SYSTEM_TYPES.items():
        out[key] = {name: {'kind': _KIND.get(t, 'text')} for name, t in (spec.get('attrs') or {}).items()}
    for key, t in cat['types'].items():
        out[key] = {name: _field(f) for name, f in t['fields'].items()}
    return out


def for_db(db):
    from . import graph_query as gq
    return from_graph(gq.catalog(db))
