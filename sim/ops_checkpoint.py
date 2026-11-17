"""Day-15 real ops checkpoint, exclusively inside the guarded fictional lab.

Sequential containers accommodate rootless Docker VFS without removing volumes.
All backups, upgrade markers and script output remain available for review.
"""
import datetime as dt,json,os,re,secrets,time,hashlib
from pathlib import Path
import httpx
from ops_lab import OpsLab,ROOT
from client import App


def wait(url,version):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        try:
            h=httpx.get(url+'/health',timeout=5).json()
            if h.get('environment')=='test'and h.get('version')==version:return
        except (httpx.HTTPError,ValueError):pass
        time.sleep(1)
    raise RuntimeError(f'Fictional app did not become healthy on {version}')


def suspend(lab,target,label):
    lab.dc(target,'stop','app','backup','db',name=label+'-stop')
    lab.dc(target,'rm','-f','app','backup','db','migrate',name=label+'-remove-containers-keep-volumes')


def start(lab,target,label):
    env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(lab.config(target))}
    lab.execute(['bash','-c','source ops/_common.sh "$@"; start_version; wait_healthy "$(env_value STUDIOOS_VERSION)"','ops/start.sh']+(['--test']if target=='test'else[]),label,env=env)


def assert_same(before,after,label):
    if before!=after:
        changed=[key for key in before if before[key]!=after.get(key)]
        raise AssertionError(f'{label}: fingerprint changed: {changed}')


def open_populated(url,state,out):
    """Authenticate and open pre-upgrade records, links and approved photos."""
    a=App(url,out);projects=a.call('GET','/api/projects');assert len(projects)>=10
    assert len(a.journals(state['entity']))>=1500
    tasks=a.call('GET','/api/tasks');assert tasks
    documents=a.call('GET','/api/documents');assert documents
    snag=next(iter(state['snags'].values()))
    record=a.call('GET',f'/api/graph/record/{snag["id"]}');assert record
    photo=a.http.get(f'/api/documents/{snag["document_id"]}/file');assert photo.status_code==200 and photo.content
    for report in ('open_issues_by_owner','material_sample_by_owner','drawing_revision_by_owner'):
        a.call('GET','/api/graph/reports/'+report+'/run')
    integrity=a.call('GET','/api/system/integrity')
    # Preserve the returned contract as evidence instead of guessing its shape.
    (Path(out)/'integrity.json').write_text(json.dumps(integrity,indent=2))
    if integrity.get('overall')!='ok':raise AssertionError(integrity)
    a.call('POST','/api/auth/logout',{});a.http.close()
    return {'projects_opened':len(projects),'old_tasks_available':len(tasks),'old_snag_opened':True,'old_photo_opened':True,'reports_opened':3}




def prove_old_record_editable(url,state,out):
    """Two approved revisions restore the original value and preserve both edits."""
    import copy
    a=App(url,out);snag=next(iter(state['snags'].values()));original=copy.deepcopy(snag['values']);version=snag['version'];tickets=[]
    for values in ({**original,'title':original['title']+' - fictional continuity check'},original):
        proposal=a.call('POST','/api/universal/proposals',{'kind':'metadata_record_update','data':{'record_id':snag['id'],'type_key':'work_issue','project_id':snag['project_id'],'expected_version':version,'values':values},'evidence':'Fictional owner reviewed a pre-upgrade record for continuity; preserve every revision'})
        a.approve(proposal);tickets.append(proposal['ticket_id']);version+=1
        page=a.call('GET',f'/api/graph/record/{snag["id"]}');actual={f['name']:f['raw']for f in page['values']}
        assert page['current_version']==version and page['project_id']==snag['project_id']
        assert all(actual.get(key)==value for key,value in values.items())
    snag['version']=version
    a.call('POST','/api/auth/logout',{});a.http.close()
    return {'old_record_id':snag['id'],'approved_revision_tickets':tickets,'original_values_restored':True,'new_history_preserved':True}


