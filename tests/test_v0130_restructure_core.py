"""v0.13.0 safe restructuring, database-free part (standard library only).

Rename / retype / remove a field, rename / merge / split a type over a fictional firm: impact
preview, blockers, unconvertible rows, references rewritten in the same change, reports giving the
same answers after a rename, and undo restoring a byte-identical world. Pack version-2 upgrades as
change items; changes drafted from words. Fictional data only."""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import build_records, packs, Resolver, TODAY  # noqa: E402

G, RC = load('graph_core', 'restructure_core')


def make_world():
    types, rels = packs()
    w = {'types': {k: {'title': t['title'], 'fields': copy.deepcopy(t['fields']), 'aliases': list(t.get('aliases', [])),
                       'label_field': t.get('label_field'), 'version': 1, 'status': 'active',
                       **({'self_read': t['self_read']} if t.get('self_read') else {})} for k, t in types.items()},
         'records': {i: {'type': r['type'], 'data': copy.deepcopy(r['values']), 'project_id': r.get('project_id')}
                     for i, r in build_records().items()},
         'relations': {k: dict(v) for k, v in rels.items()}, 'edges': [],
         'reports': {}, 'rules': {}, 'views': {}, 'layouts': {}, 'dashboards': {}, 'calculations': {}, 'templates': {}}
    for pack in ('work', 'people'):
        p = json.loads((ROOT / 'studioos' / 'business_packs' / f'{pack}.json').read_text())
        for r in p.get('reports', []):
            w['reports'][r['key']] = copy.deepcopy(r)
        for x in p.get('workflows', []):
            w['rules'][x['key']] = {'type_key': x['type_key'], 'definition': copy.deepcopy(x)}
        for v in p.get('views', []):
            w['views'][v['key']] = {'type_key': v['type_key'], 'definition': copy.deepcopy(v)}
    w['reports']['issues_by_severity'] = {'key': 'issues_by_severity', 'title': 'Issues by severity', 'base': 'work_issue', 'group_by': ['severity']}
    w['layouts']['work_issue'] = {'type_key': 'work_issue', 'sections': [{'title': 'Main', 'fields': ['title', 'owner', 'severity']},
                                                                        {'title': 'Status', 'fields': ['issue_status', 'due_date']}],
                                  'list_columns': ['title', 'severity']}
    w['dashboards']['site_home'] = {'key': 'site_home', 'title': 'Site', 'roles': ['site_engineer'], 'tiles': [{'report': 'issues_by_severity'}]}
    return w


def run(world, key):
    cat = RC.catalog_of(world)
    recs = {i: {'type': r['type'], 'values': r['data'], 'project_id': r.get('project_id')} for i, r in world['records'].items()}
    out = G.run_report(Resolver(recs, cat), cat, {k: v for k, v in world['reports'][key].items() if k in G.REPORT_KEYS}, TODAY)
    out.pop('key'), out.pop('title')
    for r in out.get('rows', []):
        r.pop('record_ids', None)
    return out


def round_trip(world, change):
    before = RC.dumps(world)
    p = RC.plan(change, world, TODAY)
    assert not p['blockers'], p['blockers']
    w2 = RC.apply(world, p)
    assert RC.dumps(w2) != before
    undo = RC.inverse(w2, {'id': 1, **p})
    assert not undo['blockers']
    w3 = RC.apply(w2, undo)
    assert RC.dumps(w3) == before                    # byte-identical
    return p, w2


def test_rename_field_rewrites_every_reference_and_round_trips():
    w = make_world()
    p, w2 = round_trip(w, {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'priority'})
    assert 'issues_by_severity' in p['impact']['reports'] and 'open_issues_by_owner' in p['impact']['reports']
    assert w2['reports']['issues_by_severity']['group_by'] == ['priority']
    assert 'severity' not in RC.dumps(w2['layouts']) and 'priority' in w2['layouts']['work_issue']['sections'][0]['fields']
    assert all('severity' not in r['data'] for r in w2['records'].values() if r['type'] == 'work_issue')
    assert p['impact']['dashboards'] == ['site_home']
    # the reports give the same answers before and after
    for key in ('issues_by_severity', 'open_issues_by_owner'):
        a, b = run(w, key), run(w2, key)
        a.pop('group_labels', None), b.pop('group_labels', None)
        assert RC.dumps(a) == RC.dumps(b)
    rule = next(k for k, x in w['rules'].items() if x['type_key'] == 'work_issue' and 'severity' in RC.dumps(x))
    assert 'severity' not in RC.dumps(w2['rules'][rule]['definition']) and rule in p['impact']['rules']


