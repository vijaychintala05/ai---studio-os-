"""v0.10.0: chat entry for every universal type (records of types made at runtime or by a pack).

"Ravi 6.5 hours on drawings yesterday for Fictional Tower" becomes a DRAFT Timesheet entry: the
fields that could be read are filled and marked with the words they came from; required fields
that could not be read are asked on the card, with choices where the type has them (options,
staff, tasks). Nothing is saved until an allowed person approves the ticket; the engine then
validates every value again (universal_engine.validate_record_item).
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import graph_core as G
from . import graph_query as gq
from . import universal_engine as u
from .db import ApprovalTicket, ApprovalTicketItem, ChatSession, RecordType, Project, add_audit

STOP_WORDS = {'cancel', 'discard', 'stop', 'yes', 'no', 'ok', 'save', 'approve', 'confirm', 'not now'}


def is_universal(rt) -> bool:
    return rt is not None and rt.status == 'active' and (rt.design or {}).get('runtime_fields') is not None \
        and rt.source_inbox_id is None


def _fields(rt):
    return rt.design['runtime_fields']


def _projects(db: Session, user):
    from .main import project_data
    from .access import visible_project_ids, filter_projects
    return filter_projects(project_data(db), visible_project_ids(db, user))


def _named_references(db,user,rt,text,project_id,read):
    """Resolve explicitly labelled names locally, using the same scoped choices as forms."""
    fields={G._norm(f['name']):f for f in _fields(rt)if f['type']=='reference'and f.get('target')!='system.user'}
    for f in list(fields.values()):
        if f.get('meaning'):fields[G._norm(f['meaning'])]=f
    for part in re.split(r'[;\n]|,(?=\s*[A-Za-z][A-Za-z _]{1,40}\s*[:=])',text):
        match=re.match(r'\s*([A-Za-z][A-Za-z _/]{1,40}?)\s*[:=]\s*(.+?)\s*$',part)
        field=fields.get(G._norm(match.group(1)))if match else None
        if not field or field['name']in read['values']:continue
        phrase=match.group(2).strip()
        choices=gq.targets(db,user,field['target'],q=phrase,project_id=project_id,limit=200)
        exact=[c for c in choices if G._norm(c['label'])==G._norm(phrase)]
        if len(exact)==1:
            read['values'][field['name']]=exact[0]['id'];read['evidence'][field['name']]=part.strip()[:200]
            read.setdefault('how',{})[field['name']]='exact'
        elif len(exact)>1:
            read.setdefault('candidates',{})[field['name']]=[{'id':c['id'],'name':c['label']}for c in exact[:5]]


def draft(db: Session, session, user, original, rt, msg: str):
    """Create the draft from one message. Returns the ticket item."""
    from .tickets import add_proposal
    from . import ai_wiring, ai_reader
    projects = _projects(db, user)
    # v0.11.0: the catalog-aware reader (AI when switched on, the offline reader otherwise; the
    # result has the same shape either way and goes through the same checks below).
    read = ai_wiring.read_message(db, user, rt, msg, u._today(), projects, gq.people(db))
    values, evidence, project = read['values'], read['evidence'], read['project']
    project_id = next((p['id'] for p in projects if p['name'] == project), None)
    _named_references(db,user,rt,msg,project_id,read)
    # Refuse what the reader picked up but the person may not use (a task in another project ...).
    for f in _fields(rt):
        if f['type'] == 'reference' and f['name'] in values:
            try:
                u.check_references(db, [f], values, project_id, user)
            except ValueError:
                values.pop(f['name'], None)
                evidence.pop(f['name'], None)
    data = {'type_key': rt.key, 'project_id': project_id, 'values': values}
    ticket, item = add_proposal(db, session, 'metadata_record', data, original.id, provider='rules')
    marks = dict(item.field_evidence or {})
    spec = G.field_map(_fields(rt))
    for name, words in evidence.items():
        if name in values:
            marks['values.' + name] = {'marker': ai_reader.marker_for(read, spec[name]), 'source_words': str(words)[:200],
                                       'read_by': read['source'], 'source_project_id': project_id}
    for name, cands in (read.get('candidates') or {}).items():
        if name in spec and name not in values:
            marks['values.' + name] = {'marker': 'missing', 'candidates': cands[:5],
                                       'source_words': 'More than one person fits; choose one'}
    if project_id:
        marks['project_id'] = {'marker': 'sourced', 'source_words': project}
    elif read.get('project_candidates'):
        marks['project_id'] = {'marker': 'missing', 'candidates': read['project_candidates'][:5],
                               'source_words': 'More than one project fits; choose one'}
    item.field_evidence = marks
    db.commit()
    return item


def missing(db: Session, user, rt, data: dict) -> list:
    """Required fields still empty, in form order; plus the project when this person needs one."""
    out = [f for f in _fields(rt) if f.get('required') and (data.get('values') or {}).get(f['name']) in (None, '')]
    if data.get('project_id') is None and user is not None and user.role not in ('admin', 'manager', 'accounts') \
            and user.role not in (u.type_options(rt).get('company_propose_roles') or []):
        out.insert(0, {'name': 'project_id', 'type': 'project', 'meaning': 'Project', 'required': True})
    return out


def summary(db: Session, user, item) -> str:
    rt = db.get(RecordType, (item.after_data or {}).get('type_key'))
    if rt is None:
        return 'Draft ready.'
    gaps = missing(db, user, rt, item.after_data or {})
    filled = len((item.after_data or {}).get('values') or {})
    if gaps:
        return (f'Draft {rt.title.lower()} with {filled} detail{"s" if filled != 1 else ""} filled. '
                f'Still needed: {", ".join((g.get("meaning") or g["name"]).lower() for g in gaps)}.')
    return f'Draft {rt.title.lower()} ready. Check the details and approve to save it.'


def chat_turn(db: Session, session, user, original, msg: str):
    """A short reply to an open universal draft's question fills that field. None otherwise."""
    if len(msg) > 160 or msg.strip().casefold() in STOP_WORDS:
        return None
    ticket = db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id == session.id))
    if ticket is None or ticket.status in ('committed', 'reversed'):
        return None
    for item in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id == ticket.id,
                                                            ApprovalTicketItem.item_type == 'metadata_record',
                                                            ApprovalTicketItem.status == 'pending').order_by(ApprovalTicketItem.id.desc())):
        rt = db.get(RecordType, (item.after_data or {}).get('type_key'))
        if not is_universal(rt):
            continue
        gaps = missing(db, user, rt, item.after_data or {})
        if not gaps or gaps[0]['type'] == 'text':
            # Free text is only taken from the card's question or edit box, never guessed from chat.
            return None
        try:
            change(db, user, ticket, item, {('values.' + gaps[0]['name']) if gaps[0]['name'] != 'project_id' else 'project_id': msg.strip()},
                   how='answered', said=msg[:200])
        except ValueError:
            return None
        db.commit()
        return {'text': summary(db, user, item), 'item': item}
    return None


