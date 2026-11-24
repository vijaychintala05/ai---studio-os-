"""v0.10.0 'One graph': the database-free core (standard library only; runs without the web app).

Covers: field specs with references, relative dates, rule conditions, the report planner over
references and links in both directions with grouping and exact sums, the three business
packs, Stage A conversion, and the offline sentence reader. All data is fictional.
"""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('graph_core', ROOT / 'studioos' / 'graph_core.py')
G = importlib.util.module_from_spec(spec)
sys.modules['graph_core'] = G
spec.loader.exec_module(G)

TODAY = dt.date(2026, 11, 14)          # a Saturday
PACKS = {p.stem: json.loads(p.read_text()) for p in (ROOT / 'studioos' / 'business_packs').glob('*.json')}


# ------------------------------------------------------------------ a stand-in for the database

class Resolver:
    """Nodes and links in memory, shaped exactly as graph_query hands them to the planner."""

    def __init__(self, records, users, tasks, projects, edges, catalog):
        self.records, self.users, self.tasks, self.projects, self.edges = records, users, tasks, projects, edges
        self.catalog = catalog

    def node(self, kind, obj_id):
        if kind == 'system.user':
            u = self.users[obj_id]
            return {'type': kind, 'id': obj_id, 'values': u, 'label': u['display_name']}
        if kind == 'system.task':
            t = self.tasks[obj_id]
            return {'type': kind, 'id': obj_id, 'values': t, 'label': t['title'], 'project_id': t['project_id']}
        if kind == 'system.project':
            p = self.projects[obj_id]
            return {'type': kind, 'id': obj_id, 'values': p, 'label': p['name']}
        r = self.records[obj_id]
        t = self.catalog['types'][r['type']]
        lf = t.get('label_field')
        label = r['values'].get(lf) if lf else None
        if lf and t['fields'][lf]['type'] == 'reference' and label is not None:
            label = self.node(t['fields'][lf]['target'], label)['label']
        return {'type': r['type'], 'id': obj_id, 'values': r['values'], 'label': str(label or f'#{obj_id}'),
                'project_id': r.get('project_id')}

    def base_rows(self, base):
        if base == 'system.task':
            return [self.node(base, i) for i in self.tasks]
        return [self.node(base, i) for i, r in self.records.items() if r['type'] == base]

    def follow(self, node, step):
        if step[0] == 'ref':
            v = (node.get('values') or {}).get(step[1])
            return [self.node(step[2], v)] if v is not None else []
        if step[0] == 'project':
            return [self.node('system.project', node['project_id'])] if node.get('project_id') else []
        if step[0] == 'out':
            return [self.node(step[2], e['target']) for e in self.edges if e['rel'] == step[1] and e['source'] == node['id']]
        if step[0] == 'in':
            return [self.node(step[2], e['source']) for e in self.edges
                    if e['rel'] == step[1] and e['target'] == node['id'] and e.get('target_kind', 'record') == ('record' if node['type'] not in G.SYSTEM_TYPES else node['type'])]
        raise AssertionError(step)


def safety_catalog():
    """A type StudioOS has never seen, plus corrective actions linked to it."""
    types = {
        'site_safety_inspection': {'title': 'Site Safety Inspection', 'label_field': 'site_location', 'fields': [
            {'name': 'inspection_date', 'type': 'date', 'required': True},
            {'name': 'site_location', 'type': 'text', 'required': True},
            {'name': 'severity', 'type': 'enum', 'required': True, 'options': ['Low', 'Medium', 'High']},
            {'name': 'inspector', 'type': 'reference', 'target': 'system.user', 'required': True}]},
        'corrective_action': {'title': 'Corrective Action', 'label_field': 'action_text', 'fields': [
            {'name': 'action_text', 'type': 'text', 'required': True},
            {'name': 'responsible', 'type': 'reference', 'target': 'system.user', 'required': True},
            {'name': 'deadline', 'type': 'date', 'required': False},
            {'name': 'action_status', 'type': 'enum', 'required': True, 'options': ['Open', 'Done']},
            {'name': 'cost', 'type': 'money', 'required': False}]},
    }
    rels = {'action_from_inspection': {'source_type': 'corrective_action', 'target_type': 'site_safety_inspection'}}
    for t in types.values():
        G.check_field_specs(t['fields'], known_targets=set(types))
    return G.catalog_from(types, rels)


