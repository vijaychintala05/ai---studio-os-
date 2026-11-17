"""Build a local review ZIP and original-release diff after observed qualification.
Never publishes, tags, merges or packages runtime credentials/databases/backups.
"""
import argparse,datetime as dt,hashlib,json,stat,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASELINE='a7c3e53'
BASELINE_SHA='94e37a05d1d4cdcb7a2387392d781823f97dabeb0bad26591c46e63d55e35dec'


def allowed(name):
    p=Path(name)
    if p.is_absolute()or '..'in p.parts:return False
    if any(x in p.parts for x in ('.git','__pycache__','.pytest_cache','data','backups','files','node_modules')):return False
    if name.startswith(('sim/runtime/','sim/evidence/')):return False
    if p.name.startswith('.env')and not p.name.endswith('.example'):return False
    return p.suffix not in ('.pyc','.db','.sqlite3','.dump','.pem','.key','.zip')


def write_zip(path,version,payload,modes):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9)as archive:
        for name,data in sorted(payload.items()):
            item=zipfile.ZipInfo('studioos-v'+version+'/'+name)
            item.create_system=3;item.compress_type=zipfile.ZIP_DEFLATED
            item.external_attr=(stat.S_IFREG|modes.get(name,0o644))<<16
            archive.writestr(item,data)


def validate_exact_qualification(manifest,control,months,proof,version,identity):
    from artifact_proof import validate
    def require(ok,why):
        if not ok:raise ValueError('Exact review qualification: '+why)
    require(manifest.get('version')==version and manifest.get('build')==identity,'candidate source mismatch')
    require(control.get('status')=='PASSED','qualification incomplete or failed')
    require(control.get('version')==version and control.get('build')==identity,'control source mismatch')
    require(control.get('image_id')==manifest.get('image_id'),'control image mismatch')
    require(control.get('database_backend')=='postgresql'and type(control.get('seed'))is int and control['seed']!=160030,'different-seed PostgreSQL month required')
    validate(proof,manifest)
    require(set(months)=={'offline-001','replay-001'},'two fresh exact months required')
    for name,result in months.items():
        require(result.get('qualified')is True and result.get('status')=='QUALIFIED_MONTH'and not result.get('failures'),'month not qualified: '+name)
        require(result.get('build')==identity and result.get('start_version')==version,'month build mismatch: '+name)
        require(result.get('database_backend')=='postgresql','month backend mismatch: '+name)
        require(result.get('model_mode')==('offline'if name=='offline-001'else'synthetic_recorded_replay'),'month reader mode mismatch')
        days=result.get('days',[])
        require([d.get('day')for d in days]==list(range(1,31)),'thirty consecutive complete days required')
        require(result.get('browser_entries',0)>=600,'six hundred genuine browser entries required')
        for day in days:
            require(day.get('app_version')==version and not day.get('failures'),'failed or different-build day')
            require(day.get('browser_entries',0)>=20,'daily browser quota missing')
            answer=day.get('answer_key')or{};coverage=answer.get('coverage')or{}
            require(answer.get('matching')is True and coverage and all(v is True for v in coverage.values()),'daily oracle or coverage missing')
            require((day.get('performance')or{}).get('passed')is True,'daily performance gate missing')
            if name=='replay-001':require((day.get('model')or{}).get('passed')is True,'daily recorded gateway coverage missing')
        ops=result.get('ops')or{}
        require(ops.get('mode')=='exact_artifact_reinstall_with_real_prior_rollback'and ops.get('baseline')==version and ops.get('candidate')==version,'monthly recovery mode mismatch')
        require(ops.get('rollback_target')==proof['source_version'],'real prior rollback missing')
        for key in ('passed','restore_copy_identical','test_upgrade_identical','live_upgrade_identical','rollback_identical'):
            require(ops.get(key)is True,'monthly recovery failed: '+key)
        require((ops.get('old_record_editable')or{}).get('new_history_preserved')is True,'old record approval/edit evidence missing')
    return True


