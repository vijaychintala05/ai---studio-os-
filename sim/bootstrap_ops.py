"""Prepare the fictional baseline through app tickets, then its normal owner migrate step."""
import argparse,json,time
from pathlib import Path
import httpx
from bootstrap import run as bootstrap
from daily_work import install
from ops_lab import OpsLab


def run(root,plan,out):
 lab=OpsLab(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 from client import App
 a=App('http://127.0.0.1:8880',out/'preflight')
 state=bootstrap('http://127.0.0.1:8880',plan,out/'bootstrap');install(a,state,plan)
 # Approved report indexes are an initial owner operation, before monthly data.
 for report in a.call('GET','/api/graph/catalog')['reports']:a.call('GET','/api/graph/reports/'+report['key']+'/run')
 lab.dc('live','run','--rm','--no-deps','migrate',name='baseline-approved-report-indexes')
 lab.dc('live','restart','app',name='baseline-restart-after-migrate')
 for _ in range(45):
  try:
   response=httpx.get('http://127.0.0.1:8880/health');response.raise_for_status();assert response.json()['version']==state['version'];break
  except (httpx.HTTPError,AssertionError):time.sleep(1)
 else:raise RuntimeError('Fictional baseline did not restart')
 snapshot=lab.capture('live','baseline-post-setup')
 assert len(snapshot['journal_hashes'])==1
 (out/'state.json').write_text(json.dumps(state,indent=2));print(json.dumps({'bootstrap':'PASS','version':state['version'],'new_kinds':len(state['new_kinds']),'opening_journals':1,'month':'NOT RUN'}),flush=True)
 return state
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--plan',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,json.loads(Path(a.plan).read_text()),a.out)
