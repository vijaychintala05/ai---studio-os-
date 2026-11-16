"""Continue the fictional validation pipeline after complete current test workers.
Each real subprocess must succeed. Interrupted/failed months are never overwritten.
"""
import argparse,datetime as dt,hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'sim/runtime'


def run(after_build=False):
    record={'status':'RUNNING','steps':[],'started_utc':dt.datetime.now(dt.UTC).isoformat()}
    path=RUNTIME/'validation-pipeline.json'
    def save():path.write_text(json.dumps(record,indent=2))
    def command(name,args):
        step={'step':name,'status':'RUNNING','started_utc':dt.datetime.now(dt.UTC).isoformat()};record['steps'].append(step);save()
        with(RUNTIME/('pipeline-'+name+'.log')).open('w')as log:
            result=subprocess.run([sys.executable]+args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        step.update(status='PASSED'if result.returncode==0 else'FAILED',exit_code=result.returncode,finished_utc=dt.datetime.now(dt.UTC).isoformat());save()
        if result.returncode:raise RuntimeError(name+' failed; inspect exact pipeline log')
    save()
    try:
        while True:
            jobs=[json.loads((RUNTIME/'jobs'/name).read_text())for name in ('books-sqlite.json','books-postgres.json')]
            if any(j['status']=='FAILED'for j in jobs):raise RuntimeError('Full suite failed; no recovery/month permitted')
            if all(j['status']=='COMPLETED'and j['exit_code']==0 for j in jobs):break
            time.sleep(10)
        sys.path.insert(0,str(ROOT/'sim'))
        from preflight_recovery import tests_green
        matrix=tests_green([RUNTIME/'durable-books-full-sqlite.xml',RUNTIME/'durable-books-full-postgres.xml'])
        assert all(r['tests']>=776 for r in matrix),'Current coordination regressions must be included'
        record['full_test_matrix']=matrix;save()
        if after_build:
            ci=json.loads((RUNTIME/'ci-books-final/result.json').read_text());assert len(ci)==8 and all(x['passed']for x in ci)
            caches=sorted(RUNTIME.glob('ci-cache-*.json'));latest=json.loads(caches[-1].read_text())
            assert hashlib.sha256(Path(latest['archive']).read_bytes()).hexdigest()==latest['sha256']
            record['reused_complete_ci_and_verified_cache']=True;save()
        else:
            command('standalone-ci',['sim/run_ci_checks.py','--out',str(RUNTIME/'ci-books-final')])
            command('archive-ci',['sim/archive_ci_cache.py'])
        command('recovery-preflight',['sim/preflight_recovery.py','--root',str(RUNTIME/'ops-lab'),'--sqlite',str(RUNTIME/'durable-books-full-sqlite.xml'),'--postgres',str(RUNTIME/'durable-books-full-postgres.xml')])
        command('ticket-guidance',['sim/check_ticket_guidance.py','--url','http://127.0.0.1:8880','--out',str(RUNTIME/'ticket-guidance-green')])
        command('two-months',['sim/run_two_months.py','--root',str(RUNTIME/'ops-lab'),'--sqlite',str(RUNTIME/'durable-books-full-sqlite.xml'),'--postgres',str(RUNTIME/'durable-books-full-postgres.xml'),
            '--plan',str(RUNTIME/'generated-v6/plan.json'),'--answers',str(RUNTIME/'generated-v6/answer-key.json'),'--assets',str(RUNTIME/'assets-v6/assets.json'),'--inputs',str(RUNTIME/'inputs-v6/inputs.json')])
        record['status']='COMPLETED'
    except Exception as error:
        record.update(status='FAILED',error=str(error));raise
    finally:
        record['finished_utc']=dt.datetime.now(dt.UTC).isoformat();save()
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Validation pipeline '+record['status']+': '+str(record.get('error','all subprocesses finished'))+'. Full step evidence in sim/runtime/validation-pipeline.json.\n')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--after-build',action='store_true');args=parser.parse_args();run(args.after_build)
