"""Validate simulator fixes, then start fresh attempts without rewriting failures."""
import datetime as dt,json,subprocess,sys,time,xml.etree.ElementTree as E
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'sim/runtime'


def count(path):return sum(int(s.get('tests',0))for s in E.parse(path).getroot().iter('testsuite'))

def run():
    record={'status':'RUNNING','steps':[],'minimum_tests':784,'started_utc':dt.datetime.now(dt.UTC).isoformat()};path=R/'runner-loop-resume.json'
    def save():path.write_text(json.dumps(record,indent=2))
    def command(name,args):
        item={'step':name,'status':'RUNNING'};record['steps'].append(item);save()
        with(R/('runner-resume-'+name+'.log')).open('w')as log:p=subprocess.run([sys.executable]+args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        item.update(status='PASSED'if p.returncode==0 else'FAILED',exit_code=p.returncode);save()
        if p.returncode:raise RuntimeError(name+' failed; inspect exact retained log')
    save()
    try:
        while True:
            a=json.loads((R/'jobs/books-sqlite.json').read_text());b=json.loads((R/'jobs/books-postgres.json').read_text())
            if any(x['status']=='FAILED'for x in (a,b)):raise RuntimeError('Complete matrix failed')
            if a['status']=='COMPLETED'and count(R/'durable-books-full-sqlite.xml')<784:
                subprocess.run([sys.executable,'sim/durable_job.py','books-sqlite'],cwd=ROOT,check=True)
            elif all(x['status']=='COMPLETED'and x['exit_code']==0 for x in (a,b))and all(count(R/('durable-books-full-'+n+'.xml'))>=784 for n in ('sqlite','postgres')):break
            time.sleep(10)
        from preflight_recovery import tests_green
        record['matrix']=tests_green([R/'durable-books-full-sqlite.xml',R/'durable-books-full-postgres.xml']);save()
        command('standalone-ci',['sim/run_ci_checks.py','--out',str(R/'ci-books-final')])
        command('archive-ci',['sim/archive_ci_cache.py'])
        from ops_lab import OpsLab
        from ops_checkpoint import start
        start(OpsLab(R/'ops-lab'),'live','runner-fix-verified-resume-live')
        command('fresh-months',['sim/run_two_months.py','--start-month','3','--resume-setup','month03','--root',str(R/'ops-lab'),
            '--sqlite',str(R/'durable-books-full-sqlite.xml'),'--postgres',str(R/'durable-books-full-postgres.xml'),
            '--plan',str(R/'generated-v6/plan.json'),'--answers',str(R/'generated-v6/answer-key.json'),'--assets',str(R/'assets-v6/assets.json'),'--inputs',str(R/'inputs-v6/inputs.json')])
        record['status']='COMPLETED'
    except Exception as error:
        record.update(status='FAILED',error=str(error));raise
    finally:
        record['finished_utc']=dt.datetime.now(dt.UTC).isoformat();save()
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Runner-fix pipeline '+record['status']+': '+str(record.get('error','all actual stages completed'))+'. See sim/runtime/runner-loop-resume.json.\n')
if __name__=='__main__':run()
