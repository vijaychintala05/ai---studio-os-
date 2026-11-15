"""Run all pytest files in small, isolated subprocess groups; fictional test database.

Usage: python -m tests.run_v0911_regression [group numbers ...]
"""
from pathlib import Path
import subprocess,sys,json
base=Path(__file__).resolve().parents[1]
files=sorted(str(x.relative_to(base)) for x in (base/'tests').glob('test_*.py'))
groups=[files[i:i+4] for i in range(0,len(files),4)]
evidence=base/'test-evidence-v0911';evidence.mkdir(exist_ok=True)
results=[]
for i,group in enumerate(groups,1):
    if len(sys.argv)>1 and i not in [int(x) for x in sys.argv[1:]]:
        continue
    print(f'Running group {i}/{len(groups)}: '+', '.join(group),flush=True)
    try:
        r=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings',*group],cwd=base,capture_output=True,text=True,timeout=100)
        out=r.stdout+'\n'+r.stderr;code=r.returncode
    except subprocess.TimeoutExpired as exc:
        a=exc.stdout or b'';b=exc.stderr or b''
        out=(a+b).decode(errors='replace') if isinstance(a,bytes) else str(a)+str(b)
        code=124
    (evidence/f'group{i}.log').write_text(out)
    last=out.strip().splitlines()[-1] if out.strip() else '(no pytest summary)'
    print(f'  exit={code}, last={last[:180]}',flush=True)
    results.append({'group':i,'files':group,'exit_code':code,'summary':last})
(evidence/('regression_batches_'+('-'.join(sys.argv[1:]) if len(sys.argv)>1 else 'all')+'.json')).write_text(json.dumps(results,indent=2))
if any(x['exit_code']!=0 for x in results):sys.exit(1)