def change(db: Session, user, ticket, item, changes: dict, how='edited', said=None, note=''):
    """Typed or tapped values (values.<field>, project_id) for a universal draft."""
    from .main import check_proposal_access, _lock_chat_draft
    from .tickets import log_decision
    if item.item_type != 'metadata_record':
        raise ValueError('That draft cannot be changed this way')
    old = json.loads(json.dumps(item.after_data or {}))
    data = json.loads(json.dumps(old))
    rt = db.get(RecordType, data.get('type_key'))
    if not is_universal(rt):
        raise ValueError('This kind of record is no longer active')
    spec = G.field_map(_fields(rt))
    for field, value in changes.items():
        if field == 'project_id':
            if value in (None, '', 'none'):
                data['project_id'] = None
                continue
            project = _project(db, value, user)
            if project is None:
                raise ValueError('Project not found')
            data['project_id'] = project.id
            continue
        group, _, name = str(field).partition('.')
        if group != 'values' or name not in spec:
            raise ValueError('That detail does not apply to this record')
        if value in (None, ''):
            data['values'].pop(name, None)
            continue
        f = spec[name]
        try:
            coerced = G.coerce_text(f, value, u._today(), gq.people(db))
        except G.GraphError as ex:
            raise ValueError(f'{f.get("meaning") or name}: {ex}') from None
        if f['type'] == 'reference':
            u.check_references(db, [f], {name: coerced}, data.get('project_id'), user)
        data['values'][name] = coerced
    # every value is checked by the engine for its type before the draft is stored
    try:
        u.normalize_values([dict(f, required=False) for f in _fields(rt)], data['values'])
    except ValueError as ex:
        raise ValueError(str(ex)) from None
    check_proposal_access(db, user, 'metadata_record', data)
    _lock_chat_draft(db, item)
    # v0.11.0: a value the reader proposed and the person changed is kept to learn from.
    from .ai_wiring import record_corrections
    if old.get('project_id') == data.get('project_id'):
        record_corrections(db, user, item, rt, old.get('values') or {},
                           {k.partition('.')[2]: data['values'].get(k.partition('.')[2]) for k in changes if k.startswith('values.')},
                           item.field_evidence or {})
    item.after_data = data
    if data != old:
        item.last_edited_by = user.id
    marks = dict(item.field_evidence or {})
    for field in changes:
        marks[field] = {'marker': how, 'source_words': said}
    item.field_evidence = marks
    item.status, item.decided_by, item.review_note = 'pending', None, note
    if how == 'edited':
        item.flags = list(dict.fromkeys(list(item.flags or []) + ['Edited by reviewer; requires reapproval']))
        ticket.status = 'in_review'
    add_audit(db, 'edit_ticket_item', 'ticket_item', item.id,
              f'Ticket #{ticket.id} {rt.title} draft changed ({", ".join(changes)})', actor=user.username)
    words = []
    for field in changes:
        name = field.partition('.')[2] or field
        f = spec.get(name, {'meaning': 'Project'})
        words.append(f'{(f.get("meaning") or name).lower()}')
    log_decision(db, ticket, user, ('answered' if how == 'answered' else 'edited') + f' the {rt.title.lower()}: ' + ', '.join(words))


