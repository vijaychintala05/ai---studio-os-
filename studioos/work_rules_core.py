"""v0.17 work rules, pure logic (no database, no web). Every function takes plain data and raises ValueError with a
plain-English message, so the same check runs whether a person or the AI proposed the change.

Rules from the owner's plan (work management, v0.17):
- dependencies: hard links block, soft links warn, loops are refused, links per task are capped;
- status changes are named transitions: who may do it and what must be present first;
- a workflow is validated before it goes live and can be dry-run on sample data;
- deleted work is restorable inside a window, and restoring a child brings its parents back;
- a template carries stages, tasks, day offsets and links, and a project is created from it with dates set.
"""
from __future__ import annotations

import datetime as dt
import re

LINK_KINDS = ('hard', 'soft', 'related', 'duplicate')
PRECEDENCE_KINDS = ('hard', 'soft')            # these have a direction, so a loop through them is refused
MAX_LINKS_PER_TASK = 25
CLOSED_TASK_STATUSES = ('done', 'closed', 'cancelled')
EVIDENCE_KINDS = ('photo', 'measurement', 'comment', 'signoff', 'different_person')
MAX_WORKFLOW_STATUSES = 30
MAX_TEMPLATE_TASKS = 300
MAX_TEMPLATE_STAGES = 40
_KEY = re.compile(r'^[a-z][a-z0-9_]{1,59}$')


def _key(value, what):
    if not isinstance(value, str) or not _KEY.match(value):
        raise ValueError(f'{what} must be 2 to 60 lower-case letters, digits or underscores, starting with a letter')
    return value


def _date(value, what):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'{what} must be a date like 2026-03-31') from None


# ---------------------------------------------------------------- dependencies

def would_create_cycle(edges, predecessor, successor):
    """True if adding predecessor -> successor would make a loop. edges: iterable of (predecessor, successor)."""
    forward = {}
    for a, b in edges:
        forward.setdefault(a, set()).add(b)
    stack, seen = [successor], set()
    while stack:
        node = stack.pop()
        if node == predecessor:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(forward.get(node, ()))
    return False


def validate_new_link(active_links, predecessor, successor, kind, *, max_links=MAX_LINKS_PER_TASK):
    """active_links: list of dicts with predecessor_id, successor_id, kind (retired links excluded by the caller)."""
    if kind not in LINK_KINDS:
        raise ValueError('Link kind must be hard, soft, related or duplicate')
    if predecessor == successor:
        raise ValueError('A task cannot depend on itself')
    for link in active_links:
        pair = {link['predecessor_id'], link['successor_id']}
        if pair == {predecessor, successor} and link['kind'] == kind:
            raise ValueError('These two tasks are already linked that way')
    for task in (predecessor, successor):
        count = sum(1 for link in active_links if task in (link['predecessor_id'], link['successor_id']))
        if count >= max_links:
            raise ValueError(f'A task can have at most {max_links} links')
    if kind in PRECEDENCE_KINDS:
        edges = [(link['predecessor_id'], link['successor_id']) for link in active_links if link['kind'] in PRECEDENCE_KINDS]
        if would_create_cycle(edges, predecessor, successor):
            raise ValueError('That link would make a loop: the later task already leads back to the earlier one')


def blocking_open_predecessors(task_id, active_links, status_of):
    """Hard predecessors of task_id that are not yet closed. status_of: {task_id: status}."""
    return sorted(link['predecessor_id'] for link in active_links
                  if link['successor_id'] == task_id and link['kind'] == 'hard'
                  and status_of.get(link['predecessor_id'], 'open') not in CLOSED_TASK_STATUSES)


def warning_open_predecessors(task_id, active_links, status_of):
    return sorted(link['predecessor_id'] for link in active_links
                  if link['successor_id'] == task_id and link['kind'] == 'soft'
                  and status_of.get(link['predecessor_id'], 'open') not in CLOSED_TASK_STATUSES)


def check_can_close(task_id, active_links, status_of):
    open_ids = blocking_open_predecessors(task_id, active_links, status_of)
    if open_ids:
        raise ValueError('Task cannot be closed while these earlier tasks it depends on are still open: '
                         + ', '.join(f'#{i}' for i in open_ids))


