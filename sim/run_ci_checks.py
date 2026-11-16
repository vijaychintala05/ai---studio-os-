"""Run standalone release CI database checks on the disposable local sim service.
No owner NAS access and no monthly-database changes. Each schema check gets a new DB.
"""
import datetime as dt,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def run(out):
 out=Path(out).resolve()
 if not out.is_relative_to(ROOT/'sim/runtime'):raise ValueError('Evidence must be inside fictional runtime')
 out.mkdir(parents=True,exist_ok=True)
 info=json.loads(subprocess.check_output(['docker','inspect','studioos-sim-db-1'],text=True))[0]
 assert info['Config']['Labels']['com.docker.compose.project']=='studioos-sim'
 prefix='studioos_ci_'+dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S')
 results=[]
 specs=[('roles','check_v0160_roles_pg.py',None),('ledger','check_v0914_ledger_guard_pg.py','ledger'),('edges','check_v0100_edge_migration.py','edges'),
 ('v22','check_v0110_migration.py','v22'),('views','check_v0120_views_db.py','views'),('history','check_v0130_migration.py','history'),
 ('inbox','check_v0140_migration.py','inbox'),('improve','check_v0150_migration.py','improve')]
 for name,script,suffix in specs:
  env={**os.environ,'STUDIOOS_GUARD_PSQL':'docker exec -i studioos-sim-db-1 psql -U studioos','STUDIOOS_ROLES_PSQL':'docker exec -i studioos-sim-db-1 psql','STUDIOOS_ROLES_SUPERUSER':'studioos'}
  if suffix:
   database=prefix+'_'+suffix
   subprocess.run(['docker','exec','studioos-sim-db-1','createdb','-U','studioos',database],check=True,capture_output=True,text=True)
   env['STUDIOOS_GUARD_DB']=database
  with(out/(name+'.log')).open('w')as log:result=subprocess.run([str(Path(os.sys.executable)),str(ROOT/'tests'/script)],cwd=ROOT,env=env,text=True,stdout=log,stderr=subprocess.STDOUT)
  results.append({'check':name,'script':script,'exit_code':result.returncode,'passed':result.returncode==0})
  (out/'result.json').write_text(json.dumps(results,indent=2))
  print(json.dumps(results[-1]),flush=True)
 return results
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();r=run(a.out);raise SystemExit(0 if all(x['passed']for x in r)else 1)