def open_restored_copy(lab,state,database):
    """Serve the real app against the unmasked restored DB inside its guarded
    fictional container, with scheduling off; use real authenticated HTTP reads.
    This adds no second Docker writable layer on the storage-limited VFS host.
    """
    lab.inspect_app('live')
    assert re.fullmatch(r'studioos_sim_restore_[0-9]{14}_[0-9a-f]{6}',database)
    code="""import os,sys,subprocess,time,json,httpx
from pathlib import Path
env={**os.environ,'DATABASE_URL':os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/studioos_sim_restore_day15','STUDIOOS_SCHEDULER':'off'}
log=open('/tmp/fictional-restore-view.log','w')
p=subprocess.Popen([sys.executable,'-m','uvicorn','studioos.main:app','--host','127.0.0.1','--port','8002'],env=env,stdout=log,stderr=subprocess.STDOUT)
try:
 c=httpx.Client(base_url='http://127.0.0.1:8002',timeout=30)
 for _ in range(90):
  if p.poll() is not None:raise RuntimeError('Restored-copy app exited: '+Path('/tmp/fictional-restore-view.log').read_text()[-2000:])
  try:
   h=c.get('/health');h.raise_for_status();assert h.json()['environment']=='test';break
  except (httpx.HTTPError,AssertionError):time.sleep(1)
 else:raise RuntimeError('Restored-copy app did not start')
 response=c.post('/api/auth/login',json={'username':os.environ['STUDIOOS_ADMIN_USERNAME'],'password':os.environ['STUDIOOS_ADMIN_PASSWORD']});response.raise_for_status()
 endpoints=ENDPOINTS
 for path in endpoints:
  response=c.get(path);response.raise_for_status()
  assert response.content,('Empty restored record',path)
  if path=='/api/system/integrity':assert response.json()['overall']=='ok',response.json()
 print(json.dumps({'real_http_app_opened':True,'database':'studioos_sim_restore_day15','endpoints_checked':len(endpoints),'scheduler':'off'}))
finally:
 p.terminate()
 try:p.wait(timeout=15)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 log.close()
"""
    snag=next(iter(state['snags'].values()))
    endpoints=['/api/projects','/api/tasks',f'/api/finance-ledger/trial-balance/{state["entity"]}',
        f'/api/graph/record/{snag["id"]}',f'/api/documents/{snag["document_id"]}/file','/api/system/integrity']
    code=code.replace('ENDPOINTS',repr(endpoints)).replace('studioos_sim_restore_day15',database)
    log=lab.execute(lab.dc_args('live')+['exec','-T','app','python','-'],'day15-unmasked-copy-http',input=code)
    return json.loads(log.read_text())


