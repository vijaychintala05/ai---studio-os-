"""v0.11.0 Phase 0, database-free part (standard library only; runs without the web app).

1. Own records: a type's ``self_read`` option lets the staff member a record names read it
   (attendance, leave, a weekly review once shared). Nobody else gains anything from it.
2. Links that start at a task or a staff member: accepted by the pack checker and the path
   compiler, refused where they make no sense (order_by on a system source).
All data is fictional.
"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('graph_core', ROOT / 'studioos' / 'graph_core.py')
G = importlib.util.module_from_spec(spec)
sys.modules['graph_core'] = G
spec.loader.exec_module(G)

TODAY = dt.date(2026, 11, 14)
PEOPLE = json.loads((ROOT / 'studioos' / 'business_packs' / 'people.json').read_text())
TYPES = {t['key']: t for t in PEOPLE['types']}


def test_people_pack_types_name_the_employee_for_self_read():
    for key in ('employee_profile', 'attendance_entry', 'leave_request', 'weekly_review'):
        assert TYPES[key]['self_read']['field'] == 'employee'
    G.check_pack(PEOPLE)   # still consistent with the option added


def test_self_read_lets_only_the_named_person_read():
    t = TYPES['attendance_entry']
    opt = t['self_read']
    values = {'employee': 7, 'attendance_date': '2026-11-13', 'attendance_status': t['fields'][2]['options'][0]}
    assert G.self_read_allows(opt, values, 7, t['fields'], TODAY) is True
    assert G.self_read_allows(opt, values, 8, t['fields'], TODAY) is False      # another staff member
    assert G.self_read_allows(opt, values, None, t['fields'], TODAY) is False
    assert G.self_read_allows(opt, values, '7', t['fields'], TODAY) is False    # ids are whole numbers only
    assert G.self_read_allows(opt, {'employee': None}, 7, t['fields'], TODAY) is False
    assert G.self_read_allows(None, values, 7, t['fields'], TODAY) is False      # type without the option


def test_weekly_review_is_readable_only_once_shared():
    t = TYPES['weekly_review']
    opt = t['self_read']
    statuses = next(f for f in t['fields'] if f['name'] == 'review_status')['options']
    for status in statuses:
        shared = status in ('Shared with employee', 'Acknowledged')
        assert G.self_read_allows(opt, {'employee': 7, 'review_status': status}, 7, t['fields'], TODAY) is shared
    assert G.self_read_allows(opt, {'employee': 7}, 7, t['fields'], TODAY) is False   # no status yet: draft


def test_self_read_option_is_checked():
    fields = TYPES['leave_request']['fields']
    for bad in ({'field': 'reason'},                     # a text field, not a staff reference
                {'field': 'nobody'},
                {'field': 'employee', 'extra': 1},
                {'when': None},
                'employee',
                {'field': 'employee', 'when': {'field': 'nope', 'op': 'eq', 'value': 'x'}}):
        with pytest.raises(G.GraphError):
            G.check_self_read(bad, fields)
    assert G.check_self_read({'field': 'employee'}, fields) == {'field': 'employee'}
    # A reference to a project is not a staff member.
    with pytest.raises(G.GraphError):
        G.check_self_read({'field': 'site'}, [{'name': 'site', 'type': 'reference', 'target': 'system.project'}])
    # Through the type checker too.
    with pytest.raises(G.GraphError):
        G.check_type_options({'fields': fields, 'self_read': {'field': 'reason'}})


def _pack(relations):
    return {'key': 'tiny', 'title': 'Tiny', 'version': 1,
            'types': [{'key': 'site_check', 'title': 'Site check',
                       'fields': [{'name': 'note', 'type': 'text', 'required': True}]}],
            'relations': relations}


def test_links_may_start_at_a_task_or_a_staff_member():
    out = G.check_pack(_pack([
        {'key': 'task_needs_check', 'source_type': 'system.task', 'target_type': 'site_check'},
        {'key': 'staff_trained_on', 'source_type': 'system.user', 'target_type': 'site_check', 'cardinality': 'many'},
        {'key': 'task_for_project', 'source_type': 'system.task', 'target_type': 'system.project', 'cardinality': 'one'}]))
    assert out['relations'] == ['task_needs_check', 'staff_trained_on', 'task_for_project']


def test_other_system_kinds_cannot_start_a_link_and_order_by_needs_a_record_type():
    for src in ('system.project', 'system.client', 'system.supplier', 'system.document', 'nothing'):
        with pytest.raises(G.GraphError):
            G.check_pack(_pack([{'key': 'bad_link', 'source_type': src, 'target_type': 'site_check'}]))
    with pytest.raises(G.GraphError):
        G.check_pack(_pack([{'key': 'bad_order', 'source_type': 'system.task', 'target_type': 'site_check',
                             'order_by': 'note'}]))


def test_paths_follow_links_from_tasks_both_ways():
    catalog = G.catalog_from({'site_check': {'title': 'Site check', 'fields': [{'name': 'note', 'type': 'text'}]}},
                             {'task_needs_check': {'source_type': 'system.task', 'target_type': 'site_check'}})
    out = G.compile_path(catalog, 'system.task', '@task_needs_check.note')
    assert out['steps'][0] == ('out', 'task_needs_check', 'site_check')
    back = G.compile_path(catalog, 'site_check', '~task_needs_check.title')
    assert back['steps'][0] == ('in', 'task_needs_check', 'system.task')
    with pytest.raises(G.GraphError):
        G.compile_path(catalog, 'site_check', '@task_needs_check.note')   # does not start at a site check
