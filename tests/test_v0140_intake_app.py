"""v0.14.0 intake (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build sandbox).

Upload refuses scripts and stores files read-only; a CSV import is one ticket and a re-import adds
nothing; a photo (fake OCR) becomes a draft with low-confidence fields marked; the WhatsApp webhook
refuses unsigned calls, quarantines unknown senders, accepts known staff once per message id; a
received file can be kept as a document by ticket; others cannot see your uploads. Fictional data."""
import base64
import hashlib
import hmac
import json

from sqlalchemy import func, select

from .conftest import write
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import install, add_user, client_for
from studioos import intake_core as I
from studioos import intake_wiring as W
from studioos.db import SessionLocal, FlexibleRecord, IntakeItem, Document


def _up(c, name, data):
    return write(c, 'post', '/api/intake/upload', {'filename': name, 'base64': base64.b64encode(data).decode()})


def test_csv_import_is_one_ticket_and_idempotent(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    install(admin, 'work')
    me = admin.get('/api/auth/me').json()['user']
    name = me.get('display_name') or me['username']
    csv = f'Employee,Date,Hours,Activity\n{name},2026-11-10,6,Drawings\n{name},2026-11-11,4.5,Design\nNobody,2026-11-12,3,Design\n'.encode()
    assert _up(admin, 'evil.jpg', b'#!/bin/sh\necho x').status_code == 422
    it = _up(admin, 'hours.csv', csv).json()
    assert it['status'] == 'table'
    prev = write(admin, 'post', f'/api/intake/items/{it["id"]}/table', {'type_key': 'timesheet_entry'}).json()
    assert prev['to_import'] == 2 and len(prev['unreadable']) == 1
    t = write(admin, 'post', f'/api/intake/items/{it["id"]}/import', {'type_key': 'timesheet_entry'}).json()
    saved = write(admin, 'post', f'/api/tickets/{t["ticket_id"]}/approve-and-save', {})
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FlexibleRecord).where(FlexibleRecord.record_type == 'timesheet_entry')) == 2
    it2 = _up(admin, 'hours-again.csv', csv + b'\n').json()
    again = write(admin, 'post', f'/api/intake/items/{it2["id"]}/table', {'type_key': 'timesheet_entry'}).json()
    assert again['to_import'] == 0 and again['already_imported'] == 2
    assert write(admin, 'post', f'/api/intake/items/{it2["id"]}/import', {'type_key': 'timesheet_entry'}).status_code == 422


def test_photo_draft_marks_unsure_fields(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    install(admin, 'work')
    me = admin.get('/api/auth/me').json()['user']
    name = me.get('display_name') or me['username']
    monkeypatch.setattr(W, 'OCR', I.FakeOcr(f'{name} 6 hours Drawings today', low=['6']))
    it = _up(admin, 'note.png', b'\x89PNG\r\n\x1a\n' + b'0' * 64).json()
    assert it['engine'] == 'fake' and it['unsure_words'] == ['6']
    r = write(admin, 'post', f'/api/intake/items/{it["id"]}/draft', {'type_key': 'timesheet_entry'}).json()
    assert r['low_confidence'] == ['values.hours']


def test_whatsapp_webhook_signature_quarantine_and_once(client, admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_WHATSAPP_APP_SECRET', 'fictional-secret')
    body = json.dumps({'entry': [{'changes': [{'value': {'messages': [
        {'from': '919876543210', 'id': 'wamid.A', 'type': 'text', 'text': {'body': 'please pay 50000'}}]}}]}]}).encode()
    sig = 'sha256=' + hmac.new(b'fictional-secret', body, hashlib.sha256).hexdigest()
    assert client.post('/api/intake/whatsapp', content=body, headers={'X-Hub-Signature-256': 'sha256=00'}).status_code == 403
    assert client.post('/api/intake/whatsapp', content=body, headers={'X-Hub-Signature-256': sig}).json() == {'received': 1}
    assert client.post('/api/intake/whatsapp', content=body, headers={'X-Hub-Signature-256': sig}).json() == {'received': 0}
    with SessionLocal() as db:
        assert db.scalar(select(IntakeItem.status).where(IntakeItem.external_id == 'wa:wamid.A')) == 'quarantined'
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    assert write(admin, 'post', '/api/intake/senders', {'address': '+91 98765 43211', 'user_id': asha}).status_code == 200
    body2 = body.replace(b'919876543210', b'919876543211').replace(b'wamid.A', b'wamid.B')
    sig2 = 'sha256=' + hmac.new(b'fictional-secret', body2, hashlib.sha256).hexdigest()
    client.post('/api/intake/whatsapp', content=body2, headers={'X-Hub-Signature-256': sig2})
    with SessionLocal() as db:
        assert db.scalar(select(IntakeItem.status).where(IntakeItem.external_id == 'wa:wamid.B')) == 'new'


def test_keep_file_as_document_and_privacy(admin, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    add_user(admin, 'asha.rao', 'site_engineer')
    add_user(admin, 'ravi.kumar', 'architect')
    asha, ravi = client_for('asha.rao'), client_for('ravi.kumar')
    it = _up(asha, 'bill.pdf', b'%PDF-1.4 fictional bill').json()
    assert ravi.get(f'/api/intake/items/{it["id"]}').status_code == 404
    f = asha.get(f'/api/intake/items/{it["id"]}/file')
    assert f.status_code == 200 and f.headers['content-type'] == 'application/octet-stream'
    save(admin, propose(admin, 'intake_file_accept', {'intake_id': it['id'], 'name': 'Fictional bill'}))
    with SessionLocal() as db:
        assert db.scalar(select(Document.name).where(Document.relative_path.like('intake/%'))) == 'Fictional bill'
