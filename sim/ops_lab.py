"""Normal StudioOS ops scripts, guarded to explicit fictional local Compose mounts.
No simulated upgrade success: subprocess failure stops the checkpoint.
"""
import argparse,json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class OpsLab:
 def __init__(self,root):
  self.root=Path(root).resolve()
  if not self.root.is_relative_to(ROOT/'sim/runtime'):raise ValueError('Fictional lab must be below sim/runtime')
  self.root.mkdir(parents=True,exist_ok=True);(self.root/'ops-logs').mkdir(exist_ok=True);self.log_mirror=None
 def config(self,target):return self.root/(target+'.example')
 def dc_args(self,target):
  if target not in ('live','test'):raise ValueError(target)
  return ['docker','compose','-p','studioos-'+target,'--env-file',str(self.config(target)),'-f','compose.yaml']+(['-f','compose.test.yaml']if target=='test'else[])
 def execute(self,args,name,env=None,input=None):
  path=self.root/'ops-logs'/(name+'.log')
  with path.open('w')as out:
   result=subprocess.run(args,cwd=ROOT,env=env,input=input,text=True,stdout=out,stderr=subprocess.STDOUT)
  if self.log_mirror:
   self.log_mirror.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,self.log_mirror/path.name)
  with(ROOT/'sim/LOG.md').open('a')as record:record.write(f'\n- Ops step {name}: exit{result.returncode}; exact output {path.relative_to(ROOT)}.\n')
  if result.returncode:raise RuntimeError(f'{name}: exit {result.returncode}; exact output: {path}')
  return path
 def dc(self,target,*args,name):return self.execute(self.dc_args(target)+list(args),name)
 def ops(self,target,script,*args,name,input=None):
  env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(self.config(target))}
  return self.execute(['bash','ops/'+script]+(['--test']if target=='test'else[])+list(args),name,env,input)
 def prepare(self,version='0.16.7',run='month01'):
  for target,port in [('live',8880),('test',8881)]:
   files=self.root/run/target/'files';primary=self.root/'primary'/target;offsite=self.root/'offsite'/target
   for path in(files,primary,offsite):path.mkdir(parents=True,exist_ok=True)
   (files/'simulation-clock.json').write_text('{"utc":"2026-01-01T00:30:00+00:00"}')
   values={'DB_PASSWORD':'FictionalOwnerDatabasePassword2026','STUDIOOS_APP_DB_USER':'studioos_app','STUDIOOS_APP_DB_PASSWORD':'Fictional_App_Database_Password_2026',
    'STUDIOOS_DB_ROLE':'app','STUDIOOS_ADMIN_USERNAME':'admin','STUDIOOS_ADMIN_PASSWORD':'FictionalOwnerLoginPassword2026',
    'STUDIOOS_VERSION':version,'STUDIOOS_ENV':'test','STUDIOOS_REQUIRE_ADMIN_2FA':'false','STUDIOOS_SECURE_COOKIE':'false',
    'STUDIOOS_PROVIDER':'demo','STUDIOOS_ALLOW_LIVE_AI':'false','STUDIOOS_SCHEDULER':'on','STUDIOOS_SIMULATION_CLOCK':'/app/files/simulation-clock.json',
    'STUDIOOS_SIMULATION_POLL_SECONDS':'1','STUDIOOS_BUILD_CA_FILE':'/etc/ssl/certs/ca-certificates.crt','APP_PORT':str(port),'BACKUP_PATH':str(primary),'OFFSITE_PATH':str(offsite),'FILES_PATH':str(files),
    'NAS_PROJECTS_PATH':str(ROOT/'sample-nas'),'LIVE_BACKUP_PATH':str(self.root/'primary/live')}
   self.config(target).write_text(''.join(f'{k}={v}\n'for k,v in values.items()));self.config(target).chmod(0o600)
  metadata=json.dumps({'fictional':True,'run':run,'baseline':version,'ports':{'live':8880,'test':8881}},indent=2)
  (self.root/'fictional-lab.json').write_text(metadata)
  (self.root/run/'fictional-lab.json').write_text(metadata)
 def inspect_app(self,target):
  ids=subprocess.check_output(self.dc_args(target)+['ps','-q','app'],cwd=ROOT,text=True).strip()
  if not ids or '\n'in ids:raise ValueError('One running fictional app required')
  info=json.loads(subprocess.check_output(['docker','inspect',ids],text=True))[0]
  labels=info['Config']['Labels'];env=info['Config']['Env'];mounts=info['Mounts']
  assert labels.get('com.docker.compose.project')=='studioos-'+target
  assert 'STUDIOOS_ENV=test'in env and 'STUDIOOS_DB_ROLE=app'in env
  assert any(m['Destination']=='/app/files'and Path(m['Source']).is_relative_to(self.root)for m in mounts)
  assert not any(m['Destination']=='/app/studioos'for m in mounts),'Frozen source image required'
  return info
 def capture(self,target,name,provenance=False,database=None):
  self.inspect_app(target)
  if database is not None and database!='studioos_sim_restore_day15'and not re.fullmatch(r'studioos_sim_restore_[0-9]{14}_[0-9a-f]{6}',database):raise ValueError('Only a named fictional restore copy is accepted')
  module='check_provenance.py'if provenance else'fingerprint.py'
  source=(ROOT/'sim'/module).read_text()
  tail="\nimport os\nurl=os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')\n"
  if database:tail+=f"url=url.rsplit('/',1)[0]+{('/'+database)!r}\n"
  tail+=("print(json.dumps(run(url,'/tmp/fictional-provenance.json',simulation_container=True),sort_keys=True))"if provenance else"print(json.dumps(capture(url,simulation_container=True),sort_keys=True))")
  code="__name__='fictional_ops_probe'\n"+source+tail
  response=subprocess.run(self.dc_args(target)+['exec','-T','app','python','-'],input=code,text=True,capture_output=True,cwd=ROOT)
  if response.returncode:raise RuntimeError(response.stderr)
  result=json.loads(response.stdout);path=self.root/'ops-logs'/(name+'.json');path.write_text(json.dumps(result,indent=2,sort_keys=True))
  if self.log_mirror:
   self.log_mirror.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,self.log_mirror/path.name)
  return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','snapshot','provenance']);p.add_argument('--root',required=True);p.add_argument('--target',choices=['live','test'],default='live');p.add_argument('--name',default='snapshot');p.add_argument('--run',default='month01');p.add_argument('--version',default='0.16.7');a=p.parse_args();lab=OpsLab(a.root)
 if a.action=='prepare':lab.prepare(version=a.version,run=a.run)
 else:print(json.dumps(lab.capture(a.target,a.name,provenance=a.action=='provenance')))
