"""v0.17 pure rules: dependencies, workflows, templates, recycle list. No database. Fictional data only."""
import pytest

from studioos import work_rules_core as c

ROLES = ('admin', 'manager', 'architect', 'site_engineer', 'accounts', 'viewer')


def L(a, b, kind='hard'):
    return {'predecessor_id': a, 'successor_id': b, 'kind': kind}


def test_cycle_detection_and_self_link():
    edges = [(1, 2), (2, 3)]
    assert c.would_create_cycle(edges, 3, 1)
    assert not c.would_create_cycle(edges, 1, 3)
    with pytest.raises(ValueError, match='itself'):
        c.validate_new_link([], 5, 5, 'hard')
    with pytest.raises(ValueError, match='loop'):
        c.validate_new_link([L(1, 2), L(2, 3)], 3, 1, 'hard')


def test_related_links_do_not_form_loops_and_duplicates_refused():
    c.validate_new_link([L(1, 2, 'related')], 2, 1, 'hard')      # a related link is not a direction, so no loop
    with pytest.raises(ValueError, match='already linked'):
        c.validate_new_link([L(1, 2, 'related')], 2, 1, 'related')
    with pytest.raises(ValueError, match='already linked'):
        c.validate_new_link([L(1, 2)], 1, 2, 'hard')
    with pytest.raises(ValueError, match='kind'):
        c.validate_new_link([], 1, 2, 'sideways')


def test_link_cap_per_task():
    links = [L(1, i) for i in range(2, 27)]
    with pytest.raises(ValueError, match='at most 25'):
        c.validate_new_link(links, 1, 99, 'soft')


def test_hard_blocks_close_soft_only_warns():
    links = [L(1, 3), L(2, 3, 'soft')]
    status = {1: 'open', 2: 'open', 3: 'open'}
    assert c.blocking_open_predecessors(3, links, status) == [1]
    assert c.warning_open_predecessors(3, links, status) == [2]
    with pytest.raises(ValueError, match='#1'):
        c.check_can_close(3, links, status)
    status[1] = 'done'
    c.check_can_close(3, links, status)


def test_hard_link_blocks_early_start():
    links = [L(1, 2)]
    with pytest.raises(ValueError, match='before the earlier task'):
        c.check_can_start(2, '2026-03-01', links, {1: '2026-03-10'}, {1: 'open'})
    c.check_can_start(2, '2026-03-11', links, {1: '2026-03-10'}, {1: 'open'})
    c.check_can_start(2, '2026-03-01', links, {1: '2026-03-10'}, {1: 'done'})


def good_workflow():
    return c.STARTING_SNAG_WORKFLOW


def test_starting_snag_workflow_is_valid_and_dry_runs():
    assert c.validate_workflow_definition(good_workflow(), ROLES) == 'reported'
    path = [
        {'transition': 'assign', 'role': 'manager', 'actor_id': 1},
        {'transition': 'mark_fixed', 'role': 'site_engineer', 'actor_id': 2, 'evidence': {'photo_document_id': 9}},
        {'transition': 'verify', 'role': 'manager', 'actor_id': 3},
        {'transition': 'close', 'role': 'manager', 'actor_id': 3},
    ]
    assert c.dry_run(good_workflow(), ROLES, path) == ['reported', 'assigned', 'fixed', 'verified', 'closed']


def test_transition_needs_photo_role_and_a_different_person():
    wf = good_workflow()
    with pytest.raises(ValueError, match='photo'):
        c.check_transition(wf, 'assigned', 'mark_fixed', 'site_engineer', {}, 2)
    with pytest.raises(ValueError, match='role'):
        c.check_transition(wf, 'assigned', 'mark_fixed', 'viewer', {'photo_document_id': 1}, 2)
    with pytest.raises(ValueError, match='different person'):
        c.check_transition(wf, 'fixed', 'verify', 'manager', {}, 2, previous_actor_ids=[2])
    assert c.check_transition(wf, 'fixed', 'verify', 'manager', {}, 3, previous_actor_ids=[2]) == 'verified'
    with pytest.raises(ValueError, match='not a step'):
        c.check_transition(wf, 'reported', 'close', 'admin', {}, 1)


