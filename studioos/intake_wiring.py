"""v0.14.0 intake connected to the database (thin; the logic is in intake_core).

The inbox (intake_items) holds what arrived and what was read from it; business data is only ever
written by an approved ticket: a draft record (metadata_record, through the v0.10/v0.11 card), an
import (metadata_import, one ticket per file), or a file kept as a document (intake_file_accept).
"""
from __future__ import annotations

import base64
import json
import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import graph_query as gq
from . import intake_core as I
from . import universal_engine as u
from .db import (ChatMessage, ChatSession, Config, Document, FlexibleRecord, IntakeImport, IntakeItem, Party, RecordType, User,
                 add_audit)

SENDERS_KEY = 'intake_known_senders'
TABLE_TYPES = ('text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
OCR = I.TesseractOcr()
SPEECH = I.SpeechToText()
SCANNER = I.Scanner()


def intake_dir() -> str:
    explicit=os.getenv('STUDIOOS_INTAKE_DIR')
    root=os.getenv('STUDIOOS_FILES_DIR')or os.getenv('FILES_PATH')
    if not root and os.getenv('STUDIOOS_INBOX_DIR'):root=os.path.dirname(os.path.abspath(os.environ['STUDIOOS_INBOX_DIR']))
    return os.path.abspath(explicit or os.path.join(root or './data','intake'))


# ------------------------------------------------------------------ who may send

def known_senders(db: Session) -> list[dict]:
    """Staff (their employee profile's work phone, plus addresses the Admin added) and contacts."""
    out = []
    row = db.get(Config, SENDERS_KEY)
    for x in (json.loads(row.value) if row else []):
        out.append(x)
    for rec in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type == 'employee_profile', FlexibleRecord.deleted_at.is_(None))):
        phone, uid = (rec.data or {}).get('work_phone'), (rec.data or {}).get('employee')
        if phone and type(uid) is int:
            out.append({'address': phone, 'kind': 'staff', 'id': uid, 'name': ''})
    for p in db.scalars(select(Party).where(Party.deleted_at.is_(None), Party.phone != '')):
        out.append({'address': p.phone, 'kind': 'client' if p.kind == 'client' else 'supplier', 'id': p.id, 'name': p.name})
    return out


def add_sender(db: Session, address: str, user_id: int, actor: str):
    """Admin: this phone number or e-mail address belongs to this staff member."""
    if not (I.phone_key(address) or I.email_key(address)):
        raise ValueError('A 10-digit phone number or an e-mail address')
    u_ = db.get(User, user_id)
    if not u_ or not u_.active:
        raise ValueError('Staff member not found')
    row = db.get(Config, SENDERS_KEY)
    items = json.loads(row.value) if row else []
    items = [x for x in items if not (I.phone_key(x['address']) and I.phone_key(x['address']) == I.phone_key(address))
             and not (I.email_key(x['address']) and I.email_key(x['address']) == I.email_key(address))]
    items.append({'address': address.strip()[:120], 'kind': 'staff', 'id': user_id, 'name': u_.display_name or u_.username})
    value = json.dumps(items[-6:] if len(json.dumps(items)) > 480 else items)
    if row:
        row.value = value
    else:
        db.add(Config(key=SENDERS_KEY, value=value))
    add_audit(db, 'intake_sender_added', 'settings', 0, f'A sender address was added for {u_.username}', actor=actor)


# ------------------------------------------------------------------ arriving things

