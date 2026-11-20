"""ViewSpec v1 core: valid and invalid specs, fit rules, closed operator set, size limits, deterministic diff, migration of a v0.12
report, and a fuzz that no input crashes the validator or lets markup through. Fictional catalog."""
import copy
import json
import random

import pytest

from studioos import viewspec_core as v

CATALOG = {
    'snag': {'title': {'kind': 'text'}, 'status': {'kind': 'select', 'options': ['open', 'fixed', 'closed']}, 'trade': {'kind': 'select'},
             'due_date': {'kind': 'date'}, 'reported_on': {'kind': 'date'}, 'photos': {'kind': 'image'}, 'cost_paise': {'kind': 'number'},
             'project': {'kind': 'relation', 'target': 'project'}, 'assignee': {'kind': 'text'}, 'tasks': {'kind': 'relation', 'target': 'task'},
             'priority': {'kind': 'select'}},
    'project': {'name': {'kind': 'text'}, 'client': {'kind': 'relation', 'target': 'client'}, 'stage': {'kind': 'select'}},
    'client': {'name': {'kind': 'text'}},
    'task': {'title': {'kind': 'text'}, 'status': {'kind': 'select'}, 'due_date': {'kind': 'date'}, 'project': {'kind': 'relation', 'target': 'project'}},
}


def board():
    return {
        'spec_version': 1, 'id': 'tpl.snag_board', 'name': 'Snags by status', 'labels': {'hi': 'Snag sthiti'}, 'primitive': 'board',
        'source': {'items': [{'record_type': 'snag',
                              'fields': [{'field': 'title'}, {'field': 'photos', 'show': 'cover'}, {'path': ['project', 'name']},
                                         {'field': 'assignee'}, {'field': 'tasks', 'show': 'count'}],
                              'filter': {'and': [{'field': 'status', 'op': 'not_in', 'value': ['closed']},
                                                 {'field': 'project', 'op': 'eq', 'value': {'param': 'project_id'}}]},
                              'sort': [{'field': 'due_date', 'dir': 'asc'}]}],
                   'context': {'param': 'project_id', 'record_type': 'project', 'optional': True}},
        'group': {'columns': {'field': 'status'}, 'rows': {'field': 'trade'}, 'hide_empty': True},
        'colour': [{'when': {'field': 'due_date', 'op': 'before', 'value': {'relative': 'today'}}, 'token': 'danger'},
                   {'when': {'field': 'priority', 'op': 'eq', 'value': 'high'}, 'token': 'warning'}],
        'aggregate': [{'fn': 'count', 'as': 'n'}],
        'relations': [{'via': 'tasks', 'primitive': 'list', 'limit': 5}],
        'layout': {'card': 'compact', 'density': 'comfortable'},
        'actions': ['open', 'quick_add', 'move_status', 'add_photo'],
        'mobile': {'primary_fields': ['title', 'photos', 'due_date']},
        'audience': {'roles': ['admin', 'manager', 'site_engineer']},
    }


def errs(spec):
    with pytest.raises(v.SpecError) as e:
        v.validate_spec(spec, CATALOG)
    return e.value.errors


def test_the_plans_example_board_is_valid():
    assert v.validate_spec(board(), CATALOG) is not None


def mutate(fn):
    s = board()
    fn(s)
    return s


def _deep_filter():
    return {'and': [{'and': [{'and': [{'and': [{'and': [{'field': 'title', 'op': 'empty'}]}]}]}]}]}