def safety_world():
    cat = safety_catalog()
    users = {1: {'display_name': 'Asha Rao', 'username': 'asha', 'role': 'site_engineer'},
             2: {'display_name': 'Ravi Kumar', 'username': 'ravi', 'role': 'architect'}}
    projects = {10: {'name': 'Fictional Tower', 'stage': 'execution'}, 11: {'name': 'Fictional Villa', 'stage': 'handover'}}
    records = {
        100: {'type': 'site_safety_inspection', 'project_id': 10, 'values': {'inspection_date': '2026-11-10', 'site_location': 'Tower B L3', 'severity': 'High', 'inspector': 1}},
        101: {'type': 'site_safety_inspection', 'project_id': 11, 'values': {'inspection_date': '2026-11-11', 'site_location': 'Villa deck', 'severity': 'Low', 'inspector': 2}},
        102: {'type': 'site_safety_inspection', 'project_id': 11, 'values': {'inspection_date': '2026-11-12', 'site_location': 'Villa stairs', 'severity': 'High', 'inspector': 2}},
        200: {'type': 'corrective_action', 'project_id': 10, 'values': {'action_text': 'Fit toe boards', 'responsible': 1, 'deadline': '2026-11-12', 'action_status': 'Open', 'cost': {'amount': '4500.50', 'currency': 'INR'}}},
        201: {'type': 'corrective_action', 'project_id': 10, 'values': {'action_text': 'Replace net', 'responsible': 2, 'deadline': '2026-11-20', 'action_status': 'Open', 'cost': {'amount': '1200.25', 'currency': 'INR'}}},
        202: {'type': 'corrective_action', 'project_id': 11, 'values': {'action_text': 'Sand deck', 'responsible': 2, 'action_status': 'Open'}},
        203: {'type': 'corrective_action', 'project_id': 11, 'values': {'action_text': 'Add handrail', 'responsible': 2, 'action_status': 'Open', 'cost': {'amount': '0.25', 'currency': 'INR'}}},
        204: {'type': 'corrective_action', 'project_id': 10, 'values': {'action_text': 'Old item', 'responsible': 1, 'action_status': 'Done'}},
    }
    edges = [{'rel': 'action_from_inspection', 'source': 200, 'target': 100},
             {'rel': 'action_from_inspection', 'source': 201, 'target': 100},
             {'rel': 'action_from_inspection', 'source': 202, 'target': 101},
             {'rel': 'action_from_inspection', 'source': 203, 'target': 102},
             {'rel': 'action_from_inspection', 'source': 204, 'target': 100}]
    return cat, Resolver(records, users, {}, projects, edges, cat)


# ------------------------------------------------------------------ fields and dates

def test_reference_fields_need_a_known_target():
    G.check_field_specs([{'name': 'inspector', 'type': 'reference', 'target': 'system.user'}])
    G.check_field_specs([{'name': 'parent', 'type': 'reference', 'target': 'inspection'}], own_key='inspection')
    with pytest.raises(G.GraphError, match='reference target'):
        G.check_field_specs([{'name': 'xy', 'type': 'reference', 'target': 'system.passwords'}])
    with pytest.raises(G.GraphError, match='target'):
        G.check_field_specs([{'name': 'xy', 'type': 'text', 'target': 'system.user'}])
    with pytest.raises(G.GraphError, match='reserved'):
        G.check_field_specs([{'name': 'system_x', 'type': 'text'}])
    with pytest.raises(G.GraphError, match='redefined'):
        G.check_field_specs([{'name': 'status', 'type': 'text'}])


def test_type_options_cannot_widen_security():
    G.check_type_options({'approver_roles': ['manager'], 'company_read_roles': ['site_engineer']})
    with pytest.raises(G.GraphError):
        G.check_type_options({'approver_roles': ['site_engineer']})
    with pytest.raises(G.GraphError):
        G.check_type_options({'company_propose_roles': ['viewer']})
    with pytest.raises(G.GraphError):
        G.check_type_options({'company_read_roles': ['root']})