def _read(item: IntakeItem, data: bytes):
    """Text out of the file: OCR for photos, the text layer of PDFs, speech for voice notes."""
    mt = item.media_type
    if mt in ('image/jpeg', 'image/png'):
        if OCR.available():
            out = OCR.read(item.stored_path)
            item.text, item.engine = out['text'][:20000], out['engine']
            item.unsure_words = [w['text'] for w in out['words'] if 0 <= w['conf'] < I.LOW_CONFIDENCE][:200]
            item.status = 'new' if item.text.strip() else 'needs_reading'
        else:
            item.status = 'needs_reading'
    elif mt == 'application/pdf':
        text = I.pdf_text(item.stored_path)
        item.text, item.engine = (text or '')[:20000], 'pdftotext' if text else ''
        item.status = 'new' if text else 'needs_reading'
    elif mt.startswith('audio/'):
        if SPEECH.available():
            item.text, item.engine, item.status = SPEECH.transcribe(item.stored_path)[:8000], SPEECH.name, 'new'
        else:
            item.status = 'needs_listening'
    elif mt in TABLE_TYPES:
        item.status = 'table'
    else:
        item.text, item.status = data.decode('utf-8', 'replace')[:20000], 'new'


def receive_file(db: Session, data: bytes, filename: str, source: str, sender: str = '', sender_match=None,
                 uploaded_by=None, note: str = '', external_id=None) -> IntakeItem:
    meta = I.check_file(data, filename)
    path = I.store(data, intake_dir())
    item = IntakeItem(source=source, sender=sender[:300], filename=meta['filename'], media_type=meta['media_type'],
                      size_bytes=meta['size_bytes'], sha256=meta['sha256'], stored_path=path, uploaded_by=uploaded_by,
                      note=note[:500], external_id=external_id)
    item.scan = SCANNER.scan(path)
    if sender_match:
        item.sender_kind, item.sender_id = sender_match['kind'], sender_match['id']
    if item.scan in ('infected', 'scan_error'):
        item.status = 'rejected' if item.scan == 'infected' else 'quarantined'
    else:
        _read(item, data)
    if source in ('whatsapp', 'email') and not sender_match:
        item.status = 'quarantined'
    db.add(item)
    db.flush()
    return item


def receive_text(db: Session, text: str, source: str, sender: str, sender_match, external_id=None) -> IntakeItem:
    item = IntakeItem(source=source, sender=sender[:300], text=text[:8000], external_id=external_id,
                      status='new' if sender_match else 'quarantined')
    if sender_match:
        item.sender_kind, item.sender_id = sender_match['kind'], sender_match['id']
    db.add(item)
    db.flush()
    return item


def upload(db: Session, user, filename: str, b64: str, note: str = '') -> IntakeItem:
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        raise ValueError('The file did not arrive whole') from None
    item = receive_file(db, data, filename, 'upload', sender=user.username, sender_match={'kind': 'staff', 'id': user.id},
                        uploaded_by=user.id, note=note)
    add_audit(db, 'intake_received', 'intake_item', item.id, f'File received ({item.media_type}, {item.size_bytes} bytes)', actor=user.username)
    return item


def whatsapp(db: Session, payload: dict, fetcher=None) -> list[int]:
    known = known_senders(db)
    made = []
    for m in I.parse_whatsapp(payload):
        if m['message_id'] and db.scalar(select(IntakeItem.id).where(IntakeItem.external_id == 'wa:' + m['message_id'])):
            continue                                   # the same message delivered twice
        who = I.who_sent(m['from'], known)
        if m['media_id'] and fetcher is not None and who:
            try:
                data, name = fetcher(m['media_id'])
                item = receive_file(db, data, name, 'whatsapp', m['from'], who, note=m['text'], external_id='wa:' + m['message_id'])
                if m['text'] and not item.text:
                    item.text = m['text']
                made.append(item.id)
                continue
            except (I.IntakeError, OSError, ValueError):
                pass
        item = receive_text(db, m['text'] or '(a file that was not downloaded)', 'whatsapp', m['from'], who, 'wa:' + m['message_id'])
        if m['media_id']:
            item.note = 'media:' + m['media_id']
            item.status = 'quarantined' if not who else 'needs_reading'
        made.append(item.id)
    db.flush()
    return made