def _copy():
    return {'statuses': [dict(s) for s in good_workflow()['statuses']],
            'transitions': [dict(t) for t in good_workflow()['transitions']]}


def test_workflow_validation_catches_each_problem():
    w = _copy(); w['statuses'][0].pop('start')
    with pytest.raises(ValueError, match='start'):
        c.validate_workflow_definition(w, ROLES)
    w = _copy(); w['statuses'][-1]['class'] = 'open'
    with pytest.raises(ValueError, match='closed'):
        c.validate_workflow_definition(w, ROLES)
    w = _copy(); del w['transitions'][0]
    with pytest.raises(ValueError, match='cannot be reached'):
        c.validate_workflow_definition(w, ROLES)
    w = _copy(); w['transitions'][0]['roles'] = ['wizard']
    with pytest.raises(ValueError, match='known role'):
        c.validate_workflow_definition(w, ROLES)
    w = _copy(); w['transitions'][1]['requires'] = ['magic']
    with pytest.raises(ValueError, match='requires only'):
        c.validate_workflow_definition(w, ROLES)
    w = _copy(); del w['transitions'][4]   # nothing leads to closed any more
    with pytest.raises(ValueError, match='closed status|cannot be reached'):
        c.validate_workflow_definition(w, ROLES)


def template():
    return {'stages': [{'key': 'design', 'name': 'Design'}, {'key': 'site', 'name': 'Site', 'client_visible': True}],
            'tasks': [{'key': 'brief', 'stage': 'design', 'title': 'Client brief', 'offset_days': 0, 'duration_days': 3},
                      {'key': 'plan', 'stage': 'design', 'title': 'Floor plan', 'offset_days': 4, 'duration_days': 7},
                      {'key': 'sub', 'stage': 'design', 'title': 'Measure', 'parent': 'plan', 'offset_days': 4},
                      {'key': 'build', 'stage': 'site', 'title': 'Start work', 'offset_days': 12, 'client_visible': True}],
            'links': [{'pred': 'brief', 'succ': 'plan', 'kind': 'hard'}, {'pred': 'plan', 'succ': 'build', 'kind': 'hard'}]}


def test_template_expands_with_dates_and_parents_first():
    plan = c.expand_template(template(), '2026-04-01')
    by = {p['key']: p for p in plan}
    assert by['plan']['start_date'] == '2026-04-05' and by['plan']['due_date'] == '2026-04-12'
    assert by['build']['client_visible'] is True and by['brief']['client_visible'] is False
    keys = [p['key'] for p in plan]
    assert keys.index('plan') < keys.index('sub')


def test_template_rejects_bad_content():
    t = template(); t['tasks'][1]['stage'] = 'nowhere'
    with pytest.raises(ValueError, match='stage that does not exist'):
        c.validate_template_definition(t)
    t = template(); t['links'].append({'pred': 'build', 'succ': 'brief', 'kind': 'hard'})
    with pytest.raises(ValueError, match='loop'):
        c.validate_template_definition(t)
    t = template(); t['tasks'][2]['parent'] = 'sub'
    with pytest.raises(ValueError, match='parent'):
        c.validate_template_definition(t)
    t = template(); t['tasks'][0]['offset_days'] = -1
    with pytest.raises(ValueError, match='whole number'):
        c.validate_template_definition(t)


def test_restore_brings_parents_and_delete_takes_children():
    parent_of = {3: 2, 2: 1, 1: None}
    assert c.restore_set(3, parent_of, {1, 2, 3}) == [3, 2, 1]
    assert c.restore_set(3, parent_of, {3}) == [3]
    with pytest.raises(ValueError, match='recycle'):
        c.restore_set(9, parent_of, {3})
    assert c.delete_set(1, {1: [2], 2: [3]}) == [1, 2, 3]


def test_variance_days():
    assert c.variance_days('2026-04-10', '2026-04-15') == 5
    assert c.variance_days('', '2026-04-15') is None