def build(original,out,qualification=None,manifest=None,sqlite=None,postgres=None):
    version=(ROOT/'VERSION').read_text().strip()
    if any(x is not None for x in (qualification,manifest,sqlite,postgres)):
        if not all(x is not None for x in (qualification,manifest,sqlite,postgres)):
            raise ValueError('Exact release qualification, build manifest and both full suites are required')
        return build_exact(original,out,qualification,manifest,sqlite,postgres)
    if version!='0.16.10':
        raise ValueError('Exact release qualification is required; historical months cannot certify a new version')
    from preflight_recovery import tests_green
    original=Path(original).resolve();out=Path(out).resolve();assert out.is_relative_to(ROOT/'artifacts')
    assert hashlib.sha256(original.read_bytes()).hexdigest()==BASELINE_SHA,'Wrong original v0.16.0 ZIP'
    assert not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).strip(),'Commit reviewed changes and final reports before packaging'
    runtime=ROOT/'sim/runtime';lab=runtime/'ops-lab';summary=json.loads((lab/'two-clean-months.json').read_text())
    assert summary['passed']and len(summary['clean_months'])==2,'No qualified two-month result'
    matrix=tests_green([runtime/'durable-books-full-sqlite.xml',runtime/'durable-books-full-postgres.xml'])
    evidence={};payload={};modes={}
    for month in summary['clean_months']:
        folder=lab/month['month'];result=json.loads((folder/'run/result.json').read_text())
        assert result['qualified']and len(result['days'])==30 and not result['failures']and result['ops']['passed']
        assert all(d['answer_key']['matching']and not d['failures']and d['browser_entries']>=20 for d in result['days'])
        evidence[month['month']]={'browser_entries':result['browser_entries'],'days':30,'money':sum(d['posted']for d in result['days'])}
        selected=[folder/'run/result.json',folder/'final-mobile/result.json',*sorted((folder/'run').glob('day-*/result.json')),*sorted((folder/'run/day15-ops').rglob('*.json')),*sorted((folder/'run/day15-ops/ops-logs').glob('*.log'))]
        for path in selected:
            if path.is_file():payload['sim/evidence/'+str(path.relative_to(lab))]=path.read_bytes()
        for path in sorted((folder/'run').glob('day-*/*/entries.jsonl')):payload['sim/evidence/'+str(path.relative_to(lab))]=path.read_bytes()
        for path in sorted((folder/'run').glob('day-*/*/reviews.jsonl')):payload['sim/evidence/'+str(path.relative_to(lab))]=path.read_bytes()
        for path in sorted((folder/'run').rglob('http.jsonl')):payload['sim/evidence/'+str(path.relative_to(lab))]=path.read_bytes()
    with zipfile.ZipFile(original)as source:
        for item in source.infolist():
            if item.is_dir():continue
            path=Path(item.filename);name=str(Path(*path.parts[1:]))
            if allowed(name):
                payload[name]=source.read(item);modes[name]=stat.S_IMODE(item.external_attr>>16)or 0o644
    tracked=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    for name in tracked:
        path=ROOT/name
        if path.is_file()and allowed(name):
            payload[name]=path.read_bytes();modes[name]=stat.S_IMODE(path.stat().st_mode)
    for path in sorted((runtime/'generated-v6').glob('*.json')):payload['sim/fixtures/'+path.name]=path.read_bytes()
    for name in ('durable-books-full-sqlite.xml','durable-books-full-postgres.xml','candidate-cache-equivalence/result.json','parallel-sessions-green/result.json','ticket-guidance-green/result.json','ci-books-final/result.json','books-benchmark.log','books-accuracy.log','books-questions.log','final-page-scripts.json','final-history-secrets.log','final-source-secrets.log','ops-lab/ops-logs/final-qualified-month05.json'):
        payload['sim/evidence/'+name]=(runtime/name).read_bytes()
    payload['sim/evidence/two-clean-months.json']=(lab/'two-clean-months.json').read_bytes()
    for path in sorted(runtime.glob('month00[1-5]/result.json')):
        payload['sim/evidence/diagnostics/'+str(path.relative_to(runtime))]=path.read_bytes()
    for folder in sorted(lab.glob('month[0-9][0-9]')):
        path=folder/'run/result.json'
        if path.exists():payload['sim/evidence/attempts/'+str(path.relative_to(lab))]=path.read_bytes()
    for folder in ('ticket-guidance-red3','parallel-sessions-red'):
        for path in (runtime/folder).glob('*.png'):payload['sim/evidence/failures/'+folder+'/'+path.name]=path.read_bytes()
    version=(ROOT/'VERSION').read_text().strip();out.mkdir(parents=True,exist_ok=True)
    diff=subprocess.check_output(['git','diff','--binary',BASELINE,'HEAD'],cwd=ROOT)
    diffpath=out/f'StudioOS_v{version}_against_v0.16.0.diff';diffpath.write_bytes(diff)
    payload[diffpath.name]=diff
    metadata={'version':version,'built_utc':dt.datetime.now(dt.UTC).isoformat(),'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'original_zip_sha256':BASELINE_SHA,'matrix':matrix,'observed_months':evidence,'patched_baseline_scenario_passed':True,'untouched_v0160_first_half_met':False,'limitations':['Both clean months use a patched baseline. Original v0.16.0 failed opening balances.','Local offsite folders emulate external storage; no owner NAS, real data or accountant sign-off was used.']}
    payload['SIMULATION_MANIFEST.json']=json.dumps(metadata,indent=2).encode()
    filename=out/f'StudioOS_v{version}_Reviewed_Simulation.zip'
    write_zip(filename,version,payload,modes)
    with zipfile.ZipFile(filename)as archive:assert archive.testzip()is None
    checksum=hashlib.sha256(filename.read_bytes()).hexdigest();filename.with_suffix('.zip.sha256').write_text(checksum+'  '+filename.name+'\n')
    metadata.update(zip=str(filename),diff=str(diffpath),sha256=checksum,files=len(payload));(out/'bundle-result.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2));return metadata
def build_exact(original,out,qualification,manifest,sqlite,postgres):
    from preflight_recovery import tests_green
    from studioos.build_identity import source_identity
    original,out=Path(original).resolve(),Path(out).resolve()
    if not out.is_relative_to(ROOT/'artifacts'):raise ValueError('Local review artifact folder required')
    if hashlib.sha256(original.read_bytes()).hexdigest()!=BASELINE_SHA:raise ValueError('Wrong untouched original ZIP')
    paths=[Path(p).resolve()for p in (qualification,manifest,sqlite,postgres)]
    if not all(p.is_relative_to(ROOT/'sim/runtime')for p in paths):raise ValueError('Fictional qualification evidence paths required')
    q,manifest_path,sqlite,postgres=paths
    expected=json.loads(manifest_path.read_text());control=json.loads((q/'run-control.json').read_text())
    months={name:json.loads((q/name/'run/result.json').read_text())for name in ('offline-001','replay-001')}
    proof=json.loads((q/'upgrade-proof/identity.json').read_text());identity=source_identity(ROOT);version=identity['version']
    validate_exact_qualification(expected,control,months,proof,version,identity)
    if subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).strip():raise ValueError('Commit reviewed changes and final reports before packaging')
    actual=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','studioos-app:'+version],text=True).strip()
    if actual!=expected['image_id']:raise ValueError('Exact candidate image changed')
    matrix=tests_green([sqlite,postgres])
    for xml in (sqlite,postgres):
        validation=json.loads((xml.parent/'result.json').read_text())
        if validation.get('status')!='PASSED'or validation.get('build')!=identity:raise ValueError('Full suite source identity mismatch')
    payload={};modes={}
    with zipfile.ZipFile(original)as source:
        for item in source.infolist():
            if item.is_dir():continue
            name=Path(*Path(item.filename).parts[1:]).as_posix()
            if allowed(name):payload[name]=source.read(item);modes[name]=stat.S_IMODE(item.external_attr>>16)or 0o644
    for name in subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines():
        p=ROOT/name
        if p.is_file()and allowed(name):payload[name]=p.read_bytes();modes[name]=stat.S_IMODE(p.stat().st_mode)
    def evidence(p,name=None):
        p=Path(p)
        if p.is_file():payload['sim/evidence/exact/'+(name or p.relative_to(q).as_posix())]=p.read_bytes()
    evidence(q/'run-control.json');evidence(manifest_path,'clean-build-manifest.json')
    evidence(q/'upgrade-proof/identity.json')
    for p in sorted((q/'upgrade-proof/checkpoint').rglob('*.json')):evidence(p)
    for p in sorted((q/'ops-logs').glob('*')):
        if p.suffix in ('.log','.json'):evidence(p)
    for name,result in months.items():
        folder=q/name
        for p in [folder/'run/result.json',folder/'final-mobile/result.json',*folder.glob('run/day-*/result.json'),*folder.glob('run/day15-ops/**/*.json'),*folder.glob('run/day15-ops/**/*.log')]:evidence(p)
        for pattern in ('run/**/http.jsonl','run/day-*/*/entries.jsonl','run/day-*/*/reviews.jsonl','final-mobile/*.png'):
            for p in sorted(folder.glob(pattern)):evidence(p)
    for p in (sqlite,postgres,sqlite.parent/'result.json',postgres.parent/'result.json'):
        evidence(p,'full-tests/'+p.parent.name+'/'+p.name)
    evidence(q/'recorded-corpus/reader-responses.json')
    version_root=q.parent
    for p in sorted(version_root.glob('qualification-*/run-control.json')):
        evidence(p,'attempts/'+p.parent.name+'/run-control.json')
    for name in ('ancillary-final.json','accuracy-final.json','questions-final.json','secrets-history.log','secrets-source.log'):
        evidence(version_root/name,'checks/'+name)
    for p in sorted((version_root/'ci-bank-final').glob('*.json')):evidence(p,'checks/'+p.parent.name+'/'+p.name)
    for folder in (version_root,ROOT/'sim/runtime/v01611'):
        prefix='history/'+folder.name+'/'
        for pattern in ('*red*.log','*green*.log','*formal*.log','*real-pg*.json','*invalid*status*.json'):
            for p in sorted(folder.glob(pattern)):evidence(p,prefix+p.name)
        for p in sorted(folder.glob('qualification-*/run-control.json')):
            evidence(p,prefix+p.relative_to(folder).as_posix())
        for p in sorted(folder.glob('qualification-*/offline-001/run/result.json')):
            evidence(p,prefix+p.relative_to(folder).as_posix())
        for p in sorted(folder.glob('qualification-*/offline-001/run/day-*/result.json')):
            evidence(p,prefix+p.relative_to(folder).as_posix())
    out.mkdir(parents=True,exist_ok=True)
    diff=subprocess.check_output(['git','diff','--binary',BASELINE,'HEAD'],cwd=ROOT)
    diffpath=out/f'StudioOS_v{version}_against_v0.16.0.diff';diffpath.write_bytes(diff);payload[diffpath.name]=diff
    metadata={'version':version,'built_utc':dt.datetime.now(dt.UTC).isoformat(),'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'original_zip_sha256':BASELINE_SHA,'build':identity,'image_id':expected['image_id'],'matrix':matrix,
      'seed':control['seed'],'database_backend':'postgresql','exact_candidate_months_passed':True,
      'actual_prior_upgrade_passed':True,'untouched_v0160_first_half_met':False,
      'model_evidence':'synthetic assistant-authored response replay; real provider inference/recordings NOT RUN',
      'observed_months':{name:{'days':len(x['days']),'money':sum(d['posted']for d in x['days']),'browser_entries':x['browser_entries']}for name,x in months.items()},
      'limitations':['Untouched v0.16.0 failed opening balances.','Monthly day15 is an exact-candidate reinstall plus real prior-version rollback; distinct-version upgrade independently verified.','No owner NAS, real data, physically off-NAS storage, accountant sign-off or paid provider was used.','Rebuilding can resolve different dependency versions; exact tested runtime image is a separate local artifact.']}
    payload['SIMULATION_MANIFEST.json']=json.dumps(metadata,indent=2).encode()
    filename=out/f'StudioOS_v{version}_Reviewed_Simulation.zip';write_zip(filename,version,payload,modes)
    with zipfile.ZipFile(filename)as z:
        assert z.testzip()is None
        for name,mode in modes.items():assert stat.S_IMODE(z.getinfo('studioos-v'+version+'/'+name).external_attr>>16)==mode
    from qualify_release import bundle_source
    if bundle_source(filename)[0]!=identity:raise ValueError('ZIP application bytes differ from the exact tested source')
    sha=hashlib.sha256(filename.read_bytes()).hexdigest();filename.with_suffix('.zip.sha256').write_text(sha+'  '+filename.name+'\n')
    metadata.update(zip=str(filename),diff=str(diffpath),sha256=sha,files=len(payload));(out/f'bundle-v{version}-result.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2));return metadata


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--out',default=str(ROOT/'artifacts'))
    for key in ('qualification','manifest','sqlite','postgres'):p.add_argument('--'+key)
    a=p.parse_args();build(a.original,a.out,a.qualification,a.manifest,a.sqlite,a.postgres)
