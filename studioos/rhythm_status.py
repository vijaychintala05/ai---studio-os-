"""The 7 pm evening status: a person replies in their own words, the sorting step files each piece under an evening heading, and where a
piece clearly matches something StudioOS holds it becomes a DRAFT ticket (a person approves it later). Nothing is saved from here.
- Tasks Completed: a piece that names one of the person's open tasks becomes an update_task draft marking it done.
- Project & Site Progress: a piece that names a project the person can see becomes a site-report draft.
- Everything else is kept in the answer as a sorted note; financial pieces are never turned into entries here (they go through the
  chat so the entry is made with its full details). The AI may later improve the sorting; it never approves anything."""
from __future__ import annotations

import re

from sqlalchemy import select

from . import sorting_core as sc
from .access import visible_project_ids
from .db import Project, Task

STOP = {'the', 'a', 'an', 'at', 'in', 'on', 'of', 'for', 'to', 'and', 'is', 'was', 'done', 'completed', 'complete', 'finished', 'ho', 'gaya', 'hai'}


def _words(text):
    return {w for w in re.findall(r'[a-z0-9]+', str(text).casefold()) if len(w) > 2 and w not in STOP}


def match_task(db, user, piece):
    """The person's single open task a piece is about, or None (zero or several matches are not guessed)."""
    names = {n for n in (user.display_name, user.username) if n}
    rows = db.scalars(select(Task).where(Task.assignee.in_(names), Task.deleted_at.is_(None), Task.status.notin_(['done', 'closed', 'cancelled']))).all()
    pw = _words(piece)
    scored = []
    for t in rows:
        tw = _words(t.title)
        if not tw:
            continue
        hit = len(pw & tw)
        if hit >= min(2, len(tw)) and hit / len(tw) >= 0.6:
            scored.append((hit, t))
    scored.sort(key=lambda x: -x[0])
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


def match_project(db, user, piece):
    allowed = visible_project_ids(db, user)
    low = str(piece).casefold()
    hits = [p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))) if p.name.casefold() in low and (allowed is None or p.id in allowed)]
    return hits[0] if len(hits) == 1 else None


def process(db, user, text):
    """-> {'pieces': [...], 'drafts': n}. Each piece: text, category, label, needs_review, action ('draft'|'note'|'ask'), ticket_id, detail."""
    from .main import _manual_draft
    out, drafts = [], 0
    for p in sc.sort_reply(text):
        row = {**p, 'action': 'ask' if p['needs_review'] else 'note', 'ticket_id': None, 'detail': ''}
        if not p['needs_review'] and user.role != 'viewer':
            try:
                if p['category'] == 'task_done':
                    t = match_task(db, user, p['text'])
                    if t:
                        d = _manual_draft(db, user, 'update_task', {'id': t.id, 'project': t.project_id, 'title': t.title, 'assignee': t.assignee,
                                                                    'due_date': t.due_date, 'status': 'done', 'progress': 100},
                                          evidence='Evening status: ' + p['text'])
                        row.update(action='draft', ticket_id=d['ticket_id'], detail=f'Task #{t.id} {t.title} marked done, waiting for approval')
                        drafts += 1
                    else:
                        row['detail'] = 'No single open task of yours matches; tell me which task, or mark it from Tasks'
                elif p['category'] == 'progress':
                    proj = match_project(db, user, p['text'])
                    if proj:
                        d = _manual_draft(db, user, 'site_update', {'project': proj.id, 'note': p['text']}, evidence='Evening status: ' + p['text'])
                        row.update(action='draft', ticket_id=d['ticket_id'], detail=f'Site note for {proj.name}, waiting for approval')
                        drafts += 1
                    else:
                        row['detail'] = 'Name the project to make this a site note'
                elif p['category'] == 'financial':
                    row['detail'] = 'Not entered from here. Send it in the chat so it is recorded with its full details'
                else:
                    row['detail'] = 'Kept for your evening summary'
            except ValueError as ex:      # a rule refused it (for example an earlier task is still open); say so, save nothing
                row.update(action='note', detail=str(ex)[:200])
        elif p['needs_review']:
            row['detail'] = 'Not sure which heading this belongs under'
        out.append(row)
    return {'pieces': out, 'drafts': drafts}
