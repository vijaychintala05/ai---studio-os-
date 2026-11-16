"""Approved bootstrap state survives; owner migration runs without app layers."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
import bootstrap_ops as B
import client


def scenario(monkeypatch,tmp_path,broken=False):
    calls=[];alive={'app','backup','db'};out=tmp_path/'setup';seed={'version':'0.16.9','new_kinds':['a','b','c','d']}
    class Lab:
        def __init__(self,root):self.root=Path(root)
        def dc(self,target,*args,name):
            calls.append(args)
            if args[0]in ('stop','rm'):
                alive.difference_update({'app','backup'})
            if args[0]=='run':
                assert not alive.intersection({'app','backup'}),'Owner migration overlaps app/backup layers'
                assert (out/'approved-seed-state.json').is_file(),'Approved seed checkpoint must survive migration failure'
                if broken:raise RuntimeError('Fictional migration failed')
            if args[0]=='up':alive.update({'app','backup'})
        def capture(self,*args,**kwargs):return {'journal_hashes':{'1':'fictional'}}
    class App:
        def __init__(self,*args):pass
        def call(self,*args):return {'reports':[]}
    monkeypatch.setattr(B,'OpsLab',Lab);monkeypatch.setattr(client,'App',App)
    monkeypatch.setattr(B,'bootstrap',lambda *args:dict(seed));monkeypatch.setattr(B,'install',lambda *args:None)
    monkeypatch.setattr(B.httpx,'get',lambda *args:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'version':'0.16.9'}))
    return calls,out,seed


def test_bootstrap_stops_app_layers_before_owner_migration(monkeypatch,tmp_path):
    calls,out,seed=scenario(monkeypatch,tmp_path)
    assert B.run(tmp_path,{},out)==seed
    migration=next(i for i,a in enumerate(calls)if a[0]=='run')
    assert any(a[0]=='stop'and 'app'in a and 'backup'in a for a in calls[:migration])
    assert any(a[0]=='up'for a in calls[migration+1:])
    assert (out/'state.json').is_file()


def test_failed_migration_retains_approved_seed_and_does_not_restart_app(monkeypatch,tmp_path):
    calls,out,seed=scenario(monkeypatch,tmp_path,True)
    with pytest.raises(RuntimeError,match='Fictional migration failed'):B.run(tmp_path,{},out)
    assert (out/'approved-seed-state.json').is_file()
    assert not any(a[0]=='up'for a in calls)
    assert not(out/'state.json').exists()