def email_poll(db: Session, mailbox) -> list[int]:
    known = known_senders(db)
    made = []
    for raw in mailbox.fetch_unseen():
        e = I.parse_email(raw)
        ext = 'mail:' + (e['message_id'] or I.row_key('mail', {'f': e['from'], 's': e['subject'], 't': e['text']}))[:190]
        if db.scalar(select(IntakeItem.id).where(IntakeItem.external_id == ext)):
            continue
        who = I.who_sent(e['from'], known)
        body = (e['subject'] + '\n' + e['text']).strip()
        item = receive_text(db, body, 'email', e['from'], who, ext)
        made.append(item.id)
        for i, f in enumerate(e['files']):
            try:
                fi = receive_file(db, f['data'], f['filename'], 'email', e['from'], who, note=f'Attached to e-mail #{item.id}',
                                  external_id=f'{ext}#{i}')
                made.append(fi.id)
            except I.IntakeError as ex:
                item.note = (item.note + f' Attachment "{f["filename"]}" refused: {ex}')[:500]
    db.flush()
    return made


# ------------------------------------------------------------------ from the inbox to a ticket

def item_view(db: Session, item: IntakeItem, full: bool = False) -> dict:
    out = {'id': item.id, 'source': item.source, 'sender': item.sender, 'sender_kind': item.sender_kind, 'status': item.status,
           'filename': item.filename, 'media_type': item.media_type, 'size_bytes': item.size_bytes, 'scan': item.scan,
           'engine': item.engine, 'ticket_id': item.ticket_id, 'note': item.note,
           'at': item.created_at.isoformat() if item.created_at else None, 'text': item.text[:300 if not full else 20000],
           'has_file': bool(item.stored_path)}
    if full:
        out['unsure_words'] = item.unsure_words or []
    return out


def visible(db: Session, user, item: IntakeItem) -> bool:
    return user.role in ('admin', 'manager') or item.uploaded_by == user.id


def make_draft(db: Session, user, item: IntakeItem, type_key: str):
    """The item's text through the reader into a draft card (a ticket); words the OCR was unsure of
    mark their fields; money is always marked for a closer look."""
    from . import graph_card
    if item.status not in ('new', 'drafted') or not item.text.strip():
        raise ValueError('Nothing to read in this item yet')
    rt = db.get(RecordType, type_key)
    if not graph_card.is_universal(rt):
        raise ValueError('Choose an active kind of record')
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, pending=None)
    db.add(session)
    db.flush()
    original = ChatMessage(session_id=session.id, user_id=user.id, speaker='user',
                           content=f'[From {item.source} {item.sender} — inbox item #{item.id}] {item.text[:4000]}')
    db.add(original)
    db.flush()
    ti = graph_card.draft(db, session, user, original, rt, item.text[:4000])
    marks = dict(ti.field_evidence or {})
    words = [{'text': w, 'conf': 0} for w in item.unsure_words or []]
    low = I.low_confidence_fields({k.partition('.')[2]: v.get('source_words') or '' for k, v in marks.items() if k.startswith('values.')}, words)
    for f in low:
        marks['values.' + f] = {**marks['values.' + f], 'marker': 'guessed', 'low_confidence': True}
    ti.field_evidence = marks
    if low:
        ti.flags = list(dict.fromkeys(list(ti.flags or []) + ['Read from a photo: check the highlighted details']))
    item.status, item.ticket_id = 'drafted', ti.ticket_id
    db.commit()
    return ti


