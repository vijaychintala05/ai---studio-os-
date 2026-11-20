"""Ready-made view specs (UI/UX plan: default templates). Each is plain ViewSpec data on record types StudioOS already has (tasks and the Work
business pack: work issues, milestones, meeting notes, timesheet entries). Nothing here is written to a live database: a person (or an AI
client) proposes one as a view_create ticket and another person approves it, like any view. A template is offered only when every record
type and field it uses exists in this firm's catalog, so a firm that has not installed the Work pack is simply not offered those.
Templates that need data StudioOS does not hold yet (deliverables, BOQ, attendance, the ledger as a view source, a task start date) are
not here; the missing source for each is listed in HELD_FOR_OWNER.md."""
from __future__ import annotations

from . import viewspec_core as core

SPEC = 1


def _spec(spec_id, name, primitive, record_type, fields, **extra):
    s = {'spec_version': SPEC, 'id': spec_id, 'name': name, 'primitive': primitive,
         'source': {'items': [{'record_type': record_type, 'fields': [{'field': f} for f in fields]}]}}
    s['source']['items'][0].update(extra.pop('item', {}))
    s.update(extra)
    return s


TEMPLATES = [
    {'key': 'task_board', 'title': 'Tasks by status', 'about': 'Every open task in columns by status.', 'scope': 'system',
     'spec': _spec('tpl.task_board', 'Tasks by status', 'board', 'system.task', ['title', 'assignee', 'due_date', 'status'],
                   group={'columns': {'field': 'status'}}, actions=['open', 'move_status'], layout={'card': 'compact'},
                   item={'sort': [{'field': 'due_date', 'dir': 'asc'}]})},
    {'key': 'overdue_tasks', 'title': 'Overdue tasks', 'about': 'Tasks past their due date and not done, oldest first.', 'scope': 'system',
     'spec': _spec('tpl.overdue_tasks', 'Overdue tasks', 'table', 'system.task', ['title', 'assignee', 'due_date', 'status'],
                   colour=[{'when': {'field': 'status', 'op': 'neq', 'value': 'done'}, 'token': 'danger'}],
                   item={'filter': {'and': [{'field': 'status', 'op': 'neq', 'value': 'done'}, {'field': 'due_date', 'op': 'before', 'value': {'relative': 'today'}}]},
                         'sort': [{'field': 'due_date', 'dir': 'asc'}]})},
    {'key': 'task_calendar', 'title': 'Task calendar', 'about': 'Tasks on the days they are due.', 'scope': 'system',
     'spec': _spec('tpl.task_calendar', 'Task calendar', 'calendar', 'system.task', ['title', 'assignee', 'due_date'],
                   layout={'date_field': 'due_date'}, item={'filter': {'and': [{'field': 'status', 'op': 'neq', 'value': 'done'}]}})},
    {'key': 'snag_board', 'title': 'Snags by status', 'about': 'Open snags in columns by status, urgent first.', 'scope': 'system',
     'spec': _spec('tpl.snag_board', 'Snags by status', 'board', 'work_issue', ['title', 'severity', 'due_date', 'issue_status'],
                   group={'columns': {'field': 'issue_status'}}, actions=['open', 'move_status'], layout={'card': 'compact'},
                   colour=[{'when': {'field': 'severity', 'op': 'eq', 'value': 'Critical'}, 'token': 'danger'}, {'when': {'field': 'severity', 'op': 'eq', 'value': 'High'}, 'token': 'warning'}],
                   item={'filter': {'and': [{'field': 'issue_status', 'op': 'neq', 'value': 'Closed'}]}})},
    {'key': 'snags_by_severity', 'title': 'Snags by severity', 'about': 'How many open snags there are at each severity.', 'scope': 'system',
     'spec': _spec('tpl.snags_by_severity', 'Snags by severity', 'chart', 'work_issue', ['title'], group={'columns': {'field': 'severity'}},
                   aggregate=[{'fn': 'count', 'as': 'n'}], item={'filter': {'and': [{'field': 'issue_status', 'op': 'neq', 'value': 'Closed'}]}})},
    {'key': 'milestones', 'title': 'Milestones calendar', 'about': 'Project milestones on their due dates.', 'scope': 'system',
     'spec': _spec('tpl.milestones', 'Milestones calendar', 'calendar', 'milestone', ['title', 'milestone_status', 'due_date'], layout={'date_field': 'due_date'},
                   colour=[{'when': {'field': 'milestone_status', 'op': 'eq', 'value': 'Delayed'}, 'token': 'danger'}])},
    {'key': 'site_visits', 'title': 'Meetings and site visits', 'about': 'Meeting notes on the days they happen (agenda on a phone).', 'scope': 'system',
     'spec': _spec('tpl.site_visits', 'Meetings and site visits', 'calendar', 'meeting_note', ['meeting_type', 'attendees', 'meeting_date'], layout={'date_field': 'meeting_date'})},
    {'key': 'timesheets', 'title': 'Timesheet entries', 'about': 'Hours logged by activity, newest first.', 'scope': 'system',
     'spec': _spec('tpl.timesheets', 'Timesheet entries', 'table', 'timesheet_entry', ['employee', 'work_date', 'hours', 'activity'], item={'sort': [{'field': 'work_date', 'dir': 'desc'}]})},
]


def available(catalog):
    """The templates every one of whose record types and fields exist in this firm's catalog (the spec is validated, not just looked up)."""
    out = []
    for t in TEMPLATES:
        try:
            core.validate_spec(t['spec'], catalog)
        except core.SpecError:
            continue
        out.append(t)
    return out


def by_key(key):
    return next((t for t in TEMPLATES if t['key'] == key), None)
