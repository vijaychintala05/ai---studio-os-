"""Real Chromium: a late records refresh must not erase an open Work draft."""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries
from client import STAFF_PASSWORD


def run(url,out):
 out=Path(out);b=BrowserEntries(url,out,username='fxstaff01',password=STAFF_PASSWORD);pending=[]
 try:
  b.nav('work');b.page.wait_for_load_state('networkidle')
  body=b.page.request.get(url+'/api/graph/records/meeting_note?q=').json()
  def hold(route):pending.append(route)
  b.page.route('**/api/graph/records/meeting_note*',hold)
  b.page.locator('[data-g=type][data-key=meeting_note]').click()
  b.page.locator('[data-g=new]').click();form=b.page.locator('#gForm');form.wait_for(state='visible')
  project=form.locator('[name=g-project]');options=project.locator('option').all()
  chosen=[o.get_attribute('value')for o in options if o.get_attribute('value')][-1]
  project.select_option(chosen);form.locator('[name=g-decisions]').fill('Fictional unsaved decision must stay')
  assert len(pending)==1,'One controlled list request required'
  route=pending.pop();route.fulfill(json=body)
  b.page.wait_for_load_state('networkidle');b.page.wait_for_timeout(100)
  values={'project':form.locator('[name=g-project]').input_value(),'decisions':form.locator('[name=g-decisions]').input_value()}
  expected={'project':chosen,'decisions':'Fictional unsaved decision must stay'}
  result={'passed':values==expected,'expected':expected,'actual':values,'app_entries':0}
  if not result['passed']:b.page.screenshot(path=str(out/'failure.png'),full_page=True)
  (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return result['passed']
 finally:
  for route in pending:route.fulfill(json=body)
  b.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(a.url,a.out)else 1)