def edit(db: Session, user, ticket, item, after: dict, note: str):
    old = item.after_data or {}
    if after.get('type_key') != old.get('type_key'):
        raise ValueError('The kind of record cannot be changed; choose "Not now" and enter it again')
    changes = {}
    for name in set(old.get('values') or {}) | set(after.get('values') or {}):
        if (old.get('values') or {}).get(name) != (after.get('values') or {}).get(name):
            changes['values.' + name] = (after.get('values') or {}).get(name)
    if after.get('project_id') != old.get('project_id'):
        changes['project_id'] = after.get('project_id')
    if changes:
        change(db, user, ticket, item, changes, note=note)


def _project(db: Session, value, user):
    from .access import can_access_project
    p = db.get(Project, value) if type(value) is int else (db.get(Project, int(value)) if str(value).isdigit() else next(
        (x for x in db.scalars(select(Project).where(Project.deleted_at.is_(None))) if x.name.casefold() == str(value).strip().casefold()), None))
    if p is None or p.deleted_at or not can_access_project(db, user, p.id):
        return None
    return p


# ------------------------------------------------------------------ the card

def fill(db: Session, item: dict, user=None) -> None:
    after, marks = item.get('after') or {}, item.get('field_evidence') or {}
    rt = db.get(RecordType, after.get('type_key')) if isinstance(after.get('type_key'), str) else None
    if rt is None or (rt.design or {}).get('runtime_fields') is None:
        return
    res = gq.Resolver(db, user) if user is not None else None
    values = after.get('values') or {}
    fields = []
    if after.get('project_id') or after.get('project_id') is None:
        p = db.get(Project, after['project_id']) if after.get('project_id') else None
        fields.append({'key': 'project_id', 'label': 'Project', 'display': p.name if p else 'Not project-related',
                       'raw': after.get('project_id'), 'type': 'project',
                       'marker': (marks.get('project_id') or {}).get('marker') or ('sourced' if p else 'guessed')})
    for f in _fields(rt):
        raw = values.get(f['name'])
        display = gq._display(f, raw, res) if res is not None and raw is not None else ('' if raw is None else str(raw))
        mark = (marks.get('values.' + f['name']) or {})
        choices = None
        if f['type'] == 'enum':
            choices = [{'value': o, 'label': o} for o in f['options']]
        elif f['type'] == 'reference' and user is not None:
            try:
                choices = [{'value': t['id'], 'label': t['label']} for t in
                           gq.targets(db, user, f['target'], project_id=after.get('project_id'), limit=40)]
            except (LookupError, ValueError):
                choices = []
        fields.append({'key': 'values.' + f['name'], 'label': f.get('meaning') or f['name'].replace('_', ' ').capitalize(),
                       'display': display or '—', 'raw': raw, 'type': f['type'], 'required': bool(f.get('required')),
                       'options': f.get('options'), 'target': f.get('target'), 'choices': choices,
                       'marker': mark.get('marker') or ('missing' if raw is None and f.get('required') else 'guessed' if raw is not None else 'empty'),
                       'source': mark.get('source_words')})
    item['record_type'] = rt.key
    item['graph'] = True
    item['title'] = rt.title
    label_field = (rt.design or {}).get('label_field')
    label = next((x['display'] for x in fields if x['key'] == 'values.' + str(label_field)), None) if label_field else None
    item['line'] = f'{rt.title} · {label}' if label and label != '—' else rt.title
    item['fields'] = [x for x in fields if x['marker'] != 'empty' or x.get('required')] + \
                     [x for x in fields if x['marker'] == 'empty' and not x.get('required')]
    item['optional_empty'] = sum(1 for x in fields if x['marker'] == 'empty' and not x.get('required'))