def test_relative_dates():
    assert G.resolve_date('today', TODAY) == '2026-11-14'
    assert G.resolve_date('today-7', TODAY) == '2026-11-07'
    assert G.resolve_date('today+30', TODAY) == '2026-12-14'
    assert G.resolve_date('week_start', TODAY) == '2026-11-09'
    assert G.resolve_date('month_start', TODAY) == '2026-11-01'
    assert G.resolve_date('2026-02-28', TODAY) == '2026-02-28'
    for bad in ('yesterday', 'today*2', '2026-13-01', 5):
        with pytest.raises(G.GraphError):
            G.resolve_date(bad, TODAY)


def test_rule_conditions():
    fields = G.field_map([{'name': 'due_date', 'type': 'date'}, {'name': 'issue_status', 'type': 'enum', 'options': ['Open', 'Closed']},
                          {'name': 'hours', 'type': 'decimal'}])
    overdue = {'all': [{'field': 'due_date', 'op': 'before_today'}, {'field': 'issue_status', 'op': 'in', 'value': ['Open']}]}
    assert G.condition_matches(overdue, {'due_date': '2026-11-13', 'issue_status': 'Open'}, fields, TODAY)
    assert not G.condition_matches(overdue, {'due_date': '2026-11-14', 'issue_status': 'Open'}, fields, TODAY)
    assert not G.condition_matches(overdue, {'due_date': '2026-11-01', 'issue_status': 'Closed'}, fields, TODAY)
    assert not G.condition_matches(overdue, {'issue_status': 'Open'}, fields, TODAY)       # no date never fires
    soon = {'field': 'due_date', 'op': 'within_days', 'value': 3}
    assert G.condition_matches(soon, {'due_date': '2026-11-17'}, fields, TODAY)
    assert not G.condition_matches(soon, {'due_date': '2026-11-18'}, fields, TODAY)
    assert G.condition_matches({'field': 'hours', 'op': 'gte', 'value': '8'}, {'hours': '8.00'}, fields, TODAY)
    with pytest.raises(G.GraphError):
        G.check_condition({'field': 'hours', 'op': 'gte', 'value': 8.5}, fields)        # floats refused
    with pytest.raises(G.GraphError):
        G.check_condition({'field': 'issue_status', 'op': 'in', 'value': ['Maybe']}, fields)
    with pytest.raises(G.GraphError):
        G.check_condition({'all': [{'field': 'due_date', 'op': 'before_today'}] * 5}, fields)


# ------------------------------------------------------------------ reports (audit Test D)

def test_paths_follow_references_and_links_both_ways():
    cat = safety_catalog()
    c = G.compile_path(cat, 'corrective_action', '@action_from_inspection.severity')
    assert c['steps'] == [('out', 'action_from_inspection', 'site_safety_inspection')] and c['kind'] == 'enum'
    c = G.compile_path(cat, 'site_safety_inspection', '~action_from_inspection.responsible.display_name')
    assert [s[0] for s in c['steps']] == ['in', 'ref'] and c['leaf'] == ('attr', 'display_name')
    assert G.compile_path(cat, 'corrective_action', 'project.stage')['steps'] == [('project',)]
    assert G.compile_path(cat, 'corrective_action', 'responsible')['kind'] == 'label'
    for bad in ('nope', 'responsible.password_hash', 'action_text.x', '@action_from_inspection.~x.y', 'a.b.c.d.e'):
        with pytest.raises(G.GraphError):
            G.compile_path(cat, 'corrective_action', bad)


