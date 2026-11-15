"""Real pytest subprocess regression runner; each file isolated and timeout bounded."""
from pathlib import Path
from subprocess import run,TimeoutExpired
import json,re,sys,time
root=Path(__file__).resolve().parents[1]
files=sorted((root/'tests').glob('test_*.py'))
folder=root/'test-evidence-v0913';folder.mkdir(exist_ok=True)
rows=[]
for i,f in enumerate(files,1):
    started=time.monotonic()
    try:
        r=run([sys.executable,'-m','pytest','-q','--disable-warnings',str(f.relative_to(root))],cwd=root,timeout=70,capture_output=True,text=True)
        out=r.stdout+'\n'+r.stderr; code=r.returncode
    except TimeoutExpired as e:
        out=f'TIMEOUT after 70 seconds: {e}';code=124
    (folder/(f.name+'.log')).write_text(out)
    counts={k:0 for k in ('passed','failed','skipped','error')}
    for num,label in re.findall(r'(\d+) (passed|failed|skipped|error|errors)',out):
        counts['error' if label=='errors' else label]=int(num)
    row={'file':f.name,'exit_code':code,'seconds':round(time.monotonic()-started,1),**counts}
    rows.append(row)
    (folder/'regression_results.json').write_text(json.dumps(rows,indent=2))
    print(f'[{i}/{len(files)}] {f.name}: exit={code} {counts} {row["seconds"]}s',flush=True)
summary={'total_files':len(files),'executed':len(rows),'complete':len(rows)==len(files) and all(x['exit_code']==0 for x in rows),
         'totals':{k:sum(x[k] for x in rows) for k in ('passed','failed','skipped','error')},
         'failed_files':[x['file'] for x in rows if x['exit_code']]}
(folder/'regression_summary.json').write_text(json.dumps(summary,indent=2))
print('FINAL',json.dumps(summary),flush=True)
sys.exit(0 if summary['complete'] else 1)
