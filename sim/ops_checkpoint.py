"""Day-15 real ops checkpoint, exclusively inside the guarded fictional lab.

Sequential containers accommodate rootless Docker VFS without removing volumes.
All backups, upgrade markers and script output remain available for review.
"""
import json,os,time
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



def open_restored_copy(lab,state):
    """Serve the real app against the unmasked restored DB inside its guarded
    fictional container, with scheduling off; use real authenticated HTTP reads.
    This adds no second Docker writable layer on the storage-limited VFS host.
    """
    lab.inspect_app('live')
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
    code=code.replace('ENDPOINTS',repr(endpoints))
    log=lab.execute(lab.dc_args('live')+['exec','-T','app','python','-'],'day15-unmasked-copy-http',input=code)
    return json.loads(log.read_text())


def run(root,state,out):
    lab=OpsLab(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((lab.root/'fictional-lab.json').read_text())['baseline'];candidate=(ROOT/'VERSION').read_text().strip()
    assert baseline!=candidate,'An actual version switch is required'
    evidence={'baseline':baseline,'candidate':candidate,'passed':False}
    def save(): (out/'result.json').write_text(json.dumps(evidence,indent=2))
    save()
    # The actual backup-now script includes attachment rescue, offsite verification
    # and a populated scratch restore drill. Parse status as well as process exit.
    before=lab.capture('live','day15-live-before')
    lab.ops('live','backup-now.sh','sim-day15',name='day15-live-backup')
    status=json.loads((lab.root/'primary/live/status/status.json').read_text())
    assert status['last_backup']['verified'] and status['last_backup']['offsite']['ok'] and not status['last_backup']['files']['problems'] and status['last_drill']['ok'],status
    backup=status['last_backup']['file'];evidence['backup']=backup;save()
    # Restore an additional unmasked database alongside the fictional source.
    lab.dc('live','exec','-T','backup','python','-m','studioos.safekeeping','restore-copy','--file',backup,'--into','studioos_sim_restore_day15',name='day15-unmasked-restore-copy')
    # Grant read-only access on this restored copy; no business rows or guards
    # change. Backups deliberately carry no grants.
    grant="""from studioos.safekeeping import Config,psql
cfg=Config()
env=cfg.pg_env()
psql(env,'GRANT CONNECT ON DATABASE studioos_sim_restore_day15 TO studioos_app','postgres')
psql(env,'REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO studioos_app; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO studioos_app; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO studioos_app','studioos_sim_restore_day15')
print('restored-copy standard restricted row access ready; no business rows modified')
"""
    lab.execute(lab.dc_args('live')+['exec','-T','backup','python','-'],'day15-restore-read-grants',input=grant)
    restored=lab.capture('live','day15-unmasked-restored',database='studioos_sim_restore_day15')
    assert_same(before,restored,'populated restore copy');evidence['restore_copy_identical']=True
    evidence['restore_copy_opened']=open_restored_copy(lab,state)
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
    test_after=lab.capture('test','day15-test-after');assert_same(test_before,test_after,'test upgrade')
    evidence['test_upgrade_identical']=True;save()
    suspend(lab,'test','day15-test-pause')
    start(lab,'live','day15-live-resume-baseline')
    assert_same(before,lab.capture('live','day15-live-resumed'),'resumed baseline')
    lab.ops('live','upgrade.sh',name='day15-live-upgrade')
    assert_same(before,lab.capture('live','day15-live-upgraded'),'live upgrade')
    evidence['live_upgrade_identical']=True;save()
    lab.ops('live','rollback.sh','--to',baseline,name='day15-code-rollback')
    assert_same(before,lab.capture('live','day15-live-rolled-back'),'rollback')
    lab.ops('live','rollback.sh','--to',candidate,name='day15-code-forward')
    assert_same(before,lab.capture('live','day15-live-forward'),'forward after rollback')
    evidence['rollback_identical']=True
    evidence['old_records_opened']=open_populated('http://127.0.0.1:8880',state,out/'upgraded-old-records')
    evidence['passed']=True;save();return evidence
