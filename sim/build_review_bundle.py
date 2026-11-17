"""Build a local review ZIP and original-release diff after observed qualification.
Never publishes, tags, merges or packages runtime credentials/databases/backups.
"""
import argparse,datetime as dt,hashlib,json,subprocess,zipfile
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


def build(original,out):
    from preflight_recovery import tests_green
    original=Path(original).resolve();out=Path(out).resolve();assert out.is_relative_to(ROOT/'artifacts')
    assert hashlib.sha256(original.read_bytes()).hexdigest()==BASELINE_SHA,'Wrong original v0.16.0 ZIP'
    assert not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).strip(),'Commit reviewed changes and final reports before packaging'
    runtime=ROOT/'sim/runtime';lab=runtime/'ops-lab';summary=json.loads((lab/'two-clean-months.json').read_text())
    assert summary['passed']and len(summary['clean_months'])==2,'No qualified two-month result'
    matrix=tests_green([runtime/'durable-books-full-sqlite.xml',runtime/'durable-books-full-postgres.xml'])
    evidence={};payload={}
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
            if allowed(name):payload[name]=source.read(item)
    tracked=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    for name in tracked:
        path=ROOT/name
        if path.is_file()and allowed(name):payload[name]=path.read_bytes()
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
    with zipfile.ZipFile(filename,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9)as archive:
        for name,data in sorted(payload.items()):archive.writestr('studioos-v'+version+'/'+name,data)
    with zipfile.ZipFile(filename)as archive:assert archive.testzip()is None
    checksum=hashlib.sha256(filename.read_bytes()).hexdigest();filename.with_suffix('.zip.sha256').write_text(checksum+'  '+filename.name+'\n')
    metadata.update(zip=str(filename),diff=str(diffpath),sha256=checksum,files=len(payload));(out/'bundle-result.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps(metadata,indent=2));return metadata
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',required=True);p.add_argument('--out',default=str(ROOT/'artifacts'));a=p.parse_args();build(a.original,a.out)
