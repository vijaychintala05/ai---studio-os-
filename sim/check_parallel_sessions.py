"""Three simultaneous real phone sessions must keep identities and runtime alive."""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries
from client import STAFF_PASSWORD


def run(url,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);sessions=[];result={'passed':False,'monthly_entries':0}
    try:
        owner=BrowserEntries(url,out/'owner');sessions.append(owner)
        accounts=BrowserEntries(url,out/'accounts',username='fxstaff13',password=STAFF_PASSWORD);sessions.append(accounts)
        other=BrowserEntries(url,out/'other',username='fxstaff14',password=STAFF_PASSWORD);sessions.append(other)
        identities=[b.page.request.get(url+'/api/auth/me').json()['user']['username']for b in sessions]
        assert identities==['admin','fxstaff13','fxstaff14'],identities
        accounts.close();sessions.remove(accounts)
        owner.nav('projects');other.nav('ledger')
        assert owner.page.request.get(url+'/api/auth/me').json()['user']['username']=='admin'
        result.update(passed=True,identities=identities,survives_other_session_close=True)
    finally:
        for b in reversed(sessions):b.close()
        (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8880');p.add_argument('--out',required=True);a=p.parse_args();run(a.url,a.out)