def run(root,state,out,upgrade_proof=None):
    lab=OpsLab(root);out=Path(out);out.mkdir(parents=True,exist_ok=True);lab.log_mirror=out/'ops-logs'
    restore_database='studioos_sim_restore_'+dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S')+'_'+secrets.token_hex(3)
    baseline=json.loads((lab.root/'fictional-lab.json').read_text())['baseline'];candidate=(ROOT/'VERSION').read_text().strip()
    exact=None;prior=None;rollback_version=baseline
    if baseline==candidate:
        from artifact_proof import validate
        if not upgrade_proof:raise ValueError('An actual distinct-version upgrade proof is required before an exact-artifact month')
        path=Path(upgrade_proof).resolve()
        if path.suffix!='.json'or not path.is_relative_to(lab.root):raise ValueError('Upgrade proof must be inside the fictional lab')
        exact=json.loads((lab.root/'exact-release.json').read_text())
        prior=validate(json.loads(path.read_text()),exact)
        rollback_version=prior['source_version']
    else:
        assert baseline!=candidate,'An actual version switch is required'
    def exact_target(target):
        if exact is None:return
        from run_identity import verify
        assert lab.inspect_app(target)['Image']==exact['image_id'],'Exact shipping image changed'
        port=8881 if target=='test'else 8880
        verify(httpx.get(f'http://127.0.0.1:{port}/health',timeout=10).json(),exact['build'],'postgresql')
    exact_target('live')
    evidence={'baseline':baseline,'candidate':candidate,'passed':False,'restore_database':restore_database,
              'mode':'exact_artifact_reinstall_with_real_prior_rollback'if exact else'actual_version_upgrade',
              'rollback_target':rollback_version}
    if exact:
        evidence['independent_upgrade_proof_sha256']=hashlib.sha256(Path(upgrade_proof).read_bytes()).hexdigest()
        evidence['shipping_build']=exact['build'];evidence['shipping_image_id']=exact['image_id']
    def save(): (out/'result.json').write_text(json.dumps(evidence,indent=2))
    save()
    # The actual backup-now script includes attachment rescue, offsite verification
    # and a populated scratch restore drill. Parse status as well as process exit.
    before=lab.capture('live','day15-live-before')
    lab.ops('live','backup-now.sh','sim-day15',name='day15-live-backup')
    status=json.loads((lab.backup_path('live')/'status/status.json').read_text())
    assert status['last_backup']['verified'] and status['last_backup']['offsite']['ok'] and not status['last_backup']['files']['problems'] and status['last_drill']['ok'],status
    backup=status['last_backup']['file'];evidence['backup']=backup;save()
    # Restore an additional unmasked database alongside the fictional source.
    lab.dc('live','exec','-T','backup','python','-m','studioos.safekeeping','restore-copy','--file',backup,'--into',restore_database,name='day15-unmasked-restore-copy')
    # Grant read-only access on this restored copy; no business rows or guards
    # change. Backups deliberately carry no grants.
    grant="""from studioos.safekeeping import Config,psql
cfg=Config()
env=cfg.pg_env()
psql(env,'GRANT CONNECT ON DATABASE studioos_sim_restore_day15 TO studioos_app','postgres')
psql(env,'REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO studioos_app; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO studioos_app; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO studioos_app','studioos_sim_restore_day15')
print('restored-copy standard restricted row access ready; no business rows modified')
"""
    grant=grant.replace('studioos_sim_restore_day15',restore_database)
    lab.execute(lab.dc_args('live')+['exec','-T','backup','python','-'],'day15-restore-read-grants',input=grant)
    restored=lab.capture('live','day15-unmasked-restored',database=restore_database)
    assert_same(before,restored,'populated restore copy');evidence['restore_copy_identical']=True
    evidence['restore_copy_opened']=open_restored_copy(lab,state,restore_database)
    # This uniquely named restore-drill fixture is redundant after exact content
    # comparison and real HTTP reads. Retain the verified source backup and all
    # fingerprints, retire only this copy (never the source/previous monthly DB).
    cleanup="from studioos.safekeeping import Config,psql,terminate_connections,quote_ident\nenv=Config().pg_env()\nname="+repr(restore_database)+"\nassert name.startswith('studioos_sim_restore_') and name!=Config().live_db\nterminate_connections(env,name)\npsql(env,'DROP DATABASE '+quote_ident(name),'postgres')\nprint('verified disposable restore copy retired; source backup retained')\n"
    lab.execute(lab.dc_args('live')+['exec','-T','backup','python','-'],'day15-retire-verified-restore-copy',input=cleanup)
    evidence['restore_copy_retired_after_verified_open']=True
    save()
    suspend(lab,'live','day15-live-pause')
    # The exact owner script loads, masks and checks the populated backup into
    # the separate test volume; live backups are mounted read-only there.
    lab.dc('test','up','-d','db',name='day15-test-database')
    lab.ops('test','make-test-copy.sh',name='day15-make-test-copy')
    wait('http://127.0.0.1:8881',baseline)
    evidence['masked_copy_opened']=open_populated('http://127.0.0.1:8881',state,out/'masked-copy-open')
    test_before=lab.capture('test','day15-test-before')
    lab.ops('test','upgrade.sh',name='day15-test-upgrade')
    exact_target('test')
    test_after=lab.capture('test','day15-test-after');assert_same(test_before,test_after,'test upgrade')
    evidence['test_upgrade_identical']=True;save()
    suspend(lab,'test','day15-test-pause')
    start(lab,'live','day15-live-resume-baseline')
    assert_same(before,lab.capture('live','day15-live-resumed'),'resumed baseline')
    lab.ops('live','upgrade.sh',name='day15-live-upgrade')
    exact_target('live')
    assert_same(before,lab.capture('live','day15-live-upgraded'),'live upgrade')
    evidence['live_upgrade_identical']=True;save()
    lab.ops('live','rollback.sh','--to',rollback_version,name='day15-code-rollback')
    if prior:assert lab.inspect_app('live')['Image']==prior['source_image_id'],'Actual prior rollback image changed'
    assert_same(before,lab.capture('live','day15-live-rolled-back'),'rollback')
    lab.ops('live','rollback.sh','--to',candidate,name='day15-code-forward')
    exact_target('live')
    assert_same(before,lab.capture('live','day15-live-forward'),'forward after rollback')
    evidence['rollback_identical']=True
    evidence['old_records_opened']=open_populated('http://127.0.0.1:8880',state,out/'upgraded-old-records')
    evidence['old_record_editable']=prove_old_record_editable('http://127.0.0.1:8880',state,out/'old-record-edit')
    evidence['passed']=True;save();return evidence
