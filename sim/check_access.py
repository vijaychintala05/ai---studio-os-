"""Fictional site-role checks using authenticated public HTTP endpoints."""
import argparse,json
from pathlib import Path
from client import App,STAFF_PASSWORD
from project_scope import out_of_scope


def run(url,plan,state,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);failures=[];results=[]
    for person in plan['employees']:
        if person['role']!='site_engineer':continue
        a=App(url,out/person['key'],username=person['username'],password=STAFF_PASSWORD)
        visible={x['id']:x['name']for x in a.call('GET','/api/projects')}
        allowed=set(visible)
        assert len({p['name']for p in plan['projects']})==len(plan['projects']),'Name-only site-report scope needs unambiguous fictional project names'
        expected={state['projects'][x['project']]for x in plan['initial_tasks']if x['employee']==person['key']}
        expected|={state['projects'][s['project']]for s in plan['days'][0]['snags']if s['owner']==person['key']}
        # Include subsequently assigned new sites, only if they have started.
        expected|={pid for key,pid in state['projects'].items()if int(key[1:])>=10 and int(key[1:])%6==int(person['key'][1:])-7}
        if allowed!=expected or not 1<=len(allowed)<=3:failures.append({'severity':'HIGH','kind':'site_membership','employee':person['key'],'expected':sorted(expected),'actual':sorted(allowed)})
        for path in ('/api/tasks','/api/site-reports','/api/documents'):
            rows=a.call('GET',path)
            if any(out_of_scope(path,x,visible)for x in rows):failures.append({'severity':'BLOCKER','kind':'project_access_leak','employee':person['key'],'path':path})
        forbidden=next(pid for pid in state['projects'].values()if pid not in allowed)
        scoped=a.call('GET',f'/api/graph/records/work_issue?project_id={forbidden}')
        if scoped['total']:failures.append({'severity':'BLOCKER','kind':'graph_filter_leak','employee':person['key']})
        response=a.http.get(f'/api/finance-ledger/trial-balance/{state["entity"]}')
        if response.status_code!=403:failures.append({'severity':'BLOCKER','kind':'finance_access','employee':person['key'],'status':response.status_code})
        hidden=next((s for s in state['snags'].values()if s['project_id']not in allowed),None)
        visible=next((s for s in state['snags'].values()if s['project_id']in allowed),None)
        if hidden:
            r=a.http.get(f'/api/graph/record/{hidden["id"]}')
            if r.status_code!=404:failures.append({'severity':'BLOCKER','kind':'hidden_snag_access','employee':person['key'],'status':r.status_code})
            r=a.http.get(f'/api/documents/{hidden["document_id"]}/file')
            if r.status_code!=404:failures.append({'severity':'BLOCKER','kind':'hidden_photo_access','employee':person['key'],'status':r.status_code})
        if visible:
            a.call('GET',f'/api/graph/record/{visible["id"]}')
            r=a.http.get(f'/api/documents/{visible["document_id"]}/file')
            if r.status_code!=200:failures.append({'severity':'HIGH','kind':'assigned_snag_photo_unavailable','employee':person['key'],'status':r.status_code,'error':r.text})
        results.append({'employee':person['key'],'assigned_projects':len(allowed),'checked':True})
        a.call('POST','/api/auth/logout',{});a.http.close()
    result={'site_roles_checked':results,'failures':failures,'passed':not failures}
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--plan',default='sim/runtime/generated-v2/plan.json');p.add_argument('--state',default='sim/runtime/month003/run/state.json');p.add_argument('--out',default='sim/runtime/access-probe');args=p.parse_args();run(args.url,json.loads(Path(args.plan).read_text()),json.loads(Path(args.state).read_text()),args.out)