def asks(db: Session, items: list, user=None) -> list:
    """Tap-to-answer questions for required details a universal draft still needs."""
    out = []
    for item in items:
        if item.get('item_type') != 'metadata_record' or item.get('status') != 'pending':
            continue
        after = item.get('after') or {}
        rt = db.get(RecordType, after.get('type_key')) if isinstance(after.get('type_key'), str) else None
        if not is_universal(rt):
            continue
        for f in missing(db, user, rt, after)[:2]:
            choices = []
            if f['type'] == 'enum':
                choices = [{'label': o, 'value': o} for o in f['options']][:8]
            elif f['type'] == 'boolean':
                choices = [{'label': 'Yes', 'value': True}, {'label': 'No', 'value': False}]
            elif f['type'] == 'reference' and user is not None:
                cands = ((item.get('field_evidence') or {}).get('values.' + f['name']) or {}).get('candidates')
                try:
                    allowed = gq.targets(db, user, f['target'], project_id=after.get('project_id'), limit=40 if cands else 8)
                except LookupError:
                    allowed = []
                if cands:   # v0.11.0: the people the message could mean, still limited to what this person may pick
                    ids = {t['id']: t['label'] for t in allowed}
                    choices = [{'label': ids[c['id']], 'value': c['id']} for c in cands if c['id'] in ids]
                else:
                    choices = [{'label': t['label'], 'value': t['id']} for t in allowed]
            elif f['type'] == 'project' and user is not None:
                choices = [{'label': p['name'], 'value': p['id']} for p in _projects(db, user)][:8]
            field = 'project_id' if f['type'] == 'project' else 'values.' + f['name']
            question = f'{f.get("meaning") or f["name"]}?' if f['type'] != 'date' else f'{f.get("meaning") or f["name"]}? (for example today, 20 Nov)'
            out.append({'id': f'graph-{item["id"]}-{f["name"]}'[:60], 'item_id': item['id'], 'field': field,
                        'text': question, 'choices': choices, 'free_text': not choices or f['type'] == 'reference'})
    return out[:4]