BAD = [
    ('unknown top key', lambda s: s.update(script='x'), 'script'),
    ('missing name', lambda s: s.pop('name'), 'name'),
    ('wrong version', lambda s: s.update(spec_version=2), 'spec_version'),
    ('bad id', lambda s: s.update(id='Bad Id'), 'id'),
    ('unknown primitive', lambda s: s.update(primitive='map'), 'primitive'),
    ('control characters in a name', lambda s: s.update(name='a\x00b'), 'name'),
    ('empty items', lambda s: s['source'].update(items=[]), 'source.items'),
    ('too many items', lambda s: s['source'].update(items=[s['source']['items'][0]] * 5), 'source.items'),
    ('unknown record type', lambda s: s['source']['items'][0].update(record_type='ghost'), 'record_type'),
    ('unknown field', lambda s: s['source']['items'][0]['fields'].append({'field': 'ghost'}), 'ghost'),
    ('both field and path', lambda s: s['source']['items'][0]['fields'].append({'field': 'title', 'path': ['title']}), 'either field or path'),
    ('three hops', lambda s: s['source']['items'][0]['fields'].append({'path': ['project', 'client', 'name', 'x']}), 'up to 2'),
    ('path through a non-relation', lambda s: s['source']['items'][0]['fields'].append({'path': ['title', 'name']}), 'not a relation'),
    ('cover on a text field', lambda s: s['source']['items'][0]['fields'].append({'field': 'title', 'show': 'cover'}), 'cover needs an image'),
    ('count on a text field', lambda s: s['source']['items'][0]['fields'].append({'field': 'title', 'show': 'count'}), 'relation field'),
    ('too many fields', lambda s: s['source']['items'][0].update(fields=[{'field': 'title'}] * 41), 'fields'),
    ('operator not in the set', lambda s: s['source']['items'][0]['filter']['and'].append({'field': 'status', 'op': 'regex', 'value': '.*'}), 'operator'),
    ('operator wrong for kind', lambda s: s['source']['items'][0]['filter']['and'].append({'field': 'status', 'op': 'gt', 'value': 1}), 'cannot be used'),
    ('expression as value', lambda s: s['source']['items'][0]['filter']['and'].append({'field': 'title', 'op': 'eq', 'value': {'expr': '1+1'}}), 'value'),
    ('bad relative', lambda s: s['source']['items'][0]['filter']['and'].append({'field': 'due_date', 'op': 'after', 'value': {'relative': 'someday'}}), 'value'),
    ('value with empty op', lambda s: s['source']['items'][0]['filter']['and'].append({'field': 'title', 'op': 'empty', 'value': 'x'}), 'not used'),
    ('filter too deep', lambda s: s['source']['items'][0].update(filter=_deep_filter()), 'nest'),
    ('empty and', lambda s: s['source']['items'][0].update(filter={'and': []}), 'conditions'),
    ('sort on a ghost field', lambda s: s['source']['items'][0].update(sort=[{'field': 'ghost'}]), 'sort'),
    ('group by an amount', lambda s: s['group'].update(rows={'field': 'cost_paise'}), 'not by an amount'),
    ('group on a ghost', lambda s: s['group'].update(columns={'field': 'ghost'}), 'group.columns'),
    ('bad colour token', lambda s: s['colour'][0].update(token='#ff0000'), 'token'),
    ('too many colour rules', lambda s: s.update(colour=[s['colour'][0]] * 11), 'colour'),
    ('sum of text', lambda s: s.update(aggregate=[{'fn': 'sum', 'field': 'title', 'as': 'x'}]), 'number'),
    ('unknown agg', lambda s: s.update(aggregate=[{'fn': 'median', 'as': 'x'}]), 'fn'),
    ('relation via a non-relation', lambda s: s.update(relations=[{'via': 'title', 'primitive': 'list'}]), 'relation field'),
    ('relation limit', lambda s: s.update(relations=[{'via': 'tasks', 'primitive': 'list', 'limit': 99}]), 'limit'),
    ('layout date field not a date', lambda s: s['layout'].update(date_field='title'), 'date field'),
    ('bad action', lambda s: s.update(actions=['delete_everything']), 'actions'),
    ('bad role', lambda s: s.update(audience={'roles': ['root']}), 'roles'),
    ('mobile field ghost', lambda s: s['mobile'].update(primary_fields=['ghost']), 'ghost'),
    ('context type ghost', lambda s: s['source']['context'].update(record_type='ghost'), 'record_type'),
]


@pytest.mark.parametrize('name,fn,text', BAD, ids=[b[0] for b in BAD])
def test_invalid_specs_are_refused_with_a_useful_message(name, fn, text):
    found = errs(mutate(fn))
    assert any(text in (e['path'] + ' ' + e['message']) for e in found), found


def test_fit_rules():
    s = board()
    s['group'] = {'columns': {'field': 'due_date'}}
    assert any('board needs' in e['message'] for e in errs(s))                    # a date is not a column to group a board by
    s['group'] = {'columns': {'field': 'title'}}
    assert v.validate_spec(s, CATALOG)                                           # a text field can be (the report engine groups boards by text)
    for prim, text in [('calendar', 'date_field'), ('timeline', 'start_field'), ('chart', 'aggregate'), ('record', 'exactly one')]:
        s = board()
        s['primitive'] = prim
        s.pop('layout')
        s['aggregate'] = []
        s['source']['items'] = s['source']['items'] * (2 if prim == 'record' else 1)
        assert any(text in e['message'] for e in errs(s)), prim
    s = board()
    s['primitive'] = 'calendar'
    s['layout'] = {'date_field': 'due_date'}
    assert v.validate_spec(s, CATALOG)
    s = board()
    s['primitive'] = 'gallery'
    assert v.validate_spec(s, CATALOG)                                            # it has an image field
    s['source']['items'][0]['fields'] = [{'field': 'title'}]
    assert any('image field' in e['message'] for e in errs(s))
    assert 'board' in v.fitting_primitives(board(), CATALOG) and 'calendar' not in v.fitting_primitives(board(), CATALOG)


