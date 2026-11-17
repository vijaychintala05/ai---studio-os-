"""A newer artifact cannot inherit old monthly passes or lose executable modes."""
import copy,hashlib,importlib.util,json,stat,zipfile
from pathlib import Path
import pytest


def module(monkeypatch):
    root=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(root/'sim'))
    spec=importlib.util.spec_from_file_location('fictional_review_builder',root/'sim/build_review_bundle.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def historical_fixture(tmp_path,monkeypatch,version):
    m=module(monkeypatch);monkeypatch.setattr(m,'ROOT',tmp_path)
    (tmp_path/'VERSION').write_text(version+'\n');(tmp_path/'VERSION').chmod(0o644)
    script=tmp_path/'ops/upgrade.sh';script.parent.mkdir();script.write_text('#!/bin/sh\nexit 0\n');script.chmod(0o755)
    original=tmp_path/'original.zip'
    with zipfile.ZipFile(original,'w')as z:
        z.writestr('studioos/VERSION','0.16.0\n')
        z.writestr('studioos/ops/upgrade.sh',script.read_text())
    monkeypatch.setattr(m,'BASELINE_SHA',hashlib.sha256(original.read_bytes()).hexdigest())
    runtime=tmp_path/'sim/runtime';lab=runtime/'ops-lab';lab.mkdir(parents=True)
    names=['month04','month05'];(lab/'two-clean-months.json').write_text(json.dumps({'passed':True,'clean_months':[{'month':n}for n in names]}))
    result={'qualified':True,'ops':{'passed':True},'browser_entries':600,'failures':[],
            'days':[{'answer_key':{'matching':True},'failures':[],'browser_entries':20,'posted':100}for _ in range(30)]}
    for name in names:
        p=lab/name/'run';p.mkdir(parents=True);(p/'result.json').write_text(json.dumps(result))
    required=('durable-books-full-sqlite.xml','durable-books-full-postgres.xml','candidate-cache-equivalence/result.json',
      'parallel-sessions-green/result.json','ticket-guidance-green/result.json','ci-books-final/result.json',
      'books-benchmark.log','books-accuracy.log','books-questions.log','final-page-scripts.json',
      'final-history-secrets.log','final-source-secrets.log','ops-lab/ops-logs/final-qualified-month05.json')
    for name in required:
        p=runtime/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    import preflight_recovery
    monkeypatch.setattr(preflight_recovery,'tests_green',lambda paths:[])
    def git(args,**kwargs):
        value=('VERSION\nops/upgrade.sh\n'if args[1]=='ls-files'else'fictional-commit'if args[1]=='rev-parse'else'')
        return value if kwargs.get('text')else value.encode()
    monkeypatch.setattr(m.subprocess,'check_output',git)
    return m,original,tmp_path/'artifacts'


def test_new_version_refuses_historical_passes_without_exact_qualification(tmp_path,monkeypatch):
    m,original,out=historical_fixture(tmp_path,monkeypatch,'0.16.12')
    with pytest.raises(ValueError,match='[Ee]xact.*qualification'):
        m.build(original,out)
    assert not list(out.glob('*.zip'))


def test_review_zip_preserves_actual_source_file_modes(tmp_path,monkeypatch):
    m,original,out=historical_fixture(tmp_path,monkeypatch,'0.16.10')
    result=m.build(original,out)
    with zipfile.ZipFile(result['zip'])as z:
        for name,mode in [('ops/upgrade.sh',0o755),('VERSION',0o644)]:
            item=z.getinfo('studioos-v0.16.10/'+name)
            assert stat.S_IMODE(item.external_attr>>16)==mode


def test_exact_bundle_guard_rejects_old_or_incomplete_months(monkeypatch):
    m=module(monkeypatch)
    from tests.test_exact_artifact_checkpoint import proof
    p,e=proof();build=e['build'];version=e['version']
    control={'status':'PASSED','version':version,'build':build,'image_id':e['image_id'],
             'database_backend':'postgresql','seed':260117}
    ops={**p['upgrade'],'baseline':version,'candidate':version,
         'mode':'exact_artifact_reinstall_with_real_prior_rollback','rollback_target':'0.16.10'}
    months={}
    for name,mode in [('offline-001','offline'),('replay-001','synthetic_recorded_replay')]:
        months[name]={'qualified':True,'status':'QUALIFIED_MONTH','start_version':version,'build':build,
          'database_backend':'postgresql','model_mode':mode,'failures':[],'ops':ops,'browser_entries':600,
          'days':[{'day':n,'app_version':version,'posted':100,'browser_entries':20,'failures':[],
            'answer_key':{'matching':True,'coverage':{'all_business_provenance':True}},
            'performance':{'passed':True},'model':{'passed':True}}for n in range(1,31)]}
    assert m.validate_exact_qualification(e,control,months,p,version,build)
    for field,value in [('build',{**build,'version':'0.16.10'}),('database_backend','sqlite'),('qualified',False)]:
        bad=copy.deepcopy(months);bad['offline-001'][field]=value
        with pytest.raises(ValueError):m.validate_exact_qualification(e,control,bad,p,version,build)
    for field in ('performance','answer_key','model'):
        bad=copy.deepcopy(months);bad['replay-001']['days'][7][field]={}
        with pytest.raises(ValueError):m.validate_exact_qualification(e,control,bad,p,version,build)
