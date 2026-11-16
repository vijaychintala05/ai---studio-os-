"""Detach long fictional test jobs from an interactive tool session.
A job records actual exit status; a missing/incomplete result is never a pass.
"""
import argparse,datetime as dt,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def specification(job):
    runtime=ROOT/'sim/runtime';lab=runtime/'ops-lab';env={**os.environ,'STUDIOOS_SCHEDULER':'off','STUDIOOS_PROVIDER':'demo','STUDIOOS_ALLOW_LIVE_AI':'false'}
    if job in ('stats-postgres','books-postgres'):
        info=json.loads(subprocess.check_output(['docker','inspect','studioos-sim-db-1'],text=True))[0]
        assert info['Config']['Labels']['com.docker.compose.project']=='studioos-sim'
        env.update(PATH='/workspace/test-bin:'+env['PATH'],STUDIOOS_TEST_DATABASE_URL='postgresql+psycopg://studioos:FictionalOwnerDatabasePassword2026@127.0.0.1:8871/studioos',STUDIOOS_TEST_PG_URL='postgresql://studioos:FictionalOwnerDatabasePassword2026@127.0.0.1:8871/studioos_safekeeping_test')
        label='stats'if job=='stats-postgres'else'books'
        cmd=[sys.executable,'-m','pytest','-q','--durations=20','--basetemp=sim/runtime/durable-'+label+'-pg-tmp','--junitxml=sim/runtime/durable-'+label+'-full-postgres.xml']
    elif job=='books-sqlite':
        env.pop('STUDIOOS_TEST_DATABASE_URL',None);env.pop('STUDIOOS_TEST_PG_URL',None)
        cmd=[sys.executable,'-m','pytest','-q','--durations=20','--basetemp=sim/runtime/durable-books-sqlite-tmp','--junitxml=sim/runtime/durable-books-full-sqlite.xml']
    elif job=='recovery-preflight':
        cmd=[sys.executable,'sim/preflight_recovery.py','--root',str(lab),'--sqlite',str(runtime/'durable-books-full-sqlite.xml'),'--postgres',str(runtime/'durable-books-full-postgres.xml')]
    elif job=='two-months':
        cmd=[sys.executable,'sim/run_two_months.py','--root',str(lab),'--sqlite',str(runtime/'durable-books-full-sqlite.xml'),'--postgres',str(runtime/'durable-books-full-postgres.xml'),
            '--plan',str(runtime/'generated-v6/plan.json'),'--answers',str(runtime/'generated-v6/answer-key.json'),'--assets',str(runtime/'assets-v6/assets.json'),'--inputs',str(runtime/'inputs-v6/inputs.json')]
    else:raise ValueError('Unknown fictional test job')
    return cmd,env


def launch(job):
    directory=ROOT/'sim/runtime/jobs';directory.mkdir(exist_ok=True)
    path=directory/(job+'.json')
    if path.exists()and json.loads(path.read_text()).get('status')=='RUNNING':
        previous=json.loads(path.read_text())
        try:os.kill(previous['pid'],0)
        except ProcessLookupError:pass
        else:raise ValueError('Job already running; inspect its evidence first')
    with(directory/(job+'.log')).open('a')as output:
        p=subprocess.Popen([sys.executable,__file__,'--worker',job],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    return {'job':job,'pid':p.pid,'detached':True,'evidence':str(path)}


def worker(job):
    directory=ROOT/'sim/runtime/jobs';path=directory/(job+'.json')
    record={'job':job,'pid':os.getpid(),'status':'RUNNING','started_utc':dt.datetime.now(dt.UTC).isoformat()};path.write_text(json.dumps(record,indent=2))
    try:
        command,env=specification(job)
        result=subprocess.run(command,cwd=ROOT,env=env)
        record.update(status='COMPLETED'if result.returncode==0 else'FAILED',exit_code=result.returncode)
    except Exception as error:
        record.update(status='FAILED',error=str(error));raise
    finally:
        record['finished_utc']=dt.datetime.now(dt.UTC).isoformat();path.write_text(json.dumps(record,indent=2))
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Detached job result: '+json.dumps(record)+'. Test/result artifacts remain the authority for pass counts.\n')
    return record
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',choices=['stats-postgres','books-postgres','books-sqlite','recovery-preflight','two-months']);p.add_argument('--worker',action='store_true');a=p.parse_args();result=worker(a.job)if a.worker else launch(a.job);print(json.dumps(result,indent=2))
    if a.worker and result['status']!='COMPLETED':raise SystemExit(result.get('exit_code',1))