def table_preview(db: Session, user, item: IntakeItem, type_key: str | None, mapping: dict | None, project_id=None) -> dict:
    from . import native_imports as N
    if type_key in N.FIELDS:
        N.check_actor(db,user,type_key,project_id)
        return N.plan(db,item,type_key,mapping,project_id)
    from .intake_documents import verified_source
    with verified_source(item)[0].open('rb') as f:
        rows = I.read_table(f.read(), item.media_type)
    if not rows:
        raise ValueError('The file has no rows')
    headers = [str(h) for h in rows[0]]
    if not type_key:
        return {'headers': headers, 'new_type': I.propose_type(os.path.splitext(item.filename)[0] or 'Imported', headers, rows[1:]),
                'rows': len(rows) - 1}
    rt = db.get(RecordType, type_key)
    if not rt or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Unknown kind of record')
    fields = rt.design['runtime_fields']
    mapping = {int(k): v for k, v in (mapping or I.match_columns(headers, fields)).items() if v}
    if any(v not in {f['name'] for f in fields} for v in mapping.values()):
        raise ValueError('A column is matched to a field this kind of record does not have')
    done = {k for imp in db.scalars(select(IntakeImport).where(IntakeImport.type_key == type_key)) for k in imp.row_keys}
    plan = I.plan_import(rows, fields, mapping, type_key, u._today(), gq.people(db), frozenset(done))
    return {'headers': headers, 'mapping': mapping, 'fields': [{'name': f['name'], 'meaning': f.get('meaning') or f['name'],
            'required': bool(f.get('required'))} for f in fields], 'sample': plan['sample'], 'unreadable': plan['unreadable'],
            'already_imported': plan['already_imported'], 'to_import': len(plan['rows']), 'total': plan['total'], '_rows': plan['rows']}


def propose_import(db: Session, user, item: IntakeItem, type_key: str, mapping: dict, project_id=None, new_type: dict | None = None):
    """One ticket per import: optionally the new type first, then every row as one import item."""
    from .tickets import add_proposal, validate_item
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, pending=None)
    db.add(session)
    db.flush()
    msg = ChatMessage(session_id=session.id, user_id=user.id, speaker='user', content=f'Import of inbox item #{item.id} ({item.filename})')
    db.add(msg)
    db.flush()
    if new_type:
        ticket, ti = add_proposal(db, session, 'metadata_type', new_type, msg.id, provider='rules')
        validate_item(db, ti)
        from .intake_documents import verified_source
        with verified_source(item)[0].open('rb') as f:
            rows = I.read_table(f.read(), item.media_type)
        mapping = {i: fld['name'] for i, fld in enumerate(new_type['fields'])}
        plan_rows = I.plan_import(rows, new_type['fields'], mapping, new_type['key'], u._today(), gq.people(db))['rows']
        type_key = new_type['key']
    else:
        preview = table_preview(db, user, item, type_key, mapping, project_id)
        plan_rows = preview['_rows']
    if not plan_rows:
        raise ValueError('No new rows to import')
    data = {'intake_id': item.id, 'type_key': type_key, 'project_id': project_id,
            'rows': [{'values': r['values'], 'key': r['key']} for r in plan_rows]}
    from . import native_imports as N
    if type_key in N.FIELDS:
        data['mapping'] = preview['mapping']
    ticket, ti = add_proposal(db, session, 'metadata_import', data, msg.id, provider='rules')
    if not new_type:
        validate_item(db, ti)
    item.status, item.ticket_id = 'drafted', ticket.id
    db.commit()
    return ticket


def validate_import(db: Session, d: dict):
    from . import native_imports as N
    if isinstance(d,dict) and d.get('type_key') in N.FIELDS:
        return N.validate(db,d)
    if not isinstance(d, dict) or set(d) - {'intake_id', 'type_key', 'project_id', 'rows'} or not isinstance(d.get('rows'), list):
        raise ValueError('An import names the kind of record and its rows')
    if not 1 <= len(d['rows']) <= I.MAX_IMPORT_ROWS:
        raise ValueError(f'1–{I.MAX_IMPORT_ROWS:,} rows per import')
    done = {k for imp in db.scalars(select(IntakeImport).where(IntakeImport.type_key == d['type_key'])) for k in imp.row_keys}
    seen = set()
    for r in d['rows']:
        if not isinstance(r, dict) or set(r) != {'values', 'key'} or r['key'] != I.row_key(d['type_key'], r['values']):
            raise ValueError('An import row was changed after it was read; read the file again')
        if r['key'] in done or r['key'] in seen:
            raise ValueError('Some rows were already imported; read the file again')
        seen.add(r['key'])
        u.validate_record_item(db, {'type_key': d['type_key'], 'project_id': d.get('project_id'), 'values': r['values']})
    return d