def test_rename_label_and_self_read_fields_too():
    w = make_world()
    p, w2 = round_trip(w, {'op': 'rename_field', 'type_key': 'weekly_review', 'field': 'review_status', 'new_name': 'sharing'})
    assert w2['types']['weekly_review']['self_read']['when']['field'] == 'sharing'
    p, w2 = round_trip(w, {'op': 'rename_field', 'type_key': 'attendance_entry', 'field': 'employee', 'new_name': 'staff_member'})
    t = w2['types']['attendance_entry']
    assert t['label_field'] == 'staff_member' and t['self_read']['field'] == 'staff_member'


def test_remove_field_blocks_when_meaning_would_change_and_keeps_values():
    w = make_world()
    p = RC.plan({'op': 'remove_field', 'type_key': 'work_issue', 'field': 'severity'}, w, TODAY)
    assert any('Issues by severity' in b for b in p['blockers'])
    with pytest.raises(RC.ChangeError):
        RC.apply(w, p)
    p, w2 = round_trip(w, {'op': 'remove_field', 'type_key': 'work_issue', 'field': 'resolution'})
    t = w2['types']['work_issue']
    assert 'resolution' not in [f['name'] for f in t['fields']] and t['removed_fields'][0]['name'] == 'resolution'
    assert w2['records'] == w['records']                     # values are kept
    lab = RC.plan({'op': 'remove_field', 'type_key': 'work_issue', 'field': 'title'}, w, TODAY)
    assert any('label field' in b for b in lab['blockers'])
    # a field only in the layout and a view's columns: those drop it
    w['layouts']['milestone'] = {'type_key': 'milestone', 'sections': [{'title': 'A', 'fields': ['title', 'notes']}], 'list_columns': ['notes']}
    p, w2 = round_trip(w, {'op': 'remove_field', 'type_key': 'milestone', 'field': 'notes'})
    assert w2['layouts']['milestone'] == {'type_key': 'milestone', 'sections': [{'title': 'A', 'fields': ['title']}], 'list_columns': []}


def test_retype_lists_unconvertible_rows_and_blocks():
    w = make_world()
    p = RC.plan({'op': 'retype_field', 'type_key': 'timesheet_entry', 'field': 'hours', 'new_type': 'integer'}, w, TODAY)
    bad = {r['value'] for r in p['unconvertible']}
    assert bad <= {'3.5', '7.5'} and p['unconvertible_total'] == sum(1 for r in w['records'].values()
                                                                      if r['type'] == 'timesheet_entry' and r['data']['hours'] in ('3.5', '7.5'))
    assert p['blockers'] and 'cannot be converted' in p['blockers'][0]
    for i in [x['record_id'] for x in p['unconvertible']]:
        w['records'][i]['data']['hours'] = '4'
    p, w2 = round_trip(w, {'op': 'retype_field', 'type_key': 'timesheet_entry', 'field': 'hours', 'new_type': 'integer'})
    assert {type(r['data']['hours']) for r in w2['records'].values() if r['type'] == 'timesheet_entry'} == {int}


