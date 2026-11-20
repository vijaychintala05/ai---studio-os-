"""v0.19 daily rhythm, pure logic (no database, no web, no AI). The morning to-do list and the on-track / at-risk /
delayed judgement are computed from dates and dependencies only, so they are facts, not guesses. The AI may later
phrase them; it never moves a task, lifts a block or approves anything.
"""
from __future__ import annotations

import datetime as dt

CLOSED = ('done', 'closed', 'cancelled')
AT_RISK_DAYS = 3          # a blocked task due within this many days makes a project "at risk" (a proposed default)
MORNING_HOUR, MORNING_MINUTE = 8, 30       # from the plan
OWNER_HOUR, OWNER_MINUTE = 20, 0           # proposed: after the 7 pm status, before the 9 pm quiet hours
QUIET_START_HOUR, QUIET_END_HOUR = 21, 8   # quiet hours stay 9 pm to 8 am


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def open_blockers(task_id, links, status_of):
    """Open hard predecessors of a task. links: [{'predecessor_id','successor_id','kind'}]."""
    return sorted(l['predecessor_id'] for l in links
                  if l['successor_id'] == task_id and l['kind'] == 'hard' and status_of.get(l['predecessor_id'], 'open') not in CLOSED)


def has_hard_predecessor(task_id, links):
    return any(l['successor_id'] == task_id and l['kind'] == 'hard' for l in links)


def morning_todos(tasks, links, status_of, today):
    """One person's list for the day. tasks: their open tasks [{'id','title','due','project'}]. Order: overdue (oldest first),
    due today, then ready to start (every earlier task it depends on is done). Blocked tasks are shown with the blocker."""
    out = []
    for t in tasks:
        if status_of.get(t['id'], 'open') in CLOSED:
            continue
        due = _date(t.get('due'))
        blockers = open_blockers(t['id'], links, status_of)
        if due and due < today:
            reason = 'overdue'
        elif due and due == today:
            reason = 'due_today'
        elif has_hard_predecessor(t['id'], links) and not blockers:
            reason = 'ready'
        else:
            continue
        out.append({'task_id': t['id'], 'title': t['title'], 'project': t.get('project', ''), 'reason': reason,
                    'due': t.get('due') or '', 'blocked_by': blockers})
    rank = {'overdue': 0, 'due_today': 1, 'ready': 2}
    out.sort(key=lambda x: (rank[x['reason']], x['due'] or '9999', x['task_id']))
    return out


def project_health(tasks, links, today):
    """tasks: a project's tasks [{'id','title','due','status'}]. Returns {'status','blocking','overdue','open'}.
    delayed: some open task is past due (the oldest is named). at_risk: not delayed, but a task due within AT_RISK_DAYS
    is still blocked by an open hard predecessor (that task and its blocker are named). Otherwise on_track."""
    status_of = {t['id']: t.get('status', 'open') for t in tasks}
    by_id = {t['id']: t for t in tasks}
    open_tasks = [t for t in tasks if t.get('status', 'open') not in CLOSED]
    overdue = sorted((t for t in open_tasks if _date(t.get('due')) and _date(t['due']) < today),
                     key=lambda t: (t['due'], t['id']))
    if overdue:
        t = overdue[0]
        return {'status': 'delayed', 'overdue': len(overdue), 'open': len(open_tasks),
                'blocking': {'task_id': t['id'], 'title': t['title'], 'reason': f"overdue since {t['due']}"}}
    horizon = today + dt.timedelta(days=AT_RISK_DAYS)
    risky = []
    for t in open_tasks:
        due = _date(t.get('due'))
        if due and due <= horizon:
            blockers = open_blockers(t['id'], links, status_of)
            if blockers:
                risky.append((t['due'], t['id'], blockers[0]))
    if risky:
        due, tid, blocker = sorted(risky)[0]
        return {'status': 'at_risk', 'overdue': 0, 'open': len(open_tasks),
                'blocking': {'task_id': tid, 'title': by_id[tid]['title'],
                             'reason': f"due {due} but waiting for #{blocker} {by_id.get(blocker, {}).get('title', '')}".strip()}}
    return {'status': 'on_track', 'overdue': 0, 'open': len(open_tasks), 'blocking': None}


LABELS = {'on_track': 'On track', 'at_risk': 'At risk', 'delayed': 'Delayed'}
REASONS = {'overdue': 'overdue', 'due_today': 'due today', 'ready': 'ready to start', 'snag': 'open snag'}
SNAG_TYPE = 'work_issue'                                   # the Work pack's issue record (its alias is "snag")
SNAG_CLOSED = {'resolved', 'closed', 'verified', 'fixed'}   # any status that means no more work is waiting on the owner