def check_can_start(task_id, start_date, active_links, due_of, status_of):
    """A hard finish-to-start link refuses a start before the earlier task is due. Returns the date shift needed (days)."""
    if not start_date:
        return 0
    start = _date(start_date, 'Start date')
    latest = None
    for link in active_links:
        if link['successor_id'] != task_id or link['kind'] != 'hard':
            continue
        if status_of.get(link['predecessor_id'], 'open') in CLOSED_TASK_STATUSES:
            continue
        due = due_of.get(link['predecessor_id'], '')
        if due:
            d = _date(due, 'Due date')
            latest = d if latest is None or d > latest else latest
    if latest is not None and start < latest:
        shift = (latest - start).days + 1
        raise ValueError(f'This task cannot start before the earlier task it depends on is due ({latest.isoformat()}); '
                         f'move the start by {shift} day(s)')
    return 0


# ---------------------------------------------------------------- workflows

def validate_workflow_definition(defn, roles):
    """Raises ValueError listing every problem. A workflow is checked before it goes live: it starts open, ends closed,
    and every status can be reached from the start and can reach a closed status."""
    problems = []
    if not isinstance(defn, dict) or set(defn) - {'statuses', 'transitions'} or not {'statuses', 'transitions'} <= set(defn):
        raise ValueError('A workflow has a list of statuses and a list of transitions')
    statuses, transitions = defn['statuses'], defn['transitions']
    if not isinstance(statuses, list) or not 2 <= len(statuses) <= MAX_WORKFLOW_STATUSES:
        raise ValueError(f'A workflow needs 2 to {MAX_WORKFLOW_STATUSES} statuses')
    if not isinstance(transitions, list) or not 1 <= len(transitions) <= MAX_WORKFLOW_STATUSES * 4:
        raise ValueError('A workflow needs at least one transition')
    keys, start, closed = [], None, []
    for s in statuses:
        if not isinstance(s, dict) or set(s) - {'key', 'label', 'class', 'start'} or not {'key', 'label', 'class'} <= set(s):
            problems.append('Each status needs a key, a label and a class (open or closed)')
            continue
        try:
            _key(s['key'], 'Status key')
        except ValueError as e:
            problems.append(str(e))
        if s['key'] in keys:
            problems.append(f"Status {s['key']} appears twice")
        keys.append(s['key'])
        if s['class'] not in ('open', 'closed'):
            problems.append(f"Status {s['key']} must be open or closed")
        if not isinstance(s['label'], str) or not 1 <= len(s['label'].strip()) <= 80:
            problems.append(f"Status {s['key']} needs a short label")
        if s.get('start'):
            if start is not None:
                problems.append('Only one status can be the start')
            start = s
        if s['class'] == 'closed':
            closed.append(s['key'])
    if start is None:
        problems.append('One status must be the start')
    elif start['class'] != 'open':
        problems.append('The start status must be an open status')
    if not closed:
        problems.append('At least one status must be closed')
    outgoing, seen_pairs = {}, set()
    for t in transitions:
        if not isinstance(t, dict) or set(t) - {'name', 'from', 'to', 'roles', 'requires'} or not {'name', 'from', 'to', 'roles'} <= set(t):
            problems.append('Each transition needs a name, from, to and roles')
            continue
        try:
            _key(t['name'], 'Transition name')
        except ValueError as e:
            problems.append(str(e))
        if t['from'] not in keys or t['to'] not in keys:
            problems.append(f"Transition {t['name']} names a status that does not exist")
            continue
        if (t['from'], t['name']) in seen_pairs:
            problems.append(f"Transition {t['name']} from {t['from']} appears twice")
        seen_pairs.add((t['from'], t['name']))
        if not isinstance(t['roles'], list) or not t['roles'] or any(r not in roles for r in t['roles']):
            problems.append(f"Transition {t['name']} must name at least one known role")
        req = t.get('requires', [])
        if not isinstance(req, list) or any(r not in EVIDENCE_KINDS for r in req) or len(set(req)) != len(req):
            problems.append(f"Transition {t['name']} requires only: {', '.join(EVIDENCE_KINDS)}")
        outgoing.setdefault(t['from'], set()).add(t['to'])
    if start is not None and not problems:
        reach, stack = set(), [start['key']]
        while stack:
            node = stack.pop()
            if node in reach:
                continue
            reach.add(node)
            stack.extend(outgoing.get(node, ()))
        for k in keys:
            if k not in reach:
                problems.append(f'Status {k} cannot be reached from the start')
        back = {k: set() for k in keys}
        for a, bs in outgoing.items():
            for b in bs:
                back[b].add(a)
        can_close, stack = set(), list(closed)
        while stack:
            node = stack.pop()
            if node in can_close:
                continue
            can_close.add(node)
            stack.extend(back.get(node, ()))
        for k in keys:
            if k not in can_close:
                problems.append(f'Status {k} has no way to reach a closed status')
    if problems:
        raise ValueError('; '.join(dict.fromkeys(problems)))
    return start['key']


