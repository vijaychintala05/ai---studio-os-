"""v0.17 work rules on the ticket path. Nothing here is called by a route directly: every change to stages, links,
workflows, templates, baselines, transitions and deleted work is a ticket item that a person approves, so the AI
can propose the same changes a person types and neither can skip a rule.

validate(db, item) raises ValueError in plain English and writes nothing; apply(db, item, actor) re-validates, then writes.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from . import work_rules_core as core
from .db import (Config, FlexibleRecord, Project, Task, TicketRecordEvent, UniversalRecordRevision, User,
                 add_audit, now)
from .work_models import (ProjectBaseline, ProjectStage, TaskLink, TaskStructure, WorkDeletion, WorkTemplate,
                          WorkTransitionLog, WorkWorkflow)

WORK_TYPES = {'work_stage', 'work_task_structure', 'work_link', 'work_unlink', 'work_workflow_publish',
              'work_workflow_retire', 'work_template_publish', 'work_apply_template', 'work_baseline',
              'work_transition', 'work_task_delete', 'work_task_restore'}

WORK_FIELDS = {
    'work_stage': {'project_id', 'name', 'client_visible', 'position'},
    'work_task_structure': {'task_id', 'stage_id', 'parent_task_id', 'client_visible', 'start_date'},
    'work_link': {'predecessor_id', 'successor_id', 'kind'},
    'work_unlink': {'link_id'},
    'work_workflow_publish': {'key', 'name', 'applies_to', 'definition'},
    'work_workflow_retire': {'key'},
    'work_template_publish': {'key', 'name', 'definition'},
    'work_apply_template': {'template_key', 'project_id', 'start_date'},
    'work_baseline': {'project_id', 'label'},
    'work_transition': {'workflow_key', 'target', 'target_id', 'transition', 'evidence'},
    'work_task_delete': {'task_id', 'reason'},
    'work_task_restore': {'task_id'},
}

RESTORE_DAYS_KEY = 'work_restore_days'
DEFAULT_RESTORE_DAYS = 30   # a proposed default: the owner decides the real window (see HELD_FOR_OWNER.md)


def restore_days(db):
    row = db.get(Config, RESTORE_DAYS_KEY)
    try:
        days = int(row.value) if row else DEFAULT_RESTORE_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_RESTORE_DAYS
    return days if 1 <= days <= 3650 else DEFAULT_RESTORE_DAYS


def _roles():
    from .security import ROLES
    return ROLES


def _int(d, key):
    if type(d.get(key)) is not int or d[key] <= 0:
        raise ValueError(f'{key} must be a record number')
    return d[key]


def _text(d, key, low=1, high=200):
    v = d.get(key)
    if not isinstance(v, str) or not low <= len(v.strip()) <= high:
        raise ValueError(f'{key} is required ({low} to {high} characters)')
    return v.strip()


def _live_task(db, task_id):
    t = db.get(Task, task_id)
    if not t or t.deleted_at:
        raise ValueError(f'Task #{task_id} does not exist')
    return t


def _live_project(db, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at:
        raise ValueError(f'Project #{project_id} does not exist')
    return p


def active_links(db, task_ids=None):
    q = select(TaskLink).where(TaskLink.retired_at.is_(None))
    rows = db.scalars(q).all()
    out = [{'id': r.id, 'predecessor_id': r.predecessor_id, 'successor_id': r.successor_id, 'kind': r.kind} for r in rows]
    if task_ids is not None:
        out = [l for l in out if l['predecessor_id'] in task_ids or l['successor_id'] in task_ids]
    return out


def _status_due_maps(db, ids):
    status, due = {}, {}
    for t in db.scalars(select(Task).where(Task.id.in_(list(ids)))).all():
        status[t.id] = 'deleted' if t.deleted_at else t.status
        due[t.id] = t.due_date or ''
    return status, due


def check_task_update(db, data):
    """Called by tickets.validate_item for update_task: closing is refused while a hard predecessor is open."""
    if not isinstance(data, dict) or type(data.get('id')) is not int:
        return
    new_status = data.get('status')
    links = active_links(db, {data['id']})
    if not links:
        return
    ids = {data['id']} | {l['predecessor_id'] for l in links} | {l['successor_id'] for l in links}
    status, due = _status_due_maps(db, ids)
    if new_status in core.CLOSED_TASK_STATUSES:
        core.check_can_close(data['id'], links, status)
    if 'due_date' in data and data.get('due_date'):
        s = db.get(TaskStructure, data['id'])
        if s and s.start_date and s.start_date > data['due_date']:
            raise ValueError('The due date cannot be before the start date')


def workflow_definition(db, key, target_kind=None):
    row = db.scalar(select(WorkWorkflow).where(WorkWorkflow.key == key, WorkWorkflow.status == 'live')
                    .order_by(WorkWorkflow.version.desc()))
    if not row:
        raise ValueError(f'No live workflow called {key}')
    return row


# ------------------------------------------------------------------ validate

def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in WORK_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - WORK_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    db.info['work_item'] = item
    try:
        return globals()['_validate_' + kind[5:]](db, d)
    finally:
        db.info.pop('work_item', None)


def _validate_stage(db, d):
    _live_project(db, _int(d, 'project_id'))
    _text(d, 'name')
    if 'client_visible' in d and not isinstance(d['client_visible'], bool):
        raise ValueError('client_visible must be true or false')
    if 'position' in d and (type(d['position']) is not int or not 0 <= d['position'] <= 1000):
        raise ValueError('position must be a whole number')
    existing = db.scalar(select(ProjectStage).where(ProjectStage.project_id == d['project_id'],
                                                    func.lower(ProjectStage.name) == d['name'].strip().lower(),
                                                    ProjectStage.deleted_at.is_(None)))
    if existing:
        raise ValueError('This project already has a stage with that name')


def _validate_task_structure(db, d):
    task = _live_task(db, _int(d, 'task_id'))
    if d.get('stage_id') is not None:
        stage = db.get(ProjectStage, d['stage_id']) if type(d['stage_id']) is int else None
        if not stage or stage.deleted_at or stage.project_id != task.project_id:
            raise ValueError('That stage does not belong to the task\'s project')
    parent = d.get('parent_task_id')
    if parent is not None:
        if type(parent) is not int or parent == task.id:
            raise ValueError('A task cannot be its own parent')
        p = _live_task(db, parent)
        if p.project_id != task.project_id:
            raise ValueError('A subtask must be in the same project as its parent')
        node, seen = parent, {task.id}
        while node is not None:
            if node in seen:
                raise ValueError('Subtasks cannot be their own ancestors')
            seen.add(node)
            s = db.get(TaskStructure, node)
            node = s.parent_task_id if s else None
    if d.get('start_date'):
        start = d['start_date']
        core._date(start, 'Start date')
        if task.due_date and start > task.due_date:
            raise ValueError('The start date cannot be after the due date')
        links = active_links(db, {task.id})
        ids = {task.id} | {l['predecessor_id'] for l in links}
        status, due = _status_due_maps(db, ids)
        core.check_can_start(task.id, start, links, due, status)
    if 'client_visible' in d and not isinstance(d['client_visible'], bool):
        raise ValueError('client_visible must be true or false')


def _validate_link(db, d):
    a, b = _int(d, 'predecessor_id'), _int(d, 'successor_id')
    ta, tb = _live_task(db, a), _live_task(db, b)
    core.validate_new_link(active_links(db), a, b, d.get('kind'))
    if d.get('kind') == 'hard' and ta.project_id != tb.project_id:
        raise ValueError('A hard link must join two tasks in the same project')


def _validate_unlink(db, d):
    link = db.get(TaskLink, _int(d, 'link_id'))
    if not link or link.retired_at:
        raise ValueError('That link does not exist or was already removed')


def _validate_workflow_publish(db, d):
    key = core._key(d.get('key'), 'Workflow key')
    _text(d, 'name')
    at = d.get('applies_to')
    if at == {'target': 'task'}:
        pass
    elif isinstance(at, dict) and set(at) == {'target', 'type', 'status_field'} and at['target'] == 'record' \
            and isinstance(at['type'], str) and isinstance(at['status_field'], str):
        from .db import RecordType
        if not db.get(RecordType, at['type']):
            raise ValueError('That record type does not exist')
    else:
        raise ValueError('A workflow applies to tasks, or to one record type and its status field')
    core.validate_workflow_definition(d.get('definition'), _roles())
    return key


def _validate_workflow_retire(db, d):
    workflow_definition(db, core._key(d.get('key'), 'Workflow key'))


def _validate_template_publish(db, d):
    core._key(d.get('key'), 'Template key')
    _text(d, 'name')
    core.validate_template_definition(d.get('definition'))


def _validate_apply_template(db, d):
    _live_project(db, _int(d, 'project_id'))
    core._key(d.get('template_key'), 'Template key')
    row = db.scalar(select(WorkTemplate).where(WorkTemplate.key == d['template_key'], WorkTemplate.status == 'live')
                    .order_by(WorkTemplate.version.desc()))
    if not row:
        raise ValueError('No live template with that key')
    core.expand_template(row.definition, d.get('start_date'))
    if db.scalar(select(func.count()).select_from(TaskStructure).join(Task, Task.id == TaskStructure.task_id)
                 .where(Task.project_id == d['project_id'], TaskStructure.template_key == d['template_key'],
                        Task.deleted_at.is_(None))):
        raise ValueError('This template was already applied to this project')


def _validate_baseline(db, d):
    _live_project(db, _int(d, 'project_id'))
    if 'label' in d:
        _text(d, 'label', 1, 120)


def _validate_transition(db, d):
    wf = workflow_definition(db, d.get('workflow_key'))
    target, tid = d.get('target'), _int(d, 'target_id')
    if target != wf.applies_to.get('target'):
        raise ValueError('This workflow is for a different kind of item')
    current, _ = _current_status(db, wf, tid)
    role, actor_id = _actor_role(db, d)
    from .main import check_proposal_access
    check_proposal_access(db, db.get(User, actor_id), 'work_transition', d)
    evidence = d.get('evidence') or {}
    if not isinstance(evidence, dict):
        raise ValueError('Evidence must be a set of named facts')
    previous = [r.actor_id for r in db.scalars(
        select(WorkTransitionLog).where(WorkTransitionLog.workflow_key == wf.key, WorkTransitionLog.target == target,
                                        WorkTransitionLog.target_id == tid).order_by(WorkTransitionLog.id.desc()).limit(1))]
    to = core.check_transition(wf.definition, current, d.get('transition'), role, evidence, actor_id, previous)
    if target == 'task' and core.status_class(wf.definition, to) == 'closed':
        links = active_links(db, {tid})
        ids = {tid} | {l['predecessor_id'] for l in links}
        status, _ = _status_due_maps(db, ids)
        core.check_can_close(tid, links, status)
    return wf, current, to


def _actor_role(db, d):
    """The person making a status change is the one who proposed it (a site engineer proposes "fixed"; an owner approves
    the ticket). Their role decides which transitions are open to them."""
    from .db import ApprovalTicket
    item = db.info.get('work_item')
    ticket = db.get(ApprovalTicket, item.ticket_id) if item is not None and item.ticket_id else None
    user = db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None
    if not user:
        raise ValueError('The person making this change is not known')
    return user.role, user.id


def _current_status(db, wf, tid):
    if wf.applies_to['target'] == 'task':
        t = _live_task(db, tid)
        return t.status, t
    rec = db.get(FlexibleRecord, tid)
    if not rec or rec.deleted_at or rec.record_type != wf.applies_to['type']:
        raise ValueError('That record does not exist')
    start = next(s['key'] for s in wf.definition['statuses'] if s.get('start'))
    return (rec.data or {}).get(wf.applies_to['status_field']) or start, rec


def _validate_task_delete(db, d):
    t = _live_task(db, _int(d, 'task_id'))
    from .period_rules import check_project_may_change
    check_project_may_change(db, t.project_id)   # v0.20: a legal hold freezes deletion
    _text(d, 'reason', 3, 500)
    return t


def _validate_task_restore(db, d):
    tid = _int(d, 'task_id')
    row = db.scalar(select(WorkDeletion).where(WorkDeletion.task_id == tid, WorkDeletion.restored_at.is_(None))
                    .order_by(WorkDeletion.id.desc()))
    if not row:
        raise ValueError('That task is not in the recycle list')
    if not core.within_restore_window(_aware(row.restore_until), _aware(now())):
        raise ValueError('The restore window for this task has passed')


def _aware(v):
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------ apply

def apply(db, item, actor):
    validate(db, item)
    d, kind = item.after_data, item.item_type
    db.info['work_item'] = item
    try:
        entity, entity_id = globals()['_apply_' + kind[5:]](db, d, actor, item)
    finally:
        db.info.pop('work_item', None)
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type=entity, entity_id=entity_id,
                             operation='update' if kind in ('work_transition', 'work_task_structure', 'work_task_restore',
                                                            'work_unlink', 'work_workflow_retire') else 'create'))
    add_audit(db, 'ticket_commit', entity, entity_id, f'Ticket #{item.ticket_id}, item #{item.id}: {kind}', actor=actor)
    db.flush()
    return {'type': entity, 'id': entity_id, 'item_id': item.id}


def _apply_stage(db, d, actor, item):
    pos = d.get('position')
    if pos is None:
        pos = (db.scalar(select(func.max(ProjectStage.position)).where(ProjectStage.project_id == d['project_id'])) or 0) + 1
    row = ProjectStage(project_id=d['project_id'], name=d['name'].strip(), position=pos,
                       client_visible=bool(d.get('client_visible', False)))
    db.add(row)
    db.flush()
    return 'project_stage', row.id


def _apply_task_structure(db, d, actor, item):
    row = db.get(TaskStructure, d['task_id']) or TaskStructure(task_id=d['task_id'])
    for k in ('stage_id', 'parent_task_id', 'client_visible', 'start_date'):
        if k in d:
            setattr(row, k, d[k] if d[k] is not None or k in ('stage_id', 'parent_task_id') else '')
    db.add(row)
    db.flush()
    return 'task', d['task_id']


def _apply_link(db, d, actor, item):
    row = TaskLink(predecessor_id=d['predecessor_id'], successor_id=d['successor_id'], kind=d['kind'], created_by=actor)
    db.add(row)
    db.flush()
    return 'task_link', row.id


def _apply_unlink(db, d, actor, item):
    row = db.get(TaskLink, d['link_id'])
    row.retired_at, row.retired_by = now(), actor
    return 'task_link', row.id


def _apply_workflow_publish(db, d, actor, item):
    last = db.scalar(select(func.max(WorkWorkflow.version)).where(WorkWorkflow.key == d['key'])) or 0
    for old in db.scalars(select(WorkWorkflow).where(WorkWorkflow.key == d['key'], WorkWorkflow.status == 'live')):
        old.status, old.retired_at = 'retired', now()
    row = WorkWorkflow(key=d['key'], version=last + 1, name=d['name'].strip(), applies_to=d['applies_to'],
                       definition=d['definition'], created_by=actor)
    db.add(row)
    db.flush()
    return 'work_workflow', row.id


def _apply_workflow_retire(db, d, actor, item):
    row = workflow_definition(db, d['key'])
    row.status, row.retired_at = 'retired', now()
    return 'work_workflow', row.id


def _apply_template_publish(db, d, actor, item):
    last = db.scalar(select(func.max(WorkTemplate.version)).where(WorkTemplate.key == d['key'])) or 0
    for old in db.scalars(select(WorkTemplate).where(WorkTemplate.key == d['key'], WorkTemplate.status == 'live')):
        old.status, old.retired_at = 'retired', now()
    row = WorkTemplate(key=d['key'], version=last + 1, name=d['name'].strip(), definition=d['definition'], created_by=actor)
    db.add(row)
    db.flush()
    return 'work_template', row.id


def _apply_apply_template(db, d, actor, item):
    tpl = db.scalar(select(WorkTemplate).where(WorkTemplate.key == d['template_key'], WorkTemplate.status == 'live')
                    .order_by(WorkTemplate.version.desc()))
    plan = core.expand_template(tpl.definition, d['start_date'])
    stage_rows = {}
    for pos, s in enumerate(tpl.definition['stages']):
        row = ProjectStage(project_id=d['project_id'], name=s['name'].strip(), position=pos,
                           client_visible=bool(s.get('client_visible', False)), template_key=tpl.key)
        db.add(row)
        db.flush()
        stage_rows[s['key']] = row.id
    task_ids = {}
    for p in plan:
        t = Task(project_id=d['project_id'], title=p['title'], due_date=p['due_date'])
        db.add(t)
        db.flush()
        task_ids[p['key']] = t.id
        db.add(TaskStructure(task_id=t.id, stage_id=stage_rows[p['stage']],
                             parent_task_id=task_ids.get(p['parent']) if p['parent'] else None,
                             client_visible=p['client_visible'], start_date=p['start_date'],
                             template_key=tpl.key, template_task_key=p['key']))
    for link in tpl.definition.get('links', []):
        db.add(TaskLink(predecessor_id=task_ids[link['pred']], successor_id=task_ids[link['succ']],
                        kind=link['kind'], created_by=actor))
    db.flush()
    return 'project', d['project_id']


def _apply_baseline(db, d, actor, item):
    rows = db.execute(select(Task, TaskStructure).outerjoin(TaskStructure, TaskStructure.task_id == Task.id)
                      .where(Task.project_id == d['project_id'], Task.deleted_at.is_(None))).all()
    data = {str(t.id): {'title': t.title, 'due_date': t.due_date, 'start_date': (s.start_date if s else '')} for t, s in rows}
    from .budget_models import WorkBudget   # v0.21: the baseline also freezes the budgets, so later changes show as variance
    data['_budgets'] = {f'{b.scope}:{b.ref_id}': b.amount_paise for b in db.scalars(
        select(WorkBudget).where(WorkBudget.project_id == d['project_id'], WorkBudget.retired_at.is_(None)))}
    row = ProjectBaseline(project_id=d['project_id'], label=(d.get('label') or '').strip(), data=data, frozen_by=actor)
    db.add(row)
    db.flush()
    return 'project_baseline', row.id


def _apply_transition(db, d, actor, item):
    wf, current, to = _validate_transition(db, d)
    tid = d['target_id']
    if wf.applies_to['target'] == 'task':
        t = db.get(Task, tid)
        t.status = to
        if core.status_class(wf.definition, to) == 'closed':
            t.progress = 100
    else:
        rec = db.get(FlexibleRecord, tid)
        before = dict(rec.data or {})
        after = {**before, wf.applies_to['status_field']: to}
        version = (db.scalar(select(func.max(UniversalRecordRevision.version)).where(UniversalRecordRevision.record_id == tid)) or 0) + 1
        rec.data = after
        db.add(UniversalRecordRevision(record_id=tid, version=version, before_data=before, after_data=after,
                                       ticket_id=item.ticket_id, actor=actor))
    role, actor_id = _actor_role(db, d)
    who = db.get(User, actor_id).username
    db.add(WorkTransitionLog(workflow_key=wf.key, workflow_version=wf.version, target=wf.applies_to['target'], target_id=tid,
                             transition=d['transition'], from_status=current, to_status=to, actor=who, actor_id=actor_id,
                             evidence=d.get('evidence') or {}, ticket_id=item.ticket_id))
    return wf.applies_to['target'], tid


def _children_map(db, project_id):
    rows = db.execute(select(TaskStructure.task_id, TaskStructure.parent_task_id).join(Task, Task.id == TaskStructure.task_id)
                      .where(Task.project_id == project_id, TaskStructure.parent_task_id.is_not(None))).all()
    out = {}
    for child, parent in rows:
        out.setdefault(parent, []).append(child)
    return out


def _apply_task_delete(db, d, actor, item):
    task = db.get(Task, d['task_id'])
    until = now() + dt.timedelta(days=restore_days(db))
    for tid in core.delete_set(task.id, _children_map(db, task.project_id)):
        t = db.get(Task, tid)
        if t and not t.deleted_at:
            t.deleted_at = now()
            db.add(WorkDeletion(task_id=tid, deleted_by=actor, restore_until=until, reason=d['reason'].strip()))
    return 'task', task.id


def _apply_task_restore(db, d, actor, item):
    task = db.get(Task, d['task_id'])
    parents = {s.task_id: s.parent_task_id for s in db.scalars(select(TaskStructure).where(TaskStructure.parent_task_id.is_not(None)))}
    deleted = {t for t in db.scalars(select(Task.id).where(Task.deleted_at.is_not(None)))}
    for tid in core.restore_set(task.id, parents, deleted):
        t = db.get(Task, tid)
        t.deleted_at = None
        for row in db.scalars(select(WorkDeletion).where(WorkDeletion.task_id == tid, WorkDeletion.restored_at.is_(None))):
            row.restored_at, row.restored_by = now(), actor
    return 'task', task.id