def test_items_shown_together_must_group_by_the_same_kind():
    s = board()
    s['source']['items'].append({'record_type': 'task', 'fields': [{'field': 'title'}]})
    s['group'] = {'columns': {'field': 'status'}}
    assert v.validate_spec(s, CATALOG)                                            # both are option fields
    s['group'] = {'columns': {'field': 'project'}}
    s['source']['items'][0]['fields'] = [{'field': 'title'}]
    assert v.validate_spec(s, CATALOG)                                            # both relate to the same type
    s['source']['items'].append({'record_type': 'project', 'fields': [{'field': 'name'}]})
    assert any('group.columns' in e['path'] for e in errs(s))                     # project has no field called project


def test_size_limit_and_read_permission():
    s = board()
    s['source']['items'][0]['filter'] = {'and': [{'field': 'title', 'op': 'in', 'value': ['y' * 190] * 50}] * 6}
    assert any('KB' in e['message'] for e in errs(s))
    with pytest.raises(v.SpecError) as e:
        v.validate_spec(board(), CATALOG, readable=lambda rt, f: f not in ('cost_paise', 'assignee'))
    assert 'snag.assignee' in str(e.value)
    assert v.validate_spec(board(), CATALOG, readable=lambda rt, f: True)


def test_diff_is_deterministic_and_structural():
    a, b = board(), board()
    b['group']['rows'] = {'field': 'priority'}
    b['actions'].append('comment')
    b['colour'].pop()
    assert v.diff_specs(a, b) == v.diff_specs(copy.deepcopy(a), copy.deepcopy(b))
    d = v.diff_specs(a, b)
    assert "changed group.rows.field: 'trade' -> 'priority'" in d and "added actions[4]: 'comment'" in d
    assert any(x.startswith('removed colour[1]') for x in d)
    assert v.diff_specs(a, a) == [] and all(x.startswith('added ') for x in v.diff_specs(None, a))
    assert v.spec_hash(a) == v.spec_hash(copy.deepcopy(a)) != v.spec_hash(b)


def test_migrating_a_v012_report():
    report = {'key': 'open_snags', 'title': 'Open snags', 'base': 'snag', 'columns': ['title', 'due_date', 'project.name'],
              'filters': [{'path': 'status', 'op': 'ne', 'value': 'closed'}], 'limit': 200}
    cal = v.from_report(report, {'kind': 'calendar', 'date_column': 1})
    assert cal['primitive'] == 'calendar' and cal['layout'] == {'date_field': 'due_date'} and cal['id'] == 'report.open_snags'
    v.validate_spec(cal, CATALOG)
    brd = v.from_report({**report, 'columns': ['title', 'status']}, {'kind': 'board', 'column': 1})
    v.validate_spec(brd, CATALOG)
    chart = v.from_report({'key': 'by_trade', 'title': 'Snags by trade', 'base': 'snag', 'group_by': ['trade'], 'measures': [{'agg': 'count'}]},
                          {'kind': 'bar', 'measure': 0})
    assert chart['primitive'] == 'chart' and v.validate_spec(chart, CATALOG)
    with pytest.raises(ValueError):
        v.from_report({**report, 'filters': [{'path': 'status', 'op': 'weird'}]})


def test_fuzz_never_crashes_and_markup_is_only_ever_data():
    rng = random.Random(7)
    pool = [None, 0, 1.5, 'x', '<script>alert(1)</script>', [], {}, [1], {'a': 1}, True, 'status', 'snag', {'param': 'p'}, 10 ** 12, 'a' * 500]

    def wreck(o):
        if isinstance(o, dict) and o and rng.random() < 0.5:
            k = rng.choice(list(o))
            o[k] = rng.choice(pool) if rng.random() < 0.5 else wreck(o[k])
        elif isinstance(o, list) and o and rng.random() < 0.5:
            i = rng.randrange(len(o))
            o[i] = rng.choice(pool) if rng.random() < 0.5 else wreck(o[i])
        return o
    for _ in range(300):
        s = wreck(copy.deepcopy(board()))
        try:
            v.validate_spec(s, CATALOG)
        except v.SpecError:
            pass                                                                    # refused is fine; any other exception would be a crash
    s = board()
    s['name'] = '<script>alert(1)</script>'
    assert v.validate_spec(s, CATALOG)['name'] == '<script>alert(1)</script>'      # labels are data; the renderer must use textContent
    json.dumps(v.validate_spec(board(), CATALOG))