def test_audit_test_d_report_grouped_by_responsible_person():
    """'All outstanding high-severity corrective actions across active projects, grouped by responsible
    employee': follows a link, filters on the linked record and on the project, groups by a reference."""
    cat, res = safety_world()
    report = {'key': 'open_high_actions', 'title': 'Open high-severity actions',
              'base': 'corrective_action',
              'filters': [{'path': 'action_status', 'op': 'eq', 'value': 'Open'},
                          {'path': '@action_from_inspection.severity', 'op': 'eq', 'value': 'High'},
                          {'path': 'project.stage', 'op': 'ne', 'value': 'closed'}],
              'group_by': ['responsible'],
              'measures': [{'agg': 'count'}, {'agg': 'sum', 'path': 'cost', 'label': 'Cost'}]}
    out = G.run_report(res, cat, report, TODAY)
    assert out['mode'] == 'grouped' and out['matched'] == 3 and out['scanned'] == 5
    rows = {tuple(r['group']): r for r in out['rows']}
    assert rows[('Asha Rao',)]['values'] == ['1', '₹4,500.50']
    assert rows[('Ravi Kumar',)]['values'] == ['2', '₹1,200.50']     # 1200.25 + 0.25, exact
    assert sorted(rows[('Ravi Kumar',)]['record_ids']) == [201, 203]


def test_report_group_by_two_paths_and_list_mode():
    cat, res = safety_world()
    out = G.run_report(res, cat, {'key': 'by_proj', 'title': 'By project', 'base': 'corrective_action', 'filters': [],
                                  'group_by': ['project', 'action_status']}, TODAY)
    assert {tuple(r['group']): r['values'][0] for r in out['rows']} == {
        ('Fictional Tower', 'Done'): '1', ('Fictional Tower', 'Open'): '2', ('Fictional Villa', 'Open'): '2'}
    out = G.run_report(res, cat, {'key': 'late', 'title': 'Late', 'base': 'corrective_action',
                                  'filters': [{'path': 'deadline', 'op': 'before_today'}],
                                  'columns': ['action_text', 'responsible', '@action_from_inspection.site_location']}, TODAY)
    assert out['mode'] == 'list' and [r['cells'] for r in out['rows']] == [['Fit toe boards', 'Asha Rao', 'Tower B L3']]
    # incoming links: inspections with their actions counted
    out = G.run_report(res, cat, {'key': 'ins', 'title': 'Inspections', 'base': 'site_safety_inspection', 'filters': [
        {'path': '~action_from_inspection.action_status', 'op': 'eq', 'value': 'Open'}],
        'group_by': ['inspector'], 'measures': [{'agg': 'count'}], 'sort': 'measure_desc'}, TODAY)
    assert [r['group'][0] for r in out['rows']] == ['Ravi Kumar', 'Asha Rao']


def test_report_definitions_are_checked():
    cat = safety_catalog()
    base = {'key': 'r_one', 'title': 'Report', 'base': 'corrective_action'}
    bad = [
        {**base, 'group_by': ['cost']},                                          # group by an amount
        {**base, 'columns': []},                                                 # nothing to show
        {**base, 'group_by': ['responsible'], 'columns': ['action_text']},       # both
        {**base, 'group_by': ['responsible'], 'measures': [{'agg': 'sum', 'path': 'action_text'}]},
        {**base, 'columns': ['action_text'], 'filters': [{'path': 'cost', 'op': 'gt', 'value': 1.5}]},
        {**base, 'columns': ['action_text'], 'limit': 10000},
        {**base, 'base': 'system.user', 'columns': ['display_name']},            # staff cannot be listed
        {**base, 'columns': ['action_text'], 'sql': 'select 1'},
    ]
    for d in bad:
        with pytest.raises(G.GraphError):
            G.check_report(cat, d)


# ------------------------------------------------------------------ business packs

def test_the_three_packs_are_consistent():
    assert set(PACKS) == {'people', 'work', 'sops', 'client_portal'}   # client_portal added with the client portal; it goes through the same checks and the same safety scan below
    summary = {k: G.check_pack(p) for k, p in PACKS.items()}
    assert summary['people']['types'] == ['employee_profile', 'attendance_entry', 'leave_request', 'weekly_review']
    assert 'step_of_sop' in summary['sops']['relations'] and len(summary['sops']['reports']) == 5
    assert summary['work']['workflows'] == ['issue_assigned', 'critical_issue_raised', 'issue_overdue', 'milestone_overdue']
    # nothing in a pack may be executable or reach protected tables
    import re
    text = json.dumps(PACKS).casefold()
    for word in (r'\beval\b', r'\bexec\b', r'\bselect\s', r'\binsert\s', r'\bgl_', r'\bfinance_', '<script'):
        assert not re.search(word, text), word