def test_retype_checks_saved_definitions_and_exact_numbers():
    w = make_world()
    p = RC.plan({'op': 'retype_field', 'type_key': 'work_issue', 'field': 'severity', 'new_type': 'text'}, w, TODAY)
    assert 'open_issues_by_owner' in p['impact']['reports']
    p = RC.plan({'op': 'retype_field', 'type_key': 'work_issue', 'field': 'severity', 'new_type': 'enum',
                 'options': ['Low', 'Medium', 'High']}, w, TODAY)
    assert p['unconvertible_total'] == sum(1 for r in w['records'].values() if r['type'] == 'work_issue' and r['data']['severity'] == 'Critical')
    ok, v = RC.convert({'amount': '4500.50', 'currency': 'INR'}, {'type': 'money'}, {'type': 'decimal'}, TODAY)
    assert ok and v == '4500.50'
    ok, v = RC.convert('4500.55', {'type': 'decimal'}, {'type': 'integer'}, TODAY)
    assert not ok                                      # no rounding, ever


def test_rename_type_keeps_the_key_and_the_old_name():
    w = make_world()
    p, w2 = round_trip(w, {'op': 'rename_type', 'type_key': 'work_issue', 'new_title': 'Snag'})
    assert w2['types']['work_issue']['title'] == 'Snag' and 'Work issue' in w2['types']['work_issue']['aliases']
    with pytest.raises(RC.ChangeError):
        RC.check_change({'op': 'rename_type', 'type_key': 'milestone', 'new_title': 'Work issue'}, w)


def test_merge_types_moves_records_relations_and_reports():
    w = make_world()
    w['types']['site_snag'] = {'title': 'Site snag', 'version': 1, 'status': 'active', 'aliases': [], 'label_field': 'what',
                               'fields': [{'name': 'what', 'type': 'text', 'required': True},
                                          {'name': 'who', 'type': 'reference', 'target': 'system.user', 'required': True},
                                          {'name': 'how_bad', 'type': 'enum', 'options': ['Low', 'High'], 'required': True},
                                          {'name': 'state', 'type': 'enum', 'options': ['Open', 'Closed'], 'required': True}]}
    for i in range(5):
        w['records'][9000 + i] = {'type': 'site_snag', 'project_id': 1, 'data': {'what': f'Fictional snag {i}', 'who': 11,
                                                                                 'how_bad': 'High' if i % 2 else 'Low', 'state': 'Open'}}
    w['reports']['snags_by_badness'] = {'key': 'snags_by_badness', 'title': 'Snags', 'base': 'site_snag', 'group_by': ['how_bad']}
    w['relations']['snag_blocks_task'] = {'source_type': 'site_snag', 'target_type': 'system.task'}
    fm = {'what': 'title', 'who': 'owner', 'how_bad': 'severity', 'state': 'issue_status'}
    p, w2 = round_trip(w, {'op': 'merge_types', 'type_key': 'site_snag', 'into': 'work_issue', 'field_map': fm})
    assert all(w2['records'][9000 + i]['type'] == 'work_issue' and w2['records'][9000 + i]['data']['owner'] == 11 for i in range(5))
    assert w2['types']['site_snag']['status'] == 'merged' and w2['relations']['snag_blocks_task']['source_type'] == 'work_issue'
    assert w2['reports']['snags_by_badness']['base'] == 'work_issue' and w2['reports']['snags_by_badness']['group_by'] == ['severity']
    with pytest.raises(RC.ChangeError):
        RC.check_change({'op': 'merge_types', 'type_key': 'site_snag', 'into': 'work_issue', 'field_map': {'what': 'title'}}, w)


def test_split_type_moves_matching_records_and_blocks_on_links():
    w = make_world()
    cond = {'field': 'attendance_status', 'op': 'eq', 'value': 'Work from home'}
    p, w2 = round_trip(w, {'op': 'split_type', 'type_key': 'attendance_entry', 'new_key': 'wfh_entry', 'new_title': 'Work from home day',
                           'condition': cond})
    moved = [i for i, r in w2['records'].items() if r['type'] == 'wfh_entry']
    assert moved and len(moved) == sum(1 for r in w['records'].values() if r['type'] == 'attendance_entry'
                                       and r['data']['attendance_status'] == 'Work from home')
    w['edges'].append({'id': 1, 'rel': 'x', 'source': moved[0], 'target': 5})
    assert any('link' in b for b in RC.plan({'op': 'split_type', 'type_key': 'attendance_entry', 'new_key': 'wfh_entry',
                                             'new_title': 'Work from home day', 'condition': cond}, w, TODAY)['blockers'])


