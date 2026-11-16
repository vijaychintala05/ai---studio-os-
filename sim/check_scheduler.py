"""Advance the fictional clock and observe the real scheduler (no manual job calls)."""
import datetime as dt,json,time
from pathlib import Path

def run(owner,clock,date,staff):
    clock=Path(clock);temp=clock.with_suffix('.tmp');temp.write_text(json.dumps({'utc':date+'T01:35:00+00:00'}));temp.replace(clock)
    owner.login();deadline=time.monotonic()+45
    while True:
        health=owner.call('GET','/api/improve/health');checks={c['key']:c for c in health['checks']}
        ready=all(checks.get('job_'+job,{}).get('detail')=='Last run 0 hour(s) ago'for job in ('daily_rules','summaries_daily'))
        if health['failures']:raise AssertionError({'scheduler_failures':health['failures']})
        if ready:break
        if time.monotonic()>deadline:raise AssertionError({'scheduler_not_observed':checks})
        time.sleep(1)
    people=[]
    for key,client in staff.items():
        client.login(*client.login_credentials)
        person=client.call('GET','/api/auth/me')['user']
        rows=client.call('GET','/api/improve/summaries/mine')['summaries']
        today=[r for r in rows if r['summary']=='fictional_daily'and r['period']==date]
        assert len(today)==1,{'employee':key,'today_summaries':len(today)}
        people.append({'employee':key,'summaries':1})
    return {'passed':True,'daily_jobs_observed':['daily_rules','summaries_daily'],'summaries':people,'manual_job_calls':0}
