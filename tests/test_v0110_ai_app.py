"""v0.11.0 AI reader (app level; needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build sandbox).

Settings are Admin-only and never take keys; AI is off by default and the chat still drafts with
the offline reader; with both switches on (fake transport) the AI reply becomes the same draft and
is logged; a bad reply falls back silently; two people with the same first name are offered, not
picked; corrections are kept; three corrections suggest an alias, which an Admin ticket approves;
the call log and corrections are append-only. Fictional data, disposable database."""
import json

import pytest
from sqlalchemy import select, func, text

from .conftest import write
from .test_v098_universal_accounting import propose, save, project
from .test_v0100_one_graph import install, add_user, client_for
from studioos import ai_gateway as GW
from studioos import ai_wiring as W
from studioos.db import SessionLocal, AiCallLog, AiCorrection, NameAlias


def _chat(c, message, session_id=None):
    body = {'message': message, **({'session_id': session_id} if session_id else {})}
    r = write(c, 'post', '/api/chat', body)
    assert r.status_code == 200, r.text
    return r.json()


def _item(reply):
    return next(i for i in reply['preview']['items'] if i['item_type'] == 'metadata_record')


def test_settings_are_admin_only_and_never_take_keys(admin):
    s = admin.get('/api/ai/settings').json()
    assert s['settings']['enabled'] is False and s['settings']['masking'] is True and s['status']['on'] is False
    assert 'key' not in json.dumps(s['settings']).lower()
    add_user(admin, 'meera.iyer', 'manager')
    assert client_for('meera.iyer').get('/api/ai/settings').status_code == 403
    assert write(admin, 'put', '/api/ai/settings', {'enabled': True}).status_code == 422        # no provider yet
    r = write(admin, 'put', '/api/ai/settings', {'provider': 'claude', 'model': 'sk-fictional'})
    assert r.status_code == 422
    ok = write(admin, 'put', '/api/ai/settings', {'provider': 'claude', 'model': 'fictional-model', 'monthly_cap_usd': '2',
                                                  'input_usd_per_1m': '3', 'output_usd_per_1m': '15', 'enabled': True})
    assert ok.status_code == 200 and ok.json()['status']['on'] is False   # the server switch is still off


def test_chat_drafts_offline_when_ai_is_off_and_asks_between_namesakes(admin):
    install(admin, 'work')
    project(admin)
    add_user(admin, 'ravi.kumar', 'architect')
    add_user(admin, 'ravi.shankar', 'architect')
    reply = _chat(admin, 'Timesheet: Ravi 4 hours on drawings today for Fictional Project A')
    item = _item(reply)
    assert 'employee' not in item['after']['values']
    asked = [a for a in reply.get('ask', []) if a['field'] == 'values.employee']
    assert asked and {c['label'] for c in asked[0]['choices']} == {'Ravi Kumar', 'Ravi Shankar'}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AiCallLog)) == 0      # nothing was sent anywhere


def _turn_on(monkeypatch, reply_fn):
    monkeypatch.setenv('STUDIOOS_ALLOW_LIVE_AI', 'true')
    fake = GW.FakeTransport(reply_fn, 900, 80)
    real = W.gateway
    monkeypatch.setattr(W, 'gateway', lambda db, transport=None: real(db, fake))
    return fake


def test_ai_reply_becomes_the_same_draft_and_is_logged(admin, monkeypatch):
    install(admin, 'work')
    project(admin)
    ravi = add_user(admin, 'ravi.kumar', 'architect')
    write(admin, 'put', '/api/ai/settings', {'provider': 'claude', 'model': 'fictional-model', 'monthly_cap_usd': '2',
                                             'input_usd_per_1m': '3', 'output_usd_per_1m': '15', 'enabled': True})
    fake = _turn_on(monkeypatch, lambda s, u: json.dumps({
        'values': {'employee': 'Ravi Kumar', 'hours': '6.5', 'activity': 'Drawings', 'work_date': '2026-11-13'},
        'evidence': {'employee': 'Ravi Kumar', 'hours': '6.5 ghante', 'activity': 'drawings', 'work_date': 'kal'},
        'project': 'Fictional Project A'}))
    item = _item(_chat(admin, 'Timesheet: Ravi Kumar ne kal 6.5 ghante drawings kiye Fictional Project A'))
    assert item['after']['values']['employee'] == ravi and item['after']['values']['hours'] == '6.5'
    assert item['field_evidence']['values.hours']['read_by'] == 'ai'
    assert 'Fictional Project A' in fake.calls[0]['system']         # the project list is in the prompt
    with SessionLocal() as db:
        row = db.scalar(select(AiCallLog).order_by(AiCallLog.id.desc()))
        assert row.outcome == 'ok' and row.prompt_tokens == 900 and row.cost_micro_usd > 0
        with pytest.raises(Exception):
            db.execute(text('UPDATE ai_call_log SET outcome = :o WHERE id = :i'), {'o': 'x', 'i': row.id}); db.flush()
        db.rollback()


