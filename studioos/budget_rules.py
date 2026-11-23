"""v0.21 budgets on the ticket path. Budgets, breach acknowledgements and the breach rule are approved ticket items.
Actual cost counts approved entries only: approved time (at the rate kept on the entry) and approved project costs.
A breach is logged and needs an acknowledgement; whether it also blocks is the owner's setting (default: warn only)."""
from __future__ import annotations

from sqlalchemy import select

from . import budget_core as core
from .budget_models import BudgetBreach, WorkBudget
from .db import ApprovalTicket, Config, GLAccount, GLLine, Project, Task, TicketRecordEvent, User, add_audit, now
from .operating_totals import project_expense
from .time_models import TimeEntry
from .work_models import ProjectStage, TaskStructure

BUDGET_TYPES = {'budget_set', 'budget_retire', 'budget_ack', 'budget_setting'}
BUDGET_FIELDS = {'budget_set': {'project_id', 'scope', 'ref_id', 'amount_paise'}, 'budget_retire': {'budget_id'},
                 'budget_ack': {'breach_id', 'note'}, 'budget_setting': {'key', 'value'}}
ROLES = {'budget_set': ('admin', 'manager'), 'budget_retire': ('admin', 'manager'), 'budget_ack': ('admin', 'manager'),
         'budget_setting': ('admin',)}
MODE_KEY = 'budget_breach_mode'
READ_ROLES = ('admin', 'manager', 'accounts')       # a site engineer never sees a budget or a cost


def breach_mode(db):
    row = db.get(Config, MODE_KEY)
    return row.value if row and row.value in core.BREACH_MODES else 'warn'


def current_budgets(db, project_id):
    return db.scalars(select(WorkBudget).where(WorkBudget.project_id == project_id, WorkBudget.retired_at.is_(None))
                      .order_by(WorkBudget.scope, WorkBudget.ref_id)).all()


def _stage_of(db):
    return {r.task_id: r.stage_id for r in db.scalars(select(TaskStructure))}


def actuals(db, project_id):
    """{'project': paise, 'stage': {id: paise}, 'task': {id: paise}} from approved entries only."""
    stage_of = _stage_of(db)
    expenses, basis = project_expense(db, project_id)
    out = {'project': expenses, 'expense_basis': basis, 'stage': {}, 'task': {}}
    rows = db.execute(select(TimeEntry, Task.project_id).join(Task, Task.id == TimeEntry.task_id)
                      .where(Task.project_id == project_id, TimeEntry.status == 'approved', TimeEntry.cost_paise.is_not(None))).all()
    for e, _ in rows:
        out['project'] += e.cost_paise
        out['task'][e.task_id] = out['task'].get(e.task_id, 0) + e.cost_paise
        sid = stage_of.get(e.task_id)
        if sid:
            out['stage'][sid] = out['stage'].get(sid, 0) + e.cost_paise
    return out


def percent_for(db, project_id, scope, ref_id):
    q = select(Task.id, Task.progress).where(Task.project_id == project_id, Task.deleted_at.is_(None))
    rows = db.execute(q).all()
    if scope == 'task':
        rows = [r for r in rows if r[0] == ref_id]
    elif scope == 'stage':
        stage_of = _stage_of(db)
        rows = [r for r in rows if stage_of.get(r[0]) == ref_id]
    return core.percent_complete([r[1] for r in rows])


def evaluate(db, project_id):
    act = actuals(db, project_id)
    out = []
    for b in current_budgets(db, project_id):
        actual = act['project'] if b.scope == 'project' else act[b.scope].get(b.ref_id, 0)
        progress = percent_for(db, project_id, b.scope, b.ref_id)
        out.append({'budget_id': b.id, 'scope': b.scope, 'ref_id': b.ref_id, 'budget_paise': b.amount_paise,
                    'actual_paise': actual, 'percent_complete': progress,
                    'expense_basis': act['expense_basis'] if b.scope == 'project' else None,
                    **core.health(b.amount_paise, actual, progress)})
    return out


