"""Phone navigation after leaving Chat must keep a reachable menu on extension screens."""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries
from client import STAFF_PASSWORD

def run(url,out):
 out=Path(out);b=BrowserEntries(url,out,username='fxstaff13',password=STAFF_PASSWORD)
 try:
  results=[]
  for view in ('chart','inbox','selfcheck'):
   b.nav(view)
   passed=b.page.locator('#tabBar').is_visible()   # on a phone the bottom tabs (Me lists every screen) replaced the menu button
   results.append({'view':view,'menu_visible':passed})
   if not passed:
    b.page.screenshot(path=str(out/f'failure-{view}.png'));break
   b.nav('assistant')
  result={'passed':all(r['menu_visible']for r in results)and len(results)==3,'screens':results,'app_entries':0}
  (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return result['passed']
 finally:b.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(a.url,a.out)else 1)
