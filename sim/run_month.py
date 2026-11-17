"""Fail-closed, resumable daily app/API/mobile runner for fictional copies.

A diagnostic replay can collect failures. Qualification additionally requires every
coverage flag and external ops checkpoints; never turns a partial run into a pass.
"""
import argparse,copy,json,time,traceback
from pathlib import Path
from collections import Counter
from client import App,STAFF_PASSWORD
from bootstrap import run as bootstrap
from browser_entries import BrowserEntries
from probe_day import payload
from daily_work import install,start_projects,run as work
from daily_check import check
from money_day import run as money
from financial_files import reconcile
from check_access import run as check_access
from check_scheduler import run as check_scheduler
from check_provenance import run as check_provenance
from ops_lab import OpsLab
from ops_checkpoint import run as ops_checkpoint
from run_identity import verify as verify_identity


def write(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(path)


def read_draft(response,expected):
    items=response.get('preview',{}).get('items',[])
    found=[i for i in items if i['item_type']=='finance_text_entry']
    if len(found)!=1:return None,['missing_or_multiple_finance_draft']
    item=found[0];actual=item['after'];diff=[]
    for field in ('recipe','project_id','accounts'):
        if actual.get(field)!=expected[field]:diff.append(field)
    for field,value in expected['slots'].items():
        got=actual.get('slots',{}).get(field,{'gst_rate':0,'gst_type':'intra','gst_mode':'none'}.get(field))
        # Descriptions may retain a sourced abbreviation if they resolve to the
        # exact approved item account. Posting lines remain independently checked.
        if field=='item':continue
        if field=='gst_type'and not expected['slots']['gst_rate']:continue
        if field=='gst_mode'and not expected['slots']['gst_rate']and got in ('none','extra'):continue
        if field=='settlement'and expected['recipe']=='client_invoice':continue
        if got!=value:diff.append('slots.'+field)
    return item,diff


def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    if (out/'result.json').exists()and not args.resume:raise ValueError('Use a new output directory, or --resume at a completed day boundary')
    plan=json.loads(Path(args.plan).read_text());answers=json.loads(Path(args.answers).read_text())
    inputs=json.loads(Path(args.inputs).read_text());manifest=json.loads(Path(args.assets).read_text());assets={k:Path(args.assets).parent/v['path']for k,v in manifest.items()}
    result={'status':'RUNNING','qualified':False,'days':[],'failures':[],'browser_entries':0,'channels':{},'ops':{},'start_version':None}
    if args.resume:
        result=json.loads((out/'result.json').read_text())
        completed=len(result['days'])
        if (out/f'day-{completed+1:02d}'/'progress.json').exists():raise ValueError('Partial day requires a fresh run; do not duplicate business rows')
    else:completed=0
    if completed>=15 and not args.diagnostic and not result['ops'].get('passed',False):
        raise ValueError('A failed/missing day15 checkpoint cannot be skipped by resume; restart a fresh loop after fixing it')
    result['status']='RUNNING'
    write(out/'result.json',result)
    if args.clock:
        clock=Path(args.clock);clock.parent.mkdir(parents=True,exist_ok=True)
        write(clock,{'utc':plan['days'][completed]['date']+'T00:30:00+00:00'})
    try:
        a=App(args.url,out/'owner')
        expected_build=None
        if getattr(args,'expected_build',None):
            path=Path(args.expected_build).resolve()
            if path.suffix!='.json' or not path.is_relative_to(Path(__file__).resolve().parents[1]/'sim/runtime'):
                raise ValueError('Expected build must be a fictional runtime JSON manifest')
            expected_build=json.loads(path.read_text())['build']
        required_backend=getattr(args,'require_backend',None)
        health=a.call('GET','/health')
        if expected_build is not None or required_backend:
            verify_identity(health,expected_build,required_backend)
    except Exception as error:
        result['status']='STOPPED'
        result['failures'].append({'severity':'BLOCKER','kind':'build_backend_gate','error':str(error)})
        write(out/'result.json',result)
        if 'a'in locals()and hasattr(a,'http'):a.http.close()
        raise
    result['database_backend']=health.get('database_backend')
    result['build']=health.get('build')
    state=json.loads((out/'state.json').read_text())if args.resume else json.loads(Path(args.state).read_text())if args.state else bootstrap(args.url,plan,out/'bootstrap')
    if result['start_version'] is None:result['start_version']=a.version
    author=App(args.url,out/'accounts',username='fxstaff13',password=STAFF_PASSWORD)
    manager=App(args.url,out/'manager',username='fxstaff01',password=STAFF_PASSWORD)
    if not args.state and not args.resume:install(a,state,plan)
    staff={'E00':a,'E01':manager,'E13':author}
    for person in plan['employees']:
        if person['key']not in staff:staff[person['key']]=App(args.url,out/'staff'/person['key'],username=person['username'],password=STAFF_PASSWORD)
    write(out/'state.json',state)
    posted=state.get('posted',{});channels=Counter(result['channels']);browser=None;field_browser=None;owner_browser=None
    try:
        for day in plan['days'][completed:args.days]:
            daydir=out/f'day-{day["day"]:02d}';daydir.mkdir(exist_ok=True)
            if expected_build is not None or required_backend:
                verify_identity(a.call('GET','/health'),expected_build,required_backend)
            if args.ops_root:
                lab=OpsLab(args.ops_root);build=json.loads((lab.root/'build-manifest.json').read_text());expected_version=build['baseline']if day['day']<=15 else build['candidate']
                actual=a.call('GET','/health')['version'];assert actual==expected_version,('Wrong version for simulated day',day['day'],actual,expected_version)
                assert lab.inspect_app('live')['Image']==build['images'][expected_version],'Frozen image changed'
            else:actual=a.call('GET','/health')['version']
            if args.clock:
                write(clock,{'utc':day['date']+'T00:30:00+00:00'});a.login();author.login('fxstaff13',STAFF_PASSWORD);manager.login('fxstaff01',STAFF_PASSWORD)
            for person in plan['employees']:
                if person['key']not in ('E00','E01','E13'):staff[person['key']].login(person['username'],STAFF_PASSWORD)
            money_person=plan['employees'][13+(day['day']-1)%2]
            money_author=staff[money_person['key']]
            browser=BrowserEntries(args.url,daydir/'browser',username=money_person['username'],password=STAFF_PASSWORD)if args.browser else None
            owner_browser=BrowserEntries(args.url,daydir/'owner-browser')if args.browser else None
            start_projects(a,state,plan,day,owner_browser)
            if browser and day['turnover']:browser.page.reload();browser.page.wait_for_load_state('networkidle')
            daily={'day':day['day'],'app_version':actual,'posted':0,'failures':[],'browser_entries':0}
            observed_clients={id(client):client for client in staff.values()}
            timing_starts={key:len(getattr(client,'timings',[]))for key,client in observed_clients.items()}
            start=time.monotonic()
            money_result=money(money_author,a,state,plan,day,assets,inputs,browser,owner_browser)
            daily['posted']=money_result['posted'];daily['planned_review_edits']=money_result['planned_review_edits'];daily['failures']+=money_result['failures'];channels.update(money_result['channels'])
            posted=state['posted']
            write(daydir/'progress.json',daily)
            if str(day['day'])in inputs['bank']:
                try:daily['bank']=reconcile(money_author,a,state,inputs['bank'][str(day['day'])]['path'],day['day'],plan,browser,review_browser=owner_browser)
                except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'bank_workflow','error':str(e),'traceback':traceback.format_exc()})
            if browser:
                closing,browser=browser,None;closing.close()
            if owner_browser:
                closing,owner_browser=owner_browser,None;closing.close()
            # Work browser uses manager role, not accounts, which cannot create tasks.
            work_person=plan['employees'][1+(day['day']-1)%2]
            field_person=plan['employees'][3+(day['day']-1)%10]
            browser=BrowserEntries(args.url,daydir/'work-browser',username=work_person['username'],password=STAFF_PASSWORD)if args.browser else None
            field_browser=BrowserEntries(args.url,daydir/'field-browser',username=field_person['username'],password=STAFF_PASSWORD)if args.browser else None
            try:
                counts=work(a,state,plan,day,assets,browser,manager,staff,field_browser,field_person);daily['work']=counts;daily['browser_entries']+=counts['browser_entries'];channels.update(counts['channels'])
            except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'work','error':str(e),'traceback':traceback.format_exc()})
            if field_browser:
                closing,field_browser=field_browser,None;closing.close()
            if browser:
                closing,browser=browser,None;closing.close()
            try:daily['answer_key']=check(a,state,plan,answers[day['day']-1],assets);daily['failures']+=daily['answer_key']['differences']
            except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'daily_comparison','error':str(e)})
            try:
                access=check_access(args.url,plan,state,daydir/'role-access');daily['failures']+=access['failures']
                daily['answer_key']['coverage']['role_access']=access['passed'];daily['answer_key']['coverage']['photo_bytes']=access['passed']
            except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'role_access','error':str(e)})
            if args.clock:
                try:
                    daily['scheduler']=check_scheduler(a,args.clock,day['date'],staff)
                    daily['answer_key']['coverage']['scheduled_jobs']=daily['scheduler']['passed']
                except Exception as e:daily['failures'].append({'severity':'HIGH','kind':'scheduler','error':str(e)})
            if args.database_url:
                try:
                    provenance=check_provenance(args.database_url,daydir/'provenance.json');daily['failures']+=provenance['failures']
                    daily['answer_key']['coverage']['all_business_provenance']=provenance['passed']
                except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'provenance','error':str(e)})
            elif args.ops_root:
                try:
                    provenance=OpsLab(args.ops_root).capture('live',f'day-{day["day"]:02d}-provenance',provenance=True)
                    daily['failures']+=provenance['failures'];daily['answer_key']['coverage']['all_business_provenance']=provenance['passed']
                except Exception as e:daily['failures'].append({'severity':'BLOCKER','kind':'provenance','error':str(e)})
            else:daily.setdefault('answer_key',{}).setdefault('coverage',{})['all_business_provenance']=False
            daily['answer_key']['matching']=not daily['failures']and all(daily['answer_key']['coverage'].values())
            # Missing coverage is explicit even if the tested numbers happen to match.
            daily['browser_entries']=sum(len(p.read_text().splitlines())for p in daydir.glob('*/entries.jsonl'))
            if args.browser and daily['browser_entries']<20:daily['failures'].append({'severity':'HIGH','kind':'browser_quota','actual':daily['browser_entries'],'required':20})
            daily['seconds']=round(time.monotonic()-start,3)
            if getattr(args,'performance',False):
                from performance import evaluate
                samples=[row for key,client in observed_clients.items()
                         for row in getattr(client,'timings',[])[timing_starts[key]:]]
                for name in ('entries.jsonl','reviews.jsonl'):
                    for path in daydir.glob('*/'+name):
                        samples.extend(json.loads(line)for line in path.read_text().splitlines())
                day_one=result['days'][0]['seconds']if result['days']else daily['seconds']
                daily['performance']=evaluate(samples,daily['seconds'],day_one)
                daily['failures']+=daily['performance']['failures']
            result['days'].append(daily)
            result['failures']+=daily['failures'];result['browser_entries']+=daily['browser_entries'];result['channels']=dict(channels)
            state['posted']=posted
            write(out/'state.json',state);write(out/'result.json',result);write(daydir/'result.json',daily)
            print(json.dumps({'day':day['day'],'posted':daily['posted'],'failures':len(daily['failures']),'browser_entries':daily['browser_entries'],'seconds':daily['seconds']}),flush=True)
            with Path(__file__).with_name('LOG.md').open('a')as record:record.write(f"\n- {out.parent.name} day{day['day']} finished on{actual}: money{daily['posted']}, browser{daily['browser_entries']}, failures{len(daily['failures'])}, seconds{daily['seconds']}; daily state/results persisted.\n")
            if daily['failures']and not args.diagnostic:raise RuntimeError('Daily differences must be fixed before a fresh qualification loop')
            if day['day']==15 and not args.diagnostic:
                if not args.ops_root:raise RuntimeError('Day-15 requires the guarded real-ops lab')
                if result['failures']:raise RuntimeError('Daily failures must be resolved before claiming an upgrade qualification')
                result['ops']=ops_checkpoint(args.ops_root,state,out/'day15-ops')
                write(out/'state.json',state);write(out/'result.json',result)
        result['qualified']=(not args.diagnostic and args.days==30 and len(result['days'])==30 and not result['failures'] and all(d['answer_key']['matching'] and d['browser_entries']>=20 for d in result['days']) and result['ops'].get('passed',False))
        result['status']='QUALIFIED_MONTH'if result['qualified']else 'PARTIAL_COMPLETE'if args.days<30 else 'DIAGNOSTIC_COMPLETE'
    except Exception as e:
        result['status']='STOPPED';result['failures'].append({'severity':'BLOCKER','kind':'runner','error':str(e),'traceback':traceback.format_exc()})
        raise
    finally:
        if owner_browser:owner_browser.close()
        if field_browser:field_browser.close()
        if browser:browser.close()
        write(out/'result.json',result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--plan',default='sim/runtime/generated-v3/plan.json');p.add_argument('--answers',default='sim/runtime/generated-v3/answer-key.json');p.add_argument('--assets',default='sim/runtime/assets-v3/assets.json');p.add_argument('--ops-root');p.add_argument('--database-url');p.add_argument('--inputs',default='sim/runtime/inputs-v3/inputs.json');p.add_argument('--out',required=True);p.add_argument('--state');p.add_argument('--resume',action='store_true');p.add_argument('--clock');p.add_argument('--days',type=int,default=30);p.add_argument('--browser',action='store_true');p.add_argument('--diagnostic',action='store_true');p.add_argument('--performance',action='store_true');p.add_argument('--require-backend',choices=['postgresql','sqlite']);p.add_argument('--expected-build');run(p.parse_args())
