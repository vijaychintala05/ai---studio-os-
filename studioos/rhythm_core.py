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
REASONS = {'overdue': 'overdue', 'due_today': 'due today', 'ready': 'ready to start'}


def morning_text(name, items, today):
    if not items:
        return f'Good morning {name}. Nothing is due today or waiting to start ({today.isoformat()}).'
    lines = [f'Good morning {name}. Your tasks for {today.isoformat()}:']
    for i in items:
        extra = f" (waiting for {', '.join('#' + str(b) for b in i['blocked_by'])})" if i['blocked_by'] else ''
        lines.append(f"- #{i['task_id']} {i['title']}: {REASONS[i['reason']]}{extra}")
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
