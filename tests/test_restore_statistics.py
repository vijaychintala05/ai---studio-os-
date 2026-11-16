"""A cold restored database must have usable planner stats before it is opened.
Masked data must be masked before stats can retain any sampled values.
"""
from pathlib import Path
import pytest
from studioos import safekeeping as sk


@pytest.mark.parametrize('masked',[False,True])
def test_restore_statistics_are_ready_and_never_sample_unmasked_test_rows(tmp_path,monkeypatch,masked):
    cfg=sk.Config({'DATABASE_URL':'postgresql://fictional:fictional@localhost/studioos_fixture','STUDIOOS_ENV':'test'})
    events=[]
    def psql(env,query,database=None):
        events.append(('sql',query,database));return ''
    def run(cmd,env,**kwargs):events.append(('process',cmd,None));return ''
    monkeypatch.setattr(sk,'psql',psql);monkeypatch.setattr(sk,'run',run)
    target='studioos_fixture_incoming'if masked else'studioos_restored_fixture'
    sk.restore_into_new({},tmp_path/'fictional.dump',target,cfg,prepare_test_copy=masked)
    stats=[event for event in events if event[0]=='sql'and event[1]=='ANALYZE']
    if masked:assert not stats,'Do not sample unmasked rows into the masked copy statistics'
    else:
        assert stats==[('sql','ANALYZE',target)],'Cold restored reports need statistics before the app opens'
        assert events[-1]==stats[0]
