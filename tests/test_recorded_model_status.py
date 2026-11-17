"""Recorded replay observability is count-only, admin-only and test-only."""
import json
from tests.test_v0100_one_graph import add_user,client_for
from studioos.db import SessionLocal,AiCallLog


def test_replay_status_counts_real_trace_and_gateway_rejections(admin,tmp_path,monkeypatch):
    from studioos import recorded_transport as recordings
    monkeypatch.setenv('STUDIOOS_ENV','test');monkeypatch.setenv('STUDIOOS_ALLOW_LIVE_AI','false')
    monkeypatch.setattr(recordings,'RECORDINGS_ROOT',tmp_path)
    rows=[{'prompt_sha256':'a'*64,'outcome':'replayed','response_fields':2,'network_calls':0},
          {'prompt_sha256':'b'*64,'outcome':'error','network_calls':0}]
    (tmp_path/'reader-replay-calls.jsonl').write_text(''.join(json.dumps(row)+'\n'for row in rows))
    with SessionLocal()as db:
        db.add(AiCallLog(purpose='reader',provider='recorded',model='fixture-v1',outcome='ok',cost_micro_usd=0))
        db.add(AiCallLog(purpose='reader',provider='recorded',model='fixture-v1',outcome='invalid',cost_micro_usd=0));db.commit()
    r=admin.get('/api/ai/replay-status');assert r.status_code==200,r.text
    data=r.json();assert data['transport_attempts']==2 and data['transport_replayed']==1
    assert data['transport_failures']==1 and data['nonempty_replies']==1
    assert data['gateway_invalid']==1 and data['network_calls']==0 and data['paid_provider_gateway_rows']==0
    assert data['paid_server_switch']is False
    assert 'recorded'in admin.get('/api/ai/settings').json()['providers']


def test_replay_status_refuses_staff_and_non_test_mode_before_reading_files(admin,tmp_path,monkeypatch):
    from studioos import recorded_transport as recordings
    monkeypatch.setenv('STUDIOOS_ENV','test')
    add_user(admin,'fictional.replay.site','site_engineer');site=client_for('fictional.replay.site')
    assert site.get('/api/ai/replay-status').status_code==403
    monkeypatch.setenv('STUDIOOS_ENV','production');monkeypatch.setattr(recordings,'RECORDINGS_ROOT',tmp_path/'must-not-open')
    assert admin.get('/api/ai/replay-status').status_code==404
    assert not(tmp_path/'must-not-open').exists()