def test_bad_ai_reply_falls_back_silently(admin, monkeypatch):
    install(admin, 'work')
    project(admin)
    write(admin, 'put', '/api/ai/settings', {'provider': 'claude', 'model': 'fictional-model', 'monthly_cap_usd': '2',
                                             'input_usd_per_1m': '3', 'output_usd_per_1m': '15', 'enabled': True})
    _turn_on(monkeypatch, lambda s, u: '{"values": {"hours": "99"}, "evidence": {"hours": "99 hours"}}')
    me = admin.get('/api/auth/me').json()['user']
    name = me.get('display_name') or me['username']
    item = _item(_chat(admin, f'Timesheet: {name} 6.5 hours on drawings yesterday for Fictional Project A'))
    assert item['after']['values']['hours'] == '6.5'            # the offline reader's draft
    with SessionLocal() as db:
        assert [r.outcome for r in db.scalars(select(AiCallLog).order_by(AiCallLog.id))][-2:] == ['ok', 'invalid']


def test_corrections_are_kept_and_become_an_alias_ticket(admin):
    install(admin, 'people')
    asha = add_user(admin, 'asha.rao', 'site_engineer')
    for _ in range(3):
        reply = _chat(admin, 'Attendance: Asha Rao Present today')      # no session id: a new conversation each time
        sid = reply['session_id']
        item = _item(reply)
        r = write(admin, 'post', '/api/chat/answer', {'session_id': sid, 'item_id': item['id'],
                                                      'field': 'values.attendance_status', 'value': 'Site visit'})
        assert r.status_code == 200, r.text
    with SessionLocal() as db:
        rows = db.scalars(select(AiCorrection)).all()
        assert len(rows) >= 3 and rows[0].proposed == {'value': 'Present'} and rows[0].chosen == {'value': 'Site visit'}
    # "Present" is itself an option of the field, so it is never offered as another name for "Site visit"
    assert admin.get('/api/ai/alias-suggestions').json()['suggestions'] == []
    with SessionLocal() as db:       # the same words ("wfh") corrected the same way three times
        for _ in range(3):
            db.add(AiCorrection(type_key='attendance_entry', field_name='attendance_status', field_type='enum', target='',
                                source_text='wfh', proposed={'value': 'Present'}, chosen={'value': 'Work from home'}))
        db.commit()
    sugg = admin.get('/api/ai/alias-suggestions').json()['suggestions']
    assert sugg and sugg[0]['data']['kind'] == 'option' and sugg[0]['data']['option'] == 'Work from home'
    assert sugg[0]['data']['alias'] == 'wfh'
    save(admin, propose(admin, 'metadata_alias', sugg[0]['data']))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(NameAlias)) == 1
    staff = save(admin, propose(admin, 'metadata_alias', {'kind': 'staff', 'alias': 'Asha didi', 'target_id': asha}))
    assert staff['type'] == 'name_alias'
    dup = write(admin, 'post', '/api/universal/proposals', {'kind': 'metadata_alias',
                'data': {'kind': 'staff', 'alias': 'asha DIDI', 'target_id': asha}, 'evidence': 'again'})
    assert dup.status_code == 422
    add_user(admin, 'meera.iyer', 'manager')
    mgr = client_for('meera.iyer')
    p = write(mgr, 'post', '/api/universal/proposals', {'kind': 'metadata_alias',
              'data': {'kind': 'staff', 'alias': 'AR', 'target_id': asha}, 'evidence': 'manager'})
    if p.status_code == 200:   # anyone may propose; only the Admin may approve
        assert write(mgr, 'post', f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save', {}).status_code == 403