def test_pack_install_twice_or_with_clashes_is_refused():
    with pytest.raises(G.GraphError, match='already exists'):
        G.check_pack(PACKS['work'], existing_types={'milestone'})
    broken = json.loads(json.dumps(PACKS['sops']))
    broken['relations'][0]['order_by'] = 'nonexistent'
    with pytest.raises(G.GraphError, match='order_by'):
        G.check_pack(broken)
    broken = json.loads(json.dumps(PACKS['people']))
    broken['workflows'][1]['notify_field'] = 'leave_type'
    with pytest.raises(G.GraphError, match='notify_field'):
        G.check_pack(broken)
    broken = json.loads(json.dumps(PACKS['people']))
    broken['types'][0]['approver_roles'] = ['site_engineer']
    with pytest.raises(G.GraphError):
        G.check_pack(broken)


def test_pack_reports_run_on_pack_data():
    pack = PACKS['work']
    types = {t['key']: t for t in pack['types']}
    rels = {r['key']: r for r in pack['relations']}
    cat = G.catalog_from(types, rels)
    users = {1: {'display_name': 'Asha Rao'}, 2: {'display_name': 'Ravi Kumar'}}
    tasks = {7: {'title': 'Kitchen drawings', 'assignee': 'Ravi', 'status': 'open', 'project_id': 10},
             8: {'title': 'Site measure', 'assignee': 'Asha', 'status': 'done', 'project_id': 10}}
    records = {
        1: {'type': 'timesheet_entry', 'project_id': 10, 'values': {'employee': 2, 'work_date': '2026-11-10', 'hours': '6.50', 'activity': 'Drawings', 'task': 7}},
        2: {'type': 'timesheet_entry', 'project_id': 10, 'values': {'employee': 2, 'work_date': '2026-11-13', 'hours': '2.25', 'activity': 'Client meeting'}},
        3: {'type': 'timesheet_entry', 'project_id': 10, 'values': {'employee': 1, 'work_date': '2026-11-12', 'hours': '8', 'activity': 'Site supervision'}},
        4: {'type': 'timesheet_entry', 'project_id': 10, 'values': {'employee': 1, 'work_date': '2026-11-06', 'hours': '9', 'activity': 'Site supervision'}},
    }
    res = Resolver(records, users, tasks, {10: {'name': 'Fictional Tower'}}, [], cat)
    rep = next(r for r in pack['reports'] if r['key'] == 'hours_this_week')
    out = G.run_report(res, cat, rep, TODAY)
    assert [(r['group'][0], r['values']) for r in out['rows']] == [('Ravi Kumar', ['8.75', '2']), ('Asha Rao', ['8', '1'])]
    rep = next(r for r in pack['reports'] if r['key'] == 'open_tasks_by_assignee')
    out = G.run_report(res, cat, rep, TODAY)
    assert [r['group'] for r in out['rows']] == [['Ravi', 'Fictional Tower']]


# ------------------------------------------------------------------ one registry

def test_stage_a_designs_become_universal_fields():
    design = {'fields': [
        {'name': 'id', 'type': 'integer', 'universal': True},
        {'name': 'visit_date', 'type': 'date', 'required_level': 'draft', 'meaning': 'Visit date'},
        {'name': 'rating', 'type': 'integer', 'required_level': 'approve'},
        {'name': 'comments', 'type': 'text', 'description': 'As supplied: comments'},
        {'name': 'mood', 'type': 'text', 'allowed_values': ['Happy', 'Unhappy']},
        {'name': 'extra_attributes', 'type': 'jsonb'},
        {'name': 'blob', 'type': 'jsonb'},
        {'name': 'status', 'type': 'text'}]}
    out = G.legacy_to_runtime(design)
    assert [(f['name'], f['type'], f['required']) for f in out] == [
        ('visit_date', 'date', True), ('rating', 'integer', False), ('comments', 'text', False), ('mood', 'enum', False)]
    G.check_field_specs(out)