def test_formulas_and_templates_block_and_undo_refuses_after_later_changes():
    w = make_world()
    w['calculations']['days_late'] = {'type_key': 'work_issue', 'definition': {'op': 'days', 'from': {'field': 'due_date'}}}
    w['templates']['issue_sheet'] = {'type_key': 'work_issue', 'definition': {'body': 'Owner: {{owner}}'}}
    p = RC.plan({'op': 'rename_field', 'type_key': 'work_issue', 'field': 'due_date', 'new_name': 'deadline'}, w, TODAY)
    assert any('Formula "days_late"' in b for b in p['blockers'])
    p = RC.plan({'op': 'remove_field', 'type_key': 'work_issue', 'field': 'owner'}, w, TODAY)
    assert any('Document template "issue_sheet"' in b for b in p['blockers'])
    del w['calculations']['days_late']
    p = RC.plan({'op': 'rename_field', 'type_key': 'work_issue', 'field': 'due_date', 'new_name': 'deadline'}, w, TODAY)
    w2 = RC.apply(w, p)
    some = next(i for i, r in w2['records'].items() if r['type'] == 'work_issue' and 'deadline' in r['data'])
    w2['records'][some]['data']['deadline'] = '2027-01-01'          # someone edited it afterwards
    assert RC.inverse(w2, {'id': 1, **p})['blockers']


def test_refusals():
    w = make_world()
    for bad in ({'op': 'rename_field', 'type_key': 'gl_lines', 'field': 'x', 'new_name': 'y'},
                {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'owner'},
                {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'project_id'},
                {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'Bad Name'},
                {'op': 'drop_table', 'type_key': 'work_issue'},
                {'op': 'remove_field', 'type_key': 'work_issue', 'field': 'severity', 'sql': 'x'},
                {'op': 'split_type', 'type_key': 'work_issue', 'new_key': 'milestone', 'new_title': 'X1', 'condition': None}):
        with pytest.raises((RC.ChangeError, G.GraphError)):
            RC.check_change(bad, w)


def test_change_from_words():
    w = make_world()
    assert RC.change_from_words('rename field severity to priority in work issue', w) == \
        {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'priority'}
    assert RC.change_from_words('remove resolution from work issues', w) == {'op': 'remove_field', 'type_key': 'work_issue', 'field': 'resolution'}
    assert RC.change_from_words('make hours in timesheet entry a whole number', w)['new_type'] == 'integer'
    assert RC.change_from_words('rename type work issue to Snag', w) == {'op': 'rename_type', 'type_key': 'work_issue', 'new_title': 'Snag'}
    with pytest.raises(RC.ChangeError):
        RC.change_from_words('delete everything', w)


def test_pack_version_two_upgrade_is_a_list_of_change_items():
    w = make_world()
    v1 = {'key': 'work', 'version': 1}
    v2 = {'key': 'work', 'version': 2, 'types': [{'key': 'timesheet_entry'}, {'key': 'site_visit', 'title': 'Site visit', 'fields': []}],
          'upgrade': {'from': 1, 'changes': [
              {'kind': 'metadata_type_change', 'data': {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'resolution', 'new_name': 'fix_notes'}},
              {'kind': 'metadata_type_options', 'data': {'type_key': 'timesheet_entry', 'self_read': {'field': 'employee'}}}]}}
    items = RC.pack_upgrade_plan(v1, v2, w)
    assert [i['kind'] for i in items] == ['metadata_type', 'metadata_type_change', 'metadata_type_options', 'metadata_pack_install']
    with pytest.raises(RC.ChangeError):
        RC.pack_upgrade_plan({'key': 'work', 'version': 1}, {**v2, 'version': 3}, w)
    bad = copy.deepcopy(v2)
    bad['upgrade']['changes'].append({'kind': 'finance_open_account', 'data': {}})
    with pytest.raises(RC.ChangeError):
        RC.pack_upgrade_plan(v1, bad, w)