def log_breaches(db, project_id):
    """Log one open breach per budget that actual cost has passed. Called when approved cost changes."""
    made = 0
    for row in evaluate(db, project_id):
        if core.is_breach(row['budget_paise'], row['actual_paise']):
            if not db.scalar(select(BudgetBreach.id).where(BudgetBreach.budget_id == row['budget_id'], BudgetBreach.acknowledged_at.is_(None))):
                db.add(BudgetBreach(budget_id=row['budget_id'], project_id=project_id, actual_paise=row['actual_paise'],
                                    budget_paise=row['budget_paise']))
                made += 1
    db.flush()
    return made


def log_posted_breaches(db, items, results):
    """Evaluate the final project balances within the approved posting transaction."""
    journal_items = {result['journal_id']: item for item, result in zip(items, results, strict=True)
                     if isinstance(result, dict) and result.get('journal_id')}
    if not journal_items:
        return
    affected = dict(db.execute(
        select(GLLine.project_id, GLLine.journal_id).join(GLAccount, GLAccount.id == GLLine.account_id)
        .where(GLLine.journal_id.in_(journal_items), GLLine.project_id.is_not(None), GLAccount.kind == 'expense')
        .order_by(GLLine.journal_id)
    ).all())
    for project_id, journal_id in sorted(affected.items()):
        item = journal_items[journal_id]
        db.info.update(ticket_item_id=item.id, source_message_id=item.source_message_id)
        log_breaches(db, project_id)


def check_time_approval(db, entry, cost_paise):
    """In block mode, approving time that would push actual cost over a budget is refused. In warn mode it is allowed and logged."""
    if breach_mode(db) != 'block' or not entry.task_id or not cost_paise:
        return
    task = db.get(Task, entry.task_id)
    if not task:
        return
    act = actuals(db, task.project_id)
    stage_id = _stage_of(db).get(task.id)
    for b in current_budgets(db, task.project_id):
        now_actual = act['project'] if b.scope == 'project' else act[b.scope].get(b.ref_id, 0)
        applies = b.scope == 'project' or (b.scope == 'task' and b.ref_id == task.id) or (b.scope == 'stage' and b.ref_id == stage_id)
        if applies and now_actual + cost_paise > b.amount_paise:
            raise ValueError(f'Approving this time would put the {b.scope} over its budget; the owner has set breaches to block')


def _actor(db, item):
    t = db.get(ApprovalTicket, item.ticket_id) if item.ticket_id else None
    u = db.get(User, t.submitter_id) if t and t.submitter_id else None
    if not u:
        raise ValueError('The person making this change is not known')
    return u


def _int(d, key):
    if type(d.get(key)) is not int or d[key] <= 0:
        raise ValueError(f'{key} must be a record number')
    return d[key]


def _tree(db, project, replace_scope=None, replace_ref=None, new_amount=None):
    stages, tasks, proj = {}, {}, None
    stage_of = _stage_of(db)
    for b in current_budgets(db, project.id):
        if b.scope == replace_scope and b.ref_id == replace_ref:
            continue
        if b.scope == 'project':
            proj = b.amount_paise
        elif b.scope == 'stage':
            stages[b.ref_id] = b.amount_paise
        else:
            tasks[b.ref_id] = (stage_of.get(b.ref_id), b.amount_paise)
    if new_amount is not None:
        if replace_scope == 'project':
            proj = new_amount
        elif replace_scope == 'stage':
            stages[replace_ref] = new_amount
        else:
            tasks[replace_ref] = (stage_of.get(replace_ref), new_amount)
    return proj, stages, tasks


def validate(db, item):
    kind, d = item.item_type, item.after_data
    if kind not in BUDGET_TYPES:
        raise ValueError('Unsupported item type')
    if not isinstance(d, dict) or set(d) - BUDGET_FIELDS[kind]:
        raise ValueError('Unrecognized ticket data')
    if _actor(db, item).role not in ROLES[kind]:
        raise ValueError('Your role may not make this change')
    return globals()['_v_' + kind](db, d)