# ------------------------------------------------------------------ reading a sentence

PEOPLE = [{'id': 1, 'name': 'Asha Rao', 'first': 'Asha', 'username': 'asha'},
          {'id': 2, 'name': 'Ravi Kumar', 'first': 'Ravi', 'username': 'ravi'}]


def test_sentence_reader_fills_a_timesheet():
    fields = next(t for t in PACKS['work']['types'] if t['key'] == 'timesheet_entry')['fields']
    values, evidence, project = G.read_values(fields, 'Ravi 6.5 hours on drawings yesterday for Fictional Tower',
                                              TODAY, PEOPLE, ['Fictional Tower', 'Fictional Villa'], 'Timesheet entry')
    assert values == {'employee': 2, 'work_date': '2026-11-13', 'hours': '6.5', 'activity': 'Drawings'}
    assert project == 'Fictional Tower' and evidence['employee'] == 'Ravi Kumar'


def test_sentence_reader_labels_and_leaves_unclear_things_empty():
    fields = next(t for t in PACKS['work']['types'] if t['key'] == 'work_issue')['fields']
    values, _, _ = G.read_values(fields, 'Issue: glass partition delayed by vendor; owner: Asha Rao; severity: high; due: 20 Nov',
                                 TODAY, PEOPLE, [], 'Work issue')
    assert values['title'] == 'glass partition delayed by vendor' and values['owner'] == 1
    assert values['severity'] == 'High' and values['due_date'] == '2026-11-20'
    assert 'issue_status' not in values            # never guessed: asked on the card
    values, _, _ = G.read_values(fields, 'Asha and Ravi to sort the hinge problem', TODAY, PEOPLE, [], 'Work issue')
    assert 'owner' not in values                   # two people named: ask, do not pick


def test_typed_answers_are_checked_per_field():
    f = {'name': 'severity', 'type': 'enum', 'options': ['Low', 'Medium', 'High', 'Critical']}
    assert G.coerce_text(f, 'crit', TODAY) == 'Critical'
    with pytest.raises(G.GraphError):
        G.coerce_text(f, 'urgent', TODAY)
    assert G.coerce_text({'name': 'd', 'type': 'date'}, 'next monday', TODAY) == '2026-11-16'
    assert G.coerce_text({'name': 'h', 'type': 'decimal'}, '7.25', TODAY) == '7.25'
    assert G.coerce_text({'name': 'm', 'type': 'money'}, '₹12,500.50', TODAY) == {'amount': '12500.50', 'currency': 'INR'}
    assert G.coerce_text({'name': 'o', 'type': 'reference', 'target': 'system.user'}, 'ravi', TODAY, PEOPLE) == 2
    with pytest.raises(G.GraphError):
        G.coerce_text({'name': 'o', 'type': 'reference', 'target': 'system.user'}, 'Nobody', TODAY, PEOPLE)
    with pytest.raises(G.GraphError):
        G.coerce_text({'name': 'h', 'type': 'decimal'}, 7.25, TODAY)        # floats refused


def test_exact_sums_never_drift():
    cat, res = safety_world()
    many = {i: {'type': 'corrective_action', 'project_id': 10, 'values': {
        'action_text': f'a{i}', 'responsible': 1, 'action_status': 'Open', 'cost': {'amount': '0.10', 'currency': 'INR'}}}
        for i in range(1000, 1300)}
    res.records.update(many)
    out = G.run_report(res, cat, {'key': 'cost_sum', 'title': 'Cost', 'base': 'corrective_action',
                                  'filters': [{'path': 'action_text', 'op': 'contains', 'value': 'a1'}],
                                  'group_by': ['responsible'], 'measures': [{'agg': 'sum', 'path': 'cost'}]}, TODAY)
    assert out['rows'][0]['values'] == ['₹30.00']
    assert G.as_number({'amount': '0.10'}) * 300 == Decimal('30.00')
