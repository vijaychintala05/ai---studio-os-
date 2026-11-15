"""Record types and the waiting area (v0.9.0).

A new kind of information goes:  captured -> waiting (with a build request) ->
built (Admin approves; becomes a record type) -> waiting entries checked and
drafted -> each draft approved -> saved.

Records of a built type are stored in flexible_records (record_type = key) and
are checked against the approved design on every save. No database structure
is created, so building a type can never damage existing data.
"""
from __future__ import annotations
import datetime as dt
import re
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import (RecordType, NewTypeInbox, ApprovalTicket, ApprovalTicketItem, ChatSession, ChatMessage,
                 Project, FlexibleRecord, TicketRecordLink, add_audit, now)
from .field_spec import validate_record
from . import chat_ux
from .record_logic import (NO_PROJECT, is_no_project, user_fields, field_label, _norm, _date_from, prefill, display,
                           coerce_value, title_match_score)

DONE_STATES = ('rejected', 'revoked_design_only', 'kept')
UTC = dt.timezone.utc
REMIND_AFTER_DAYS = 7


# ------------------------------------------------------------------ types

def active_types(db: Session) -> dict[str, RecordType]:
    return {rt.key: rt for rt in db.scalars(select(RecordType).where(RecordType.status == 'active')).all()}


def match_active_type(db: Session, message: str) -> RecordType | None:
    """Does this message belong to a built type? 'Log site-visit feedback for Mehta Villa'
    matches 'client site-visit feedback'."""
    best, best_score = None, 0
    for rt in active_types(db).values():
        score = title_match_score(rt.title, message)
        if (rt.design or {}).get('runtime_fields') is not None:
            # v0.10.0: a universal type's approved aliases count too ("timesheet", "SOP checklist").
            score = max([score] + [title_match_score(a, message) for a in (rt.design or {}).get('aliases') or []])
        if score > best_score:
            best, best_score = rt, score
    return best


def to_record(db: Session, details: dict) -> dict:
    """The ticket's draft as the design sees it: data fields plus the project link."""
    record = {k: v for k, v in (details.get('data') or {}).items()}
    ref = details.get('project')
    project = None
    if is_no_project(ref):
        record['not_project_related'] = True
        return record
    if ref:
        project = db.get(Project, ref) if isinstance(ref, int) else next(
            (p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all() if p.name.casefold() == str(ref).casefold()), None)
    if project:
        record['project_id'] = project.id
    return record


def missing_fields(db: Session, rt: RecordType, details: dict, level='approve') -> list[dict]:
    """Fields that block approval, in plain words."""
    result = validate_record(rt.design, to_record(db, details), level)
    labels = {f['name']: field_label(f) for f in rt.design['fields']}
    out = []
    for b in result['blocking']:
        name = 'project' if b['field'] in ('project_id', 'not_project_related') else b['field']
        if any(x['name'] == name for x in out):
            continue
        out.append({'name': name, 'key': 'project' if name == 'project' else 'data.' + name,
                    'label': 'Project' if name == 'project' else labels.get(name, name), 'reason': b['reason']})
    return out