def available_transitions(defn, current_status, role):
    return sorted(t['name'] for t in defn['transitions'] if t['from'] == current_status and role in t['roles'])


def check_transition(defn, current_status, name, role, evidence, actor_id, previous_actor_ids=()):
    """Plain-English refusal if the named transition is not allowed now. Returns the destination status."""
    candidates = [t for t in defn['transitions'] if t['from'] == current_status and t['name'] == name]
    if not candidates:
        raise ValueError(f'"{name}" is not a step from the current status ({current_status})')
    t = candidates[0]
    if role not in t['roles']:
        raise ValueError('Your role may not make this change')
    evidence = evidence or {}
    for need in t.get('requires', []):
        if need == 'photo' and not evidence.get('photo_document_id'):
            raise ValueError('A photo must be attached first')
        if need == 'measurement' and not str(evidence.get('measurement', '')).strip():
            raise ValueError('A measurement must be recorded first')
        if need == 'comment' and len(str(evidence.get('comment', '')).strip()) < 3:
            raise ValueError('A comment must be written first')
        if need == 'signoff' and not evidence.get('signoff_by'):
            raise ValueError('A sign-off by a named person is needed first')
        if need == 'different_person' and actor_id in set(previous_actor_ids):
            raise ValueError('A different person must make this change (not the one who made the previous step)')
    return t['to']


def dry_run(defn, roles, path):
    """Walk sample data through a workflow with no database. path: list of dicts {transition, role, evidence, actor_id}.
    Returns the statuses visited, or raises on the first refused step."""
    start = validate_workflow_definition(defn, roles)
    status, visited, previous = start, [start], []
    for step in path:
        status = check_transition(defn, status, step['transition'], step['role'], step.get('evidence'), step.get('actor_id'), previous)
        previous = [step.get('actor_id')]
        visited.append(status)
    return visited


def status_class(defn, status):
    for s in defn['statuses']:
        if s['key'] == status:
            return s['class']
    raise ValueError(f'Unknown status {status}')


# ---------------------------------------------------------------- templates

def validate_template_definition(defn):
    if not isinstance(defn, dict) or set(defn) - {'stages', 'tasks', 'links'} or not {'stages', 'tasks'} <= set(defn):
        raise ValueError('A template has stages, tasks and (optionally) links')
    stages, tasks, links = defn['stages'], defn['tasks'], defn.get('links', [])
    if not isinstance(stages, list) or not 1 <= len(stages) <= MAX_TEMPLATE_STAGES:
        raise ValueError(f'A template needs 1 to {MAX_TEMPLATE_STAGES} stages')
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TEMPLATE_TASKS:
        raise ValueError(f'A template needs 1 to {MAX_TEMPLATE_TASKS} tasks')
    stage_keys = []
    for s in stages:
        if not isinstance(s, dict) or set(s) - {'key', 'name', 'client_visible'} or not {'key', 'name'} <= set(s):
            raise ValueError('Each stage needs a key and a name')
        _key(s['key'], 'Stage key')
        if s['key'] in stage_keys:
            raise ValueError(f"Stage {s['key']} appears twice")
        if not isinstance(s['name'], str) or not 1 <= len(s['name'].strip()) <= 200:
            raise ValueError('Each stage needs a short name')
        if 'client_visible' in s and not isinstance(s['client_visible'], bool):
            raise ValueError('client_visible must be true or false')
        stage_keys.append(s['key'])
    task_keys = []
    for t in tasks:
        if not isinstance(t, dict) or set(t) - {'key', 'stage', 'title', 'parent', 'offset_days', 'duration_days', 'client_visible'} \
                or not {'key', 'stage', 'title'} <= set(t):
            raise ValueError('Each task needs a key, a stage and a title')
        _key(t['key'], 'Task key')
        if t['key'] in task_keys:
            raise ValueError(f"Task {t['key']} appears twice")
        if t['stage'] not in stage_keys:
            raise ValueError(f"Task {t['key']} names a stage that does not exist")
        if not isinstance(t['title'], str) or not 1 <= len(t['title'].strip()) <= 400:
            raise ValueError('Each task needs a short title')
        for field in ('offset_days', 'duration_days'):
            v = t.get(field, 0)
            if type(v) is not int or not 0 <= v <= 3650:
                raise ValueError(f'{field} must be a whole number of days, 0 to 3650')
        if 'client_visible' in t and not isinstance(t['client_visible'], bool):
            raise ValueError('client_visible must be true or false')
        task_keys.append(t['key'])
    for t in tasks:
        parent = t.get('parent')
        if parent is not None and (parent not in task_keys or parent == t['key']):
            raise ValueError(f"Task {t['key']} names a parent that does not exist")
    parent_of = {t['key']: t.get('parent') for t in tasks}
    for k in task_keys:
        seen, node = set(), k
        while node is not None:
            if node in seen:
                raise ValueError('Subtasks cannot be their own ancestors')
            seen.add(node)
            node = parent_of.get(node)
    if not isinstance(links, list):
        raise ValueError('links must be a list')
    existing = []
    for i, link in enumerate(links):
        if not isinstance(link, dict) or set(link) != {'pred', 'succ', 'kind'}:
            raise ValueError('Each link needs pred, succ and kind')
        if link['pred'] not in task_keys or link['succ'] not in task_keys:
            raise ValueError('A link names a task that does not exist')
        validate_new_link(existing, link['pred'], link['succ'], link['kind'])
        existing.append({'predecessor_id': link['pred'], 'successor_id': link['succ'], 'kind': link['kind']})
    return stage_keys, task_keys