def apply_import(db: Session, item, actor: str):
    from . import native_imports as N
    if (item.after_data or {}).get('type_key') in N.FIELDS:
        return N.apply(db,item,actor)
    from types import SimpleNamespace
    d = validate_import(db, item.after_data or {})
    ids = []
    for r in d['rows']:
        sub = SimpleNamespace(after_data={'type_key': d['type_key'], 'project_id': d.get('project_id'), 'values': r['values']},
                              item_type='metadata_record', ticket_id=item.ticket_id, id=item.id)
        out = u.apply_item(db, sub, actor)
        ids.append(out.get('id'))
    db.add(IntakeImport(intake_id=d.get('intake_id'), type_key=d['type_key'], row_keys=[r['key'] for r in d['rows']],
                        record_ids=ids, ticket_id=item.ticket_id))
    db.flush()
    src = db.get(IntakeItem, d['intake_id']) if type(d.get('intake_id')) is int else None
    if src is not None:
        src.status = 'imported'
    add_audit(db, 'intake_import', 'intake_item', d.get('intake_id') or 0, f'Ticket #{item.ticket_id} imported {len(ids)} {d["type_key"]} rows', actor=actor)
    return {'type': 'intake_import', 'id': len(ids), 'item_id': item.id}


def validate_file_accept(db: Session, d: dict, actor=None):
    if not isinstance(d, dict) or set(d) - {'intake_id', 'name', 'project_id'} or type(d.get('intake_id')) is not int:
        raise ValueError('Name the inbox item to keep')
    it = db.get(IntakeItem, d['intake_id'])
    if not it or not it.stored_path or it.scan in ('infected', 'scan_error') or it.status in ('rejected', 'quarantined'):
        raise ValueError('That file cannot be kept')
    from .intake_documents import verified_source
    verified_source(it)
    if d.get('project_id')is not None:
        from .db import Project
        project=db.get(Project,d['project_id'])if type(d['project_id'])is int else None
        if not project or project.deleted_at:raise ValueError('Active project required')
    if actor is not None:
        if not visible(db,actor,it):raise ValueError('Inbox source not found')
        if d.get('project_id')is not None:
            from .access import require_project_access
            require_project_access(db,actor,d['project_id'])
    if db.scalar(select(Document.id).where(Document.relative_path == 'intake/' + it.sha256)):
        raise ValueError('This file is already kept')
    return it


def apply_file_accept(db: Session, item, actor: str):
    d = item.after_data or {}
    from .db import ApprovalTicket,TicketRecordEvent
    ticket=db.get(ApprovalTicket,item.ticket_id)
    requester=db.get(User,ticket.submitter_id)if ticket else None
    if not requester or not requester.active:raise ValueError('File sender is no longer active')
    it = validate_file_accept(db, d,actor=requester)
    doc = Document(project_id=d.get('project_id'), name=str(d.get('name') or it.filename)[:300], relative_path='intake/' + it.sha256,
                   doc_type=it.media_type.split('/')[-1][:32], size_bytes=it.size_bytes)
    db.add(doc)
    db.flush()
    db.add(TicketRecordEvent(ticket_id=item.ticket_id,item_id=item.id,entity_type='document',entity_id=doc.id,operation='create'))
    it.status = 'kept'
    add_audit(db, 'intake_file_kept', 'document', doc.id, f'Ticket #{item.ticket_id} kept inbox file #{it.id}', actor=actor)
    return {'type': 'document', 'id': doc.id, 'item_id': item.id}