def check_generic(db: Session, details: dict) -> None:
    """Server-enforced rules for a built type. Raises ValueError naming what is missing."""
    key = str(details.get('record_type') or '')
    rt = db.get(RecordType, key)
    if rt is None:
        # v0.9.1 (audit F-03): fail closed. Only StudioOS's built-in reference notes
        # (category budget, site observation ...) or an Admin-built type may be saved.
        from .new_types import SUPPORTED_FLEXIBLE_REFERENCE_TYPES
        if key not in SUPPORTED_FLEXIBLE_REFERENCE_TYPES:
            raise ValueError('"' + key[:60] + '" is not an approved kind of record. New kinds of records must be built by the Admin first.')
        return
    if rt.status != 'active':
        raise ValueError(rt.title + ' is no longer accepted (its design was undone)')
    from .db import SchemaDesign
    approved = db.scalar(select(SchemaDesign).where(SchemaDesign.inbox_id == rt.source_inbox_id,
                                                    SchemaDesign.status == 'approved_design_only')) if rt.source_inbox_id else None
    if rt.source_inbox_id is None and (rt.design or {}).get('runtime_approval_ticket_id'):
        # Runtime metadata types use the SAME ticket approval mechanism but were not
        # discovered through the Stage-A inbox; their committed ticket is authoritative.
        from .db import ApprovalTicketItem
        tid=rt.design['runtime_approval_ticket_id']
        ticket=db.get(ApprovalTicket,tid)
        valid=bool(ticket and ticket.status=='committed' and db.scalar(select(ApprovalTicketItem.id).where(
            ApprovalTicketItem.ticket_id==tid, ApprovalTicketItem.item_type=='metadata_type',
            ApprovalTicketItem.status=='approved')))
        if not valid:raise ValueError('Runtime type is missing a committed Admin approval')
        # The existing chat ticket path does not know the richer runtime primitives.
        # Validation occurs in universal_engine.normalize_values instead.
        raise ValueError('Use the universal record ticket API for this metadata-defined type')
    if approved is None or approved.design.get('table_name') != rt.key:
        raise ValueError(rt.title + ' has no matching Admin-approved design; it cannot be used')
    if approved.design.get('fields') != rt.design.get('fields'):
        raise ValueError(rt.title + ' differs from its approved design; it cannot be used')
    data = details.get('data') or {}
    allowed = {f['name'] for f in user_fields(rt.design)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError('Not part of ' + rt.title + ': ' + ', '.join(sorted(unknown)))
    try:
        missing = missing_fields(db, rt, details)
    except ValueError as ex:
        raise ValueError(str(ex))
    if missing:
        raise ValueError('Still needed for ' + rt.title + ': ' + ', '.join(m['label'] for m in missing))


def coerce_field(rt: RecordType, name: str, value):
    f = next((x for x in user_fields(rt.design) if x['name'] == name), None)
    if f is None:
        raise ValueError('That detail is not part of ' + rt.title)
    return coerce_value(f, value)


def card_fields(db: Session, rt: RecordType, item: dict) -> list[dict]:
    after = item.get('after') or {}
    data = after.get('data') or {}
    evidence = item.get('field_evidence') or {}
    blocking = {m['key'] for m in missing_fields(db, rt, after)}
    fields = [{'key': 'project', 'label': 'Project', 'display': str(after.get('project') or '—'), 'raw': after.get('project'),
               'type': 'text', 'marker': (evidence.get('project') or {}).get('marker') or ('missing' if 'project' in blocking or not after.get('project') else 'guessed'),
               'source': (evidence.get('project') or {}).get('source_words')}]
    for f in user_fields(rt.design):
        key = 'data.' + f['name']
        v = data.get(f['name'])
        marker = (evidence.get(key) or {}).get('marker') or ('missing' if key in blocking or v in (None, '') else 'guessed')
        fields.append({'key': key, 'label': field_label(f), 'display': display(f, v), 'raw': v, 'type': f.get('type') or 'text',
                       'required': f.get('required_level'), 'marker': marker, 'source': (evidence.get(key) or {}).get('source_words')})
    return fields


def record_line(rt: RecordType, details: dict) -> str:
    data = details.get('data') or {}
    parts = [rt.title[:1].upper() + rt.title[1:]]
    if details.get('project'):
        parts.append(str(details['project']))
    for f in user_fields(rt.design)[:3]:
        v = data.get(f['name'])
        if v not in (None, ''):
            parts.append(display(f, v)[:40])
    return ' · '.join(parts)


def asks_for(db: Session, rt: RecordType, item_id: int, details: dict, visible_projects=()) -> list[dict]:
    """Tap-to-answer questions for whatever still blocks approval."""
    asks = []
    fields = {f['name']: f for f in user_fields(rt.design)}
    for m in missing_fields(db, rt, details):
        if m['name'] == 'project':
            choices = [{'label': p, 'value': p} for p in visible_projects][:6] + [{'label': NO_PROJECT, 'value': NO_PROJECT}]
            asks.append({'id': 'project', 'text': 'Which project is this for?', 'field': 'project', 'item_id': item_id,
                         'choices': choices, 'free_text': False})
            continue
        f = fields.get(m['name'], {})
        if f.get('type') == 'boolean':
            choices = [{'label': 'Yes', 'value': True}, {'label': 'No', 'value': False}]
        elif f.get('allowed_values'):
            choices = [{'label': str(v), 'value': v} for v in f['allowed_values']][:8]
        elif f.get('type') == 'integer' and f.get('min') is not None and f.get('max') is not None and f['max'] - f['min'] <= 9:
            choices = [{'label': str(n), 'value': n} for n in range(int(f['min']), int(f['max']) + 1)]
        else:
            choices = []
        asks.append({'id': m['key'], 'text': m['label'] + '?', 'field': m['key'], 'item_id': item_id,
                     'choices': choices, 'free_text': not choices})
    return asks


# ------------------------------------------------------------------ waiting area

def request_id_of(entry: NewTypeInbox) -> int | None:
    if entry.proposed_design:
        return entry.id
    if entry.state == 'reuse_existing_proposal':
        props = (entry.match_review or {}).get('existing_proposals') or []
        return props[0].get('inbox_id') if props else None
    return None


def entry_status(db: Session, entry: NewTypeInbox) -> dict:
    back = (entry.match_review or {}).get('backfill') or {}
    if back.get('skipped'):
        return {'status': 'nothing_to_add', 'note': 'This message described the kind of information but held no values to add.'}
    item = db.get(ApprovalTicketItem, back['item_id']) if back.get('item_id') else None
    if item is None:
        return {'status': 'waiting'}
    ticket = db.get(ApprovalTicket, item.ticket_id)
    if item.status == 'rejected':
        return {'status': 'waiting', 'note': 'Not added: ' + (item.review_note or 'rejected at review'), 'ticket_id': ticket.id}
    if ticket.status == 'committed' and item.status == 'approved':
        link = db.scalar(select(TicketRecordLink).where(TicketRecordLink.item_id == item.id))
        return {'status': 'added', 'ticket_id': ticket.id, 'record_id': link.entity_id if link else None}
    if ticket.status == 'reversed':
        return {'status': 'undone', 'ticket_id': ticket.id}
    return {'status': 'drafted', 'ticket_id': ticket.id, 'session_id': back.get('session_id')}


def _age_days(t, at) -> int:
    if t is None:
        return 0
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return max(0, (at - t).days)


def waiting_overview(db: Session, user, project_names=()) -> dict:
    at = now()
    q = select(NewTypeInbox).order_by(NewTypeInbox.id)
    if user.role not in ('admin', 'manager'):
        q = q.where(NewTypeInbox.user_id == user.id)
    entries = db.scalars(q).all()
    types_by_source = {rt.source_inbox_id: rt for rt in db.scalars(select(RecordType)).all() if rt.source_inbox_id}
    groups, others = {}, []
    for e in entries:
        rid = request_id_of(e)
        if rid is None:
            if e.state not in DONE_STATES:
                others.append({'id': e.id, 'state': e.state, 'text': (e.raw_payload or {}).get('text', '')[:200],
                               'created_at': e.created_at.isoformat(), 'decision': (e.match_review or {}).get('decision')})
            continue
        groups.setdefault(rid, []).append(e)
    out = []
    for rid, members in groups.items():
        request = db.get(NewTypeInbox, rid)
        if request is None or not request.proposed_design:
            continue
        rt = types_by_source.get(rid)
        design = rt.design if rt else request.proposed_design
        statuses = [entry_status(db, m) for m in members]
        state = ('built' if rt and rt.status == 'active' else 'retired' if rt else
                 'rejected' if request.state == 'rejected' else 'kept' if request.state == 'kept' else 'waiting_for_approval')
        oldest = min(m.created_at for m in members)
        samples = []
        for m in members[:3]:
            data, _, project = prefill(design, (m.raw_payload or {}).get('text', ''), project_names,
                                       today=(m.created_at.date() if m.created_at else None))
            samples.append({'entry_id': m.id, 'project': project, 'values': {f['name']: display(f, data.get(f['name'])) for f in user_fields(design)}})
        unanswered = [{'id': q['id'], 'text': q['text']} for q in (request.questions or []) if q['id'] not in (request.answers or {})]
        out.append({
            'request_id': rid, 'title': (rt.title if rt else design.get('description') or design.get('table_name')),
            'key': rt.key if rt else design.get('table_name'), 'state': state,
            'purpose': (request.answers or {}).get('purpose') or design.get('purpose'),
            'why_needed': (f"{len(members)} {'entry is' if len(members) == 1 else 'entries are'} waiting with no place to be stored."
                           if state == 'waiting_for_approval' else
                           f"{len(members)} {'entry was' if len(members) == 1 else 'entries were'} kept here before this was decided."),
            'entries': len(members), 'waiting': sum(s['status'] == 'waiting' for s in statuses),
            'nothing_to_add': sum(s['status'] == 'nothing_to_add' for s in statuses),
            'drafted': sum(s['status'] == 'drafted' for s in statuses), 'added': sum(s['status'] == 'added' for s in statuses),
            'oldest_days': _age_days(oldest, at), 'remind': state == 'waiting_for_approval' and _age_days(oldest, at) >= REMIND_AFTER_DAYS,
            'fields': [{'name': f['name'], 'label': field_label(f), 'type': f.get('type'), 'required': f.get('required_level')} for f in user_fields(design)],
            'samples': samples, 'unanswered_questions': unanswered,
            'impact': 'Adds a new kind of record. Changes nothing in your existing data and creates no database tables.',
            'entry_list': [{'id': m.id, 'text': (m.raw_payload or {}).get('text', '')[:240], 'created_at': m.created_at.isoformat(), **s}
                           for m, s in zip(members, statuses)],
        })
    out.sort(key=lambda g: (g['state'] != 'waiting_for_approval', -g['oldest_days']))
    return {'requests': out, 'other_parked': others,
            'reminders': [g for g in out if g['remind']]}


def build_request_for(db: Session, user, entry: NewTypeInbox, project_names=()) -> dict | None:
    rid = request_id_of(entry)
    if rid is None:
        return None
    return next((g for g in waiting_overview(db, user, project_names)['requests'] if g['request_id'] == rid), None)


def backfill(db: Session, actor, project_names=(), keys=None) -> list[dict]:
    """Check the waiting area against every built type and draft what can be added.
    Drafts are tickets: nothing is saved until someone approves them."""
    from .tickets import add_proposal
    summaries = []
    for rt in active_types(db).values():
        if keys and rt.key not in keys:
            continue
        candidates = [e for e in db.scalars(select(NewTypeInbox).order_by(NewTypeInbox.id)).all()
                      if request_id_of(e) == rt.source_inbox_id and not (e.match_review or {}).get('backfill')]
        members, prepared = [], {}
        for e in candidates:
            raw = (e.raw_payload or {}).get('text', '')
            data, evidence, project = prefill(rt.design, raw, project_names, today=(e.created_at.date() if e.created_at else None))
            if not data:
                # A description of the kind of information, not an entry of it.
                review = dict(e.match_review or {})
                review['backfill'] = {'skipped': 'no_values', 'at': now().isoformat()}
                e.match_review = review
                continue
            members.append(e)
            prepared[e.id] = (raw, data, evidence, project)
        if not members:
            continue
        session = ChatSession(id=f'waiting-{rt.key[:40]}-{uuid.uuid4().hex[:8]}', user_id=actor.id, pending=None)
        db.add(session); db.flush()
        intro = ChatMessage(session_id=session.id, user_id=actor.id, speaker='system',
                            content=f'{rt.title[:1].upper() + rt.title[1:]} is now available. StudioOS checked the waiting area and found {len(members)} '
                                    f"{'entry' if len(members) == 1 else 'entries'} to add.")
        db.add(intro); db.flush()
        ready = need = 0
        ticket = None
        for e in members:
            raw, data, evidence, project = prepared[e.id]
            details = {'record_type': rt.key, 'project': project, 'data': data}
            ticket, item = add_proposal(db, session, 'generic_record', details, intro.id)
            item.field_evidence = {**(item.field_evidence or {}), **evidence,
                                   'original': {'marker': 'sourced', 'source_words': raw[:400]}}
            missing = missing_fields(db, rt, details)
            item.flags = [f for f in (item.flags or []) if 'Offline interpreter' not in f] + [f'From waiting entry #{e.id}'] + \
                         (['MISSING: ' + ', '.join(m['label'] for m in missing)] if missing else [])
            if missing:
                need += 1
            else:
                ready += 1
            review = dict(e.match_review or {})
            review['backfill'] = {'item_id': item.id, 'ticket_id': ticket.id, 'session_id': session.id, 'at': now().isoformat()}
            e.match_review = review
        if ticket is not None:
            ticket.summary = f'Waiting entries for {rt.title}'
        db.add(ChatMessage(session_id=session.id, user_id=actor.id, speaker='assistant',
                           content=' '.join(x for x in (
                               f"{ready} {'is' if ready == 1 else 'are'} complete and ready to approve." if ready else '',
                               f"{need} {'needs' if need == 1 else 'need'} an answer before {'it' if need == 1 else 'they'} can be approved." if need else '',
                               'Nothing is saved until you approve.') if x)))
        add_audit(db, 'waiting_area_check', 'record_type', 0,
                  f'{rt.key}: drafted {len(members)} waiting entries ({ready} ready, {need} need answers)', actor=actor.username)
        summaries.append({'key': rt.key, 'title': rt.title, 'drafted': len(members), 'ready': ready, 'need_answers': need,
                          'session_id': session.id, 'ticket_id': ticket.id if ticket else None})
    db.flush()
    return summaries


MONEY_WORDS = ('wage', 'cost', 'price', 'amount', 'rate', 'total', 'fee', 'budget', 'salary', 'payment')


def is_money_field(f: dict) -> bool:
    return bool(f.get('change_requires_approval')) or any(w in f['name'] for w in MONEY_WORDS)


def records_of(db: Session, key: str, allowed_projects: set | None, show_money: bool = True) -> list[dict]:
    """v0.9.5 (review F09): money-like fields (wages, rates, amounts) are shown only to
    finance roles; others see "finance only"."""
    rt = db.get(RecordType, key)
    if rt is None:
        raise LookupError('Unknown record type')
    rows = db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == key, FlexibleRecord.deleted_at.is_(None))
                      .order_by(FlexibleRecord.id.desc())).all()
    names = {p.id: p.name for p in db.scalars(select(Project)).all()}
    fields = user_fields(rt.design)
    return [{'id': r.id, 'project': names.get(r.project_id), 'created_at': r.created_at.isoformat(),
             'values': [{'label': field_label(f), 'display': display(f, (r.data or {}).get(f['name']))
                         if show_money or not is_money_field(f) else 'finance only'} for f in fields]}
            for r in rows if allowed_projects is None or r.project_id in allowed_projects]