def expand_template(defn, start_date):
    """The plan a template makes for a project starting on start_date: dated tasks in a safe creation order
    (parents before subtasks). Pure: nothing is written."""
    validate_template_definition(defn)
    start = _date(start_date, 'Start date')
    plan = []
    for order, t in enumerate(defn['tasks']):
        begin = start + dt.timedelta(days=t.get('offset_days', 0))
        due = begin + dt.timedelta(days=t.get('duration_days', 0))
        plan.append({'key': t['key'], 'stage': t['stage'], 'title': t['title'].strip(), 'parent': t.get('parent'),
                     'start_date': begin.isoformat(), 'due_date': due.isoformat(),
                     'client_visible': bool(t.get('client_visible', False)), 'order': order})
    by_key = {p['key']: p for p in plan}

    def depth(p):
        d, node = 0, p
        while node['parent']:
            d, node = d + 1, by_key[node['parent']]
        return d
    plan.sort(key=lambda p: (depth(p), p['order']))
    return plan


# ---------------------------------------------------------------- soft delete

def within_restore_window(restore_until, now_value):
    return now_value <= restore_until


def restore_set(task_id, parent_of, deleted_ids):
    """The tasks to bring back when task_id is restored: itself plus every deleted ancestor ("restoring a child brings
    its parents back"). parent_of: {task_id: parent_id or None}; deleted_ids: tasks currently deleted."""
    if task_id not in deleted_ids:
        raise ValueError('That task is not in the recycle list')
    result, node, seen = [task_id], parent_of.get(task_id), {task_id}
    while node is not None and node not in seen:
        if node in deleted_ids:
            result.append(node)
        seen.add(node)
        node = parent_of.get(node)
    return result


def delete_set(task_id, children_of):
    """Deleting a task deletes its subtasks with it (so no orphan stays in the live list). Returns task_id first."""
    result, stack, seen = [], [task_id], set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        result.append(node)
        stack.extend(children_of.get(node, ()))
    return result


# ---------------------------------------------------------------- baselines

def variance_days(baseline_due, current_due):
    """Days a task has slipped since the baseline (positive = later). Empty dates give None."""
    if not baseline_due or not current_due:
        return None
    return (_date(current_due, 'Due date') - _date(baseline_due, 'Baseline date')).days


# ---------------------------------------------------------------- the owner's starting snag workflow (a proposal to edit)

STARTING_SNAG_WORKFLOW = {
    'statuses': [
        {'key': 'reported', 'label': 'Reported', 'class': 'open', 'start': True},
        {'key': 'assigned', 'label': 'Assigned', 'class': 'open'},
        {'key': 'fixed', 'label': 'Fixed', 'class': 'open'},
        {'key': 'verified', 'label': 'Verified', 'class': 'open'},
        {'key': 'closed', 'label': 'Closed', 'class': 'closed'},
    ],
    'transitions': [
        {'name': 'assign', 'from': 'reported', 'to': 'assigned', 'roles': ['admin', 'manager', 'architect']},
        {'name': 'mark_fixed', 'from': 'assigned', 'to': 'fixed', 'roles': ['admin', 'manager', 'architect', 'site_engineer'],
         'requires': ['photo']},
        {'name': 'send_back', 'from': 'fixed', 'to': 'assigned', 'roles': ['admin', 'manager'], 'requires': ['comment']},
        {'name': 'verify', 'from': 'fixed', 'to': 'verified', 'roles': ['admin', 'manager'], 'requires': ['different_person']},
        {'name': 'close', 'from': 'verified', 'to': 'closed', 'roles': ['admin', 'manager']},
    ],
}