def _v_budget_set(db, d):
    p = db.get(Project, _int(d, 'project_id'))
    if not p or p.deleted_at:
        raise ValueError('That project does not exist')
    scope = d.get('scope')
    if scope not in core.SCOPES:
        raise ValueError('Budget scope must be project, stage or task')
    ref = 0 if scope == 'project' else _int(d, 'ref_id')
    if scope == 'project' and d.get('ref_id') not in (None, 0):
        raise ValueError('A project budget has no reference')
    if scope == 'stage':
        st = db.get(ProjectStage, ref)
        if not st or st.deleted_at or st.project_id != p.id:
            raise ValueError('That stage is not in this project')
    if scope == 'task':
        t = db.get(Task, ref)
        if not t or t.deleted_at or t.project_id != p.id:
            raise ValueError('That task is not in this project')
    core.check_amount(d.get('amount_paise'))
    proj, stages, tasks = _tree(db, p, scope, ref, d['amount_paise'])
    core.check_tree(proj, stages, tasks)
    return scope, ref


def _v_budget_retire(db, d):
    row = db.get(WorkBudget, _int(d, 'budget_id'))
    if not row or row.retired_at:
        raise ValueError('That budget does not exist or was already retired')
    p = db.get(Project, row.project_id)
    if row.scope != 'project':
        return
    if any(b.scope != 'project' for b in current_budgets(db, row.project_id)):
        raise ValueError('Retire the stage and task budgets first, or replace the project budget instead')


def _v_budget_ack(db, d):
    row = db.get(BudgetBreach, _int(d, 'breach_id'))
    if not row or row.acknowledged_at:
        raise ValueError('That breach does not exist or was already acknowledged')
    if not isinstance(d.get('note'), str) or len(d['note'].strip()) < 5:
        raise ValueError('An acknowledgement needs a note of at least 5 characters')


def _v_budget_setting(db, d):
    if d.get('key') != MODE_KEY:
        raise ValueError('Unknown budget setting')
    core.check_mode(d.get('value'))


def apply(db, item, actor):
    validate(db, item)
    d, kind = item.after_data, item.item_type
    if kind == 'budget_set':
        scope, ref = d['scope'], 0 if d['scope'] == 'project' else d['ref_id']
        for old in db.scalars(select(WorkBudget).where(WorkBudget.project_id == d['project_id'], WorkBudget.scope == scope,
                                                       WorkBudget.ref_id == ref, WorkBudget.retired_at.is_(None))):
            old.retired_at = now()
        row = WorkBudget(project_id=d['project_id'], scope=scope, ref_id=ref, amount_paise=d['amount_paise'], set_by=actor)
        db.add(row)
        db.flush()
        log_breaches(db, d['project_id'])
        entity, op = 'work_budget', 'create'
    elif kind == 'budget_retire':
        row = db.get(WorkBudget, d['budget_id'])
        row.retired_at = now()
        entity, op = 'work_budget', 'update'
    elif kind == 'budget_ack':
        row = db.get(BudgetBreach, d['breach_id'])
        row.acknowledged_by, row.acknowledged_at, row.note = actor, now(), d['note'].strip()
        entity, op = 'budget_breach', 'update'
    else:
        row = db.get(Config, MODE_KEY)
        if row:
            row.value = d['value']
        else:
            db.add(Config(key=MODE_KEY, value=d['value']))
            db.flush()
        class _R:   # settings have no row id of their own
            id = 0
        row = _R
        entity, op = 'setting', 'update'
    db.add(TicketRecordEvent(ticket_id=item.ticket_id, item_id=item.id, entity_type=entity, entity_id=row.id, operation=op))
    add_audit(db, 'ticket_commit', entity, row.id, f'Ticket #{item.ticket_id}, item #{item.id}: {kind}', actor=actor)
    db.flush()
    return {'type': entity, 'id': row.id, 'item_id': item.id}