def snag_items(records, user_id, today):
    """A person's open snags for the morning list. records: [{'id','data','project'}] of snag records. A snag is theirs when its
    owner is them and its status is not a closed one. Oldest due date first; undated snags last."""
    out = []
    for r in records:
        d = r.get('data') or {}
        if d.get('owner') != user_id or str(d.get('issue_status', '')).casefold() in SNAG_CLOSED:
            continue
        out.append({'task_id': None, 'snag_id': r['id'], 'title': str(d.get('title', 'Snag')), 'project': r.get('project', ''),
                    'reason': 'snag', 'due': str(d.get('due_date') or ''), 'blocked_by': [], 'severity': str(d.get('severity', ''))})
    out.sort(key=lambda x: (x['due'] or '9999', x['snag_id']))
    return out


def morning_text(name, items, today):
    if not items:
        return f'Good morning {name}. Nothing is due today or waiting to start ({today.isoformat()}).'
    lines = [f'Good morning {name}. Your tasks for {today.isoformat()}:']
    for i in items:
        extra = f" (waiting for {', '.join('#' + str(b) for b in i['blocked_by'])})" if i['blocked_by'] else ''
        label = f"snag #{i['snag_id']}" if i['reason'] == 'snag' else f"#{i['task_id']}"
        lines.append(f"- {label} {i['title']}: {REASONS[i['reason']]}{extra}")
    return '\n'.join(lines)


def owner_text(project_name, health, today):
    line = f"{project_name} on {today.isoformat()}: {LABELS[health['status']]}. {health['open']} open task(s), {health['overdue']} overdue."
    if health['blocking']:
        b = health['blocking']
        line += f" Blocking: #{b['task_id']} {b['title']} ({b['reason']})."
    return line


def job_due(job_time, last_run_date, local_now):
    """A rhythm job runs once a day, at or after its time, never in quiet hours."""
    h, m = job_time
    if local_now.hour >= QUIET_START_HOUR or local_now.hour < QUIET_END_HOUR:
        return False
    if (local_now.hour, local_now.minute) < (h, m):
        return False
    return last_run_date is None or last_run_date < local_now.date()


# ------------------------------------------------------------------ the sectioned morning and evening summaries (owner's headings)

MORNING_HEADINGS = ('Urgent & Critical Issues', "Today's Priorities", 'Overdue Tasks', 'Meetings & Follow-ups', 'Pending Approvals',
                    'Payments & Purchases', 'Project Plans & Dependencies')
EVENING_HEADINGS = ('Critical Unresolved Issues', 'Tasks Completed', 'Pending & Overdue Tasks', 'Project & Site Progress',
                    'Decisions & Approvals', 'Financial Transactions', "Tomorrow's Priorities")
EVENING_HOUR, EVENING_MINUTE = 20, 0       # the evening summary goes out with the owner summary, before quiet hours
URGENT_OVERDUE_DAYS = 7                    # a task this many days overdue counts as urgent (a proposed default)
URGENT_SEVERITIES = {'critical', 'high'}


def _days_late(due, today):
    d = _date(due)
    return (today - d).days if d else 0


def urgent(todos, today):
    """Critical or high snags, and tasks overdue for URGENT_OVERDUE_DAYS or more."""
    out = []
    for i in todos:
        if i['reason'] == 'snag' and str(i.get('severity', '')).casefold() in URGENT_SEVERITIES:
            out.append(i)
        elif i['reason'] == 'overdue' and _days_late(i['due'], today) >= URGENT_OVERDUE_DAYS:
            out.append(i)
    return out


def item_line(i, today=None):
    label = f"snag #{i['snag_id']}" if i['reason'] == 'snag' else f"#{i['task_id']}"
    bits = [f"{label} {i['title']}"]
    if i.get('project'):
        bits.append(f"({i['project']})")
    if i.get('due'):
        bits.append(f"due {i['due']}")
    if i.get('blocked_by'):
        bits.append('waiting for ' + ', '.join('#' + str(b) for b in i['blocked_by']))
    return ' '.join(bits)


def render_summary(greeting, today, headings, sections, per_section=8):
    """sections: {heading: [lines]}. Every heading is printed; an empty one says Nothing. Long lists are cut with a count."""
    out = [f'{greeting} ({today.isoformat()})']
    for h in headings:
        lines = [l for l in sections.get(h, []) if l]
        out.append(f'{h}:')
        if not lines:
            out.append('  Nothing.')
        for l in lines[:per_section]:
            out.append(f'  - {l}')
        if len(lines) > per_section:
            out.append(f'  ... and {len(lines) - per_section} more')
    return chr(10).join(out)


def has_content(sections):
    return any(sections.get(k) for k in sections)
