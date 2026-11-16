"""Fresh consecutive clean months after the retained failed-loop recovery proof.
Runs actual processes, no synthesized passes. Stops on any failure; max10loops.
"""
import argparse,json,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from ops_lab import OpsLab,ROOT
from preflight_recovery import tests_green,verify_build
from reset_month import run as reset
from bootstrap_ops import run as bootstrap
from run_month import run as month
from browser_probe import run as screens


def run(args):
    lab=OpsLab(args.root);tests_green([args.sqlite,args.postgres]);manifest=verify_build(lab)
    preflight=json.loads((lab.root/'month01/recovery-preflight/result.json').read_text());assert preflight['passed']
    plan_path=Path(args.plan).resolve();plan=json.loads(plan_path.read_text())
    summary={'clean_months':[],'passed':False,'failed_loop':'month01','baseline':manifest['baseline'],'candidate':manifest['candidate']}
    previous=lab.root/'month01/run/result.json'
    for number in (2,3):
        name=f'month{number:02d}';directory=lab.root/name
        if (directory/'run/result.json').exists():raise ValueError('Existing month evidence must be resumed/reviewed explicitly, never overwritten')
        reset(lab.root,previous,name,manifest['baseline'],restart_failed=(number==2))
        state_path=directory/'setup/state.json';bootstrap(lab.root,plan,directory/'setup')
        params=SimpleNamespace(url='http://127.0.0.1:8880',out=str(directory/'run'),plan=str(plan_path),answers=args.answers,
            assets=args.assets,inputs=args.inputs,state=str(state_path),resume=False,clock=str(directory/'live/files/simulation-clock.json'),
            days=30,browser=True,diagnostic=False,ops_root=str(lab.root),database_url=None)
        result=month(params)
        if not result['qualified']:raise RuntimeError(f'{name} did not qualify; do not count it as consecutive clean')
        # Clock remains stable after the last daily check; visits count zero entries.
        mobile=screens(params.url,directory/'final-mobile')
        assert not mobile['errors'],mobile['errors']
        channels=result['channels'];total=sum(channels.values());mix={k:round(100*v/total,2)for k,v in channels.items()}
        assert 50<=mix.get('chat',0)<=70 and 15<=mix.get('form',0)<=35 and 5<=mix.get('import',0)<=15 and 2<=mix.get('file',0)<=10,mix
        summary['clean_months'].append({'month':name,'days':len(result['days']),'money':sum(d['posted']for d in result['days']),
            'browser_entries':result['browser_entries'],'answer_days_matching':sum(d['answer_key']['matching']for d in result['days']),
            'input_mix_percent':mix,'mobile_screens':len(mobile['screens']),'qualified':True})
        (lab.root/'two-clean-months.json').write_text(json.dumps(summary,indent=2))
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- '+name+' finished with real app/API/browser execution: '+json.dumps(summary['clean_months'][-1])+'. Full per-day/ops evidence retained.\n')
        previous=directory/'run/result.json'
    summary['passed']=True;(lab.root/'two-clean-months.json').write_text(json.dumps(summary,indent=2));return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--sqlite',required=True);p.add_argument('--postgres',required=True)
 p.add_argument('--plan',required=True);p.add_argument('--answers',required=True);p.add_argument('--assets',required=True);p.add_argument('--inputs',required=True)
 print(json.dumps(run(p.parse_args()),indent=2))
