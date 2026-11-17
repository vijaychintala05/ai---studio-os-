"""New qualification must reject SQLite and even a merely relabelled build."""
import importlib.util
from pathlib import Path
import pytest


def checker():
    p=Path(__file__).resolve().parents[1]/'sim/run_identity.py'
    spec=importlib.util.spec_from_file_location('fictional_run_identity',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_qualification_requires_actual_postgres_and_exact_source_hash():
    m=checker();expected={'version':'0.16.11','source_sha256':'a'*64,'source_files':107}
    health={'version':'0.16.11','environment':'test','database_backend':'postgresql','build':expected}
    assert m.verify(health,expected,'postgresql')['database_backend']=='postgresql'
    with pytest.raises(ValueError,match='backend'):m.verify({**health,'database_backend':'sqlite'},expected,'postgresql')
    with pytest.raises(ValueError,match='build'):m.verify({**health,'build':{**expected,'source_sha256':'b'*64}},expected,'postgresql')
    with pytest.raises(ValueError,match='version'):m.verify({**health,'version':'0.16.10'},expected,'postgresql')


def test_missing_identity_and_live_environment_fail_closed():
    m=checker();expected={'version':'0.16.11','source_sha256':'a'*64,'source_files':107}
    with pytest.raises(ValueError):m.verify({'version':'0.16.11','environment':'test'},expected,'postgresql')
    with pytest.raises(ValueError):m.verify({'environment':'live','build':expected,'database_backend':'postgresql','version':'0.16.11'},expected,'postgresql')


def test_wrong_backend_is_persisted_as_stopped_before_business_bootstrap(tmp_path,monkeypatch):
    import json,sys
    from types import SimpleNamespace
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
    import run_month as runner
    calls=[]
    class App:
        def __init__(self,*args,**kwargs):pass
        def call(self,method,path,*args):
            calls.append((method,path));return {'environment':'test','version':'0.16.11','database_backend':'sqlite'}
    monkeypatch.setattr(runner,'App',App)
    files={}
    for key,value in {'plan':{'days':[]},'answers':[],'inputs':{},'assets':{}}.items():
        p=tmp_path/(key+'.json');p.write_text(json.dumps(value));files[key]=str(p)
    args=SimpleNamespace(**files,url='http://127.0.0.1:8880',out=str(tmp_path/'run'),resume=False,clock=None,expected_build=None,require_backend='postgresql')
    with pytest.raises(ValueError,match='backend'):runner.run(args)
    result=json.loads((tmp_path/'run/result.json').read_text())
    assert result['status']=='STOPPED'and not result['qualified']
    assert result['failures'][0]['kind']=='build_backend_gate'
    assert calls==[('GET','/health')]
